import datetime
import pandas as pd
import numpy as np
import json
import pytest
from core.strategy.fa_ta_momentum import FaTaMomentumStrategy
from core.execution.trader import LiveTrader
from apps.worker.fa_contract import DEFAULT_CONFIG as FA_CONTRACT
from run_live_trader import build_result_message, send_intraday_notification_once

def test_fa_ta_momentum_strategy_signals():
    params = {
        "entry_size": 0.2,
        "ma_window": 10,
        "ma_window_fast": 5,
        "fa_score_min": 60.0,
        "fa_score_exit": 40.0,
        "debt_ratio_max": 2.0,
    }
    strategy = FaTaMomentumStrategy(params)
    
    # Create mock OHLCV with FA metrics
    dates = pd.date_range(start="2026-01-01", periods=20, freq="D")
    ohlcv = pd.DataFrame({
        "open": np.linspace(100, 200, 20),
        "high": np.linspace(105, 205, 20),
        "low": np.linspace(95, 195, 20),
        "close": np.linspace(100, 200, 20),  # strictly increasing
        "volume": [1000] * 20,
        "fa_score": [75.0] * 20,
        "is_eligible": [True] * 20,
        "debt_ratio": [1.2] * 20,
        "score_confidence": [0.9] * 20,
        "fa_is_stale": [False] * 20,
    }, index=dates)
    
    regime_df = pd.DataFrame({"REGIME": ["UPTREND"] * 20}, index=dates)
    
    # UPTREND regime with high fa_score and positive momentum -> BUY signal
    signals = strategy.make_signals(ohlcv, regime_df)
    non_nan_signals = signals.dropna()
    
    assert len(non_nan_signals) == 1
    assert non_nan_signals.iloc[0] > 0.0
    
    # Test exit when fa_score deteriorates below FA_SCORE_EXIT
    ohlcv_exit = ohlcv.copy()
    ohlcv_exit.loc[dates[-1], "fa_score"] = 35.0  # below 40.0
    
    state = None
    signals_exit, meta = strategy.make_signals_with_metadata(ohlcv_exit, regime_df, state)
    non_nan_exit_signals = signals_exit.dropna()
    
    # Should have a buy signal and then a sell signal (0.0)
    assert len(non_nan_exit_signals) == 2
    assert non_nan_exit_signals.iloc[-1] == 0.0
    # The last row's signal reason should reflect the exit reason
    assert meta["signal_reason"].iloc[-1] == "FA_SCORE_DETERIORATED"


def test_live_trader_calculate_orders(monkeypatch):
    # Mock KisBroker and PostgreDB to avoid connections during init
    monkeypatch.setattr("core.execution.trader.KisBroker", lambda *args, **kwargs: None)
    class FakeDB:
        def fetch_all(self, *args, **kwargs):
            return []

    monkeypatch.setattr("core.execution.trader.PostgreDB", lambda *args, **kwargs: FakeDB())
    monkeypatch.setenv("POSTGRES_PASSWORD", "test-only")
    
    trader = LiveTrader(mock=True)
    trader.broker = type("Broker", (), {"masked_account": "***1234-01"})()
    assert trader.strategy.FA_SCORE_MIN == FA_CONTRACT.minimum_company_fa_score
    
    total_eval = 10_000_000
    current_positions = {
        "005930": {"qty": 10, "avg_price": 70000, "current_price": 80000, "profit_rate": 14.28}
    }
    
    # If 005930 target weight is 0.0 -> SELL order
    # If 000660 target weight is 0.2 -> BUY order
    target_positions = {
        "005930": 0.0,
        "000660": 0.2,
    }
    
    ohlcv_store = {
        "000660": pd.DataFrame({"close": [150_000]}, index=[pd.Timestamp("2026-07-08")]),
    }
    
    orders = trader._calculate_orders(total_eval, current_positions, target_positions, ohlcv_store)
    
    sell_orders = [o for o in orders if o["type"] == "SELL"]
    buy_orders = [o for o in orders if o["type"] == "BUY"]
    
    assert len(sell_orders) == 1
    assert sell_orders[0]["ticker"] == "005930"
    assert sell_orders[0]["qty"] == 10
    
    assert len(buy_orders) == 1
    assert buy_orders[0]["ticker"] == "000660"
    # Target value: 10,000,000 * 0.2 = 2,000,000
    # Qty: 2,000,000 // 150,000 = 13
    assert buy_orders[0]["qty"] == 13


