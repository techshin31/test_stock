import pandas as pd
import pytest

from apps.backtester.paper_execution_stress import _risk_control_gate
from apps.backtester.paper_strategy_experiments import (
    _apply_execution_model,
    _common_execution_event_key,
    write_outputs,
)


def test_execution_model_applies_side_specific_expected_fills():
    current = pd.Series({"BUY_NAME": 0.10, "SELL_NAME": 0.20})
    requested = pd.Series({"BUY_NAME": 0.20, "SELL_NAME": 0.00})

    final, delta, fractions = _apply_execution_model(
        current,
        requested,
        {"buy_fill_fraction": 0.5, "sell_fill_fraction": 0.75},
    )

    assert delta["BUY_NAME"] == pytest.approx(0.05)
    assert delta["SELL_NAME"] == pytest.approx(-0.15)
    assert final["BUY_NAME"] == pytest.approx(0.15)
    assert final["SELL_NAME"] == pytest.approx(0.05)
    assert fractions.to_dict() == {"BUY_NAME": 0.5, "SELL_NAME": 0.75}


def test_execution_model_rejects_invalid_fill_fraction():
    with pytest.raises(ValueError, match="between 0 and 1"):
        _apply_execution_model(
            pd.Series({"A": 0.0}),
            pd.Series({"A": 1.0}),
            {"buy_fill_fraction": 1.1, "sell_fill_fraction": 1.0},
        )


def test_deterministic_bernoulli_model_is_reproducible_and_discrete():
    current = pd.Series({"A": 0.0, "B": 0.2, "C": 0.0})
    requested = pd.Series({"A": 0.1, "B": 0.0, "C": 0.1})
    model = {
        "code": "STRESS",
        "application": "DETERMINISTIC_BERNOULLI",
        "buy_fill_fraction": 0.5,
        "sell_fill_fraction": 0.5,
    }

    first = _apply_execution_model(current, requested, model, event_key="2026-07-21")
    second = _apply_execution_model(current, requested, model, event_key="2026-07-21")

    assert first[2].equals(second[2])
    assert set(first[2].unique()) <= {0.0, 1.0}


def test_common_execution_event_key_is_variant_independent():
    assert _common_execution_event_key(pd.Timestamp("2026-07-21")) == "2026-07-21"


def test_strategy_output_defaults_to_compact_canonical_files(tmp_path):
    result = {"summary": {"A_CURRENT": {"total_return": -0.01}}}
    frames = {
        "daily_returns": pd.DataFrame({"A_CURRENT": [0.01]}),
        "events": pd.DataFrame({"event": ["BUY"]}),
        "period_summary": pd.DataFrame({"total_return": [-0.01]}),
        "comparison_vs_current": pd.DataFrame({"delta": [0.0]}),
    }

    write_outputs(result, frames, tmp_path)

    assert {path.name for path in tmp_path.iterdir()} == {
        "comparison_vs_current.csv",
        "metrics.json",
        "period_summary.csv",
        "summary.csv",
    }


def test_risk_control_gate_requires_every_execution_scenario():
    scenarios = {}
    for scenario in ("IDEAL", "POSTERIOR", "LOWER"):
        scenarios[scenario] = {
            "F_CAP15_HARD20_BAND20": {
                "total_return": -0.05,
                "max_drawdown": -0.15,
                "annualized_turnover": 20.0,
            },
            "C_CAP10": {
                "total_return": -0.05,
                "max_drawdown": -0.15,
                "annualized_turnover": 20.0,
            },
            "C_CAP08": {
                "total_return": -0.04,
                "max_drawdown": -0.14,
                "annualized_turnover": 15.0,
            },
        }
    scenarios["LOWER"]["F_CAP15_HARD20_BAND20"]["max_drawdown"] = -0.21
    scenarios["LOWER"]["C_CAP10"]["max_drawdown"] = -0.21

    gate = _risk_control_gate(scenarios)

    assert gate["fallback_available"] is True
    assert gate["robust_variants"] == ["C_CAP08"]
    assert gate["checks"][0]["all_scenarios_pass"] is False
