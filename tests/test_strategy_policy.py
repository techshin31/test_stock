import pytest

from apps.backtester.paper_strategy_experiments import VARIANTS
from core.execution.strategy_policy import (
    PAPER_LEGACY_POLICY,
    PAPER_RECOVERY_EXPERIMENT,
    PAPER_RECOVERY_POLICY,
    resolve_strategy_policy,
)


def test_paper_defaults_to_named_recovery_policy():
    policy = resolve_strategy_policy("PAPER", {})

    assert policy.code == PAPER_RECOVERY_POLICY
    assert policy.status == "PAPER_RECOVERY_PROVISIONAL"
    assert policy.paper_only is True
    assert policy.max_position_weight == 0.15
    assert policy.rebalance_band == 0.20
    assert policy.stop_loss_pct == 0.20
    assert policy.trailing_stop_enabled is False


def test_paper_legacy_policy_is_explicit_rollback_only():
    policy = resolve_strategy_policy(
        "PAPER", {"PAPER_STRATEGY_POLICY": PAPER_LEGACY_POLICY}
    )

    assert policy.status == "FAILED_ROLLBACK_ONLY"
    assert policy.rebalance_band == 0.10
    assert policy.stop_loss_pct == 0.10
    assert policy.trailing_stop_enabled is True


def test_unknown_paper_policy_fails_closed():
    with pytest.raises(ValueError, match="unsupported PAPER_STRATEGY_POLICY"):
        resolve_strategy_policy("PAPER", {"PAPER_STRATEGY_POLICY": "unknown"})


def test_non_paper_legacy_environment_overrides_are_preserved():
    policy = resolve_strategy_policy(
        "REAL",
        {
            "MAX_POSITION_WEIGHT": "0.12",
            "STOP_LOSS_PCT": "0.09",
            "TRAILING_STOP_PCT": "0.07",
        },
    )

    assert policy.code == "non_paper_legacy_guardrails_v1"
    assert policy.max_position_weight == 0.12
    assert policy.stop_loss_pct == 0.09
    assert policy.trailing_stop_pct == 0.07
    assert policy.trailing_stop_enabled is True
    assert policy.paper_only is False


def test_runtime_policy_and_backtest_candidate_do_not_drift():
    policy = resolve_strategy_policy("PAPER", {})
    variant = next(item for item in VARIANTS if item.code == PAPER_RECOVERY_EXPERIMENT)

    assert variant.max_weight == policy.max_position_weight
    assert variant.rebalance_band == policy.rebalance_band
    assert variant.stop_loss == policy.stop_loss_pct
    assert variant.trailing_stop is None
