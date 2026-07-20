import pandas as pd
import numpy as np
import json
import pytest
from core.strategy.fa_ta_momentum import FaTaMomentumStrategy
from core.execution.trader import LiveTrader
from apps.worker.fa_contract import DEFAULT_CONFIG as FA_CONTRACT

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
    assert "신규매수" not in line


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
