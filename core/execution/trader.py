import logging
import json
import os
import re
import pandas as pd
import datetime
from collections import Counter
from zoneinfo import ZoneInfo
from pathlib import Path
from data.loaders.kospi_data import download_multiple_stocks, download_kospi_index
from data.loaders.fa_ta_loader import enrich_ohlcv_with_fa
from apps.worker.fa_contract import (
    DEFAULT_CONFIG as FA_CONTRACT,
    PAPER_TRADING_MODEL_VERSION,
    REAL_TRADING_MODEL_VERSION,
)
from storage.postgres.connection import PostgreDB
from core.strategy.fa_ta_momentum import FaTaMomentumStrategy
from core.analytics.paper_portfolio_cap_shadow import (
    evaluate_paper_portfolio_cap_shadow,
)
from core.analytics.paper_shadow_reentry import evaluate_paper_shadow_reentry
from core.broker.kis_api import KisBroker, normalize_symbol
from core.broker.simulation import LocalSimulationBroker
from core.constant.types import Tickers
from core.execution.order_planning import OrderPlanningMixin
from core.execution.order_execution import OrderExecutionMixin
from core.execution.order_reconciliation import OrderReconciliationMixin
from core.execution.inverse_hedge import InverseHedgeConfig, evaluate_inverse_hedge
from core.execution.strategy_policy import resolve_strategy_policy
from core.utils.trading_calendar import previous_krx_trading_day

KST = ZoneInfo("Asia/Seoul")


def _now_kst() -> datetime.datetime:
    """Return the current timestamp in the exchange's operating timezone."""
    return datetime.datetime.now(KST)


def _today_kst() -> datetime.date:
    """Return today's KRX operating date, independent of host/DB timezone."""
    return _now_kst().date()


