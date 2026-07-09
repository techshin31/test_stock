import logging
import json
import os
import pandas as pd
import numpy as np
from typing import Dict, List
import datetime
from data.loaders.kospi_data import get_kospi_top_n, download_multiple_stocks, download_kospi_index
from data.loaders.fa_ta_loader import enrich_ohlcv_with_fa, FA_MODEL_VERSION
from storage.postgres.connection import PostgreDB
from core.strategy.fa_ta_momentum import FaTaMomentumStrategy
from core.broker.kis_api import KisBroker

class LiveTrader:
    def __init__(self, mock=True):
        self.broker = KisBroker(mock=mock)
        db_config = {
            'host': 'localhost',
            'port': 5433,
            'user': 'admin',
            'password': 'admin1234',
            'database': 'quantpilot_db'
        }
        self.db = PostgreDB(db_config)
        
        # 최적화된 파라미터 적용
        strategy_params = {
            "entry_size": 0.2,      # 최대 5종목 분산
            "ma_window": 60,        # 60일선 돌파 모멘텀
            "ma_window_fast": 20,
            "fa_score_min": 60.0,   # DB fa_score 진입 기준
            "fa_score_exit": 40.0,  # fa_score 하락 시 매도 기준
            "debt_ratio_max": 2.0,  # 부채비율 상한 (200%)
        }
        self.strategy = FaTaMomentumStrategy(strategy_params)
        self.strategy_name = self.strategy.INVESTMENT_TYPE.name.lower()
        
    def run_premarket_batch(self):
        logging.info(f"[{datetime.datetime.now()}] 프리마켓 FA 필터링 시작")
        universe = get_kospi_top_n(200)
        tickers = list(universe.keys())
        end_date = datetime.datetime.now().strftime('%Y-%m-%d')
        start_date = (datetime.datetime.now() - datetime.timedelta(days=200)).strftime('%Y-%m-%d')
        
        ohlcv_store = download_multiple_stocks(tickers, start=start_date, end=end_date, show_progress=False)
        ohlcv_store = enrich_ohlcv_with_fa(self.db, ohlcv_store, end_date)
        
        # 기업 위험 상태(매수 차단 종목) 조회
        from storage.postgres.repositories.company_risk_repo import fetch_buy_blocked_stock_codes
        try:
            blocked_codes = fetch_buy_blocked_stock_codes(self.db, datetime.date.today())
        except Exception as e:
            logging.error(f"기업 위험 상태 조회 실패: {e}")
            blocked_codes = set()

        fa_candidates = []
        for ticker, df in ohlcv_store.items():
            if df.empty or 'fa_score' not in df.columns: continue
            
            symbol = ticker.split('.')[0]
            if symbol in blocked_codes:
                logging.info(f"[{symbol}] 기업 위험 상태(BLOCK_BUY/SELL_ONLY)로 후보 제외")
                continue
                
            last = df.iloc[-1]
            fa_score = last.get('fa_score', None)
            is_eligible = last.get('is_eligible', False)
            debt_ratio = last.get('debt_ratio', None)
            # is_eligible 플래그 + fa_score >= 60 + 부채비율 200% 이하
            if (
                is_eligible and
                fa_score is not None and float(fa_score) >= self.strategy.FA_SCORE_MIN and
                (debt_ratio is None or float(debt_ratio) <= self.strategy.DEBT_RATIO_MAX)
            ):
                fa_candidates.append(ticker)
        
        os.makedirs("logs", exist_ok=True)
        with open("logs/fa_candidates.json", "w", encoding="utf-8") as f:
            json.dump(fa_candidates, f)
        logging.info(f"프리마켓 FA 필터링 완료. 관심 종목 {len(fa_candidates)}개 저장.")
        
        # 타임라인 업데이트
        dashboard_state = {"timeline": []}
        if os.path.exists("logs/dashboard_state.json"):
            try:
                with open("logs/dashboard_state.json", "r", encoding="utf-8") as f:
                    dashboard_state = json.load(f)
            except: pass
        
        timeline = dashboard_state.setdefault("timeline", [])
        timeline.append(f"[{datetime.datetime.now().strftime('%H:%M')}] ☀️ 프리마켓 우량주(FA) {len(fa_candidates)}개 발굴 완료")
        dashboard_state["timeline"] = timeline[-5:] # 최근 5개 유지
        
        with open("logs/dashboard_state.json", "w", encoding="utf-8") as f:
            json.dump(dashboard_state, f, ensure_ascii=False, indent=2)
            
        # DB 동기화
        self._sync_universe_to_db(fa_candidates, ohlcv_store)
            
        return fa_candidates

    def run_daily_batch(self):
        logging.info(f"[{datetime.datetime.now()}] 실전 매매 배치 시작 (Intraday)")
        
        # 1. 잔고 조회
        balance_info = self.broker.get_balance()
        cash = balance_info['cash']
        positions = balance_info['positions']
        
        # 2026-07-09 하루만 장 초반(09:00 이후)에 포지션을 자동 청산(현금화)하는 일회성 트리거
        today_str = datetime.date.today().strftime('%Y-%m-%d')
        flag_file = "logs/liquidated_20260709.flag"
        if today_str == "2026-07-09":
            if not os.path.exists(flag_file):
                now = datetime.datetime.now()
                if now.hour >= 9:
                    logging.info("[일회성 자동 청산] 2026-07-09 아침 전체 포지션 강제 현금화 실행!")
                    sell_orders = []
                    for ticker, pos in positions.items():
                        sell_orders.append({
                            "type": "SELL",
                            "ticker": ticker,
                            "qty": pos['qty'],
                            "reason": "ONETIME_AUTO_LIQUIDATION_20260709"
                        })
                    if sell_orders:
                        self._execute_orders(sell_orders)
                        # 대기 후 잔고 재조회
                        import time
                        time.sleep(2)
                        balance_info = self.broker.get_balance()
                        cash = balance_info['cash']
                        positions = balance_info['positions']
                    
                    # 플래그 작성하여 두 번 실행 방지
                    try:
                        with open(flag_file, "w") as f:
                            f.write(f"Liquidated at {now}\n")
                    except Exception as e:
                        logging.error(f"청산 플래그 생성 실패: {e}")
        else:
            # 2026-07-09가 지난 다른 날에는 플래그 파일이 존재하면 자동으로 청소 삭제
            if os.path.exists(flag_file):
                try:
                    os.remove(flag_file)
                    logging.info("[일회성 자동 청산] 사용 완료된 청산 플래그 파일(.flag) 자동 청소 완료.")
                except Exception as e:
                    logging.error(f"청산 플래그 파일 삭제 실패: {e}")
                    
        logging.info(f"현재 예수금: {cash:,.0f}원")
        logging.info(f"보유 종목: {list(positions.keys())}")
        
        # 총 자산 — API의 tot_evlu_amt를 우선 사용 (D+2 결제분까지 정확히 포함)
        # 없을 경우 예수금 + 평가금액 합산으로 대체
        total_eval = balance_info.get("total_asset") or (cash + sum(p['qty'] * p['current_price'] for p in positions.values()))
        logging.info(f"총 자산 추정치: {total_eval:,.0f}원")
        
        # DB 동기화
        self._sync_balance_and_positions(balance_info, total_eval)
        
        # 대시보드 표시용 상태 업데이트
        if not os.path.exists("logs"):
            os.makedirs("logs", exist_ok=True)
        dashboard_state = {"timeline": []}
        if os.path.exists("logs/dashboard_state.json"):
            try:
                with open("logs/dashboard_state.json", "r", encoding="utf-8") as f:
                    dashboard_state = json.load(f)
            except: pass
            
        dashboard_state["updated_at"] = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        dashboard_state["cash"] = cash
        dashboard_state["total_eval"] = total_eval
        dashboard_state["positions"] = list(positions.keys())
        
        with open("logs/dashboard_state.json", "w", encoding="utf-8") as f:
            json.dump(dashboard_state, f, ensure_ascii=False, indent=2)
            
        # ponytail: append to csv for timeseries tracking
        with open("logs/asset_timeseries.csv", "a", encoding="utf-8") as f:
            f.write(f"{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')},{total_eval}\n")
        
        # 2. 데이터 로드 (최근 150일)
        end_date = datetime.datetime.now().strftime('%Y-%m-%d')
        start_date = (datetime.datetime.now() - datetime.timedelta(days=200)).strftime('%Y-%m-%d')
        
        try:
            with open("logs/fa_candidates.json", "r", encoding="utf-8") as f:
                fa_candidates = json.load(f)
        except:
            fa_candidates = list(get_kospi_top_n(200).keys())
            
        tickers = list(set(fa_candidates + list(positions.keys())))
        
        logging.info(f"[데이터 로드] 관심 종목 + 보유 종목 ({len(tickers)}개) 초고속 병합 중...")
        ohlcv_store = download_multiple_stocks(tickers, start=start_date, end=end_date, show_progress=False)
        ohlcv_store = enrich_ohlcv_with_fa(self.db, ohlcv_store, end_date)
        self.last_ohlcv_store = ohlcv_store
        
        # 3. 시그널 생성 및 타겟 비중 산출
        print("[시그널 생성] 전 종목 전략 평가 중...")
        target_positions = {}
        
        # KOSPI 200MA 기준 시장 국면 판단 (루프 밖에서 1회만 계산)
        # ponytail: download_kospi_index가 ^KS11 전용 함수, download_multiple_stocks는 .KS suffix 필요
        try:
            start_date_kospi = (datetime.datetime.now() - datetime.timedelta(days=320)).strftime('%Y-%m-%d')
            kospi_close = download_kospi_index(start_date_kospi, end_date)
            if len(kospi_close) >= 200:
                ma200 = kospi_close.rolling(200).mean()
                market_regime = "UPTREND" if kospi_close.iloc[-1] > ma200.iloc[-1] else "DOWNTREND"
            elif len(kospi_close) >= 60:
                ma200 = kospi_close.rolling(200, min_periods=60).mean()
                market_regime = "UPTREND" if kospi_close.iloc[-1] > ma200.iloc[-1] else "DOWNTREND"
            else:
                market_regime = "SIDEWAYS"
        except Exception as e:
            logging.warning(f"KOSPI 지수 다운로드 실패: {e}. SIDEWAYS로 처리.")
            market_regime = "SIDEWAYS"
        # 기업 위험 상태(매수 차단 종목) 조회
        from storage.postgres.repositories.company_risk_repo import fetch_buy_blocked_stock_codes
        try:
            blocked_codes = fetch_buy_blocked_stock_codes(self.db, datetime.date.today())
        except Exception as e:
            logging.error(f"기업 위험 상태 조회 실패: {e}")
            blocked_codes = set()
            
        for ticker, df in ohlcv_store.items():
            if df.empty or len(df) < 60:
                continue
                
            regime_df = pd.DataFrame(index=df.index)
            regime_df["REGIME"] = market_regime
            
            # 여기서 과거 포지션 상태를 유지해야 하지만, 당일 시그널만 보기 위해 초기 상태로 평가
            # 실제로는 이전에 매수한 종목인지 여부를 state에 반영해야 함
            signals = self.strategy.make_signals(df, regime_df, state=None)
            
            if not signals.empty:
                # ponytail: 전략이 신규 매수/매도 시점에만 스파스하게 값을 채우고 평상시(유지일)에는 NaN을 내보내므로,
                # ffill()을 사용하여 현재 시점의 활성 보유 비중을 정상적으로 복원시킵니다.
                signals = signals.ffill().fillna(0.0)
                target_weight = float(signals.iloc[-1])
                symbol = ticker.split('.')[0]
                
                # 기업 위험 상태(BLOCK_BUY/SELL_ONLY)로 매수 차단된 종목 신규 진입 차단
                if symbol in blocked_codes and ticker not in positions:
                    target_weight = 0.0
                
                # 보유 중인 종목인데 타겟이 0.0이면 매도 (또는 보유 중지)
                if ticker in positions and target_weight == 0.0:
                    target_positions[ticker] = 0.0
                # 신규 진입 시그널
                elif target_weight > 0.0:
                    target_positions[ticker] = target_weight
                    
        # 이미 보유 중인데 target_positions에 안 뜬 종목은 계속 홀딩 (target_weight == 기존 비중)
        for ticker in positions.keys():
            if ticker not in target_positions:
                target_positions[ticker] = self.strategy.ENTRY_SIZE # 기본 비중 유지
                
        print(f"[타겟 산출 완료] 타겟 포지션 수: {len(target_positions)}개")
        
        # 4. 주문 실행 (주식 수 계산 및 API 전송)
        orders = self._calculate_orders(total_eval, positions, target_positions, ohlcv_store)
        # 타임라인 업데이트 (장중)
        buy_count = sum(1 for o in orders if o['type'] == 'BUY')
        sell_count = sum(1 for o in orders if o['type'] == 'SELL')
        
        dashboard_state = {"timeline": []}
        if os.path.exists("logs/dashboard_state.json"):
            try:
                with open("logs/dashboard_state.json", "r", encoding="utf-8") as f:
                    dashboard_state = json.load(f)
            except: pass
            
        timeline = dashboard_state.setdefault("timeline", [])
        timeline.append(f"[{datetime.datetime.now().strftime('%H:%M')}] ⚡ 장중 매매 완료: 신규매수 {buy_count}건 / 손절·익절 {sell_count}건")
        dashboard_state["timeline"] = timeline[-5:]
        
        with open("logs/dashboard_state.json", "w", encoding="utf-8") as f:
            json.dump(dashboard_state, f, ensure_ascii=False, indent=2)
            
        print(f"[{datetime.datetime.now()}] 배치 종료")
        return orders
        
    def _calculate_orders(self, total_eval, current_positions, target_positions, ohlcv_store):
        """현재 비중과 타겟 비중을 비교하여 실제 매수/매도할 주식 수 계산"""
        orders = []
        
        # 1. 매도 주문 먼저 계산 (현금 확보)
        for ticker, pos in current_positions.items():
            target_weight = target_positions.get(ticker, 0.0)
            if target_weight == 0.0:
                # 전량 매도
                orders.append({
                    "type": "SELL",
                    "ticker": ticker,
                    "qty": pos['qty'],
                    "reason": "DOWNTREND or OVERVALUED or MOMENTUM_LOSS"
                })
                
        # 2. 매수 주문 계산
        for ticker, weight in target_positions.items():
            if weight > 0.0 and ticker not in current_positions:
                if ticker not in ohlcv_store or ohlcv_store[ticker].empty:
                    continue
                current_price = ohlcv_store[ticker].iloc[-1]['close']
                if current_price <= 0:
                    continue
                    
                target_amount = total_eval * weight
                target_qty = int(target_amount // current_price)
                
                if target_qty > 0:
                    orders.append({
                        "type": "BUY",
                        "ticker": ticker,
                        "qty": target_qty,
                        "reason": "FA+TA MOMENTUM ENTRY"
                    })
                    
        return orders
        
    def _execute_orders(self, orders):
        for order in orders:
            ticker = order['ticker']
            qty = order['qty']
            action = order['type']
            
            print(f"[주문 실행] {action} {ticker} 수량: {qty}주 (사유: {order['reason']})")
            
            current_price = None
            if hasattr(self, 'last_ohlcv_store') and ticker in self.last_ohlcv_store and not self.last_ohlcv_store[ticker].empty:
                current_price = float(self.last_ohlcv_store[ticker].iloc[-1]['close'])
            
            # DB 주문 데이터 생성
            from storage.postgres.repositories.order_repo import create_order, attach_broker_order_id, update_order_status
            order_id = None
            try:
                order_id = create_order(self.db, {
                    "symbol": ticker,
                    "order_side_code": action,
                    "strategy_name": self.strategy_name,
                    "qty": qty,
                    "price": current_price,
                    "market_type_code": "KOSPI",
                    "instrument_type_code": "STOCK",
                    "order_type_code": "MARKET"
                })
            except Exception as e:
                logging.error(f"[DB 에러] 주문 기록 생성 실패: {e}")
                
            # API 호출
            try:
                if action == "BUY":
                    resp = self.broker.place_market_buy(ticker, qty)
                else:
                    resp = self.broker.place_market_sell(ticker, qty)
                print(f" -> 결과: {resp}")
                
                # DB 주문 연동 업데이트
                if resp and isinstance(resp, dict) and order_id:
                    rt_cd = resp.get("rt_cd")
                    output = resp.get("output", {})
                    odno = output.get("ODNO") if isinstance(output, dict) else None
                    
                    if rt_cd == '0' and odno:
                        attach_broker_order_id(self.db, order_id, odno, resp)
                        # 시장가는 실시간 즉시 전량 체결로 간주
                        update_order_status(self.db, order_id, "FILLED", filled_qty=qty, avg_fill_price=current_price, note="시장가 주문 접수 및 즉시 체결 완료")
                    else:
                        msg = resp.get("msg1", "주문 제출 거부됨")
                        update_order_status(self.db, order_id, "REJECTED", note=msg)
            except Exception as e:
                print(f" -> [에러] 주문 실패: {e}")
                if order_id:
                    try:
                        update_order_status(self.db, order_id, "REJECTED", note=str(e))
                    except: pass

    def _sync_balance_and_positions(self, balance_info, total_eval):
        cash = balance_info['cash']
        positions = balance_info['positions']
        stock_value = total_eval - cash
        
        # 1. balance_history 저장
        from storage.postgres.repositories.balance_repo import insert_balance_history
        try:
            insert_balance_history(self.db, self.strategy_name, {
                "cash": cash,
                "stock_value": stock_value,
                "total_value": total_eval,
                "date": datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            })
            logging.info(f"[DB 동기화] balance_history 기록 완료")
        except Exception as e:
            logging.error(f"[DB 동기화 에러] balance_history 기록 실패: {e}")
            
        # 2. positions 테이블 저장
        from storage.postgres.repositories.position_repo import upsert_position, zero_out_position, fetch_active_position_symbols
        try:
            db_symbols = fetch_active_position_symbols(self.db, self.strategy_name)
            
            for symbol, pos in positions.items():
                upsert_position(self.db, self.strategy_name, symbol, {
                    "qty": pos["qty"],
                    "avg_cost": pos["avg_price"],
                    "market_type_code": "KOSPI",
                    "instrument_type_code": "STOCK"
                })
                
            for db_symbol in db_symbols:
                if db_symbol not in positions:
                    zero_out_position(self.db, self.strategy_name, db_symbol)
            logging.info(f"[DB 동기화] positions 테이블 갱신 완료")
        except Exception as e:
            logging.error(f"[DB 동기화 에러] positions 테이블 갱신 실패: {e}")

    def _sync_universe_to_db(self, fa_candidates, ohlcv_store):
        try:
            strategy = self.db.fetch_one(
                "SELECT id FROM strategies WHERE name = %s",
                (self.strategy_name,)
            )
            if not strategy:
                logging.error(f"[DB 에러] 전략 {self.strategy_name}을 찾을 수 없습니다.")
                return
            strategy_id = strategy["id"]
            
            current_rows = self.db.fetch_all(
                "SELECT symbol FROM universe WHERE strategy_id = %s AND universe_status_code = 'ACTIVE'",
                (strategy_id,)
            )
            active_symbols = {r["symbol"] for r in current_rows}
            
            today = datetime.date.today()
            
            for ticker in fa_candidates:
                symbol = ticker.split('.')[0]
                fa_score = None
                if ohlcv_store and ticker in ohlcv_store and not ohlcv_store[ticker].empty:
                    fa_score = ohlcv_store[ticker].iloc[-1].get('fa_score', None)
                    if pd.notnull(fa_score):
                        fa_score = float(fa_score)
                    else:
                        fa_score = None
                
                self.db.execute(
                    """
                    INSERT INTO universe (
                        strategy_id, symbol, market_type_code, instrument_type_code,
                        universe_status_code, fa_score, entry_date
                    )
                    VALUES (%s, %s, 'KOSPI', 'STOCK', 'ACTIVE', %s, %s)
                    ON CONFLICT (strategy_id, symbol)
                    DO UPDATE SET
                        universe_status_code = 'ACTIVE',
                        fa_score = COALESCE(EXCLUDED.fa_score, universe.fa_score),
                        updated_at = NOW()
                    """,
                    (strategy_id, symbol, fa_score, today)
                )
                
            balance_info = self.broker.get_balance()
            held_symbols = set(balance_info.get('positions', {}).keys())
            
            candidates_symbols = {t.split('.')[0] for t in fa_candidates}
            
            for old_symbol in active_symbols:
                if old_symbol not in candidates_symbols:
                    new_status = 'SELL_ONLY' if old_symbol in held_symbols else 'REMOVED'
                    self.db.execute(
                        """
                        UPDATE universe
                        SET universe_status_code = %s, updated_at = NOW()
                        WHERE strategy_id = %s AND symbol = %s
                        """,
                        (new_status, strategy_id, old_symbol)
                    )
            logging.info("[DB 동기화] universe 테이블 갱신 완료")
        except Exception as e:
            logging.error(f"[DB 동기화 에러] universe 테이블 갱신 실패: {e}")