def test_portfolio_limit_does_not_cap_position_count():
    trader = object.__new__(LiveTrader)
    trader.max_position_weight = 0.90
    targets = {"HELD1": 0.2, "HELD2": 0.2, "NEW": 0.2}
    details = {
        "HELD1": {"fa_score": 70, "momentum": 0.10},
        "HELD2": {"fa_score": 60, "momentum": 0.10},
        "NEW": {"fa_score": 90, "momentum": 0.10},
    }

    result = trader._apply_portfolio_limits(
        targets, details, {"HELD1": {}, "HELD2": {}}
    )

    assert all(result[ticker] > 0 for ticker in targets)
    assert sum(result.values()) == pytest.approx(0.9)
    assert result["NEW"] > result["HELD1"] > result["HELD2"]
    assert result["NEW"] / result["HELD2"] == pytest.approx(4.0, rel=1e-3)


def test_portfolio_limit_caps_single_name_concentration():
    trader = object.__new__(LiveTrader)
    trader.max_position_weight = 0.15
    targets = {"A": 0.4, "B": 0.3, "C": 0.2}
    details = {
        "A": {"fa_score": 90}, "B": {"fa_score": 70}, "C": {"fa_score": 60},
    }

    result = trader._apply_portfolio_limits(targets, details, {})

    assert all(weight <= 0.15 for weight in result.values())
    assert sum(result.values()) == pytest.approx(0.45)


def test_many_positions_are_scaled_to_total_exposure_limit():
    trader = object.__new__(LiveTrader)
    targets = {f"T{index}": 0.2 for index in range(10)}
    details = {ticker: {} for ticker in targets}

    result = trader._apply_portfolio_limits(targets, details, {})

    assert len([weight for weight in result.values() if weight > 0]) == 10
    assert sum(result.values()) == pytest.approx(0.90)
    assert all(weight == pytest.approx(0.09) for weight in result.values())


def test_portfolio_limit_preserves_position_when_data_is_unavailable():
    trader = object.__new__(LiveTrader)
    targets = {"RANKED": 0.2, "NO_DATA": 0.15}
    details = {
        "RANKED": {"fa_score": 90, "momentum": 0.10},
        "NO_DATA": {
            "fa_score": 0,
            "momentum": -1,
            "signal_reason": "DATA_UNAVAILABLE_HOLD",
        },
    }

    result = trader._apply_portfolio_limits(targets, details, {"NO_DATA": {}})

    assert result["RANKED"] > 0
    assert result["NO_DATA"] == 0.15


def test_cancelled_order_uses_next_idempotency_attempt(monkeypatch):
    trader = object.__new__(LiveTrader)
    trader.strategy_name = "aggressive"
    trader.execution_venue = "PAPER"
    trader.broker = type("Broker", (), {"masked_account": "***1234-01"})()
    trader.max_order_attempts = 2
    trader.db = type("DB", (), {
        "fetch_all": lambda *a, **k: [{
            "symbol": "005930", "order_side_code": "SELL",
            "order_status_code": "CANCELLED",
        }]
    })()

    orders = trader._calculate_orders(
        1_000_000,
        {"005930.KS": {"qty": 1, "current_price": 100}},
        {"005930.KS": 0.0},
        {},
        {"005930.KS": {"signal_reason": "PORTFOLIO_RANK_EXIT"}},
    )

    assert len(orders) == 1
    assert orders[0]["idempotency_key"]