class LiveTrader(OrderPlanningMixin, OrderExecutionMixin, OrderReconciliationMixin):
    """Coordinate market analysis, order planning, execution and reconciliation."""

    @staticmethod
    def _trading_date():
        return _today_kst()

    def __init__(
        self,
        mock=True,
        simulate=False,
        dry_run=False,
        force_rebalance=False,
    ):
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
        self.execution_venue = (
            "DRY_RUN"
            if dry_run
            else "SIMULATE"
            if simulate
            else "PAPER"
            if mock
            else "REAL"
        )
        self.strategy_policy = resolve_strategy_policy(self.execution_venue, os.environ)
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
        self.max_position_weight = self.strategy_policy.max_position_weight
        self.rebalance_band = self.strategy_policy.rebalance_band
        self.transition_max_gross_exposure = float(
            os.getenv("TRANSITION_MAX_GROSS_EXPOSURE", "0.30")
        )
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
        if not 0 < self.transition_max_gross_exposure <= 0.90:
            raise ValueError("TRANSITION_MAX_GROSS_EXPOSURE must be in (0, 0.90]")
        if not 0 < self.max_daily_loss_rate <= 0.20:
            raise ValueError("MAX_DAILY_LOSS_RATE must be in (0, 0.20]")

        self.force_rebalance = bool(force_rebalance)
        if self.force_rebalance and self.execution_venue != "PAPER":
            raise PermissionError(
                "force_rebalance is permitted only for one-shot PAPER execution"
            )
        self.fa_model_version = self._fa_model_for_venue(self.execution_venue)
        # The hedge policy is deliberately unavailable outside PAPER. It must
        # earn its own evidence before any future REAL-mode approval.
        self.inverse_hedge_enabled = (
            self.execution_venue == "PAPER"
            and os.getenv("PAPER_INVERSE_HEDGE_ENABLED", "true").lower() == "true"
        )
        # Do not even parse hedge environment overrides outside its permitted
        # PAPER policy. This keeps the documented PAPER-only boundary strict.
        if self.inverse_hedge_enabled:
            self.inverse_hedge_config = InverseHedgeConfig(
                min_confirmations=int(os.getenv("HEDGE_MIN_CONFIRMATIONS", "2")),
                min_confidence=float(os.getenv("HEDGE_MIN_CONFIDENCE", str(2 / 3))),
                stop_loss_pct=float(os.getenv("HEDGE_STOP_LOSS_PCT", "0.05")),
                max_holding_sessions=int(os.getenv("HEDGE_MAX_HOLDING_SESSIONS", "5")),
                cooldown_sessions=int(os.getenv("HEDGE_REENTRY_COOLDOWN_SESSIONS", "3")),
                stage_weights=(
                    float(os.getenv("HEDGE_STAGE_ONE_WEIGHT", "0.10")),
                    float(os.getenv("HEDGE_STAGE_TWO_WEIGHT", "0.20")),
                    float(os.getenv("HEDGE_STAGE_THREE_WEIGHT", "0.30")),
                ),
            )
        else:
            self.inverse_hedge_config = InverseHedgeConfig()

        # 최적화된 파라미터 적용
        strategy_params = {
            "entry_size": 0.18,     # 5종목 분산 (5 * 18% = 90% 비중, 10% 현금 유지)
            "ma_window": 60,        # 60일선 돌파 모멘텀
            "ma_window_fast": 20,
            "fa_score_min": FA_CONTRACT.minimum_company_fa_score,
            "fa_score_exit": 40.0,  # fa_score 하락 시 매도 기준
            "debt_ratio_max": 2.0,  # 부채비율 상한 (200%)
            "min_score_confidence": FA_CONTRACT.minimum_score_confidence,
            "stop_loss_pct": self.strategy_policy.stop_loss_pct,
            "trailing_stop_enabled": self.strategy_policy.trailing_stop_enabled,
            "trailing_stop_pct": self.strategy_policy.trailing_stop_pct,
            "transition_keep_ratio": float(
                os.getenv("TRANSITION_KEEP_RATIO", "0.40")
            ),
            "transition_entry_enabled": os.getenv(
                "TRANSITION_ENTRY_ENABLED", "true"
            ).lower() == "true" and self.execution_venue != "REAL",
            "transition_entry_size": float(
                os.getenv("TRANSITION_ENTRY_SIZE", "0.10")
            ),
        }
        self.strategy = FaTaMomentumStrategy(strategy_params)
        self.strategy_name = self.strategy.INVESTMENT_TYPE.name.lower()
        self.log_dir = Path("logs") / self.execution_venue.lower()
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.risk_state_path = self.log_dir / "risk_state.json"
        self.price_guard_path = self.log_dir / "price_guard_state.json"
        self.inverse_hedge_state_path = self.log_dir / "inverse_hedge_state.json"
        self.market_regime_cache_path = self.log_dir / "market_regime_close_cache.json"
        self.last_data_health = {}
        self.last_order_candidates = []
        self.last_order_suppressions = []
        self.last_global_order_pause = None

    @staticmethod
    def _fa_model_for_venue(execution_venue: str) -> str:
        """Permit the candidate FA model only in the explicitly PAPER venue."""
        return (
            PAPER_TRADING_MODEL_VERSION
            if execution_venue == "PAPER"
            else REAL_TRADING_MODEL_VERSION
        )

    def run_premarket_batch(self):
        logging.info(f"[{datetime.datetime.now()}] 프리마켓 FA 필터링 시작")
        signal_date = previous_krx_trading_day(_today_kst())
        published_run, published_candidates = self._load_published_fa_candidates(signal_date)
        tickers = [f"{row['stock_code']}.KS" for row in published_candidates]
        end_date = (signal_date + datetime.timedelta(days=1)).isoformat()
        start_date = (signal_date - datetime.timedelta(days=200)).isoformat()
        
        ohlcv_store = download_multiple_stocks(tickers, start=start_date, end=end_date, show_progress=False)
        ohlcv_store = enrich_ohlcv_with_fa(
            self.db, ohlcv_store, signal_date.isoformat(),
            model_version=self.fa_model_version,
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
            blocked_codes = fetch_buy_blocked_stock_codes(self.db, _today_kst())
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
        
        self._write_json_state(
            Path("logs") / "fa_candidates.json",
            {
                "source": "published_fa",
                "run_id": published_run["id"],
                "signal_date": signal_date.isoformat(),
                "tickers": fa_candidates,
                "minimum_fa_score": self.strategy.FA_SCORE_MIN,
                "minimum_score_confidence": self.strategy.MIN_SCORE_CONFIDENCE,
                "score_model_code": self.fa_model_version,
            },
        )
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
        
        self._write_json_state(dashboard_path, dashboard_state)
        self._append_operational_health(dashboard_state)

        return fa_candidates

    def run_daily_batch(self):
        logging.info(f"[{datetime.datetime.now()}] 실전 매매 배치 시작 (Intraday)")
        self.last_global_order_pause = None
        
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
        execution_ledger_health = {
            "status": "NOT_APPLICABLE",
            "filled_order_count": 0,
            "execution_linked_order_count": 0,
            "quantity_matched_order_count": 0,
            "execution_link_coverage": 1.0,
            "quantity_match_rate": 1.0,
        }
        execution_ledger_entry_blocker = None
        if not getattr(self.broker, "is_simulated", False):
            self._sync_balance_and_positions(balance_info, total_eval)
            self._reconcile_open_orders(positions)
            self._reconcile_trade_history_with_db()
            try:
                self._assert_no_unresolved_orders()
            except RuntimeError as exc:
                unresolved_error = str(exc)
            try:
                execution_ledger_health = self._daily_execution_ledger_health()
                if execution_ledger_health["status"] != "READY":
                    execution_ledger_entry_blocker = "EXECUTION_LEDGER_INCOMPLETE"
            except Exception as exc:
                logging.exception("daily execution-ledger integrity check failed: %s", exc)
                execution_ledger_health = {
                    "status": "ERROR",
                    "error": str(exc),
                    "filled_order_count": 0,
                    "execution_linked_order_count": 0,
                    "quantity_matched_order_count": 0,
                    "execution_link_coverage": 0.0,
                    "quantity_match_rate": 0.0,
                }
                execution_ledger_entry_blocker = "EXECUTION_LEDGER_CHECK_ERROR"
        
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
        dashboard_state["positions"] = [
            {
                "ticker": k,
                "qty": v.get("qty", 0),
                "current_price": v.get("current_price", 0.0),
                "avg_price": v.get("avg_price", 0.0),
                "profit_rate": v.get("profit_rate", 0.0)
            } for k, v in positions.items()
        ]
        dashboard_state["total_slippage"] = total_slippage
        dashboard_state["unrealized_pnl"] = float(balance_info.get("unrealized_pnl", 0.0))
        dashboard_state["daily_asset_change"] = float(balance_info.get("daily_asset_change", 0.0))
        dashboard_state["daily_asset_change_rate"] = float(
            balance_info.get("daily_asset_change_rate", 0.0)
        )
        dashboard_state["risk_controls"] = {
            "stop_loss_pct": self.strategy.STOP_LOSS_PCT,
            "trailing_stop_enabled": self.strategy.TRAILING_STOP_ENABLED,
            "trailing_stop_pct": self.strategy.TRAILING_STOP_PCT,
            "max_position_weight": self.max_position_weight,
            "rebalance_band": self.rebalance_band,
            "max_daily_loss_rate": self.max_daily_loss_rate,
            "manual_entry_pause": self.manual_entry_pause,
        }
        dashboard_state["strategy_policy"] = self.strategy_policy.as_dict()
        dashboard_state["execution_mode"] = self.execution_venue
        dashboard_state["strategy"] = self.strategy_name
        dashboard_state["account_scope"] = getattr(
            self.broker, "masked_account", "UNKNOWN"
        )
        actual_orders = self._daily_order_summary()
        dashboard_state["actual_orders"] = actual_orders
        dashboard_state["daily_orders"] = actual_orders
        dashboard_state["order_candidates"] = self._candidate_order_summary([])
        dashboard_state["execution_sample_progress"] = (
            self._execution_sample_progress()
        )
        previous_data_health = dashboard_state.get("data_health") or {}
        previous_suppressions = (
            dashboard_state.get("order_suppressions")
            or previous_data_health.get("order_suppressions")
        )
        if previous_suppressions:
            previous_data_health = dict(previous_data_health)
            previous_data_health["order_suppressions"] = previous_suppressions
        dashboard_state["operational_status"] = self._derive_scan_operational_status(
            previous_data_health,
            actual_orders,
            unresolved_error=unresolved_error,
        )
        dashboard_state["last_error"] = unresolved_error
        
        self._write_json_state(dashboard_path, dashboard_state)
            
        # ponytail: append to csv for timeseries tracking
        self._append_account_history(balance_info, total_eval)

        if unresolved_error:
            self.last_global_order_pause = unresolved_error
            logging.warning(f"{unresolved_error}; this scan will not create new orders")
            timeline = dashboard_state.setdefault("timeline", [])
            timeline.append(
                f"[{datetime.datetime.now():%H:%M}] 미정산 주문 보호: "
                "모든 신규 주문 일시 중지 (정산 후 자동 해제)"
            )
            dashboard_state["timeline"] = timeline[-5:]
            self._write_json_state(dashboard_path, dashboard_state)
            return []
        
        # 2. 데이터 로드. 데이터/의존성 장애는 신규 진입만 차단하며, 보유
        # 포지션의 가격 기반 손절은 아래 독립 위험 계층에서 계속 평가한다.
        signal_date = previous_krx_trading_day(_today_kst())
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

        inverse_ticker = Tickers.INVERSE_ETF.ticker
        hedge_universe = {inverse_ticker} if (
            self.inverse_hedge_enabled or inverse_ticker in positions
        ) else set()
        tickers = sorted(set(fa_candidates) | set(positions) | hedge_universe)
        logging.info(f"[데이터 로드] 관심 종목 + 보유 종목 ({len(tickers)}개) 병합 중...")
        try:
            downloaded = download_multiple_stocks(
                tickers, start=start_date, end=end_date, show_progress=False
            )
            enriched = enrich_ohlcv_with_fa(
                self.db,
                downloaded,
                signal_date.isoformat(),
                model_version=self.fa_model_version,
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
        regime_frame = None
        kospi_close = pd.Series(dtype=float)
        market_regime_data = {
            "status": "UNAVAILABLE",
            "source": "NONE",
            "signal_date": signal_date.isoformat(),
            "last_observation_date": None,
        }
        try:
            start_date_kospi = (signal_date - datetime.timedelta(days=320)).isoformat()
            kospi_close, regime_source = self._load_completed_kospi_close(
                signal_date=signal_date,
                start_date=start_date_kospi,
                end_date=end_date,
            )
            if len(kospi_close) < 200:
                raise ValueError("KOSPI 200일 이동평균 계산 데이터 부족")
            kospi_last_date = pd.Timestamp(kospi_close.index[-1]).date()
            if kospi_last_date != signal_date:
                raise ValueError(
                    f"KOSPI 데이터가 오래됨(last={kospi_last_date}, expected={signal_date})"
                )
            from core.analytics.regime import calc_close_regime
            regime_frame = calc_close_regime(kospi_close)
            market_regime = str(regime_frame["REGIME"].iloc[-1])
            market_regime_data = {
                "status": "READY",
                "source": regime_source,
                "signal_date": signal_date.isoformat(),
                "last_observation_date": kospi_last_date.isoformat(),
            }
        except Exception as exc:
            message = f"KOSPI 시장국면 오류: {exc}"
            logging.error(f"{message}; 신규 매수를 차단합니다")
            dependency_errors.append(message)

        from storage.postgres.repositories.company_risk_repo import fetch_buy_blocked_stock_codes
        blocked_codes = None
        try:
            blocked_codes = fetch_buy_blocked_stock_codes(self.db, _today_kst())
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

        inverse_hedge = {
            "schema_version": 1,
            "instrument": "KODEX_INVERSE_1X",
            "ticker": inverse_ticker,
            "status": "DISABLED",
            "reason": "PAPER_ONLY",
            "target_weight": 0.0,
            "current_weight": 0.0,
        }
        if self.inverse_hedge_enabled:
            hedge_decision, hedge_state = evaluate_inverse_hedge(
                signal_date=signal_date,
                regime_frame=regime_frame if regime_frame is not None else pd.DataFrame(),
                close=kospi_close,
                market_regime=market_regime,
                position=positions.get(inverse_ticker),
                total_eval=float(total_eval),
                state=self._read_json_state(self.inverse_hedge_state_path),
                config=self.inverse_hedge_config,
            )
            self._write_json_state(self.inverse_hedge_state_path, hedge_state)
            inverse_hedge = {**hedge_decision, "ticker": inverse_ticker}

            # A first confirmed downtrend immediately moves ordinary long
            # holdings to cash. The separate inverse entry still waits for its
            # confirmation, confidence, cooldown, and dedicated risk gates.
            if market_regime == "DOWNTREND":
                for ticker in list(target_positions.keys()):
                    if ticker != inverse_ticker:
                        target_positions[ticker] = 0.0
                        if ticker in target_details:
                            target_details[ticker]["signal_reason"] = "DOWNTREND"

            if inverse_ticker in positions or inverse_hedge["target_weight"] > 0:
                target_positions[inverse_ticker] = inverse_hedge["target_weight"]
                target_details[inverse_ticker] = {
                    "signal_reason": inverse_hedge["reason"],
                    "fa_score": None,
                    "momentum": None,
                }
        elif inverse_ticker in positions:
            # Do not leave an inverse position unmanaged when the PAPER-only
            # policy is disabled or the trader is instantiated in another mode.
            target_positions[inverse_ticker] = 0.0
            target_details[inverse_ticker] = {
                "signal_reason": "DOWNTREND_EXIT",
                "fa_score": None,
                "momentum": None,
            }

        data_health["insufficient_history_tickers"] = sorted(insufficient_history)
        data_health["held_stale_tickers"] = sorted(set(positions) - usable_signal_tickers)
        data_health["risk_checks_total"] = len(positions)
        data_health["risk_checks_completed"] = risk_checked
        data_health["risk_check_coverage"] = (
            risk_checked / len(positions) if positions else 1.0
        )
        data_health["dependency_errors"] = dependency_errors
        data_health["market_regime_data"] = market_regime_data
        data_health["daily_return_decimal"] = daily_return_decimal
        data_health["execution_ledger"] = execution_ledger_health
        dependency_entry_blocker = (
            "DEPENDENCY_ERROR_ENTRY_BLOCK" if dependency_errors else None
        )
        data_health["entry_circuit_breaker"] = (
            entry_circuit_breaker
            or execution_ledger_entry_blocker
            or dependency_entry_blocker
        )
        shadow_reentry = None
        portfolio_cap_shadow = None
        if self.execution_venue == "PAPER":
            try:
                shadow_reentry = evaluate_paper_shadow_reentry(
                    mode=self.execution_venue,
                    strategy=self.strategy_name,
                    account_scope=getattr(self.broker, "masked_account", "UNKNOWN"),
                    signal_date=signal_date,
                    ohlcv_store=ohlcv_store,
                    positions=positions,
                    log_dir=self.log_dir,
                )
                data_health["shadow_reentry"] = {
                    "variant": shadow_reentry["variant"],
                    "observe_only": True,
                    "completed_observation_sessions": shadow_reentry[
                        "completed_observation_sessions"
                    ],
                    "required_observation_sessions": shadow_reentry[
                        "required_observation_sessions"
                    ],
                    "risk_exit_count": shadow_reentry["risk_exit_count"],
                    "shadow_ready_candidate_count": shadow_reentry[
                        "shadow_ready_candidate_count"
                    ],
                }
            except Exception as exc:
                logging.exception("PAPER shadow re-entry observation failed: %s", exc)
                data_health["shadow_reentry"] = {
                    "variant": "R_TREND_REARM",
                    "observe_only": True,
                    "status": "OBSERVATION_ERROR",
                    "error": str(exc),
                }
        self.last_data_health = data_health

        target_positions = self._apply_portfolio_limits(
            target_positions, target_details, positions
        )
        target_positions = self._apply_transition_exposure_cap(
            target_positions,
            target_details,
            market_regime,
        )
        if dependency_entry_blocker:
            target_positions = self._apply_entry_circuit_breaker(
                target_positions,
                target_details,
                positions,
                total_eval,
                dependency_entry_blocker,
            )
        if execution_ledger_entry_blocker:
            target_positions = self._apply_entry_circuit_breaker(
                target_positions,
                target_details,
                positions,
                total_eval,
                execution_ledger_entry_blocker,
            )
        if entry_circuit_breaker:
            target_positions = self._apply_entry_circuit_breaker(
                target_positions,
                target_details,
                positions,
                total_eval,
                entry_circuit_breaker,
            )
        inverse_hedge["effective_target_weight"] = round(
            float(target_positions.get(inverse_ticker, 0.0)), 4
        )
        if (
            inverse_hedge.get("target_weight", 0.0) > 0
            and inverse_hedge["effective_target_weight"] <= 0
        ):
            inverse_hedge["entry_blocked_by"] = target_details.get(
                inverse_ticker, {}
            ).get("signal_reason", "ENTRY_CIRCUIT_BREAKER")
        inverse_hedge = self._inverse_hedge_dashboard_payload(
            inverse_hedge,
            positions,
            total_eval,
            kospi_close,
            ohlcv_store,
        )
        data_health["inverse_hedge"] = inverse_hedge
        self.last_data_health = data_health
        if self.execution_venue == "PAPER":
            try:
                portfolio_cap_shadow = evaluate_paper_portfolio_cap_shadow(
                    mode=self.execution_venue,
                    strategy=self.strategy_name,
                    account_scope=getattr(self.broker, "masked_account", "UNKNOWN"),
                    signal_date=signal_date,
                    target_positions=target_positions,
                    log_dir=self.log_dir,
                )
                data_health["portfolio_cap_shadow"] = {
                    "variants": [
                        challenger["variant"]
                        for challenger in portfolio_cap_shadow["challengers"]
                    ],
                    "observe_only": True,
                    "order_permission": "DENIED_BY_DESIGN",
                    "observed_session_count": len(
                        portfolio_cap_shadow["observed_sessions"]
                    ),
                }
            except Exception as exc:
                logging.exception("PAPER portfolio-cap observation failed: %s", exc)
                data_health["portfolio_cap_shadow"] = {
                    "variants": ["C_CAP10", "C_CAP08"],
                    "observe_only": True,
                    "status": "OBSERVATION_ERROR",
                    "error": str(exc),
                }
        self._write_decision_snapshot(
            total_eval,
            positions,
            target_positions,
            target_details,
            market_regime or "UNAVAILABLE",
            signal_date=signal_date,
            inverse_hedge=inverse_hedge,
        )

        signal_evaluation = self._signal_evaluation_summary(
            target_details, target_positions
        )
        data_health["signal_evaluation"] = signal_evaluation
        self.last_data_health = data_health

        print(f"[타겟 산출 완료] 타겟 포지션 수: {len([t for t, w in target_positions.items() if w > 0.0])}개")

        # 4. 주문 후보 계산. DRY_RUN에서는 후보만 기록되고 실제 주문은 0건이다.
        orders = self._calculate_orders(
            total_eval, positions, target_positions, ohlcv_store, target_details
        )
        self.last_order_candidates = list(orders)
        candidate_summary = self._candidate_order_summary(orders)
        suppression_summary = self._suppression_summary(
            getattr(self, "last_order_suppressions", [])
        )
        data_health["order_suppressions"] = suppression_summary
        dashboard_state["data_health"] = data_health
        dashboard_state["signal_evaluation"] = signal_evaluation
        dashboard_state["inverse_hedge"] = inverse_hedge
        if shadow_reentry is not None:
            dashboard_state["shadow_reentry"] = shadow_reentry
        if portfolio_cap_shadow is not None:
            dashboard_state["portfolio_cap_shadow"] = portfolio_cap_shadow
        dashboard_state["order_candidates"] = candidate_summary
        dashboard_state["order_suppressions"] = suppression_summary
        dashboard_state["execution_sample_progress"] = (
            self._execution_sample_progress()
        )
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
            suppressions = list(
                getattr(self, "last_order_suppressions", []) or []
            )
            if suppressions:
                buy_blocked = sum(row.get("side") == "BUY" for row in suppressions)
                sell_blocked = sum(row.get("side") == "SELL" for row in suppressions)
                summary += (
                    f" / 안전차단 매수 {buy_blocked}건·매도 {sell_blocked}건"
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
        suppression_summary = self._suppression_summary(
            getattr(self, "last_order_suppressions", [])
        )
        dashboard_state["order_suppressions"] = suppression_summary
        data_health = getattr(self, "last_data_health", {}) or dashboard_state.get(
            "data_health", {}
        )
        data_health = dict(data_health)
        data_health["order_suppressions"] = suppression_summary
        self.last_data_health = data_health
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
    def _signal_evaluation_summary(target_details, target_positions):
        """Summarize why symbols did or did not produce target exposure.

        This is diagnostic evidence only: it does not alter target weights or
        order permissions.  Keeping reason counts beside the order outcome
        distinguishes a quiet strategy scan from a broker execution failure.
        """
        details = target_details or {}
        targets = target_positions or {}
        reason_counts = Counter(
            str((detail or {}).get("signal_reason") or "UNKNOWN")
            for detail in details.values()
        )
        condition_breakdown = Counter()
        ta_failure_breakdown = Counter()
        for detail in details.values():
            if str((detail or {}).get("signal_reason")) != "ENTRY_CONDITIONS_NOT_MET":
                continue
            fa_met = (detail or {}).get("fa_conditions_met")
            ta_met = (detail or {}).get("ta_conditions_met")
            if fa_met is True and ta_met is False:
                condition_breakdown["FA_PASS_TA_FAIL"] += 1
            elif fa_met is False and ta_met is False:
                condition_breakdown["FA_FAIL_TA_FAIL"] += 1
            elif fa_met is True and ta_met is True:
                condition_breakdown["FA_PASS_TA_PASS"] += 1
            else:
                condition_breakdown["UNAVAILABLE"] += 1
            if ta_met is not False:
                continue
            try:
                if float((detail or {}).get("close")) <= float((detail or {}).get("ma")):
                    ta_failure_breakdown["CLOSE_NOT_ABOVE_MA"] += 1
            except (TypeError, ValueError):
                ta_failure_breakdown["CLOSE_MA_UNAVAILABLE"] += 1
            try:
                if float((detail or {}).get("ma_fast")) <= float((detail or {}).get("ma")):
                    ta_failure_breakdown["FAST_MA_NOT_ABOVE_MA"] += 1
            except (TypeError, ValueError):
                ta_failure_breakdown["FAST_MA_UNAVAILABLE"] += 1
            try:
                if float((detail or {}).get("momentum")) <= 0:
                    ta_failure_breakdown["MOMENTUM_NON_POSITIVE"] += 1
            except (TypeError, ValueError):
                ta_failure_breakdown["MOMENTUM_UNAVAILABLE"] += 1
        selected_count = sum(
            float(targets.get(ticker, 0.0) or 0.0) > 0.0 for ticker in targets
        )
        return {
            "evaluated_count": len(details),
            "selected_count": int(selected_count),
            "target_weight_sum": round(
                sum(float(value or 0.0) for value in targets.values()), 6
            ),
            "reason_counts": dict(sorted(reason_counts.items())),
            "condition_breakdown": dict(sorted(condition_breakdown.items())),
            "ta_failure_breakdown": dict(sorted(ta_failure_breakdown.items())),
        }

    @staticmethod
    def _suppression_summary(suppressions):
        rows = list(suppressions or [])
        by_reason = {}
        incident_codes = {}
        for row in rows:
            reason = row.get("reason") or "UNKNOWN"
            by_reason[reason] = by_reason.get(reason, 0) + 1
            incident_code = row.get("incident_code")
            if incident_code:
                incident_codes[incident_code] = incident_codes.get(incident_code, 0) + 1
        return {
            "total": len(rows),
            "buy": sum(row.get("side") == "BUY" for row in rows),
            "sell": sum(row.get("side") == "SELL" for row in rows),
            "by_reason": by_reason,
            "incident_codes": incident_codes,
            "symbols": sorted({row.get("ticker") for row in rows if row.get("ticker")}),
        }

    @staticmethod
    def _broker_incident_code(message):
        """Return a safe, aggregate-only broker failure code for audit output."""
        text = str(message or "")
        existing = re.search(
            r"\b(BROKER_(?:HTTP_[45]\d{2}|TIMEOUT|TRANSPORT_ERROR|REJECTED|"
            r"UNKNOWN_RESULT|PRICE_LOOKUP_FAILED|BALANCE_LOOKUP_FAILED|"
            r"STATUS_LOOKUP_FAILED))\b",
            text,
            re.I,
        )
        if existing:
            return existing.group(1).upper()
        match = re.search(
            r"\b([45]\d{2})\s+(?:server|client)\s+error\b",
            text,
            re.I,
        )
        if match:
            return f"BROKER_HTTP_{match.group(1)}"
        lowered = text.lower()
        if "timeout" in lowered or "timed out" in lowered:
            return "BROKER_TIMEOUT"
        if any(marker in lowered for marker in (
            "connection", "network", "transport", "ssl", "socket",
            "connectionpool", "remote disconnected",
        )):
            return "BROKER_TRANSPORT_ERROR"
        return None

    @staticmethod
    def _safe_broker_failure_code(message, default):
        """Return an operator-safe failure code without persisting broker text."""
        return LiveTrader._broker_incident_code(message) or default

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
        suppressions = health.get("order_suppressions") or {}
        suppression_reasons = set((suppressions.get("by_reason") or {}).keys())
        critical_suppressions = {
            "AMBIGUOUS_RESULT_SAME_DAY",
            "PRICE_GUARD_COOLDOWN",
            "RETRY_LIMIT",
        }
        if suppression_reasons & critical_suppressions:
            return "ORDER_SUPPRESSION"
        if int(suppressions.get("total") or 0) > 0:
            return "ORDER_DEDUPLICATION"
        if health.get("held_stale_tickers"):
            return "DEGRADED_DATA_STALE"
        if int(health.get("stale_count") or 0) or int(health.get("missing_count") or 0):
            return "DEGRADED_DATA_STALE"
        if health.get("dependency_errors"):
            return "DEGRADED_DEPENDENCY"
        if last_error:
            return "ERROR"
        return "NORMAL"

    @staticmethod
    def _derive_scan_operational_status(
        previous_data_health, actual_orders, unresolved_error=None
    ):
        """Keep a prior actionable safety state visible while a new scan runs."""
        if unresolved_error:
            return "ORDER_RECONCILIATION"
        status = LiveTrader._derive_operational_status(
            previous_data_health,
            actual_orders,
        )
        return "SCANNING" if status == "NORMAL" else status

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
            "order_suppressions": dashboard_state.get("order_suppressions", {}),
            "execution_sample_progress": dashboard_state.get(
                "execution_sample_progress", {}
            ),
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
            strategy_name, execution_venue, account_scope = self._order_scope()
            rows = self.db.fetch_all(
                """SELECT o.order_side_code, o.order_status_code, COUNT(*) AS count
                   FROM orders o
                   JOIN strategies s ON s.id = o.strategy_id
                   WHERE (o.created_at AT TIME ZONE 'Asia/Seoul')::date =
                         (CURRENT_TIMESTAMP AT TIME ZONE 'Asia/Seoul')::date
                     AND s.name = %s
                     AND o.execution_venue_code = %s
                     AND o.account_scope = %s
                   GROUP BY o.order_side_code, o.order_status_code""",
                (
                    strategy_name,
                    execution_venue,
                    account_scope,
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

    def _execution_sample_progress(self):
        """Expose cumulative PAPER order-side samples without changing execution."""
        empty = {
            "buy": 0,
            "sell": 0,
            "required_per_side": 30,
            "observed_order_count": 0,
            "sample_ready": False,
            "status": "UNAVAILABLE",
        }
        if getattr(self, "execution_venue", None) in {"DRY_RUN", "SIMULATE"}:
            return empty
        if getattr(getattr(self, "broker", None), "is_simulated", False):
            return empty
        if not hasattr(self, "db"):
            return empty
        try:
            strategy_name, execution_venue, account_scope = self._order_scope()
            rows = self.db.fetch_all(
                """SELECT o.order_side_code, COUNT(*) AS count
                   FROM orders o
                   JOIN strategies s ON s.id = o.strategy_id
                   WHERE s.name = %s
                     AND o.execution_venue_code = %s
                     AND o.account_scope = %s
                   GROUP BY o.order_side_code""",
                (strategy_name, execution_venue, account_scope),
            )
        except Exception as exc:
            logging.warning(f"execution sample progress unavailable: {exc}")
            return empty
        buy = sum(
            int(row.get("count") or 0)
            for row in rows
            if row.get("order_side_code") == "BUY"
        )
        sell = sum(
            int(row.get("count") or 0)
            for row in rows
            if row.get("order_side_code") == "SELL"
        )
        ready = buy >= 30 and sell >= 30
        return {
            "buy": buy,
            "sell": sell,
            "required_per_side": 30,
            "observed_order_count": buy + sell,
            "sample_ready": ready,
            "status": "READY" if ready else "PROVISIONAL_SMALL_SAMPLE",
        }

    def _order_scope(self):
        """Return the current strategy/account scope used by every order query."""
        strategy_name = getattr(self, "strategy_name", None)
        execution_venue = getattr(self, "execution_venue", None)
        account_scope = getattr(
            getattr(self, "broker", None), "masked_account", None
        )
        if not strategy_name or not execution_venue or not account_scope:
            raise RuntimeError("strategy, execution venue, and account scope are required")
        if execution_venue == "UNKNOWN" or account_scope == "UNKNOWN":
            raise RuntimeError("unknown execution venue/account scope is not allowed")
        return strategy_name, execution_venue, account_scope

    @staticmethod
    def _read_json_state(path):
        try:
            return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        except (OSError, ValueError, TypeError):
            return {}

    @staticmethod
    def _write_json_state(path, payload):
        path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = path.with_suffix(path.suffix + ".tmp")
        temp_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        temp_path.replace(path)

    @staticmethod
    def _validate_completed_kospi_close(close, signal_date):
        if not isinstance(close, pd.Series):
            raise ValueError("KOSPI close data must be a pandas Series")
        normalized = close.dropna().sort_index().astype(float)
        if len(normalized) < 200:
            raise ValueError("KOSPI close history has fewer than 200 observations")
        last_date = pd.Timestamp(normalized.index[-1]).date()
        if last_date != signal_date:
            raise ValueError(
                f"KOSPI close history is stale: last={last_date}, expected={signal_date}"
            )
        return normalized

    def _read_cached_kospi_close(self, signal_date):
        payload = self._read_json_state(self.market_regime_cache_path)
        if payload.get("signal_date") != signal_date.isoformat():
            return None
        rows = payload.get("closes")
        if not isinstance(rows, list) or not rows:
            return None
        try:
            close = pd.Series(
                [float(row["close"]) for row in rows],
                index=pd.to_datetime([row["date"] for row in rows]),
                dtype=float,
            )
            return self._validate_completed_kospi_close(close, signal_date)
        except (KeyError, TypeError, ValueError):
            return None

    def _load_completed_kospi_close(self, *, signal_date, start_date, end_date):
        """Load one immutable completed-session KOSPI series per signal date."""
        cached = self._read_cached_kospi_close(signal_date)
        if cached is not None:
            return cached, "DAILY_VALIDATED_CACHE"

        close = self._validate_completed_kospi_close(
            download_kospi_index(start_date, end_date),
            signal_date,
        )
        self._write_json_state(
            self.market_regime_cache_path,
            {
                "schema_version": 1,
                "signal_date": signal_date.isoformat(),
                "cached_at": datetime.datetime.now(
                    ZoneInfo("Asia/Seoul")
                ).isoformat(timespec="seconds"),
                "closes": [
                    {
                        "date": pd.Timestamp(index).date().isoformat(),
                        "close": float(value),
                    }
                    for index, value in close.items()
                ],
            },
        )
        return close, "PROVIDER_REFRESH"

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
        self,
        total_eval,
        positions,
        target_positions,
        target_details,
        market_regime,
        signal_date=None,
        inverse_hedge=None,
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
                "is_eligible": detail.get("is_eligible"),
                "fa_conditions_met": detail.get("fa_conditions_met"),
                "ta_conditions_met": detail.get("ta_conditions_met"),
                "score_confidence": detail.get("score_confidence"),
                "debt_ratio": detail.get("debt_ratio"),
                "close": detail.get("close"),
                "ma": detail.get("ma"),
                "ma_fast": detail.get("ma_fast"),
                "momentum": detail.get("momentum"),
                "transition_exposure_scale": detail.get(
                    "transition_exposure_scale"
                ),
                "selected": float(target_positions.get(ticker, 0.0)) > 0.0,
            })
        payload = {
            "updated_at": datetime.datetime.now().isoformat(timespec="seconds"),
            "mode": self.execution_venue,
            "strategy": self.strategy_name,
            "market_regime": market_regime,
            "signal_date": (
                signal_date.isoformat() if hasattr(signal_date, "isoformat") else None
            ),
            "target_count": sum(row["selected"] for row in rows),
            "decisions": rows,
            "transition_policy": {
                "entry_enabled": bool(
                    getattr(
                        getattr(self, "strategy", None),
                        "TRANSITION_ENTRY_ENABLED",
                        False,
                    )
                ),
                "entry_size": float(
                    getattr(
                        getattr(self, "strategy", None),
                        "TRANSITION_ENTRY_SIZE",
                        0.10,
                    )
                ),
                "keep_ratio": float(
                    getattr(
                        getattr(self, "strategy", None),
                        "TRANSITION_KEEP_RATIO",
                        0.40,
                    )
                ),
                "max_gross_exposure": float(
                    getattr(self, "transition_max_gross_exposure", 0.30)
                ),
            },
        }
        if isinstance(inverse_hedge, dict):
            payload["inverse_hedge"] = inverse_hedge
        state_path = self.log_dir / "decision_state.json"
        temp_path = self.log_dir / "decision_state.json.tmp"
        with temp_path.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, default=str)
        os.replace(temp_path, state_path)
        with (self.log_dir / "decision_history.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")

    @staticmethod
    def _inverse_hedge_dashboard_payload(
        decision, positions, total_eval, kospi_close, ohlcv_store
    ):
        """Attach observed exposure, PnL, and a clearly-labelled proxy gap."""
        payload = dict(decision or {})
        inverse_ticker = Tickers.INVERSE_ETF.ticker
        inverse_position = (positions or {}).get(inverse_ticker, {})

        def position_value(position):
            return float(position.get("qty") or 0.0) * float(
                position.get("current_price") or position.get("avg_price") or 0.0
            )

        inverse_value = position_value(inverse_position)
        long_value = sum(
            position_value(position)
            for ticker, position in (positions or {}).items()
            if ticker != inverse_ticker
        )
        total = float(total_eval or 0.0)
        actual_weight = inverse_value / total if total > 0 else 0.0
        long_weight = long_value / total if total > 0 else 0.0
        average = float(inverse_position.get("avg_price") or 0.0)
        current = float(inverse_position.get("current_price") or 0.0)
        quantity = float(inverse_position.get("qty") or 0.0)
        pnl = quantity * (current - average) if average > 0 and current > 0 else 0.0

        payload.update({
            "actual_weight": round(actual_weight, 6),
            "long_market_weight": round(long_weight, 6),
            "net_market_exposure": round(long_weight - actual_weight, 6),
            "unrealized_pnl": round(pnl, 2),
            "profit_rate": (
                round((current / average - 1.0) * 100, 4)
                if average > 0 and current > 0 else None
            ),
            "position_open": quantity > 0,
            "tracking_reference": "KOSPI_CLOSE_PROXY",
            "tracking_gap": None,
        })
        try:
            inverse_close = ohlcv_store.get(inverse_ticker, pd.DataFrame())["close"]
            inverse_return = float(inverse_close.iloc[-1] / inverse_close.iloc[-2] - 1.0)
            market_return = float(kospi_close.iloc[-1] / kospi_close.iloc[-2] - 1.0)
            payload["daily_inverse_return"] = round(inverse_return, 6)
            payload["daily_market_return"] = round(market_return, 6)
            payload["tracking_gap"] = round(inverse_return + market_return, 6)
        except (AttributeError, IndexError, KeyError, TypeError, ValueError, ZeroDivisionError):
            pass
        return payload

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

    def _append_trade_history_reconciliation(
        self, broker_order_id, final_status, status_payload=None
    ):
        """Append a final broker-status correction without rewriting raw history.

        The first broker poll can return ``PARTIAL`` while a later
        reconciliation poll proves ``FILLED``. Keeping only the first result
        makes the intraday log disagree with the database ledger. An
        append-only correction preserves that raw observation and records the
        later authoritative status for evidence builders.
        """
        broker_id = str(broker_order_id or "").strip()
        if not broker_id:
            return False
        path = self.log_dir / "trade_history.jsonl"
        if not path.exists():
            return False

        latest = None
        try:
            for raw in path.read_text(encoding="utf-8").splitlines():
                if not raw.strip():
                    continue
                try:
                    row = json.loads(raw)
                except (TypeError, ValueError, json.JSONDecodeError):
                    continue
                if str(row.get("broker_order_id") or "").strip() == broker_id:
                    latest = row
        except OSError as exc:
            logging.warning("trade history reconciliation read failed: %s", exc)
            return False

        normalized_status = str(final_status or "").upper()
        if not latest or str(latest.get("status") or "").upper() == normalized_status:
            return False

        timestamp = datetime.datetime.now().isoformat(timespec="seconds")
        correction = {
            **latest,
            "timestamp": timestamp,
            "status": final_status,
            "previous_status": latest.get("status"),
            "status_source": "PAPER_ORDER_RECONCILIATION",
            "reconciliation_event": "ORDER_STATUS_CORRECTION",
            "reconciled_at": timestamp,
        }
        if isinstance(status_payload, dict):
            for key in (
                "ordered_qty",
                "filled_qty",
                "remaining_qty",
                "avg_fill_price",
                "total_fill_amount",
            ):
                if key in status_payload:
                    correction[key] = status_payload[key]
            raw_payload = status_payload.get("raw") or {}
            correction["reconciliation_source"] = (
                raw_payload.get("source", "BROKER_STATUS_RECONCILIATION")
                if isinstance(raw_payload, dict)
                else "BROKER_STATUS_RECONCILIATION"
            )

        try:
            with path.open("a", encoding="utf-8") as handle:
                handle.write(
                    json.dumps(correction, ensure_ascii=False, default=str) + "\n"
                )
        except OSError as exc:
            logging.warning("trade history reconciliation write failed: %s", exc)
            return False
        return True

    def _reconcile_trade_history_with_db(self):
        """Backfill terminal statuses for today's raw trade-history events.

        A prior scan may have logged ``PARTIAL`` before a later scan resolved
        the same order to ``FILLED``. This read-only pass joins those raw log
        rows to the scoped order table so the correction is recorded even when
        the database order is already terminal and no longer appears in the
        open-order reconciliation query.
        """
        path = self.log_dir / "trade_history.jsonl"
        if not path.exists():
            return 0
        today = _today_kst().isoformat()
        open_statuses = {"PENDING", "SUBMITTED", "ACCEPTED", "PARTIAL", "UNKNOWN"}
        pending_ids = set()
        try:
            for raw in path.read_text(encoding="utf-8").splitlines():
                if not raw.strip():
                    continue
                try:
                    row = json.loads(raw)
                except (TypeError, ValueError, json.JSONDecodeError):
                    continue
                if not str(row.get("timestamp") or "").startswith(today):
                    continue
                if str(row.get("status") or "").upper() not in open_statuses:
                    continue
                broker_id = str(row.get("broker_order_id") or "").strip()
                if broker_id:
                    pending_ids.add(broker_id)
        except OSError as exc:
            logging.warning("trade history reconciliation scan failed: %s", exc)
            return 0
        if not pending_ids:
            return 0

        try:
            strategy_name, execution_venue, account_scope = self._order_scope()
            rows = self.db.fetch_all(
                """SELECT o.broker_order_id, o.order_status_code, o.qty,
                          o.filled_qty, o.avg_fill_price
                   FROM orders o
                   JOIN strategies s ON s.id = o.strategy_id
                   WHERE (o.created_at AT TIME ZONE 'Asia/Seoul')::date =
                         (CURRENT_TIMESTAMP AT TIME ZONE 'Asia/Seoul')::date
                     AND o.broker_order_id = ANY(%s)
                     AND s.name = %s
                     AND o.execution_venue_code = %s
                     AND o.account_scope = %s""",
                (list(pending_ids), strategy_name, execution_venue, account_scope),
            )
        except Exception as exc:
            logging.warning("trade history reconciliation query failed: %s", exc)
            return 0

        corrections = 0
        for row in rows:
            final_status = str(row.get("order_status_code") or "").upper()
            if final_status not in {"FILLED", "CANCELLED", "REJECTED"}:
                continue
            broker_id = str(row.get("broker_order_id") or "").strip()
            if self._append_trade_history_reconciliation(
                broker_id,
                final_status,
                {
                    "ordered_qty": row.get("qty"),
                    "filled_qty": row.get("filled_qty"),
                    "remaining_qty": max(
                        float(row.get("qty") or 0)
                        - float(row.get("filled_qty") or 0),
                        0.0,
                    ),
                    "avg_fill_price": row.get("avg_fill_price"),
                    "raw": {"source": "PAPER_TRADE_HISTORY_DB_RECONCILIATION"},
                },
            ):
                corrections += 1
        return corrections


        
        


    def _load_published_fa_candidates(self, cutoff_date, as_of_date=None):
        """검증·발행된 최신 월간 FA 결과만 라이브 후보로 반환한다."""
        as_of_date = as_of_date or _today_kst()
        model_version = getattr(self, "fa_model_version", REAL_TRADING_MODEL_VERSION)
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
              AND r.model_version = %s
              AND r.effective_date <= %s::date
              {quality_condition}
            ORDER BY r.effective_date DESC, r.run_version DESC, r.id DESC
            LIMIT 1
            """,
            (self.strategy_name, model_version, as_of_date),
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
                today = _today_kst()

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
