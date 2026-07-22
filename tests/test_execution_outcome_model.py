import pandas as pd
import pytest

from core.analytics.execution_outcome_model import calibrate_execution_outcomes


def test_execution_calibration_separates_legacy_and_stabilized_periods():
    orders = pd.DataFrame(
        [
            {"date": "2026-07-09", "side": "BUY", "status": "REJECTED", "ordered_qty": 10, "filled_qty": 0},
            {"date": "2026-07-09", "side": "SELL", "status": "FILLED", "ordered_qty": 5, "filled_qty": 5},
            {"date": "2026-07-21", "side": "BUY", "status": "FILLED", "ordered_qty": 4, "filled_qty": 4},
            {"date": "2026-07-21", "side": "BUY", "status": "REJECTED", "ordered_qty": 4, "filled_qty": 0},
            {"date": "2026-07-21", "side": "SELL", "status": "FILLED", "ordered_qty": 3, "filled_qty": 3},
        ]
    )

    result = calibrate_execution_outcomes(orders)

    assert result["full_history"]["BUY"]["order_fill_rate"] == pytest.approx(1 / 3)
    assert result["stabilized"]["BUY"]["order_fill_rate"] == 0.5
    assert result["stabilized"]["SELL"]["order_fill_rate"] == 1.0
    assert result["calibration_status"] == "PROVISIONAL_SMALL_SAMPLE"
    assert result["production_parameter_permission"] == "DENIED_BY_DESIGN"


def test_execution_scenarios_are_bounded_probabilities():
    orders = pd.DataFrame(
        [
            {"date": "2026-07-21", "side": side, "status": status, "ordered_qty": 1, "filled_qty": int(status == "FILLED")}
            for side in ("BUY", "SELL")
            for status in ("FILLED", "REJECTED")
        ]
    )

    result = calibrate_execution_outcomes(orders)

    for scenario in result["scenarios"].values():
        assert 0.0 <= scenario["buy_fill_fraction"] <= 1.0
        assert 0.0 <= scenario["sell_fill_fraction"] <= 1.0