def test_ambiguous_broker_result_blocks_same_day_retry():
    trader = object.__new__(LiveTrader)
    trader.strategy_name = "aggressive"
    trader.execution_venue = "PAPER"
    trader.broker = type("Broker", (), {"masked_account": "***1234-01"})()
    trader.max_order_attempts = 2
    trader.db = type("DB", (), {
        "fetch_all": lambda *a, **k: [{
            "symbol": "005930", "order_side_code": "BUY",
            "order_status_code": "REJECTED", "had_unknown_result": True,
        }]
    })()
    trader._price_guard_blocked = lambda *args: False

    orders = trader._calculate_orders(
        1_000_000,
        {"005930.KS": {"qty": 1, "current_price": 100}},
        {"005930.KS": 0.15},
        {"005930.KS": pd.DataFrame({"close": [100]})},
    )

    assert orders == []
    assert trader.last_order_suppressions == [{
        "ticker": "005930.KS",
        "side": "BUY",
        "reason": "AMBIGUOUS_RESULT_SAME_DAY",
    }]


def test_filled_order_is_not_reported_as_suppression_when_no_order_is_needed():
    trader = object.__new__(LiveTrader)
    trader.strategy_name = "aggressive"
    trader.execution_venue = "PAPER"
    trader.broker = type("Broker", (), {"masked_account": "***1234-01"})()
    trader.max_order_attempts = 2
    trader.db = type("DB", (), {
        "fetch_all": lambda *a, **k: [{
            "symbol": "005930", "order_side_code": "BUY",
            "order_status_code": "FILLED", "had_unknown_result": False,
        }]
    })()
    trader._price_guard_blocked = lambda *args: False

    orders = trader._calculate_orders(
        1_000_000,
        {"005930.KS": {"qty": 1_450, "current_price": 100}},
        {"005930.KS": 0.15},
        {"005930.KS": pd.DataFrame({"close": [100]})},
    )

    assert orders == []
    assert trader.last_order_suppressions == []


def test_held_position_rebalance_uses_broker_current_price():
    trader = object.__new__(LiveTrader)
    trader.strategy_name = "aggressive"
    trader.execution_venue = "PAPER"
    trader.broker = type("Broker", (), {"masked_account": "***1234-01"})()
    trader.max_order_attempts = 2
    trader.db = type("DB", (), {"fetch_all": lambda *a, **k: []})()
    trader._price_guard_blocked = lambda *args: False

    orders = trader._calculate_orders(
        1_000_000,
        {"005930.KS": {"qty": 200, "current_price": 6_000}},
        {"005930.KS": 0.50},
        {"005930.KS": pd.DataFrame({"close": [1_000]})},
    )

    assert len(orders) == 1
    assert orders[0]["type"] == "SELL"
    assert orders[0]["expected_price"] == 6_000
    assert orders[0]["qty"] == 116


def test_urgent_risk_exit_is_allowed_after_earlier_filled_sell():
    trader = object.__new__(LiveTrader)
    trader.strategy_name = "aggressive"
    trader.execution_venue = "PAPER"
    trader.broker = type("Broker", (), {"masked_account": "***1234-01"})()
    trader.max_order_attempts = 2
    trader.db = type("DB", (), {
        "fetch_all": lambda *a, **k: [{
            "symbol": "005930", "order_side_code": "SELL",
            "order_status_code": "FILLED", "had_unknown_result": False,
        }]
    })()
    trader._price_guard_blocked = lambda *args: False

    orders = trader._calculate_orders(
        1_000_000,
        {"005930.KS": {"qty": 10, "current_price": 100}},
        {"005930.KS": 0.0},
        {},
        {"005930.KS": {"signal_reason": "HARD_STOP_LOSS"}},
    )

    assert len(orders) == 1
    assert orders[0]["reason"] == "HARD_STOP_LOSS"
    assert trader.last_order_suppressions == []


