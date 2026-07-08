import logging
import pandas as pd
from typing import Dict, List
import datetime
from data.loaders.kospi_data import get_kospi_top_n, download_multiple_stocks
from data.loaders.fa_ta_loader import enrich_ohlcv_with_fa
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
            "entry_size": 0.2, # 최대 5종목 분산
            "ma_window": 60,   # 60일선 돌파 모멘텀
            "ma_fast": 10, 
            "per_buy": 15.0,
            "roe_min": 0.05
        }
        self.strategy = FaTaMomentumStrategy(strategy_params)
        
    def run_premarket_batch(self):
        logging.info(f"[{datetime.datetime.now()}] 프리마켓 FA 필터링 시작")
        universe = get_kospi_top_n(200)
        tickers = list(universe.keys())
        end_date = datetime.datetime.now().strftime('%Y-%m-%d')
        start_date = (datetime.datetime.now() - datetime.timedelta(days=200)).strftime('%Y-%m-%d')
        
        ohlcv_store = download_multiple_stocks(tickers, start=start_date, end=end_date, show_progress=False)
        ohlcv_store = enrich_ohlcv_with_fa(self.db, ohlcv_store, end_date)
        
        import numpy as np
        fa_candidates = []
        for ticker, df in ohlcv_store.items():
            if df.empty or 'per_proxy' not in df.columns or 'roe' not in df.columns: continue
            last_row = df.iloc[-1]
            per = last_row.get('per_proxy', np.nan)
            roe = last_row.get('roe', np.nan)
            if pd.notnull(per) and pd.notnull(roe) and 0 < per < self.strategy.PER_THRESHOLD_BUY and roe > self.strategy.ROE_MIN:
                fa_candidates.append(ticker)
        
        import json, os
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
            
        return fa_candidates

    def run_daily_batch(self):
        logging.info(f"[{datetime.datetime.now()}] 실전 매매 배치 시작 (Intraday)")
        
        # 1. 잔고 조회
        balance_info = self.broker.get_balance()
        cash = balance_info['cash']
        positions = balance_info['positions']
        logging.info(f"현재 예수금: {cash:,.0f}원")
        logging.info(f"보유 종목: {list(positions.keys())}")
        
        # 총 자산 (예수금 + 평가금액)
        total_eval = cash + sum(p['qty'] * p['current_price'] for p in positions.values())
        logging.info(f"총 자산 추정치: {total_eval:,.0f}원")
        
        # 대시보드 표시용 상태 업데이트 (전광판 모드용)
        import json, os
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
        
        import json
        try:
            with open("logs/fa_candidates.json", "r", encoding="utf-8") as f:
                fa_candidates = json.load(f)
        except:
            fa_candidates = list(get_kospi_top_n(200).keys())
            
        tickers = list(set(fa_candidates + list(positions.keys())))
        
        logging.info(f"[데이터 로드] 관심 종목 + 보유 종목 ({len(tickers)}개) 초고속 병합 중...")
        ohlcv_store = download_multiple_stocks(tickers, start=start_date, end=end_date, show_progress=False)
        ohlcv_store = enrich_ohlcv_with_fa(self.db, ohlcv_store, end_date)
        
        # 3. 시그널 생성 및 타겟 비중 산출
        print("[시그널 생성] 전 종목 전략 평가 중...")
        target_positions = {}
        
        for ticker, df in ohlcv_store.items():
            if df.empty or len(df) < 60:
                continue
                
            # 가짜 regime_df (라이브러리 외부 의존성을 줄이기 위해 일단 횡보장으로 간주, 향후 시장 레짐 적용 가능)
            regime_df = pd.DataFrame(index=df.index)
            regime_df["REGIME"] = "UPTREND" # 임시로 항상 UPTREND 가정 (또는 별도 지수 데이터로 판별 가능)
            
            # 여기서 과거 포지션 상태를 유지해야 하지만, 당일 시그널만 보기 위해 초기 상태로 평가
            # 실제로는 이전에 매수한 종목인지 여부를 state에 반영해야 함
            signals = self.strategy.make_signals(df, regime_df, state=None)
            
            if not signals.empty:
                target_weight = float(signals.iloc[-1])
                
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
            
            # API 호출
            try:
                if action == "BUY":
                    resp = self.broker.place_market_buy(ticker, qty)
                else:
                    resp = self.broker.place_market_sell(ticker, qty)
                print(f" -> 결과: {resp}")
            except Exception as e:
                print(f" -> [에러] 주문 실패: {e}")
