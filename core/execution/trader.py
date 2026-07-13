import logging
import json
import os
import pandas as pd
import datetime
import hashlib
from zoneinfo import ZoneInfo
from pathlib import Path
from data.loaders.kospi_data import download_multiple_stocks, download_kospi_index
from data.loaders.fa_ta_loader import enrich_ohlcv_with_fa
from apps.worker.fa_contract import DEFAULT_CONFIG as FA_CONTRACT
from storage.postgres.connection import PostgreDB
from core.strategy.fa_ta_momentum import FaTaMomentumStrategy
from core.broker.kis_api import BrokerResponseError, KisBroker, normalize_symbol
from core.broker.simulation import LocalSimulationBroker
from core.utils.trading_calendar import previous_krx_trading_day

class LiveTrader:
    def __init__(self, mock=True, simulate=False, dry_run=False):
        self.broker = LocalSimulationBroker() if simulate else KisBroker(mock=mock)
        db_config = {
            'host': os.getenv('POSTGRES_HOST', 'localhost'),
            'port': int(os.getenv('POSTGRES_PORT', '5433')),
            'user': os.getenv('POSTGRES_USER', 'admin'),
            'password': os.getenv('POSTGRES_PASSWORD', ''),
            'database': os.getenv('POSTGRES_DB', 'quantpilot_db')
        }
        if not db_config['password']:
            raise ValueError("POSTGRES_PASSWORD 환경변수가 필요합니다.")
        self.db = PostgreDB(db_config)
        self.max_price_deviation = float(os.getenv("MAX_PRICE_DEVIATION", "0.02"))
        self.buy_cash_buffer = float(os.getenv("BUY_CASH_BUFFER", "1.03"))
        self.max_order_attempts = int(os.getenv("MAX_ORDER_ATTEMPTS", "2"))
        self.fill_poll_attempts = int(os.getenv("KIS_FILL_POLL_ATTEMPTS", "5"))
        self.fill_poll_interval = float(os.getenv("KIS_FILL_POLL_INTERVAL", "1"))
        self.unknown_order_grace_seconds = int(
            os.getenv("KIS_UNKNOWN_ORDER_GRACE_SECONDS", "300")
        )
        self.allow_warning_fa_run = os.getenv("ALLOW_WARNING_FA_RUN", "false").lower() == "true"
        if not 0 <= self.max_price_deviation <= 0.20:
            raise ValueError("MAX_PRICE_DEVIATION은 0~0.20 범위여야 합니다.")
        if not 1.0 <= self.buy_cash_buffer <= 1.20:
            raise ValueError("BUY_CASH_BUFFER는 1.0~1.20 범위여야 합니다.")
        if self.max_order_attempts < 1 or self.fill_poll_attempts < 1:
            raise ValueError("주문/체결 시도 횟수는 1 이상이어야 합니다.")
        if self.fill_poll_interval < 0:
            raise ValueError("KIS_FILL_POLL_INTERVAL은 0 이상이어야 합니다.")

        # 최적화된 파라미터 적용
        strategy_params = {
            "entry_size": 0.18,     # 5종목 분산 (5 * 18% = 90% 비중, 10% 현금 유지)
            "ma_window": 60,        # 60일선 돌파 모멘텀
            "ma_window_fast": 20,
            "fa_score_min": FA_CONTRACT.minimum_company_fa_score,
            "fa_score_exit": 40.0,  # fa_score 하락 시 매도 기준
            "debt_ratio_max": 2.0,  # 부채비율 상한 (200%)
        }
        self.strategy = FaTaMomentumStrategy(strategy_params)
        self.strategy_name = self.strategy.INVESTMENT_TYPE.name.lower()
        self.execution_venue = (
            "DRY_RUN" if dry_run else "SIMULATE" if simulate else "PAPER" if mock else "REAL"
        )
        self.log_dir = Path("logs") / self.execution_venue.lower()
        self.log_dir.mkdir(parents=True, exist_ok=True)

    def run_premarket_batch(self):
        logging.info(f"[{datetime.datetime.now()}] 프리마켓 FA 필터링 시작")
        signal_date = previous_krx_trading_day(datetime.date.today())
        published_run, published_candidates = self._load_published_fa_candidates(signal_date)
        tickers = [f"{row['stock_code']}.KS" for row in published_candidates]
        end_date = (signal_date + datetime.timedelta(days=1)).isoformat()
        start_date = (signal_date - datetime.timedelta(days=200)).isoformat()
        
        ohlcv_store = download_multiple_stocks(tickers, start=start_date, end=end_date, show_progress=False)
        ohlcv_store = enrich_ohlcv_with_fa(self.db, ohlcv_store, signal_date.isoformat())
        ohlcv_store = self._filter_stale_data(ohlcv_store, signal_date)
        
        # 기업 위험 상태(매수 차단 종목) 조회
        from storage.postgres.repositories.company_risk_repo import fetch_buy_blocked_stock_codes
        try:
            blocked_codes = fetch_buy_blocked_stock_codes(self.db, datetime.date.today())
        except Exception as e:
            raise RuntimeError(f"기업 위험 상태 조회 실패로 프리마켓을 중단합니다: {e}") from e

        candidate_by_symbol = {row["stock_code"]: row for row in published_candidates}
        fa_candidates = []
        for ticker, df in ohlcv_store.items():
            if df.empty or 'fa_score' not in df.columns:
                continue

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
                symbol in candidate_by_symbol and
                is_eligible and
                fa_score is not None and float(fa_score) >= self.strategy.FA_SCORE_MIN and
                (debt_ratio is None or float(debt_ratio) <= self.strategy.DEBT_RATIO_MAX)
            ):
                fa_candidates.append(ticker)
        
        os.makedirs("logs", exist_ok=True)
        with open("logs/fa_candidates.json", "w", encoding="utf-8") as f:
            json.dump({
                "source": "published_fa",
                "run_id": published_run["id"],
                "signal_date": signal_date.isoformat(),
                "tickers": fa_candidates,
            }, f, ensure_ascii=False, indent=2)
        logging.info(f"프리마켓 FA 필터링 완료. 관심 종목 {len(fa_candidates)}개 저장.")
        
        # 타임라인 업데이트
        dashboard_path = self.log_dir / "dashboard_state.json"
        dashboard_state = {"timeline": []}
        if dashboard_path.exists():
            try:
                with dashboard_path.open("r", encoding="utf-8") as f:
                    dashboard_state = json.load(f)
            except (OSError, ValueError, TypeError) as e:
                logging.warning(f"대시보드 상태 로드 실패: {e}")
        
        timeline = dashboard_state.setdefault("timeline", [])
        timeline.append(f"[{datetime.datetime.now().strftime('%H:%M')}] ☀️ 프리마켓 우량주(FA) {len(fa_candidates)}개 발굴 완료")
        dashboard_state["timeline"] = timeline[-5:] # 최근 5개 유지
        
        with dashboard_path.open("w", encoding="utf-8") as f:
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
        
        # 총 자산 — API의 tot_evlu_amt를 우선 사용 (D+2 결제분까지 정확히 포함)
        # 없을 경우 예수금 + 평가금액 합산으로 대체
        total_eval = balance_info.get("total_asset") or (cash + sum(p['qty'] * p['current_price'] for p in positions.values()))
        logging.info(f"총 자산 추정치: {total_eval:,.0f}원")
        
        # Local simulation state is isolated from operational order/position tables.
        if not getattr(self.broker, "is_simulated", False):
            self._sync_balance_and_positions(balance_info, total_eval)
            self._reconcile_open_orders(positions)
            self._assert_no_unresolved_orders()
        
        # 대시보드 표시용 상태 업데이트
        if not os.path.exists("logs"):
            os.makedirs("logs", exist_ok=True)
        dashboard_path = self.log_dir / "dashboard_state.json"
        dashboard_state = {"timeline": []}
        if dashboard_path.exists():
            try:
                with dashboard_path.open("r", encoding="utf-8") as f:
                    dashboard_state = json.load(f)
            except (OSError, ValueError, TypeError) as e:
                logging.warning(f"대시보드 상태 로드 실패: {e}")
            
        # 누적 슬리피지 합산 조회
        try:
            row = self.db.fetch_one("SELECT SUM(slippage) as total FROM executions")
            total_slippage = float(row['total'] or 0.0) if row else 0.0
        except Exception as e:
            logging.warning(f"누적 슬리피지 조회 실패: {e}")
            total_slippage = 0.0
            
        dashboard_state["updated_at"] = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        dashboard_state["cash"] = cash
        dashboard_state["total_eval"] = total_eval
        dashboard_state["positions"] = list(positions.keys())
        dashboard_state["total_slippage"] = total_slippage
        
        with dashboard_path.open("w", encoding="utf-8") as f:
            json.dump(dashboard_state, f, ensure_ascii=False, indent=2)
            
        # ponytail: append to csv for timeseries tracking
        self._append_account_history(balance_info, total_eval)
        
        # 2. 데이터 로드 (최근 150일)
        signal_date = previous_krx_trading_day(datetime.date.today())
        end_date = (signal_date + datetime.timedelta(days=1)).isoformat()
        start_date = (signal_date - datetime.timedelta(days=200)).isoformat()
        
        try:
            with open("logs/fa_candidates.json", "r", encoding="utf-8") as f:
                candidate_payload = json.load(f)
            if candidate_payload.get("source") != "published_fa":
                raise ValueError("legacy/unverified FA candidate file")
            if candidate_payload.get("signal_date") != signal_date.isoformat():
                raise ValueError(
                    "FA candidate signal_date mismatch: "
                    f"expected={signal_date.isoformat()}, "
                    f"actual={candidate_payload.get('signal_date')}"
                )
            fa_candidates = list(candidate_payload.get("tickers", []))
        except (OSError, ValueError, TypeError) as e:
            # 프리마켓 결과가 없으면 신규 매수를 허용하지 않고 보유 종목만 평가한다.
            logging.error(f"FA 후보 파일 로드 실패로 신규 매수를 차단합니다: {e}")
            fa_candidates = []
            
        tickers = list(set(fa_candidates + list(positions.keys())))
        
        logging.info(f"[데이터 로드] 관심 종목 + 보유 종목 ({len(tickers)}개) 초고속 병합 중...")
        ohlcv_store = download_multiple_stocks(tickers, start=start_date, end=end_date, show_progress=False)
        ohlcv_store = enrich_ohlcv_with_fa(self.db, ohlcv_store, signal_date.isoformat())
        ohlcv_store = self._filter_stale_data(ohlcv_store, signal_date)
        self.last_ohlcv_store = ohlcv_store
        
        # 3. 시그널 생성 및 타겟 비중 산출
        print("[시그널 생성] 전 종목 전략 평가 중...")
        target_positions = {}
        
        # KOSPI 200MA 기준 시장 국면 이력. 조회 실패 시 신규 주문을 중단한다.
        try:
            start_date_kospi = (signal_date - datetime.timedelta(days=320)).isoformat()
            kospi_close = download_kospi_index(start_date_kospi, end_date)
            if len(kospi_close) < 200:
                raise ValueError("KOSPI 200일 이동평균 계산 데이터 부족")
            ma200 = kospi_close.rolling(200, min_periods=200).mean()
            market_regimes = pd.Series("TRANSITION", index=kospi_close.index, dtype=object)
            market_regimes.loc[kospi_close > ma200] = "UPTREND"
            market_regimes.loc[kospi_close <= ma200] = "DOWNTREND"
            market_regime = str(market_regimes.iloc[-1])
        except Exception as e:
            raise RuntimeError(f"KOSPI 시장 국면 계산 실패로 주문을 중단합니다: {e}") from e
        # 기업 위험 상태(매수 차단 종목) 조회
        from storage.postgres.repositories.company_risk_repo import fetch_buy_blocked_stock_codes
        try:
            blocked_codes = fetch_buy_blocked_stock_codes(self.db, datetime.date.today())
        except Exception as e:
            raise RuntimeError(f"기업 위험 상태 조회 실패로 신규 주문 계산을 중단합니다: {e}") from e
            
        target_details = {}
        for ticker, df in ohlcv_store.items():
            if df.empty or len(df) < 60:
                continue

            pos = positions.get(ticker)
            current_weight = (
                pos["qty"] * pos["current_price"] / total_eval
                if pos and total_eval > 0 else 0.0
            )
            target_weight, metadata = self.strategy.evaluate_latest(
                df, market_regime, current_position=current_weight
            )
            symbol = ticker.split('.')[0]
            if symbol in blocked_codes and ticker not in positions:
                target_weight = 0.0
            target_positions[ticker] = target_weight
            target_details[ticker] = metadata
                    
        # 이미 보유 중인데 target_positions에 안 뜬 종목은 계속 홀딩 (target_weight == 기존 비중)
        for ticker in positions.keys():
            if ticker not in target_positions:
                pos = positions[ticker]
                current_weight = (
                    pos["qty"] * pos["current_price"] / total_eval
                    if total_eval > 0 else 0.0
                )
                target_positions[ticker] = current_weight
                target_details[ticker] = {
                    "fa_score": 0.0,
                    "momentum": -1.0,
                    "signal_reason": "DATA_UNAVAILABLE_HOLD",
                }

        target_positions = self._apply_portfolio_limits(
            target_positions, target_details, positions
        )
        self._write_decision_snapshot(
            total_eval, positions, target_positions, target_details, market_regime
        )
                
        print(f"[타겟 산출 완료] 타겟 포지션 수: {len([t for t, w in target_positions.items() if w > 0.0])}개")
        
        # 4. 주문 실행 (주식 수 계산 및 API 전송)
        orders = self._calculate_orders(
            total_eval, positions, target_positions, ohlcv_store, target_details
        )
        print(f"[{datetime.datetime.now()}] 배치 종료")
        return orders

    def update_intraday_dashboard(self, execution_results):
        """Record broker outcomes, not pre-execution order candidates."""
        results = list(execution_results or [])
        dashboard_path = self.log_dir / "dashboard_state.json"
        dashboard_state = {"timeline": []}
        if dashboard_path.exists():
            try:
                with dashboard_path.open("r", encoding="utf-8") as f:
                    dashboard_state = json.load(f)
            except (OSError, ValueError, TypeError) as exc:
                logging.warning(f"대시보드 상태 로드 실패: {exc}")

        if self.execution_venue == "DRY_RUN":
            buy_count = sum(row.get("type") == "BUY" for row in results)
            sell_count = sum(row.get("type") == "SELL" for row in results)
            summary = f"모의계산: 매수후보 {buy_count}건 / 매도후보 {sell_count}건"
        else:
            filled = {"FILLED"}
            open_statuses = {"PARTIAL", "ACCEPTED", "SUBMITTED", "UNKNOWN"}
            skipped_statuses = {"SKIPPED", "REJECTED", "CANCELLED"}
            buy_filled = sum(
                row.get("type") == "BUY" and row.get("status") in filled
                for row in results
            )
            sell_filled = sum(
                row.get("type") == "SELL" and row.get("status") in filled
                for row in results
            )
            open_count = sum(row.get("status") in open_statuses for row in results)
            skipped_count = sum(row.get("status") in skipped_statuses for row in results)
            summary = (
                f"장중 결과: 매수체결 {buy_filled}건 / 매도체결 {sell_filled}건 / "
                f"부분·대기 {open_count}건 / 건너뜀 {skipped_count}건"
            )

        timeline = dashboard_state.setdefault("timeline", [])
        timeline.append(f"[{datetime.datetime.now().strftime('%H:%M')}] ⚡ {summary}")
        dashboard_state["timeline"] = timeline[-5:]
        with dashboard_path.open("w", encoding="utf-8") as f:
            json.dump(dashboard_state, f, ensure_ascii=False, indent=2)

    def _write_decision_snapshot(
        self, total_eval, positions, target_positions, target_details, market_regime
    ):
        rows = []
        for ticker in sorted(set(positions) | set(target_positions)):
            pos = positions.get(ticker, {})
            current_weight = (
                float(pos.get("qty", 0)) * float(pos.get("current_price", 0)) / total_eval
                if total_eval > 0 else 0.0
            )
            detail = target_details.get(ticker, {})
            rows.append({
                "ticker": ticker,
                "current_weight": round(current_weight, 6),
                "target_weight": round(float(target_positions.get(ticker, 0.0)), 6),
                "signal_reason": detail.get("signal_reason", "UNKNOWN"),
                "fa_score": detail.get("fa_score"),
                "momentum": detail.get("momentum"),
                "selected": float(target_positions.get(ticker, 0.0)) > 0.0,
            })
        payload = {
            "updated_at": datetime.datetime.now().isoformat(timespec="seconds"),
            "mode": self.execution_venue,
            "strategy": self.strategy_name,
            "market_regime": market_regime,
            "target_count": sum(row["selected"] for row in rows),
            "decisions": rows,
        }
        state_path = self.log_dir / "decision_state.json"
        temp_path = self.log_dir / "decision_state.json.tmp"
        with temp_path.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, default=str)
        os.replace(temp_path, state_path)
        with (self.log_dir / "decision_history.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")

    def _append_account_history(self, balance_info, total_eval):
        path = self.log_dir / "account_history.csv"
        if not path.exists():
            path.write_text(
                "timestamp,mode,cash,total_asset,position_count\n",
                encoding="utf-8",
            )
        with path.open("a", encoding="utf-8") as handle:
            handle.write(
                f"{datetime.datetime.now().isoformat(timespec='seconds')},"
                f"{self.execution_venue},{float(balance_info['cash']):.4f},"
                f"{float(total_eval):.4f},{len(balance_info.get('positions', {}))}\n"
            )

    def append_trade_history(self, results):
        if not results:
            return
        path = self.log_dir / "trade_history.jsonl"
        timestamp = datetime.datetime.now().isoformat(timespec="seconds")
        with path.open("a", encoding="utf-8") as handle:
            for result in results:
                payload = {
                    "timestamp": timestamp,
                    "mode": self.execution_venue,
                    "strategy": self.strategy_name,
                    **result,
                }
                handle.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")

    def _apply_portfolio_limits(self, targets, details, positions):
        """Allocate 90% exposure by FA conviction above the entry threshold."""
        result = dict(targets)
        active = [ticker for ticker, weight in result.items() if weight > 0]
        protected = {
            ticker
            for ticker in active
            if details.get(ticker, {}).get("signal_reason") == "DATA_UNAVAILABLE_HOLD"
        }
        protected_total = sum(result[ticker] for ticker in protected)
        allocatable = [ticker for ticker in active if ticker not in protected]
        allocation_budget = max(0.90 - protected_total, 0.0)
        fa_scores = {
            ticker: max(
                float(details.get(ticker, {}).get("fa_score") or 0.0)
                - float(FA_CONTRACT.minimum_company_fa_score),
                0.0,
            )
            for ticker in allocatable
        }
        score_total = sum(fa_scores.values())
        if allocatable:
            if score_total > 0:
                raw_weights = {
                    ticker: allocation_budget * fa_scores[ticker] / score_total
                    for ticker in allocatable
                }
            else:
                equal_weight = allocation_budget / len(allocatable)
                raw_weights = {ticker: equal_weight for ticker in allocatable}
            assigned = 0.0
            ordered = sorted(allocatable)
            for ticker in ordered[:-1]:
                result[ticker] = round(raw_weights[ticker], 4)
                assigned += result[ticker]
            result[ordered[-1]] = round(max(allocation_budget - assigned, 0.0), 4)
        return result
        
    def _calculate_orders(
        self,
        total_eval,
        current_positions,
        target_positions,
        ohlcv_store,
        target_details=None,
    ):
        """현재 비중과 타겟 비중을 비교하여 실제 매수/매도할 주식 수 계산 (부분 매수/매도 포함 리밸런싱)"""
        orders = []
        target_details = target_details or {}
        
        # 상태 기반 중복 방지. 거부 주문은 제한 횟수 내에서만 재시도한다.
        today_str = datetime.datetime.now().strftime('%Y-%m-%d')
        if getattr(getattr(self, "broker", None), "is_simulated", False):
            rows = []
        else:
            try:
                rows = self.db.fetch_all(
                    """SELECT symbol, order_side_code, order_status_code
                       FROM orders WHERE created_at::date = %s::date""",
                    (today_str,)
                )
            except Exception as e:
                raise RuntimeError(f"당일 주문 이력 조회 실패로 주문 계산을 중단합니다: {e}") from e

        active_statuses = {'PENDING', 'SUBMITTED', 'ACCEPTED', 'PARTIAL', 'FILLED'}
        active_keys = {
            (normalize_symbol(r['symbol']), r['order_side_code'])
            for r in rows if r['order_status_code'] in active_statuses
        }
        retry_counts = {}
        for row in rows:
            if row['order_status_code'] in {'REJECTED', 'CANCELLED'}:
                key = (normalize_symbol(row['symbol']), row['order_side_code'])
                retry_counts[key] = retry_counts.get(key, 0) + 1

        def can_order(ticker, side):
            key = (normalize_symbol(ticker), side)
            if key in active_keys:
                logging.info(f"[{ticker}] 오늘 활성/체결 {side} 주문이 존재하여 스킵합니다.")
                return False
            if retry_counts.get(key, 0) >= self.max_order_attempts:
                logging.warning(f"[{ticker}] 오늘 {side} 주문 재시도 한도에 도달했습니다.")
                return False
            return True

        def add_identity(order):
            key = (normalize_symbol(order['ticker']), order['type'])
            attempt = retry_counts.get(key, 0) + 1
            venue = getattr(self, "execution_venue", "PAPER")
            raw = f"{today_str}:{self.strategy_name}:{venue}:{key[0]}:{key[1]}:{attempt}"
            order['idempotency_key'] = hashlib.sha256(raw.encode()).hexdigest()
            return order

        # 1. 매도 주문 계산 (현금 확보를 위해 먼저 실행)
        for ticker, pos in current_positions.items():
            if not can_order(ticker, 'SELL'):
                continue
            target_weight = target_positions.get(ticker, 0.0)
            current_price = ohlcv_store[ticker].iloc[-1]['close'] if ticker in ohlcv_store and not ohlcv_store[ticker].empty else pos['current_price']
            if current_price <= 0:
                continue
                
            current_value = pos['qty'] * current_price
            target_value = total_eval * target_weight
            
            if target_weight == 0.0:
                # 전량 매도
                orders.append(add_identity({
                    "type": "SELL",
                    "ticker": ticker,
                    "qty": pos['qty'],
                    "expected_price": float(current_price),
                    "reason": target_details.get(ticker, {}).get(
                        "signal_reason", "TARGET_WEIGHT_ZERO"
                    )
                }))
            elif current_value > target_value * 1.10: # 10% 이상 초과 시 부분 매도
                sell_qty = int((current_value - target_value) // current_price)
                if sell_qty > 0:
                    orders.append(add_identity({
                        "type": "SELL",
                        "ticker": ticker,
                        "qty": sell_qty,
                        "expected_price": float(current_price),
                        "reason": f"REBALANCE_WEIGHT_REDUCTION_FROM_{int(current_value/total_eval*100)}%_TO_{int(target_weight*100)}%"
                    }))
                    
        # 2. 매수 주문 계산
        for ticker, weight in target_positions.items():
            if weight <= 0.0:
                continue
            if not can_order(ticker, 'BUY'):
                continue
            if ticker not in ohlcv_store or ohlcv_store[ticker].empty:
                continue
            current_price = ohlcv_store[ticker].iloc[-1]['close']

            if current_price <= 0:
                continue
                
            target_value = total_eval * weight
            
            if ticker in current_positions:
                pos = current_positions[ticker]
                current_value = pos['qty'] * current_price
                if current_value < target_value * 0.90: # 10% 이상 부족 시 부분 매수
                    buy_qty = int((target_value - current_value) // current_price)
                    if buy_qty > 0:
                        orders.append(add_identity({
                            "type": "BUY",
                            "ticker": ticker,
                            "qty": buy_qty,
                            "expected_price": float(current_price),
                            "reason": f"REBALANCE_WEIGHT_INCREASE_TO_{int(weight*100)}%"
                        }))
            else:
                # 신규 진입
                target_qty = int(target_value // current_price)
                if target_qty > 0:
                    orders.append(add_identity({
                        "type": "BUY",
                        "ticker": ticker,
                        "qty": target_qty,
                        "expected_price": float(current_price),
                        "reason": f"FA+TA MOMENTUM ENTRY_{int(weight*100)}%"
                    }))
                    
        return orders
        
    def _execute_orders(self, orders):
        if getattr(self.broker, "is_simulated", False):
            return self._execute_simulation_orders(orders)
        import time
        from storage.postgres.repositories.order_repo import (
            DuplicateOrderError, attach_broker_order_id, create_order,
            mark_order_submitted, update_order_status,
        )
        
        # 실시간 계좌 잔고를 다시 조회하여 당일 가용 현금 획득
        try:
            balance_info = self.broker.get_balance()
            today_cash = float(balance_info.get("today_cash", balance_info.get("cash", 0.0)))
            logging.info(f"[주문 실행 전 잔고 검증] 실시간 당일 가용 예수금: {today_cash:,.0f}원")
        except Exception as e:
            raise RuntimeError(f"실시간 잔고 조회 실패로 모든 주문을 중단합니다: {e}") from e

        live_positions = balance_info.get("positions", {})
        results = []

        for order in orders:
            # ponytail: 한국투자증권 API의 모의투자 초당 거래제한(2 TPS)을 초과하지 않도록 0.6초 딜레이 부여
            time.sleep(0.6)
            ticker = order['ticker']
            qty = order['qty']
            action = order['type']
            
            try:
                if getattr(self.broker, "is_simulated", False):
                    current_price = float(order["expected_price"])
                    self.broker.set_market_price(ticker, current_price)
                else:
                    current_price = self.broker.get_current_price(ticker)
            except Exception as e:
                logging.error(f"[{ticker}] 실시간 현재가 조회 실패로 주문을 건너뜁니다: {e}")
                results.append({**order, "status": "SKIPPED", "message": str(e)})
                continue

            expected_price = float(order.get("expected_price") or current_price)
            deviation = abs(current_price - expected_price) / expected_price
            if action == "BUY" and deviation > self.max_price_deviation:
                msg = f"가격 편차 {deviation:.2%}가 허용치 {self.max_price_deviation:.2%}를 초과"
                logging.warning(f"[{ticker}] {msg}")
                results.append({**order, "status": "SKIPPED", "message": msg})
                continue

            if action == "SELL":
                held_qty = int(live_positions.get(ticker, {}).get("qty", 0))
                if held_qty <= 0:
                    results.append({**order, "status": "SKIPPED", "message": "실시간 보유수량 없음"})
                    continue
                qty = min(qty, held_qty)
                
            # 매수 시 당일 가용 예수금 검증 및 동적 조절
            if action == "BUY":
                buffered_price = current_price * self.buy_cash_buffer
                order_amount = qty * buffered_price
                if today_cash < buffered_price:
                    msg = f"당일 예수금 부족으로 주문 전송 취소 (필요 최소금액: {buffered_price:,.0f}원, 가용 현금: {today_cash:,.0f}원)"
                    logging.warning(f"[{ticker}] {msg}")
                    results.append({**order, "status": "SKIPPED", "message": msg})
                    continue
                elif today_cash < order_amount:
                    new_qty = int(today_cash // buffered_price)
                    msg = f"당일 예수금 부족으로 수량 축소 조정 ({qty}주 -> {new_qty}주, 가용 예수금: {today_cash:,.0f}원)"
                    logging.info(f"[{ticker}] {msg}")
                    qty = new_qty
                    order_amount = qty * buffered_price
                    order['qty'] = qty # 객체 수량 업데이트
                    order['reason'] += f" (수량 축소: {msg})"

            print(f"[주문 실행] {action} {ticker} 수량: {qty}주 (사유: {order['reason']})")
            
            # DB에 주문 의도를 선점하지 못하면 실제 주문을 절대 전송하지 않는다.
            order_id = None
            try:
                order_id = create_order(self.db, {
                    "symbol": normalize_symbol(ticker),
                    "order_side_code": action,
                    "strategy_name": self.strategy_name,
                    "qty": qty,
                    "price": current_price,
                    "market_type_code": "KOSPI",
                    "instrument_type_code": "STOCK",
                    "order_type_code": "MARKET",
                    "idempotency_key": order.get("idempotency_key") or self._idempotency_key(order),
                })
            except DuplicateOrderError as e:
                logging.warning(f"[{ticker}] 중복 주문 차단: {e}")
                results.append({**order, "status": "SKIPPED", "message": str(e)})
                continue
            except Exception as e:
                raise RuntimeError(f"[{ticker}] 주문 DB 선점 실패로 실행을 중단합니다: {e}") from e
                
            # SUBMITTED 전환 실패 시에는 브로커를 호출하지 않는다.
            try:
                mark_order_submitted(self.db, order_id)
            except Exception as e:
                raise RuntimeError(f"[{ticker}] 주문 제출 상태 기록 실패: {e}") from e

            # API 호출
            try:
                if action == "BUY":
                    resp = self.broker.place_market_buy(ticker, qty)
                else:
                    resp = self.broker.place_market_sell(ticker, qty)
                output = resp.get("output", {})
                odno = output.get("ODNO") if isinstance(output, dict) else None
                if not odno:
                    msg = resp.get("msg1", "주문번호가 없는 주문 응답")
                    update_order_status(self.db, order_id, "REJECTED", note=msg, raw_payload=resp)
                    results.append({**order, "status": "REJECTED", "message": msg})
                    continue

                attach_broker_order_id(self.db, order_id, odno, resp)
                final_status = "ACCEPTED"
                for _ in range(max(self.fill_poll_attempts, 1)):
                    try:
                        status = self.broker.get_order_status(odno)
                        final_status = self._record_broker_status(
                            order_id, ticker, action, expected_price, odno, status
                        )
                        if final_status in {"FILLED", "CANCELLED", "REJECTED"}:
                            break
                    except BrokerResponseError as poll_error:
                        logging.warning(f"[{ticker}] 체결 확인 대기: {poll_error}")
                    time.sleep(self.fill_poll_interval)

                if self.broker.is_mock and final_status == "ACCEPTED":
                    inferred = self._infer_paper_fill_from_balance(
                        ticker, action, qty, current_price, live_positions
                    )
                    if inferred is not None:
                        final_status = self._record_broker_status(
                            order_id, ticker, action, expected_price, odno, inferred
                        )

                if action == "BUY" and final_status in {"ACCEPTED", "PARTIAL", "FILLED"}:
                    today_cash -= qty * current_price
                results.append({**order, "status": final_status, "broker_order_id": odno})
            except BrokerResponseError as e:
                logging.error(f"[{ticker}] 증권사 주문 거부: {e}")
                update_order_status(
                    self.db, order_id, "REJECTED", note=str(e), event_type="BROKER_REJECTED"
                )
                results.append({**order, "status": "REJECTED", "message": str(e)})
            except Exception as e:
                # 네트워크 타임아웃은 주문 성공 여부가 불명확하므로 REJECTED로 단정하지 않는다.
                logging.exception(f"[{ticker}] 주문 결과 확인 불가: {e}")
                inferred = None
                if self.broker.is_mock:
                    inferred = self._infer_paper_fill_from_balance(
                        ticker, action, qty, current_price, live_positions
                    )
                if inferred is not None:
                    final_status = self._record_broker_status(
                        order_id, ticker, action, expected_price,
                        "BALANCE", inferred,
                    )
                    results.append({**order, "status": final_status})
                    continue
                if order_id:
                    try:
                        update_order_status(
                            self.db, order_id, "SUBMITTED", note=f"UNKNOWN_BROKER_RESULT: {e}",
                            event_type="UNKNOWN_RESULT"
                        )
                    except Exception as status_error:
                        logging.error(f"주문 결과 불명 상태 기록에도 실패했습니다: {status_error}")
                results.append({**order, "status": "UNKNOWN", "message": str(e)})

        return results

    def _execute_simulation_orders(self, orders):
        results = []
        for order in orders:
            ticker = order["ticker"]
            qty = int(order["qty"])
            price = float(order["expected_price"])
            try:
                self.broker.set_market_price(ticker, price)
                if order["type"] == "BUY":
                    response = self.broker.place_market_buy(ticker, qty)
                else:
                    response = self.broker.place_market_sell(ticker, qty)
                order_id = response["output"]["ODNO"]
                status = self.broker.get_order_status(order_id)
                results.append({
                    **order,
                    "status": status["status"],
                    "broker_order_id": order_id,
                    "fill_price": status["avg_fill_price"],
                })
            except Exception as exc:
                logging.exception(f"[{ticker}] local simulation order failed: {exc}")
                results.append({**order, "status": "REJECTED", "message": str(exc)})
        return results

    def _idempotency_key(self, order):
        raw = ":".join([
            datetime.date.today().isoformat(), self.strategy_name,
            getattr(self, "execution_venue", "PAPER"),
            normalize_symbol(order['ticker']), order['type'], str(order.get('reason', 'manual')),
        ])
        return hashlib.sha256(raw.encode()).hexdigest()

    def _record_broker_status(self, order_id, ticker, action, expected_price, broker_order_id, status):
        from storage.postgres.repositories.execution_repo import (
            fetch_execution_totals_by_order, insert_execution,
        )
        from storage.postgres.repositories.order_repo import update_order_status

        totals = fetch_execution_totals_by_order(self.db, order_id)
        cumulative_qty = float(status['filled_qty'])
        cumulative_amount = float(status.get('total_fill_amount') or 0)
        if cumulative_amount <= 0 and cumulative_qty > 0:
            cumulative_amount = cumulative_qty * float(status['avg_fill_price'])
        delta_qty = cumulative_qty - totals['qty']
        delta_amount = cumulative_amount - totals['amount']

        if delta_qty > 0:
            fill_price = delta_amount / delta_qty
            slippage = (
                (fill_price - expected_price) if action == 'BUY'
                else (expected_price - fill_price)
            ) * delta_qty
            net_amount = -delta_amount if action == 'BUY' else delta_amount
            insert_execution(self.db, order_id, {
                "symbol": normalize_symbol(ticker), "order_side_code": action,
                "qty": delta_qty, "price": fill_price, "amount": delta_amount,
                "net_amount": net_amount, "market_type_code": "KOSPI",
                "instrument_type_code": "STOCK", "commission": 0.0,
                "tax": 0.0, "slippage": slippage,
            })

        update_order_status(
            self.db, order_id, status['status'], filled_qty=cumulative_qty,
            avg_fill_price=float(status.get('avg_fill_price') or 0) or None,
            remaining_qty=float(status['remaining_qty']), broker_order_id=broker_order_id,
            event_type="STATUS_POLL", raw_payload=status.get('raw'),
            note="KIS 주문/체결 조회로 동기화",
        )
        return status['status']

    def _infer_paper_fill_from_balance(
        self, ticker, action, ordered_qty, current_price, before_positions
    ):
        """Infer VTS fills from balance changes when daily order inquiry is empty."""
        try:
            after_positions = self.broker.get_balance().get("positions", {})
        except Exception as exc:
            logging.warning(f"[{ticker}] paper balance fallback failed: {exc}")
            return None

        before_qty = int(before_positions.get(ticker, {}).get("qty", 0))
        after_qty = int(after_positions.get(ticker, {}).get("qty", 0))
        filled_qty = (
            max(before_qty - after_qty, 0)
            if action == "SELL"
            else max(after_qty - before_qty, 0)
        )
        filled_qty = min(filled_qty, int(ordered_qty))
        if filled_qty <= 0:
            return None
        return {
            "status": "FILLED" if filled_qty >= int(ordered_qty) else "PARTIAL",
            "ordered_qty": int(ordered_qty),
            "filled_qty": filled_qty,
            "remaining_qty": max(int(ordered_qty) - filled_qty, 0),
            "avg_fill_price": float(current_price),
            "total_fill_amount": filled_qty * float(current_price),
            "raw": {"source": "PAPER_BALANCE_FALLBACK"},
        }

    def _assert_no_unresolved_orders(self):
        row = self.db.fetch_one(
            """SELECT COUNT(*) AS count FROM orders
               WHERE created_at::date = CURRENT_DATE
                 AND order_status_code IN ('PENDING','SUBMITTED','ACCEPTED','PARTIAL')"""
        )
        count = int((row or {}).get("count") or 0)
        if count:
            raise RuntimeError(
                f"unresolved order circuit breaker: {count} open orders require reconciliation"
            )

    def _reconcile_open_orders(self, live_positions=None):
        """이전 실행에서 남은 접수/부분체결 주문을 브로커 원장과 동기화한다."""
        from storage.postgres.repositories.order_repo import (
            attach_broker_order_id, update_order_status,
        )

        try:
            rows = self.db.fetch_all(
                """SELECT id::text, broker_order_id, symbol, order_side_code,
                          price, qty, created_at
                   FROM orders
                   WHERE order_status_code IN ('SUBMITTED', 'ACCEPTED', 'PARTIAL')
                     AND created_at::date = CURRENT_DATE"""
            )
            all_linked_rows = self.db.fetch_all(
                """SELECT broker_order_id FROM orders
                   WHERE created_at::date = CURRENT_DATE
                     AND broker_order_id IS NOT NULL"""
            )
        except Exception as e:
            raise RuntimeError(f"열린 주문 조회 실패: {e}") from e
        daily_broker_rows = None
        linked_ids = {
            str(row['broker_order_id']).lstrip('0') or '0' for row in all_linked_rows
        }
        for row in rows:
            if not row['broker_order_id']:
                try:
                    if daily_broker_rows is None:
                        daily_broker_rows = self.broker.fetch_daily_orders()
                    matches = self._match_unknown_broker_order(row, daily_broker_rows, linked_ids)
                    if len(matches) != 1:
                        if len(matches) == 0 and self._unknown_order_grace_elapsed(row):
                            update_order_status(
                                self.db, row['id'], 'REJECTED',
                                note=(
                                    'AUTO_RECONCILED_NOT_FOUND: successful KIS daily-order '
                                    'query found no matching order after grace period'
                                ),
                                event_type='AUTO_RECONCILE_NOT_FOUND',
                                raw_payload={
                                    'source': 'KIS_DAILY_ORDER_RECONCILIATION',
                                    'broker_order_count': len(daily_broker_rows),
                                },
                            )
                            logging.warning(
                                f"[auto reconcile] order {row['id']} was not found in "
                                "the KIS daily-order list; marked REJECTED"
                            )
                            continue
                        logging.error(
                            f"[정산 필요] 로컬 주문 {row['id']}의 브로커 주문 후보가 "
                            f"{len(matches)}건입니다. 자동 재주문하지 않습니다."
                        )
                        continue
                    broker_order_id = str(matches[0].get('odno') or matches[0].get('ODNO'))
                    attach_broker_order_id(self.db, row['id'], broker_order_id, matches[0])
                    row['broker_order_id'] = broker_order_id
                    linked_ids.add(broker_order_id.lstrip('0') or '0')
                except Exception as e:
                    logging.warning(f"주문번호 미확인 주문 {row['id']} 자동 복구 보류: {e}")
                    continue
            try:
                status = self.broker.get_order_status(row['broker_order_id'])
                self._record_broker_status(
                    row['id'], row['symbol'], row['order_side_code'],
                    float(row['price'] or 0), row['broker_order_id'], status,
                )
            except Exception as e:
                logging.warning(f"열린 주문 {row['id']} 정산 보류: {e}")

        if self.broker.is_mock and live_positions is not None:
            remaining = self.db.fetch_all(
                """SELECT id::text, broker_order_id, symbol, order_side_code,
                          price, qty, created_at
                   FROM orders
                   WHERE order_status_code IN ('SUBMITTED', 'ACCEPTED', 'PARTIAL')
                     AND created_at::date = CURRENT_DATE"""
            )
            for row in remaining:
                ticker = f"{normalize_symbol(row['symbol'])}.KS"
                if row['order_side_code'] != 'SELL':
                    continue
                ordered_qty = int(row['qty'])
                held_qty = int(live_positions.get(ticker, {}).get('qty', 0))
                if held_qty >= ordered_qty:
                    continue
                filled_qty = ordered_qty - held_qty
                synthetic = {
                    "status": "FILLED" if held_qty == 0 else "PARTIAL",
                    "ordered_qty": ordered_qty,
                    "filled_qty": filled_qty,
                    "remaining_qty": held_qty,
                    "avg_fill_price": float(row['price']),
                    "total_fill_amount": filled_qty * float(row['price']),
                    "raw": {"source": "PAPER_POSITION_RECONCILIATION"},
                }
                self._record_broker_status(
                    row['id'], ticker, 'SELL', float(row['price']),
                    row['broker_order_id'] or 'BALANCE', synthetic,
                )

    def _unknown_order_grace_elapsed(self, row, now=None):
        created_at = row.get('created_at')
        if not isinstance(created_at, datetime.datetime):
            return False
        now = now or datetime.datetime.now(datetime.timezone.utc)
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=datetime.timezone.utc)
        if now.tzinfo is None:
            now = now.replace(tzinfo=datetime.timezone.utc)
        grace = max(int(getattr(self, 'unknown_order_grace_seconds', 300)), 0)
        return (now - created_at).total_seconds() >= grace

    @staticmethod
    def _match_unknown_broker_order(local_order, broker_rows, linked_ids):
        """응답 유실 주문을 2분 이내의 유일한 KIS 주문과만 연결한다."""
        created_at = local_order.get('created_at')
        if not isinstance(created_at, datetime.datetime):
            return []
        if created_at.tzinfo is not None:
            created_at = created_at.astimezone(ZoneInfo("Asia/Seoul"))
        local_time = created_at.timetz().replace(tzinfo=None)
        local_seconds = local_time.hour * 3600 + local_time.minute * 60 + local_time.second
        expected_side = '02' if local_order['order_side_code'] == 'BUY' else '01'
        matches = []
        for broker_row in broker_rows:
            broker_id = str(broker_row.get('odno') or broker_row.get('ODNO') or '')
            if not broker_id or (broker_id.lstrip('0') or '0') in linked_ids:
                continue
            order_time = str(broker_row.get('ord_tmd') or '')
            if len(order_time) != 6 or not order_time.isdigit():
                continue
            broker_seconds = int(order_time[:2]) * 3600 + int(order_time[2:4]) * 60 + int(order_time[4:])
            if abs(broker_seconds - local_seconds) > 120:
                continue
            side = str(broker_row.get('sll_buy_dvsn_cd') or '')
            symbol = normalize_symbol(broker_row.get('pdno') or '')
            qty = int(broker_row.get('ord_qty') or 0)
            if (
                side == expected_side
                and symbol == normalize_symbol(local_order['symbol'])
                and qty == int(local_order['qty'])
            ):
                matches.append(broker_row)
        return matches

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
            logging.info("[DB 동기화] balance_history 기록 완료")
        except Exception as e:
            raise RuntimeError(f"balance_history 기록 실패: {e}") from e
            
        # 2. positions 테이블 저장
        from storage.postgres.repositories.position_repo import (
            delete_position, fetch_active_position_symbols, upsert_position,
            zero_out_position,
        )
        try:
            db_symbols = fetch_active_position_symbols(self.db, self.strategy_name)
            
            for symbol, pos in positions.items():
                upsert_position(self.db, self.strategy_name, normalize_symbol(symbol), {
                    "qty": pos["qty"],
                    "avg_cost": pos["avg_price"],
                    "market_type_code": "KOSPI",
                    "instrument_type_code": "STOCK"
                })
                
            for db_symbol in db_symbols:
                if db_symbol != normalize_symbol(db_symbol):
                    delete_position(self.db, self.strategy_name, db_symbol)
                    continue
                if normalize_symbol(db_symbol) not in {normalize_symbol(s) for s in positions}:
                    zero_out_position(self.db, self.strategy_name, db_symbol)
            logging.info("[DB 동기화] positions 테이블 갱신 완료")
        except Exception as e:
            raise RuntimeError(f"positions 테이블 갱신 실패: {e}") from e

    def _load_published_fa_candidates(self, cutoff_date, as_of_date=None):
        """검증·발행된 최신 월간 FA 결과만 라이브 후보로 반환한다."""
        as_of_date = as_of_date or datetime.date.today()
        quality_condition = ""
        if not self.allow_warning_fa_run:
            quality_condition = "AND COALESCE(r.validation_summary->>'status', 'FAIL') = 'PASS'"
        run = self.db.fetch_one(
            f"""
            SELECT r.*
            FROM fa_analysis_runs r
            JOIN strategies s ON s.id = r.strategy_id
            WHERE r.status_code = 'PUBLISHED'
              AND s.name = %s
              AND r.effective_date <= %s::date
              {quality_condition}
            ORDER BY r.effective_date DESC, r.run_version DESC, r.id DESC
            LIMIT 1
            """,
            (self.strategy_name, as_of_date),
        )
        if not run:
            mode = "PASS 또는 WARNING" if self.allow_warning_fa_run else "PASS"
            raise RuntimeError(f"{cutoff_date} 기준 발행된 {mode} FA 분석 결과가 없습니다.")
        rows = self.db.fetch_all(
            """
            SELECT c.id AS fa_company_result_id, c.stock_code, c.fa_score,
                   c.score_confidence, c.latest_available_date,
                   q.debt_ratio, q.is_eligible, q.score_model_code
            FROM fa_company_results c
            JOIN company_quarter_fa q ON q.id = c.company_quarter_fa_id
            WHERE c.run_id = %s
              AND c.is_selected = TRUE
              AND c.is_eligible = TRUE
              AND c.latest_available_date <= %s::date
              AND c.score_confidence >= 0.50
              AND q.score_model_code <> 'UNSUPPORTED'
              AND (%s::date - c.latest_available_date) <= 180
            ORDER BY c.industry_rank NULLS LAST, c.fa_score DESC, c.stock_code
            """,
            (run["id"], cutoff_date, cutoff_date),
        )
        if not rows:
            raise RuntimeError(f"발행 FA run_id={run['id']}에 사용 가능한 선택 종목이 없습니다.")
        return run, rows

    def _sync_universe_to_db(self, fa_candidates, ohlcv_store, *, lineage=None):
        lineage = lineage or {}
        try:
            # Broker state is required to distinguish REMOVED from SELL_ONLY.  Fetch it
            # before opening the DB transaction so an unavailable broker cannot leave a
            # partially updated universe behind.
            balance_info = self.broker.get_balance()
            held_symbols = {
                normalize_symbol(s) for s in balance_info.get('positions', {}).keys()
            }

            with self.db.transaction() as conn:
                strategy = conn.execute(
                    "SELECT id FROM strategies WHERE name = %s FOR UPDATE",
                    (self.strategy_name,),
                ).fetchone()
                if not strategy:
                    raise RuntimeError(f"전략 {self.strategy_name}을 찾을 수 없습니다.")
                strategy_id = strategy["id"]

                current_rows = conn.execute(
                    "SELECT symbol FROM universe WHERE strategy_id = %s AND universe_status_code = 'ACTIVE'",
                    (strategy_id,),
                ).fetchall()
                active_symbols = {r["symbol"] for r in current_rows}
                today = datetime.date.today()

                for ticker in fa_candidates:
                    symbol = ticker.split('.')[0]
                    fa_score = None
                    if ohlcv_store and ticker in ohlcv_store and not ohlcv_store[ticker].empty:
                        fa_score = ohlcv_store[ticker].iloc[-1].get('fa_score', None)
                        fa_score = float(fa_score) if pd.notnull(fa_score) else None

                    conn.execute(
                    """
                    INSERT INTO universe (
                        strategy_id, symbol, market_type_code, instrument_type_code,
                        universe_status_code, fa_score, entry_date,
                        source_fa_company_result_id
                    )
                    VALUES (%s, %s, 'KOSPI', 'STOCK', 'ACTIVE', %s, %s, %s)
                    ON CONFLICT (strategy_id, symbol)
                    DO UPDATE SET
                        universe_status_code = 'ACTIVE',
                        fa_score = COALESCE(EXCLUDED.fa_score, universe.fa_score),
                        source_fa_company_result_id = EXCLUDED.source_fa_company_result_id,
                        updated_at = NOW()
                    """,
                        (strategy_id, symbol, fa_score, today, lineage.get(ticker)),
                    )

                candidates_symbols = {t.split('.')[0] for t in fa_candidates}
                for old_symbol in active_symbols:
                    if old_symbol not in candidates_symbols:
                        new_status = 'SELL_ONLY' if old_symbol in held_symbols else 'REMOVED'
                        conn.execute(
                        """
                        UPDATE universe
                        SET universe_status_code = %s, updated_at = NOW()
                        WHERE strategy_id = %s AND symbol = %s
                        """,
                            (new_status, strategy_id, old_symbol),
                        )
            logging.info("[DB 동기화] universe 테이블 갱신 완료")
        except Exception as e:
            raise RuntimeError(f"universe 테이블 갱신 실패: {e}") from e

    @staticmethod
    def _filter_stale_data(ohlcv_store, expected_date):
        """마지막 완결 거래일 데이터가 없는 종목을 신호 계산에서 제외한다."""
        fresh = {}
        for ticker, df in ohlcv_store.items():
            if df is None or df.empty:
                continue
            last_date = pd.Timestamp(df.index[-1]).date()
            if last_date != expected_date:
                logging.warning(
                    f"[{ticker}] 시세가 오래되었습니다(last={last_date}, expected={expected_date})."
                )
                continue
            fresh[ticker] = df
        return fresh