def test_normal_sell_is_blocked_after_earlier_filled_sell():
    trader = object.__new__(LiveTrader)
    trader.strategy_name = "aggressive"
    trader.execution_venue = "PAPER"
    trader.broker = type("Broker", (), {"masked_account": "***1234-01"})()
    trader.max_order_attempts = 2
    trader.db = type("DB", (), {
        "fetch_all": lambda *a, **k: [{
            "symbol": "005930", "order_side_code": "SELL",
            "order_status_code": "FILLED", "had_unknown_result": False,
        }]
    })()
    trader._price_guard_blocked = lambda *args: False

    orders = trader._calculate_orders(
        1_000_000,
        {"005930.KS": {"qty": 10, "current_price": 100}},
        {"005930.KS": 0.0},
        {},
        {"005930.KS": {"signal_reason": "PORTFOLIO_EXIT"}},
    )

    assert orders == []
    assert trader.last_order_suppressions[0]["reason"] == "FILLED_ORDER_TODAY"


def test_result_message_distinguishes_candidate_suppression_from_global_stop():
    message = build_result_message([], [], [{
        "ticker": "021240.KS",
        "side": "BUY",
        "reason": "AMBIGUOUS_RESULT_SAME_DAY",
    }])

    assert "주문 후보 안전 차단" in message
    assert "021240.KS" in message
    assert "전역 신규주문 중지가 아니라" in message


def test_result_message_keeps_suppression_visible_when_another_order_executes():
    order = {
        "ticker": "483650.KS",
        "type": "SELL",
        "qty": 51,
        "reason": "REBALANCE_WEIGHT_REDUCTION",
    }
    message = build_result_message(
        [order],
        [{**order, "status": "FILLED"}],
        [{
            "ticker": "021240.KS",
            "side": "BUY",
            "reason": "AMBIGUOUS_RESULT_SAME_DAY",
        }],
    )

    assert "483650.KS (51주) [FILLED]" in message
    assert "별도 주문 후보 안전 차단" in message
    assert "021240.KS" in message
    assert "전역 신규주문 중지가 아니라" in message


def test_result_message_identifies_true_global_order_pause():
    message = build_result_message(
        [], [], [], "unresolved order circuit breaker: 1 open order"
    )

    assert "미정산 주문 보호 작동" in message
    assert "모든 신규 주문을 일시 중지" in message
    assert "자동 해제" in message


def test_intraday_notification_deduplicates_repeated_state_and_skips_idle(tmp_path):
    state_path = tmp_path / "notification_state.json"
    today = datetime.date(2026, 7, 21)
    bot = type("Bot", (), {
        "calls": [],
        "send_message": lambda self, message: self.calls.append(message) or True,
    })()
    suppression = [{
        "ticker": "021240.KS",
        "side": "BUY",
        "reason": "AMBIGUOUS_RESULT_SAME_DAY",
    }]

    assert not send_intraday_notification_once(
        bot, "idle", [], [], [], None, state_path, today=today
    )
    assert send_intraday_notification_once(
        bot, "suppressed", [], [], suppression, None, state_path, today=today
    )
    assert not send_intraday_notification_once(
        bot, "suppressed", [], [], suppression, None, state_path, today=today
    )
    assert send_intraday_notification_once(
        bot, "paused", [], [], [], "one unresolved order", state_path, today=today
    )
    assert bot.calls == ["suppressed", "paused"]


def test_intraday_notification_failure_is_retried(tmp_path):
    state_path = tmp_path / "notification_state.json"
    today = datetime.date(2026, 7, 21)
    failing_bot = type("Bot", (), {"send_message": lambda *_: False})()
    working_bot = type("Bot", (), {"send_message": lambda *_: True})()
    suppression = [{"ticker": "021240.KS", "reason": "RETRY_LIMIT"}]

    assert not send_intraday_notification_once(
        failing_bot, "blocked", [], [], suppression, None,
        state_path, today=today,
    )
    assert send_intraday_notification_once(
        working_bot, "blocked", [], [], suppression, None,
        state_path, today=today,
    )


