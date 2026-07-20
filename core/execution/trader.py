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
        self.price_guard_cooldown_seconds = int(os.getenv("PRICE_GUARD_COOLDOWN_SECONDS", "900"))
        self.max_position_weight = float(os.getenv("MAX_POSITION_WEIGHT", "0.15"))
        self.max_daily_loss_rate = float(os.getenv("MAX_DAILY_LOSS_RATE", "0.03"))
        self.manual_entry_pause = os.getenv("TRADING_KILL_SWITCH", "false").lower() == "true"
        if not 0 <= self.max_price_deviation <= 0.20:
            raise ValueError("MAX_PRICE_DEVIATION은 0~0.20 범위여야 합니다.")
        if not 1.0 <= self.buy_cash_buffer <= 1.20:
            raise ValueError("BUY_CASH_BUFFER는 1.0~1.20 범위여야 합니다.")
        if self.max_order_attempts < 1 or self.fill_poll_attempts < 1:
            raise ValueError("주문/체결 시도 횟수는 1 이상이어야 합니다.")
        if self.fill_poll_interval < 0:
            raise ValueError("KIS_FILL_POLL_INTERVAL은 0 이상이어야 합니다.")
        if not 0 < self.max_position_weight <= 0.30:
            raise ValueError("MAX_POSITION_WEIGHT must be in (0, 0.30]")
        if not 0 < self.max_daily_loss_rate <= 0.20:
            raise ValueError("MAX_DAILY_LOSS_RATE must be in (0, 0.20]")

        # 최적화된 파라미터 적용
        strategy_params = {
            "entry_size": 0.18,     # 5종목 분산 (5 * 18% = 90% 비중, 10% 현금 유지)
            "ma_window": 60,        # 60일선 돌파 모멘텀
            "ma_window_fast": 20,
            "fa_score_min": FA_CONTRACT.minimum_company_fa_score,
            "fa_score_exit": 40.0,  # fa_score 하락 시 매도 기준
            "debt_ratio_max": 2.0,  # 부채비율 상한 (200%)
            "min_score_confidence": FA_CONTRACT.minimum_score_confidence,
            "stop_loss_pct": float(os.getenv("STOP_LOSS_PCT", "0.10")),
            "trailing_stop_pct": float(os.getenv("TRAILING_STOP_PCT", "0.08")),
        }
        self.strategy = FaTaMomentumStrategy(strategy_params)
        self.strategy_name = self.strategy.INVESTMENT_TYPE.name.lower()
        self.execution_venue = (
            "DRY_RUN" if dry_run else "SIMULATE" if simulate else "PAPER" if mock else "REAL"
        )
        self.log_dir = Path("logs") / self.execution_venue.lower()
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.risk_state_path = self.log_dir / "risk_state.json"
        self.price_guard_path = self.log_dir / "price_guard_state.json"
        self.last_data_health = {}
        self.last_order_candidates = []

    def run_premarket_batch(self):
        logging.info(f"[{datetime.datetime.now()}] 프리마켓 FA 필터링 시작")
        signal_date = previous_krx_trading_day(datetime.date.today())
        published_run, published_candidates = self._load_published_fa_candidates(signal_date)
        tickers = [f"{row['stock_code']}.KS" for row in published_candidates]
        end_date = (signal_date + datetime.timedelta(days=1)).isoformat()
        start_date = (signal_date - datetime.timedelta(days=200)).isoformat()
        
        ohlcv_store = download_multiple_stocks(tickers, start=start_date, end=end_date, show_progress=False)
        ohlcv_store = enrich_ohlcv_with_fa(
            self.db, ohlcv_store, signal_date.isoformat(),
            min_score_confidence=FA_CONTRACT.minimum_score_confidence,
        )
        ohlcv_store, data_health = self._filter_stale_data(
            ohlcv_store,
            signal_date,
            expected_tickers=tickers,
            return_health=True,
        )
        self.last_data_health = data_health
        
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
            score_confidence = last.get('score_confidence', None)
            # is_eligible 플래그 + fa_score >= 60 + 부채비율 200% 이하
            if (
                symbol in candidate_by_symbol and
                is_eligible and
                fa_score is not None and float(fa_score) >= self.strategy.FA_SCORE_MIN and
                debt_ratio is not None and pd.notnull(debt_ratio) and
                float(debt_ratio) <= self.strategy.DEBT_RATIO_MAX and
                score_confidence is not None and pd.notnull(score_confidence) and
                float(score_confidence) >= self.strategy.MIN_SCORE_CONFIDENCE
            ):
                fa_candidates.append(ticker)
        
        os.makedirs("logs", exist_ok=True)
        with open("logs/fa_candidates.json", "w", encoding="utf-8") as f:
            json.dump({
                "source": "published_fa",
                "run_id": published_run["id"],
                "signal_date": signal_date.isoformat(),
                "tickers": fa_candidates,
                "minimum_fa_score": self.strategy.FA_SCORE_MIN,
                "minimum_score_confidence": self.strategy.MIN_SCORE_CONFIDENCE,
                "score_model_code": FA_CONTRACT.model_version,
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
        dashboard_state["execution_mode"] = self.execution_venue
        dashboard_state["strategy"] = self.strategy_name
        dashboard_state["account_scope"] = getattr(
            self.broker, "masked_account", "UNKNOWN"
        )
        dashboard_state["data_health"] = data_health
        dashboard_state["order_candidates"] = self._candidate_order_summary([])
        actual_orders = self._daily_order_summary()
        dashboard_state["actual_orders"] = actual_orders
        dashboard_state["daily_orders"] = actual_orders
        dashboard_state["operational_status"] = self._derive_operational_status(
            data_health, actual_orders
        )
        dashboard_state["last_error"] = (
            "; ".join(data_health.get("dependency_errors", [])) or None
        )
        
        with dashboard_path.open("w", encoding="utf-8") as f:
            json.dump(dashboard_state, f, ensure_ascii=False, indent=2)
        self._append_operational_health(dashboard_state)

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
        daily_asset_change = float(balance_info.get("daily_asset_change", 0.0))
        previous_total_eval = float(total_eval) - daily_asset_change
        daily_return_decimal = (
            daily_asset_change / previous_total_eval if previous_total_eval > 0 else 0.0
        )
        entry_circuit_breaker = None
        if self.manual_entry_pause:
            entry_circuit_breaker = "MANUAL_KILL_SWITCH"
        elif daily_return_decimal <= -self.max_daily_loss_rate:
            entry_circuit_breaker = "DAILY_LOSS_LIMIT"
        
        # Local simulation state is isolated from operational order/position tables.
        unresolved_error = None
        if not getattr(self.broker, "is_simulated", False):
            self._sync_balance_and_positions(balance_info, total_eval)
            self._reconcile_open_orders(positions)
            try:
                self._assert_no_unresolved_orders()
            except RuntimeError as exc:
                unresolved_error = str(exc)
        
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
            
        # 현재 전략/실행환경/계좌 범위의 누적 슬리피지 합산 조회
        try:
            row = self.db.fetch_one(
                """SELECT SUM(e.slippage) AS total
                   FROM executions e
                   JOIN orders o ON o.id = e.order_id
                   JOIN strategies s ON s.id = o.strategy_id
                   WHERE s.name = %s
                     AND o.execution_venue_code = %s
                     AND o.account_scope = %s""",
                (
                    self.strategy_name,
                    self.execution_venue,
                    getattr(self.broker, "masked_account", "UNKNOWN"),
                ),
            )
            total_slippage = float(row['total'] or 0.0) if row else 0.0
        except Exception as e:
            logging.warning(f"누적 슬리피지 조회 실패: {e}")
            total_slippage = 0.0
            
        dashboard_state["updated_at"] = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        dashboard_state["cash"] = cash
        dashboard_state["total_eval"] = total_eval
        dashboard_state["positions"] = list(positions.keys())
        dashboard_state["total_slippage"] = total_slippage
        dashboard_state["unrealized_pnl"] = float(balance_info.get("unrealized_pnl", 0.0))
        dashboard_state["daily_asset_change"] = float(balance_info.get("daily_asset_change", 0.0))
        dashboard_state["daily_asset_change_rate"] = float(
            balance_info.get("daily_asset_change_rate", 0.0)
        )
        dashboard_state["risk_controls"] = {
            "stop_loss_pct": self.strategy.STOP_LOSS_PCT,
            "trailing_stop_pct": self.strategy.TRAILING_STOP_PCT,
            "max_daily_loss_rate": self.max_daily_loss_rate,
            "manual_entry_pause": self.manual_entry_pause,
        }
        dashboard_state["execution_mode"] = self.execution_venue
        dashboard_state["strategy"] = self.strategy_name
        dashboard_state["account_scope"] = getattr(
            self.broker, "masked_account", "UNKNOWN"
        )
        actual_orders = self._daily_order_summary()
        dashboard_state["actual_orders"] = actual_orders
        dashboard_state["daily_orders"] = actual_orders
        dashboard_state["order_candidates"] = self._candidate_order_summary([])
        dashboard_state["operational_status"] = (
            "ORDER_RECONCILIATION" if unresolved_error else "SCANNING"
        )
        dashboard_state["last_error"] = unresolved_error
        
        with dashboard_path.open("w", encoding="utf-8") as f:
            json.dump(dashboard_state, f, ensure_ascii=False, indent=2)
            
        # ponytail: append to csv for timeseries tracking
        self._append_account_history(balance_info, total_eval)

        if unresolved_error:
            logging.warning(f"{unresolved_error}; this scan will not create new orders")
            timeline = dashboard_state.setdefault("timeline", [])
            timeline.append(
                f"[{datetime.datetime.now():%H:%M}] 주문 정산 대기: 신규 주문 생성 중지"
            )
            dashboard_state["timeline"] = timeline[-5:]
            self._write_json_state(dashboard_path, dashboard_state)
            return []
        
        # 2. 데이터 로드. 데이터/의존성 장애는 신규 진입만 차단하며, 보유
        # 포지션의 가격 기반 손절은 아래 독립 위험 계층에서 계속 평가한다.
        signal_date = previous_krx_trading_day(datetime.date.today())
        end_date = (signal_date + datetime.timedelta(days=1)).isoformat()
        start_date = (signal_date - datetime.timedelta(days=200)).isoformat()
        dependency_errors = []

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
        except (OSError, ValueError, TypeError) as exc:
            message = f"FA 후보 파일 오류: {exc}"
            logging.error(f"{message}; 신규 매수를 차단합니다")
            dependency_errors.append(message)
            fa_candidates = []

        tickers = sorted(set(fa_candidates) | set(positions))
        logging.info(f"[데이터 로드] 관심 종목 + 보유 종목 ({len(tickers)}개) 병합 중...")
        try:
            downloaded = download_multiple_stocks(
                tickers, start=start_date, end=end_date, show_progress=False
            )
            enriched = enrich_ohlcv_with_fa(
                self.db,
                downloaded,
                signal_date.isoformat(),
                min_score_confidence=FA_CONTRACT.minimum_score_confidence,
            )
            ohlcv_store, data_health = self._filter_stale_data(
                enriched,
                signal_date,
                expected_tickers=tickers,
                return_health=True,
            )
        except Exception as exc:
            message = f"종목 데이터 로드 오류: {exc}"
            logging.exception(message)
            dependency_errors.append(message)
            ohlcv_store = {}
            data_health = {
                "expected_date": signal_date.isoformat(),
                "expected_count": len(tickers),
                "fresh_count": 0,
                "stale_count": 0,
                "missing_count": len(tickers),
                "stale_tickers": [],
                "missing_tickers": tickers,
            }
        self.last_ohlcv_store = ohlcv_store

        # 3. 보유 위험을 먼저 평가한다. 이 계층은 일봉/FA/시장국면과 무관하다.
        print("[시그널 생성] 위험관리 후 진입·청산 신호 평가 중...")
        target_positions = {}
        target_details = {}
        risk_peaks = self._update_risk_peaks(positions)
        risk_decisions = {}
        risk_checked = 0
        for ticker, pos in positions.items():
            price_for_weight = float(pos.get("current_price") or pos.get("avg_price") or 0.0)
            current_weight = (
                float(pos.get("qty") or 0.0) * price_for_weight / total_eval
                if total_eval > 0 else 0.0
            )
            risk_target, risk_metadata = self.strategy.evaluate_position_risk(
                current_position=current_weight,
                average_price=pos.get("avg_price"),
                current_price=pos.get("current_price"),
                peak_price=risk_peaks.get(ticker),
            )
            risk_decisions[ticker] = (risk_target, risk_metadata)
            if (
                float(pos.get("avg_price") or 0.0) > 0
                and float(pos.get("current_price") or 0.0) > 0
            ):
                risk_checked += 1

        # 시장국면 실패 시에도 가격/FA/TA 청산은 계속 평가하되 신규 진입은 차단한다.
        market_regime = None
        try:
            start_date_kospi = (signal_date - datetime.timedelta(days=320)).isoformat()
            kospi_close = download_kospi_index(start_date_kospi, end_date)
            if len(kospi_close) < 200:
                raise ValueError("KOSPI 200일 이동평균 계산 데이터 부족")
            kospi_last_date = pd.Timestamp(kospi_close.index[-1]).date()
            if kospi_last_date != signal_date:
                raise ValueError(
                    f"KOSPI 데이터가 오래됨(last={kospi_last_date}, expected={signal_date})"
                )
            ma200 = kospi_close.rolling(200, min_periods=200).mean()
            market_regimes = pd.Series("TRANSITION", index=kospi_close.index, dtype=object)
            market_regimes.loc[kospi_close > ma200] = "UPTREND"
            market_regimes.loc[kospi_close <= ma200] = "DOWNTREND"
            market_regime = str(market_regimes.iloc[-1])
        except Exception as exc:
            message = f"KOSPI 시장국면 오류: {exc}"
            logging.error(f"{message}; 신규 매수를 차단합니다")
            dependency_errors.append(message)

        from storage.postgres.repositories.company_risk_repo import fetch_buy_blocked_stock_codes
        blocked_codes = None
        try:
            blocked_codes = fetch_buy_blocked_stock_codes(self.db, datetime.date.today())
        except Exception as exc:
            message = f"기업 위험상태 오류: {exc}"
            logging.error(f"{message}; 신규 매수를 차단합니다")
            dependency_errors.append(message)

        minimum_bars = max(self.strategy.MA_WINDOW, self.strategy.MA_WINDOW_FAST) + 1
        insufficient_history = []
        usable_signal_tickers = set()
        for ticker, df in ohlcv_store.items():
            if df.empty or len(df) < minimum_bars:
                insufficient_history.append(ticker)
                continue
            usable_signal_tickers.add(ticker)

            pos = positions.get(ticker)
            if pos and risk_decisions[ticker][1]["signal_reason"] != "RISK_CLEAR":
                target_positions[ticker], target_details[ticker] = risk_decisions[ticker]
                continue
            if pos:
                current_weight = risk_decisions[ticker][0]
            else:
                current_weight = 0.0
                # 알 수 없는 기업 위험 상태에서는 신규 진입을 fail-closed 한다.
                if blocked_codes is None:
                    continue

            target_weight, metadata = self.strategy.evaluate_latest(
                df,
                market_regime or "UNAVAILABLE",
                current_position=current_weight,
                average_price=pos.get("avg_price") if pos else None,
                current_price=pos.get("current_price") if pos else None,
                peak_price=risk_peaks.get(ticker),
            )
            symbol = ticker.split('.')[0]
            if blocked_codes is not None and symbol in blocked_codes and not pos:
                target_weight = 0.0
                metadata["signal_reason"] = "COMPANY_RISK_BLOCKED"
            target_positions[ticker] = target_weight
            target_details[ticker] = metadata

        # 신호 데이터가 없어도 독립 위험청산은 실행한다. 위험 신호가 없을 때만
        # 현재 비중을 보존하며, 이 상태는 정상(NORMAL)으로 표시하지 않는다.
        for ticker, pos in positions.items():
            if ticker in target_positions:
                continue
            risk_target, risk_metadata = risk_decisions[ticker]
            if risk_metadata["signal_reason"] != "RISK_CLEAR":
                target_positions[ticker] = risk_target
                target_details[ticker] = risk_metadata
                continue
            target_positions[ticker] = risk_target
            target_details[ticker] = {
                **risk_metadata,
                "fa_score": None,
                "momentum": None,
                "signal_reason": "DATA_UNAVAILABLE_HOLD",
            }

        data_health["insufficient_history_tickers"] = sorted(insufficient_history)
        data_health["held_stale_tickers"] = sorted(set(positions) - usable_signal_tickers)
        data_health["risk_checks_total"] = len(positions)
        data_health["risk_checks_completed"] = risk_checked
        data_health["risk_check_coverage"] = (
            risk_checked / len(positions) if positions else 1.0
        )
        data_health["dependency_errors"] = dependency_errors
        data_health["daily_return_decimal"] = daily_return_decimal
        data_health["entry_circuit_breaker"] = entry_circuit_breaker
        self.last_data_health = data_health

        target_positions = self._apply_portfolio_limits(
            target_positions, target_details, positions
        )
        if entry_circuit_breaker:
            target_positions = self._apply_entry_circuit_breaker(
                target_positions,
                target_details,
                positions,
                total_eval,
                entry_circuit_breaker,
            )
        self._write_decision_snapshot(
            total_eval,
            positions,
            target_positions,
            target_details,
            market_regime or "UNAVAILABLE",
        )

        print(f"[타겟 산출 완료] 타겟 포지션 수: {len([t for t, w in target_positions.items() if w > 0.0])}개")

        # 4. 주문 후보 계산. DRY_RUN에서는 후보만 기록되고 실제 주문은 0건이다.
        orders = self._calculate_orders(
            total_eval, positions, target_positions, ohlcv_store, target_details
        )
        self.last_order_candidates = list(orders)
        candidate_summary = self._candidate_order_summary(orders)
        dashboard_state["data_health"] = data_health
        dashboard_state["order_candidates"] = candidate_summary
        dashboard_state["actual_orders"] = actual_orders
        dashboard_state["daily_orders"] = actual_orders
        dashboard_state["operational_status"] = self._derive_operational_status(
            data_health, actual_orders
        )
        dashboard_state["last_error"] = "; ".join(dependency_errors) or None
        self._write_json_state(dashboard_path, dashboard_state)
        print(f"[{datetime.datetime.now()}] 배치 종료")
        return orders

    def update_intraday_dashboard(self, execution_results):
        """Record candidates and broker outcomes as separate operational metrics."""
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
            candidates = list(getattr(self, "last_order_candidates", results) or results)
            buy_count = sum(row.get("type") == "BUY" for row in candidates)
            sell_count = sum(row.get("type") == "SELL" for row in candidates)
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
        dashboard_state["updated_at"] = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        actual_orders = self._daily_order_summary()
        candidates = list(getattr(self, "last_order_candidates", []) or [])
        dashboard_state["execution_mode"] = self.execution_venue
        dashboard_state["actual_orders"] = actual_orders
        dashboard_state["daily_orders"] = actual_orders  # backward-compatible alias
        dashboard_state["order_candidates"] = self._candidate_order_summary(candidates)
        data_health = getattr(self, "last_data_health", {}) or dashboard_state.get(
            "data_health", {}
        )
        dashboard_state["data_health"] = data_health
        dashboard_state["operational_status"] = self._derive_operational_status(
            data_health,
            actual_orders,
            last_error=dashboard_state.get("last_error"),
        )
        self._write_json_state(dashboard_path, dashboard_state)
        self._append_operational_health(dashboard_state)

    @staticmethod
    def _candidate_order_summary(orders):
        rows = list(orders or [])
        risk_reasons = {"HARD_STOP_LOSS", "TRAILING_STOP"}
        return {
            "total": len(rows),
            "buy": sum(row.get("type") == "BUY" for row in rows),
            "sell": sum(row.get("type") == "SELL" for row in rows),
            "risk_exit": sum(row.get("reason") in risk_reasons for row in rows),
        }

    @staticmethod
    def _derive_operational_status(data_health, actual_orders, last_error=None):
        health = data_health or {}
        actual = actual_orders or {}
        if int(actual.get("open") or 0) > 0:
            return "ORDER_RECONCILIATION"
        risk_total = int(health.get("risk_checks_total") or 0)
        risk_completed = int(health.get("risk_checks_completed") or 0)
        if risk_completed < risk_total:
            return "DEGRADED_RISK_UNCHECKED"
        if health.get("entry_circuit_breaker"):
            return "ENTRY_CIRCUIT_BREAKER"
        if health.get("held_stale_tickers"):
            return "DEGRADED_DATA_STALE"
        if int(health.get("stale_count") or 0) or int(health.get("missing_count") or 0):
            return "DEGRADED_DATA_STALE"
        if health.get("dependency_errors"):
            return "DEGRADED_DEPENDENCY"
        if last_error:
            return "ERROR"
        return "NORMAL"

    def record_operational_error(self, error):
        """Persist an unexpected failure so the dashboard cannot remain NORMAL."""
        dashboard_path = self.log_dir / "dashboard_state.json"
        state = self._read_json_state(dashboard_path)
        state.setdefault("timeline", []).append(
            f"[{datetime.datetime.now():%H:%M}] 실행 오류: {error}"
        )
        state["timeline"] = state["timeline"][-5:]
        state["updated_at"] = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        state["execution_mode"] = self.execution_venue
        state["operational_status"] = "ERROR"
        state["last_error"] = str(error)
        self._write_json_state(dashboard_path, state)
        self._append_operational_health(state)

    def _append_operational_health(self, dashboard_state):
        """Append one auditable operational observation for KPI rollups."""
        payload = {
            "timestamp": datetime.datetime.now(ZoneInfo("Asia/Seoul")).isoformat(),
            "mode": getattr(self, "execution_venue", "UNKNOWN"),
            "strategy": getattr(self, "strategy_name", "UNKNOWN"),
            "account_scope": getattr(
                getattr(self, "broker", None), "masked_account", "UNKNOWN"
            ),
            "operational_status": dashboard_state.get("operational_status"),
            "data_health": dashboard_state.get("data_health", {}),
            "order_candidates": dashboard_state.get("order_candidates", {}),
            "actual_orders": dashboard_state.get(
                "actual_orders", dashboard_state.get("daily_orders", {})
            ),
            "last_error": dashboard_state.get("last_error"),
        }
        with (self.log_dir / "operational_health.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")

    def _daily_order_summary(self):
        """Return today's cumulative order state; this is not the last scan result."""
        empty = {"buy_filled": 0, "sell_filled": 0, "open": 0, "rejected": 0}
        if getattr(self, "execution_venue", None) in {"DRY_RUN", "SIMULATE"}:
            return empty
        if getattr(getattr(self, "broker", None), "is_simulated", False):
            return empty
        if not hasattr(self, "db"):
            return empty
        try:
            rows = self.db.fetch_all(
                """SELECT o.order_side_code, o.order_status_code, COUNT(*) AS count
                   FROM orders o
                   JOIN strategies s ON s.id = o.strategy_id
                   WHERE o.created_at::date = CURRENT_DATE
                     AND s.name = %s
                     AND o.execution_venue_code = %s
                     AND o.account_scope = %s
                   GROUP BY o.order_side_code, o.order_status_code""",
                (
                    self.strategy_name,
                    self.execution_venue,
                    getattr(self.broker, "masked_account", "UNKNOWN"),
                ),
            )
        except Exception as exc:
            logging.warning(f"daily order summary unavailable: {exc}")
            return empty
        summary = dict(empty)
        for row in rows:
            count = int(row.get("count") or 0)
            status = row.get("order_status_code")
            side = row.get("order_side_code")
            if status == "FILLED":
                summary["buy_filled" if side == "BUY" else "sell_filled"] += count
            elif status in {"PENDING", "SUBMITTED", "ACCEPTED", "PARTIAL"}:
                summary["open"] += count
            elif status in {"REJECTED", "CANCELLED"}:
                summary["rejected"] += count
        return summary

    @staticmethod
    def _read_json_state(path):
        try:
            return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        except (OSError, ValueError, TypeError):
            return {}

    @staticmethod
    def _write_json_state(path, payload):
        temp_path = path.with_suffix(path.suffix + ".tmp")
        temp_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        temp_path.replace(path)

    def _update_risk_peaks(self, positions):
        """Persist the highest observed broker price while a position is held."""
        state = self._read_json_state(self.risk_state_path)
        peaks = {}
        for ticker, position in positions.items():
            current = float(position.get("current_price") or 0.0)
            average = float(position.get("avg_price") or 0.0)
            previous = float((state.get(ticker) or {}).get("peak_price") or 0.0)
            peak = max(current, average, previous)
            if peak > 0:
                peaks[ticker] = peak
        payload = {
            ticker: {
                "peak_price": peak,
                "updated_at": datetime.datetime.now(ZoneInfo("Asia/Seoul")).isoformat(),
            }
            for ticker, peak in peaks.items()
        }
        self._write_json_state(self.risk_state_path, payload)
        return peaks

    def _price_guard_blocked(self, ticker, side):
        path = getattr(self, "price_guard_path", None)
        if path is None or side != "BUY":
            return False
        state = self._read_json_state(path)
        item = state.get(f"{normalize_symbol(ticker)}:{side}", {})
        try:
            return datetime.datetime.fromisoformat(item.get("blocked_until")) > datetime.datetime.now(
                ZoneInfo("Asia/Seoul")
            )
        except (TypeError, ValueError):
            return False

    def _record_price_guard(self, ticker, side, deviation):
        path = getattr(self, "price_guard_path", None)
        if path is None:
            return
        now = datetime.datetime.now(ZoneInfo("Asia/Seoul"))
        state = self._read_json_state(path)
        state[f"{normalize_symbol(ticker)}:{side}"] = {
            "deviation": float(deviation),
            "blocked_at": now.isoformat(),
            "blocked_until": (
                now + datetime.timedelta(seconds=self.price_guard_cooldown_seconds)
            ).isoformat(),
        }
        self._write_json_state(path, state)

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
        timestamp = datetime.datetime.now(ZoneInfo("Asia/Seoul")).isoformat(
            timespec="seconds"
        )
        snapshot = {
            "timestamp": timestamp,
            "mode": self.execution_venue,
            "strategy": self.strategy_name,
            "account_scope": getattr(self.broker, "masked_account", "UNKNOWN"),
            "cash": float(balance_info["cash"]),
            "total_asset": float(total_eval),
            "position_count": len(balance_info.get("positions", {})),
        }
        with (self.log_dir / "account_snapshots.jsonl").open(
            "a", encoding="utf-8"
        ) as handle:
            handle.write(json.dumps(snapshot, ensure_ascii=False) + "\n")

        # Keep the legacy CSV for existing dashboard and notebook consumers.  The
        # scoped JSONL above is the authoritative source for promotion evidence.
        path = self.log_dir / "account_history.csv"
        if not path.exists():
            path.write_text(
                "timestamp,mode,cash,total_asset,position_count\n",
                encoding="utf-8",
            )
        with path.open("a", encoding="utf-8") as handle:
            handle.write(
                f"{timestamp},"
                f"{self.execution_venue},{float(balance_info['cash']):.4f},"
                f"{float(total_eval):.4f},{len(balance_info.get('positions', {}))}\n"
            )

    def capture_account_snapshot(self):
        """Capture a scoped balance observation without evaluating or placing orders."""
        balance_info = self.broker.get_balance()
        cash = float(balance_info.get("cash") or 0.0)
        positions = balance_info.get("positions", {})
        total_eval = cash + sum(
            float(position.get("qty") or 0.0)
            * float(position.get("current_price") or position.get("avg_price") or 0.0)
            for position in positions.values()
        )
        self._append_account_history(balance_info, total_eval)
        return {
            "mode": self.execution_venue,
            "strategy": self.strategy_name,
            "account_scope": getattr(self.broker, "masked_account", "UNKNOWN"),
            "cash": cash,
            "total_asset": total_eval,
            "position_count": len(positions),
        }

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
            if str(details.get(ticker, {}).get("signal_reason", "")).endswith("_HOLD")
        }
        protected_total = sum(result[ticker] for ticker in protected)
        allocatable = [ticker for ticker in active if ticker not in protected]
        allocation_budget = max(0.90 - protected_total, 0.0)
        max_weight = getattr(self, "max_position_weight", 0.15)
        fa_scores = {
            ticker: max(
                float(details.get(ticker, {}).get("fa_score") or 0.0)
                - float(FA_CONTRACT.minimum_company_fa_score),
                0.0,
            )
            for ticker in allocatable
        }
        if allocatable:
            remaining = set(allocatable)
            remaining_budget = min(allocation_budget, max_weight * len(remaining))
            raw_weights = {}
            use_scores = sum(fa_scores.values()) > 0
            convictions = {
                ticker: fa_scores[ticker] if use_scores else 1.0 for ticker in remaining
            }
            while remaining and remaining_budget > 0:
                conviction_total = sum(convictions[ticker] for ticker in remaining)
                capped = []
                for ticker in remaining:
                    proposed = remaining_budget * convictions[ticker] / conviction_total
                    if proposed >= max_weight:
                        raw_weights[ticker] = max_weight
                        capped.append(ticker)
                if not capped:
                    for ticker in remaining:
                        raw_weights[ticker] = (
                            remaining_budget * convictions[ticker] / conviction_total
                        )
                    break
                for ticker in capped:
                    remaining.remove(ticker)
                    remaining_budget -= max_weight
            for ticker in allocatable:
                result[ticker] = round(raw_weights.get(ticker, 0.0), 4)
        return result

    @staticmethod
    def _apply_entry_circuit_breaker(
        targets,
        details,
        positions,
        total_eval,
        reason,
    ):
        """Block exposure increases while preserving all sell/risk-exit targets."""
        result = dict(targets)
        for ticker, target_weight in list(result.items()):
            position = positions.get(ticker)
            if not position:
                if target_weight > 0:
                    result[ticker] = 0.0
                    details.setdefault(ticker, {})["signal_reason"] = reason
                continue
            price = float(
                position.get("current_price") or position.get("avg_price") or 0.0
            )
            current_weight = (
                float(position.get("qty") or 0.0) * price / total_eval
                if total_eval > 0 else 0.0
            )
            if target_weight > current_weight:
                result[ticker] = current_weight
                details.setdefault(ticker, {})["signal_reason"] = reason
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
            if self._price_guard_blocked(ticker, side):
                logging.info(f"[{ticker}] price guard cooldown is active for {side}")
                return False
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
                self._record_price_guard(ticker, action, deviation)
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
                    "execution_venue_code": getattr(self, "execution_venue", "PAPER"),
                    "account_scope": getattr(self.broker, "masked_account", "UNKNOWN"),
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
                "date": datetime.datetime.now(ZoneInfo("Asia/Seoul"))
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
              AND c.score_confidence >= %s
              AND q.score_model_code <> 'UNSUPPORTED'
              AND q.debt_ratio IS NOT NULL
              AND q.debt_ratio <= %s
              AND (%s::date - c.latest_available_date) <= 180
            ORDER BY c.industry_rank NULLS LAST, c.fa_score DESC, c.stock_code
            """,
            (
                run["id"], cutoff_date, FA_CONTRACT.minimum_score_confidence,
                getattr(getattr(self, "strategy", None), "DEBT_RATIO_MAX", 2.0), cutoff_date,
            ),
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
    def _filter_stale_data(
        ohlcv_store,
        expected_date,
        *,
        expected_tickers=None,
        return_health=False,
    ):
        """Exclude stale bars and optionally return a structured freshness report."""
        fresh = {}
        stale_tickers = []
        for ticker, df in ohlcv_store.items():
            if df is None or df.empty:
                continue
            last_date = pd.Timestamp(df.index[-1]).date()
            if last_date != expected_date:
                logging.warning(
                    f"[{ticker}] 시세가 오래되었습니다(last={last_date}, expected={expected_date})."
                )
                stale_tickers.append(ticker)
                continue
            fresh[ticker] = df
        expected = set(expected_tickers or ohlcv_store.keys())
        missing_tickers = sorted(expected - set(ohlcv_store))
        empty_tickers = sorted(
            ticker
            for ticker in expected & set(ohlcv_store)
            if ohlcv_store[ticker] is None or ohlcv_store[ticker].empty
        )
        missing_tickers = sorted(set(missing_tickers) | set(empty_tickers))
        health = {
            "expected_date": expected_date.isoformat(),
            "expected_count": len(expected),
            "fresh_count": len(fresh),
            "stale_count": len(stale_tickers),
            "missing_count": len(missing_tickers),
            "stale_tickers": sorted(stale_tickers),
            "missing_tickers": missing_tickers,
            "dependency_errors": [],
        }
        return (fresh, health) if return_health else fresh
