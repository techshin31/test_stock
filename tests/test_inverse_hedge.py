import datetime as dt

import pandas as pd
import pytest

from core.constant.types import Tickers
from core.execution.inverse_hedge import InverseHedgeConfig, evaluate_inverse_hedge
from core.execution.trader import LiveTrader


def _regime_frame(regimes):
    index = pd.date_range("2026-07-20", periods=len(regimes), freq="B")
    return pd.DataFrame(
        {
            "REGIME": regimes,
            "ma20": [95.0] * len(regimes),
            "ma60": [100.0] * len(regimes),
            "ma120": [110.0] * len(regimes),
        },
        index=index,
    )


def _close(frame):
    return pd.Series([90.0] * len(frame), index=frame.index)


def test_kodex_inverse_uses_the_tradeable_1x_symbol():
    assert Tickers.INVERSE_ETF.ticker == "114800.KS"


@pytest.mark.parametrize(
    "field,value",
    [
        ("min_confidence", float("nan")),
        ("stop_loss_pct", float("nan")),
        ("stage_weights", (0.10, float("nan"), 0.30)),
    ],
)
def test_inverse_hedge_rejects_non_finite_risk_configuration(field, value):
    with pytest.raises(ValueError):
        InverseHedgeConfig(**{field: value})


@pytest.mark.parametrize(
    ("sessions", "expected_weight"),
    [(2, 0.10), (3, 0.20), (4, 0.30)],
)
def test_inverse_hedge_scales_only_after_confirmed_downtrends(sessions, expected_weight):
    frame = _regime_frame(["DOWNTREND"] * sessions)

    decision, _ = evaluate_inverse_hedge(
        signal_date=dt.date(2026, 7, 28),
        regime_frame=frame,
        close=_close(frame),
        market_regime="DOWNTREND",
        position=None,
        total_eval=1_000_000,
        state={},
        config=InverseHedgeConfig(),
    )

    assert decision["status"] == "ENTRY_READY"
    assert decision["target_weight"] == expected_weight
    assert decision["confidence"] == 1.0


def test_inverse_hedge_waits_for_confirmation_and_exits_on_transition():
    confirming = _regime_frame(["SIDEWAYS", "DOWNTREND"])
    waiting, _ = evaluate_inverse_hedge(
        signal_date=dt.date(2026, 7, 28),
        regime_frame=confirming,
        close=_close(confirming),
        market_regime="DOWNTREND",
        position=None,
        total_eval=1_000_000,
        state={},
        config=InverseHedgeConfig(),
    )
    assert waiting["status"] == "WAIT_CONFIRMATION"
    assert waiting["target_weight"] == 0.0

    transition = _regime_frame(["DOWNTREND", "TRANSITION"])
    exiting, _ = evaluate_inverse_hedge(
        signal_date=dt.date(2026, 7, 29),
        regime_frame=transition,
        close=_close(transition),
        market_regime="TRANSITION",
        position={"qty": 100, "avg_price": 100, "current_price": 100},
        total_eval=1_000_000,
        state={"active": True, "entry_date": "2026-07-28", "held_sessions": 1},
        config=InverseHedgeConfig(),
    )
    assert exiting["status"] == "EXIT_REGIME"
    assert exiting["reason"] == "DOWNTREND_EXIT"


def test_inverse_hedge_stop_and_holding_window_start_a_reentry_cooldown():
    frame = _regime_frame(["DOWNTREND"] * 4)
    stopped, stop_state = evaluate_inverse_hedge(
        signal_date=dt.date(2026, 7, 28),
        regime_frame=frame,
        close=_close(frame),
        market_regime="DOWNTREND",
        position={"qty": 100, "avg_price": 100, "current_price": 94},
        total_eval=1_000_000,
        state={"active": True, "entry_date": "2026-07-24", "held_sessions": 3},
        config=InverseHedgeConfig(),
    )
    assert stopped["reason"] == "INVERSE_HEDGE_STOP_LOSS"
    assert stopped["cooldown_sessions_remaining"] == 3

    cooled, _ = evaluate_inverse_hedge(
        signal_date=dt.date(2026, 7, 29),
        regime_frame=frame,
        close=_close(frame),
        market_regime="DOWNTREND",
        position=None,
        total_eval=1_000_000,
        state=stop_state,
        config=InverseHedgeConfig(),
    )
    assert cooled["status"] == "COOLDOWN"
    assert cooled["target_weight"] == 0.0

    maxed, _ = evaluate_inverse_hedge(
        signal_date=dt.date(2026, 7, 29),
        regime_frame=frame,
        close=_close(frame),
        market_regime="DOWNTREND",
        position={"qty": 100, "avg_price": 100, "current_price": 101},
        total_eval=1_000_000,
        state={
            "active": True,
            "entry_date": "2026-07-22",
            "held_sessions": 4,
            "last_held_signal_date": "2026-07-28",
        },
        config=InverseHedgeConfig(),
    )
    assert maxed["reason"] == "INVERSE_HEDGE_MAX_HOLD"
    assert maxed["target_weight"] == 0.0


def _order_test_trader():
    trader = object.__new__(LiveTrader)
    trader.strategy_name = "aggressive"
    trader.execution_venue = "PAPER"
    trader.broker = type("Broker", (), {"masked_account": "***1234-01"})()
    trader.max_order_attempts = 2
    trader.db = type("DB", (), {"fetch_all": lambda *args, **kwargs: []})()
    trader._price_guard_blocked = lambda *args: False
    trader.last_order_suppressions = []
    return trader


def test_hedge_order_waits_for_full_long_exit_and_bypasses_generic_position_cap():
    trader = _order_test_trader()
    inverse = Tickers.INVERSE_ETF.ticker
    targets = {"005930.KS": 0.0, inverse: 0.30}
    details = {
        "005930.KS": {"signal_reason": "DOWNTREND"},
        inverse: {"signal_reason": "INVERSE_HEDGE_ENTRY", "fa_score": None},
    }
    limited = trader._apply_portfolio_limits(targets, details, {})
    assert limited[inverse] == 0.30

    orders = trader._calculate_orders(
        1_000_000,
        {"005930.KS": {"qty": 1_000, "current_price": 100}},
        targets,
        {inverse: pd.DataFrame({"close": [100]})},
        details,
    )
    assert [order["type"] for order in orders] == ["SELL", "BUY"]
    assert orders[1]["ticker"] == inverse
    assert orders[1]["requires_prior_sell_fills"] == ["005930.KS"]
    assert not LiveTrader._hedge_exit_prerequisites_met(
        orders[1], [{**orders[0], "status": "PARTIAL"}]
    )[0]
    assert LiveTrader._hedge_exit_prerequisites_met(
        orders[1], [{**orders[0], "status": "FILLED"}]
    )[0]


def test_inverse_hedge_dashboard_payload_labels_the_kospi_proxy_gap():
    inverse = Tickers.INVERSE_ETF.ticker
    payload = LiveTrader._inverse_hedge_dashboard_payload(
        {"target_weight": 0.10},
        {
            "005930.KS": {"qty": 100, "current_price": 100},
            inverse: {"qty": 100, "avg_price": 100, "current_price": 101},
        },
        20_000,
        pd.Series([3_000.0, 2_970.0]),
        {inverse: pd.DataFrame({"close": [100.0, 101.0]})},
    )

    assert payload["actual_weight"] == pytest.approx(0.505)
    assert payload["net_market_exposure"] == pytest.approx(-0.005)
    assert payload["tracking_reference"] == "KOSPI_CLOSE_PROXY"
    assert payload["tracking_gap"] == pytest.approx(0.0)