def test_order_history_query_is_scoped_to_current_account():
    calls = []

    class DB:
        def fetch_all(self, query, params):
            calls.append((query, params))
            return []

    trader = object.__new__(LiveTrader)
    trader.strategy_name = "aggressive"
    trader.execution_venue = "PAPER"
    trader.broker = type("Broker", (), {"masked_account": "***1234-01"})()
    trader.max_order_attempts = 2
    trader.db = DB()
    trader._price_guard_blocked = lambda *args: False

    trader._calculate_orders(
        1_000_000,
        {},
        {"005930.KS": 0.15},
        {"005930.KS": pd.DataFrame({"close": [100]})},
    )

    query, params = calls[0]
    assert "execution_venue_code = %s" in query
    assert "account_scope = %s" in query
    assert params[1:] == ("aggressive", "PAPER", "***1234-01")


def test_idempotency_key_is_isolated_by_account_scope():
    trader = object.__new__(LiveTrader)
    trader.strategy_name = "aggressive"
    trader.execution_venue = "PAPER"
    trader.broker = type("Broker", (), {"masked_account": "***1111-01"})()
    order = {"ticker": "005930.KS", "type": "BUY", "reason": "ENTRY"}

    first = trader._idempotency_key(order)
    trader.broker = type("Broker", (), {"masked_account": "***2222-01"})()
    second = trader._idempotency_key(order)

    assert first != second


