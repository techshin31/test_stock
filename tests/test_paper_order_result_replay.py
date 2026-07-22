import pytest

from apps.backtester.paper_order_result_replay import (
    build_parity_report,
    replay_order_events,
)


def _order(order_id, side, qty, price, *, status="FILLED", cost=0.0):
    return {
        "order_id": order_id,
        "created_at": f"2026-07-21T09:0{order_id}:00+09:00",
        "symbol": "005930",
        "stock_name": "삼성전자",
        "side": side,
        "status": status,
        "ordered_qty": qty,
        "filled_qty": qty if status == "FILLED" else 0,
        "avg_fill_price": price,
        "fill_amount": qty * price if status == "FILLED" else 0,
        "recorded_commission": cost,
        "recorded_tax": 0,
        "modeled_commission": 0,
        "modeled_tax": 0,
    }


def test_order_result_replay_applies_fills_and_ignores_rejections():
    orders = [
        _order("1", "BUY", 10, 100, cost=1),
        _order("2", "SELL", 4, 120, cost=1),
        _order("3", "BUY", 20, 90, status="REJECTED"),
    ]

    result = replay_order_events(orders, opening_cash=10_000)

    assert result["ending_cash"] == pytest.approx(9_478)
    assert result["ending_positions"] == {"005930": 6.0}
    assert result["event_count"] == 2
    assert result["issues"] == []


def test_parity_report_separates_missing_opening_state_from_trades():
    orders = [_order("1", "BUY", 10, 100)]

    report = build_parity_report(
        orders,
        endpoint_cash=8_500,
        endpoint_positions={"005930": 12},
        starting_capital=10_000,
    )

    assert report["raw_replay"]["ending_cash"] == pytest.approx(9_000)
    assert report["calibration"]["opening_cash_required"] == pytest.approx(9_500)
    assert report["calibration"]["opening_position_balancing_entries"] == {
        "005930": 2.0
    }
    assert report["calibrated_replay"]["exact_endpoint_parity"] is True
    assert report["promotion_gate"]["ready"] is False
    assert (
        "opening state exceeds the 0.10% starting-capital reconciliation tolerance"
        in report["promotion_gate"]["blockers"]
    )


def test_unpriced_fill_is_explicit_and_blocks_promotion():
    order = _order("1", "BUY", 10, 100)
    order["avg_fill_price"] = 0
    order["fill_amount"] = 0

    report = build_parity_report(
        [order], endpoint_cash=10_000, endpoint_positions={}, starting_capital=10_000
    )

    assert report["data_quality"]["priced_fill_event_coverage"] == 0.0
    assert report["data_quality"]["issues"][0]["code"] == "MISSING_FILL_PRICE"
    assert report["promotion_gate"]["ready"] is False


def test_small_cash_residual_is_accepted_with_explicit_tolerance():
    report = build_parity_report(
        [_order("1", "BUY", 10, 100)],
        endpoint_cash=9_005,
        endpoint_positions={"005930": 10},
        starting_capital=10_000,
    )

    assert report["promotion_gate"]["calibration_free_from_500m"] is False
    assert report["promotion_gate"]["reconciled_from_500m_within_tolerance"] is True
    assert report["promotion_gate"]["opening_cash_difference_abs"] == 5
    assert report["promotion_gate"]["opening_cash_tolerance"] == 10
    assert report["promotion_gate"]["ready"] is True
