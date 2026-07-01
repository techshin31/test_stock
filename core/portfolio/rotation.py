"""분기 종목 교체 계획 적용.

rotation.py는 분기 검토 결과를 PortfolioUniverse에 반영한다.
편출 종목은 SELL_ONLY로 전환하고, 기한 내 청산되지 않으면 강제청산 대상으로 표시한다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

import pandas as pd

from core.constant.types import UniverseStatus
from .universe import PortfolioUniverse


@dataclass
class RotationPlan:
    """분기 종목 교체 계획."""

    review_date: date
    exits: list[str] = field(default_factory=list)
    entries: list[str] = field(default_factory=list)
    force_exit_days: int = 20
    reason: str | None = None


def _to_date(value: date | pd.Timestamp) -> date:
    if isinstance(value, pd.Timestamp):
        return value.date()
    return value


def calc_force_exit_date(
    review_date: date | pd.Timestamp,
    force_exit_days: int = 20,
    trading_calendar: pd.DatetimeIndex | None = None,
) -> date:
    """검토일 기준 force_exit_days 거래일 뒤의 강제청산일을 계산한다."""
    review_ts = pd.Timestamp(review_date)

    if trading_calendar is None:
        return (review_ts + pd.offsets.BDay(force_exit_days)).date()

    calendar = pd.DatetimeIndex(trading_calendar).sort_values()
    valid_dates = calendar[calendar >= review_ts]
    if len(valid_dates) == 0:
        return review_ts.date()

    deadline_idx = min(force_exit_days, len(valid_dates) - 1)
    return valid_dates[deadline_idx].date()


def apply_rotation_plan(
    universe: PortfolioUniverse,
    plan: RotationPlan,
    trading_calendar: pd.DatetimeIndex | None = None,
) -> PortfolioUniverse:
    """분기 교체 계획을 유니버스 상태에 반영한다."""
    deadline = calc_force_exit_date(
        plan.review_date,
        force_exit_days = plan.force_exit_days,
        trading_calendar = trading_calendar,
    )

    for ticker in plan.exits:
        universe.set_sell_only(
            ticker,
            sell_only_since = plan.review_date,
            force_exit_date = deadline,
            reason = plan.reason,
        )

    for ticker in plan.entries:
        universe.set_active(
            ticker,
            added_at = plan.review_date,
            reason = plan.reason,
        )

    return universe


def force_exit_targets(
    universe: PortfolioUniverse,
    current_weights: pd.Series,
    as_of: date | pd.Timestamp,
    min_weight: float = 1e-9,
) -> pd.Series:
    """강제청산 기한이 지난 SELL_ONLY 종목의 목표 비중 0.0을 반환한다."""
    as_of_date = _to_date(as_of)
    targets: dict[str, float] = {}

    for entry in universe:
        if entry.status != UniverseStatus.SELL_ONLY:
            continue
        if entry.force_exit_date is None or entry.force_exit_date > as_of_date:
            continue
        if float(current_weights.get(entry.ticker, 0.0)) > min_weight:
            targets[entry.ticker] = 0.0

    return pd.Series(targets, dtype=float)


def mark_removed_after_exit(
    universe: PortfolioUniverse,
    current_weights: pd.Series,
    as_of: date | pd.Timestamp,
    min_weight: float = 1e-9,
) -> PortfolioUniverse:
    """SELL_ONLY 종목 중 보유 비중이 사라진 종목을 REMOVED로 전환한다."""
    as_of_date = _to_date(as_of)

    for entry in list(universe):
        if entry.status != UniverseStatus.SELL_ONLY:
            continue
        if float(current_weights.get(entry.ticker, 0.0)) <= min_weight:
            universe.remove(entry.ticker, removed_at=as_of_date, reason=entry.reason)

    return universe