def test_decision_snapshot_explains_zero_and_selected_targets(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    trader = object.__new__(LiveTrader)
    trader.execution_venue = "SIMULATE"
    trader.strategy_name = "aggressive"
    trader.log_dir = tmp_path / "logs" / "simulate"
    trader.log_dir.mkdir(parents=True)
    trader._write_decision_snapshot(
        1_000,
        {"HELD.KS": {"qty": 1, "current_price": 100}},
        {"HELD.KS": 0.0, "NEW.KS": 0.2},
        {
            "HELD.KS": {"signal_reason": "PORTFOLIO_RANK_EXIT", "fa_score": 60},
            "NEW.KS": {"signal_reason": "FA_TA_ENTRY", "fa_score": 80},
        },
        "UPTREND",
    )

    payload = json.loads((trader.log_dir / "decision_state.json").read_text(encoding="utf-8"))
    assert payload["target_count"] == 1
    assert payload["decisions"][0]["signal_reason"] == "PORTFOLIO_RANK_EXIT"
    assert payload["decisions"][1]["selected"] is True
    assert (trader.log_dir / "decision_history.jsonl").read_text(encoding="utf-8").count("\n") == 1


def test_snapshot_only_capture_is_scoped_and_places_no_order(tmp_path):
    class ReadOnlyBroker:
        masked_account = "1234****"

        def get_balance(self):
            return {
                "cash": 500.0,
                "positions": {
                    "005930.KS": {
                        "qty": 2, "avg_price": 90.0, "current_price": 100.0,
                    }
                },
            }

    trader = object.__new__(LiveTrader)
    trader.broker = ReadOnlyBroker()
    trader.execution_venue = "PAPER"
    trader.strategy_name = "aggressive"
    trader.log_dir = tmp_path

    result = trader.capture_account_snapshot()
    record = json.loads(
        (tmp_path / "account_snapshots.jsonl").read_text(encoding="utf-8").splitlines()[-1]
    )

    assert result["total_asset"] == 700.0
    assert result["position_count"] == 1
    assert record["account_scope"] == "1234****"
    assert record["mode"] == "PAPER"


def test_dashboard_counts_execution_outcomes_not_order_candidates(tmp_path):
    trader = object.__new__(LiveTrader)
    trader.execution_venue = "PAPER"
    trader.log_dir = tmp_path
    trader.last_order_suppressions = [{
        "ticker": "005930.KS",
        "side": "BUY",
        "reason": "AMBIGUOUS_RESULT_SAME_DAY",
    }]
    trader.update_intraday_dashboard([
        {"type": "BUY", "status": "SKIPPED"},
        {"type": "BUY", "status": "SKIPPED"},
        {"type": "BUY", "status": "FILLED"},
        {"type": "SELL", "status": "PARTIAL"},
    ])

    payload = json.loads((tmp_path / "dashboard_state.json").read_text(encoding="utf-8"))
    line = payload["timeline"][-1]
    assert "매수체결 1건" in line
    assert "매도체결 0건" in line
    assert "부분·대기 1건" in line
    assert "건너뜀 2건" in line
    assert "안전차단 매수 1건" in line
    assert "신규매수" not in line
    assert payload["order_suppressions"]["by_reason"] == {
        "AMBIGUOUS_RESULT_SAME_DAY": 1,
    }


def test_broker_trailing_stop_does_not_require_daily_bars():
    strategy = FaTaMomentumStrategy({
        "ma_window": 60,
        "ma_window_fast": 20,
        "stop_loss_pct": 0.10,
        "trailing_stop_pct": 0.08,
    })

    target, metadata = strategy.evaluate_latest(
        pd.DataFrame(),
        "UNAVAILABLE",
        current_position=0.12,
        average_price=100,
        current_price=105,
        peak_price=120,
    )

    assert target == 0.0
    assert metadata["signal_reason"] == "TRAILING_STOP"
    assert metadata["risk_price_source"] == "BROKER_BALANCE"


def test_risk_exit_generates_sell_when_daily_bars_are_stale():
    trader = object.__new__(LiveTrader)
    trader.strategy_name = "aggressive"
    trader.execution_venue = "DRY_RUN"
    trader.broker = type("Broker", (), {"masked_account": "***1234-01"})()
    trader.max_order_attempts = 2
    trader.price_guard_path = None
    trader.db = type("DB", (), {"fetch_all": lambda *a, **k: []})()
    strategy = FaTaMomentumStrategy({
        "stop_loss_pct": 0.10,
        "trailing_stop_pct": 0.08,
    })
    target, metadata = strategy.evaluate_position_risk(
        current_position=0.12,
        average_price=100,
        current_price=105,
        peak_price=120,
    )

    orders = trader._calculate_orders(
        1_000_000,
        {"005930.KS": {"qty": 10, "current_price": 105, "avg_price": 100}},
        {"005930.KS": target},
        {},
        {"005930.KS": metadata},
    )

    assert len(orders) == 1
    assert orders[0]["type"] == "SELL"
    assert orders[0]["reason"] == "TRAILING_STOP"
    assert orders[0]["expected_price"] == 105


def test_dry_run_dashboard_separates_candidates_from_actual_orders(tmp_path):
    trader = object.__new__(LiveTrader)
    trader.execution_venue = "DRY_RUN"
    trader.log_dir = tmp_path
    trader.last_order_candidates = [
        {"type": "SELL", "ticker": "005930.KS", "reason": "TRAILING_STOP"}
    ]
    trader.last_data_health = {
        "held_stale_tickers": ["005930.KS"],
        "risk_checks_total": 1,
        "risk_checks_completed": 1,
    }

    trader.update_intraday_dashboard(trader.last_order_candidates)

    payload = json.loads((tmp_path / "dashboard_state.json").read_text(encoding="utf-8"))
    assert payload["actual_orders"] == {
        "buy_filled": 0,
        "sell_filled": 0,
        "open": 0,
        "rejected": 0,
    }
    assert payload["order_candidates"]["sell"] == 1
    assert payload["order_candidates"]["risk_exit"] == 1
    assert payload["operational_status"] == "DEGRADED_DATA_STALE"


def test_freshness_report_identifies_stale_and_missing_tickers():
    fresh, health = LiveTrader._filter_stale_data(
        {
            "FRESH.KS": pd.DataFrame(
                {"close": [100]}, index=[pd.Timestamp("2026-07-16")]
            ),
            "STALE.KS": pd.DataFrame(
                {"close": [90]}, index=[pd.Timestamp("2026-07-15")]
            ),
        },
        pd.Timestamp("2026-07-16").date(),
        expected_tickers=["FRESH.KS", "STALE.KS", "MISSING.KS"],
        return_health=True,
    )

    assert list(fresh) == ["FRESH.KS"]
    assert health["stale_tickers"] == ["STALE.KS"]
    assert health["missing_tickers"] == ["MISSING.KS"]


def test_entry_circuit_breaker_blocks_buys_but_preserves_sells():
    targets = {
        "NEW.KS": 0.15,
        "ADD.KS": 0.20,
        "HOLD.KS": 0.08,
        "EXIT.KS": 0.0,
    }
    details = {ticker: {"signal_reason": "FA_TA_ENTRY"} for ticker in targets}
    positions = {
        "ADD.KS": {"qty": 10, "current_price": 10_000},
        "HOLD.KS": {"qty": 10, "current_price": 10_000},
        "EXIT.KS": {"qty": 10, "current_price": 10_000},
    }

    result = LiveTrader._apply_entry_circuit_breaker(
        targets,
        details,
        positions,
        total_eval=1_000_000,
        reason="DAILY_LOSS_LIMIT",
    )

    assert result["NEW.KS"] == 0.0
    assert result["ADD.KS"] == pytest.approx(0.10)
    assert result["HOLD.KS"] == 0.08
    assert result["EXIT.KS"] == 0.0
    assert details["NEW.KS"]["signal_reason"] == "DAILY_LOSS_LIMIT"
    assert details["ADD.KS"]["signal_reason"] == "DAILY_LOSS_LIMIT"


def test_dependency_error_blocks_existing_position_increase():
    targets = {"ADD.KS": 0.15, "EXIT.KS": 0.0}
    details = {ticker: {"signal_reason": "HOLD"} for ticker in targets}
    positions = {
        "ADD.KS": {"qty": 10, "current_price": 10_000},
        "EXIT.KS": {"qty": 10, "current_price": 10_000},
    }

    result = LiveTrader._apply_entry_circuit_breaker(
        targets,
        details,
        positions,
        total_eval=1_000_000,
        reason="DEPENDENCY_ERROR_ENTRY_BLOCK",
    )

    assert result["ADD.KS"] == pytest.approx(0.10)
    assert result["EXIT.KS"] == 0.0
    assert details["ADD.KS"]["signal_reason"] == "DEPENDENCY_ERROR_ENTRY_BLOCK"


def test_entry_circuit_breaker_has_visible_operational_status():
    status = LiveTrader._derive_operational_status(
        {
            "risk_checks_total": 2,
            "risk_checks_completed": 2,
            "entry_circuit_breaker": "MANUAL_KILL_SWITCH",
        },
        {"open": 0},
    )
    assert status == "ENTRY_CIRCUIT_BREAKER"


def test_order_suppression_has_visible_operational_status():
    status = LiveTrader._derive_operational_status(
        {
            "risk_checks_total": 1,
            "risk_checks_completed": 1,
            "order_suppressions": {
                "total": 1,
                "by_reason": {"AMBIGUOUS_RESULT_SAME_DAY": 1},
            },
        },
        {"open": 0},
    )

    assert status == "ORDER_SUPPRESSION"


def test_filled_order_deduplication_is_not_a_critical_suppression():
    status = LiveTrader._derive_operational_status(
        {
            "risk_checks_total": 1,
            "risk_checks_completed": 1,
            "order_suppressions": {
                "total": 1,
                "by_reason": {"FILLED_ORDER_TODAY": 1},
            },
        },
        {"open": 0},
    )

    assert status == "ORDER_DEDUPLICATION"
