"""Named, venue-scoped strategy policies for the execution runtime.

The recovery policy is deliberately PAPER-only.  REAL, DRY_RUN, and SIMULATE
retain the legacy guardrails unless a future reviewed change explicitly creates
another venue policy.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Mapping


PAPER_RECOVERY_POLICY = "paper_recovery_cap15_hard20_band20_v1"
PAPER_LEGACY_POLICY = "paper_legacy_cap15_hard10_trail08_band10_v1"
PAPER_RECOVERY_EXPERIMENT = "F_CAP15_HARD20_BAND20"


@dataclass(frozen=True)
class StrategyPolicy:
    code: str
    status: str
    selected_experiment: str
    max_position_weight: float
    rebalance_band: float
    stop_loss_pct: float
    trailing_stop_enabled: bool
    trailing_stop_pct: float
    paper_only: bool

    def __post_init__(self) -> None:
        if not 0 < self.max_position_weight <= 0.30:
            raise ValueError("max_position_weight must be in (0, 0.30]")
        if not 0 <= self.rebalance_band <= 0.50:
            raise ValueError("rebalance_band must be in [0, 0.50]")
        if not 0 < self.stop_loss_pct < 1:
            raise ValueError("stop_loss_pct must be in (0, 1)")
        if not 0 < self.trailing_stop_pct < 1:
            raise ValueError("trailing_stop_pct must be in (0, 1)")

    def as_dict(self) -> dict:
        return asdict(self)


_PAPER_POLICIES = {
    PAPER_RECOVERY_POLICY: StrategyPolicy(
        code=PAPER_RECOVERY_POLICY,
        status="PAPER_RECOVERY_PROVISIONAL",
        selected_experiment=PAPER_RECOVERY_EXPERIMENT,
        max_position_weight=0.15,
        rebalance_band=0.20,
        stop_loss_pct=0.20,
        trailing_stop_enabled=False,
        trailing_stop_pct=0.08,
        paper_only=True,
    ),
    PAPER_LEGACY_POLICY: StrategyPolicy(
        code=PAPER_LEGACY_POLICY,
        status="FAILED_ROLLBACK_ONLY",
        selected_experiment="A_CURRENT",
        max_position_weight=0.15,
        rebalance_band=0.10,
        stop_loss_pct=0.10,
        trailing_stop_enabled=True,
        trailing_stop_pct=0.08,
        paper_only=True,
    ),
}

def resolve_strategy_policy(
    execution_venue: str,
    environment: Mapping[str, str],
) -> StrategyPolicy:
    """Resolve an audited strategy policy without cross-venue leakage."""
    venue = str(execution_venue or "").upper()
    if venue != "PAPER":
        return StrategyPolicy(
            code="non_paper_legacy_guardrails_v1",
            status="UNCHANGED",
            selected_experiment="NOT_APPLICABLE",
            max_position_weight=float(environment.get("MAX_POSITION_WEIGHT", "0.15")),
            rebalance_band=0.10,
            stop_loss_pct=float(environment.get("STOP_LOSS_PCT", "0.10")),
            trailing_stop_enabled=True,
            trailing_stop_pct=float(environment.get("TRAILING_STOP_PCT", "0.08")),
            paper_only=False,
        )

    code = str(
        environment.get("PAPER_STRATEGY_POLICY", PAPER_RECOVERY_POLICY)
    ).strip()
    try:
        return _PAPER_POLICIES[code]
    except KeyError as exc:
        supported = ", ".join(sorted(_PAPER_POLICIES))
        raise ValueError(
            f"unsupported PAPER_STRATEGY_POLICY={code!r}; supported: {supported}"
        ) from exc
