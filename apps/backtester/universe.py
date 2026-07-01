from __future__ import annotations

from datetime import date

import numpy as np

from core.portfolio.rotation import RotationPlan
from data.loaders.kospi_data import KOSPI_LARGE_CAP_POOL
from storage.postgres.connection import PostgreDB
from storage.postgres.repositories.fa_analysis_repo import fetch_published_fa_selections

MAX_FA_UNIVERSE_SIZE = 10


def default_rotation_dates(
    start_date: date,
    end_date: date,
    interval_years: int = 2,
) -> list[date]:
    """투자 기간 내 매 interval_years년 1월 초를 종목 교체 시점으로 사용한다."""
    dates: list[date] = []
    year = start_date.year + interval_years
    while year <= end_date.year:
        dates.append(date(year, 1, 2))
        year += interval_years
    return dates


def build_random_universe(
    rotation_dates: list[date],
    universe_size: int,
    rotation_size: int,
    seed: int,
) -> tuple[list[str], list[RotationPlan], set[str]]:
    """랜덤 초기 유니버스와 종목 교체 계획을 생성한다.

    FA(펀더멘털) 분석 기반 종목 선정을 생략한 데모/테스트용 모드다.
    실제 운용 시에는 펀더멘털 스크리닝 결과로 initial_universe와
    rotation_plans를 대체해야 한다.

    Returns
    -------
    initial_universe : list[str]
        백테스트 시작 시점의 유니버스.
    rotation_plans : list[RotationPlan]
        rotation_dates마다 적용되는 편출/편입 계획.
    all_tickers : set[str]
        백테스트 전체 기간에 등장하는 모든 종목 (OHLCV 다운로드 대상).
    """
    rng = np.random.default_rng(seed)
    tickers = list(KOSPI_LARGE_CAP_POOL.keys())

    initial_universe = list(rng.choice(tickers, size=universe_size, replace=False))
    current_universe = set(initial_universe)
    all_tickers = set(initial_universe)

    rotation_plans: list[RotationPlan] = []
    for review_date in rotation_dates:
        pool = list(current_universe)
        n_exit = min(rotation_size, len(pool))
        exits = list(rng.choice(pool, size=n_exit, replace=False)) if n_exit else []

        remaining = [t for t in tickers if t not in current_universe]
        n_enter = min(rotation_size, len(remaining))
        entries = list(rng.choice(remaining, size=n_enter, replace=False)) if n_enter else []

        rotation_plans.append(RotationPlan(
            review_date=review_date,
            exits=exits,
            entries=entries,
            force_exit_days=20,
            reason=f"랜덤 교체 ({review_date})",
        ))

        current_universe -= set(exits)
        current_universe |= set(entries)
        all_tickers |= set(entries)

    return initial_universe, rotation_plans, all_tickers


def drop_failed_tickers(
    initial_universe: list[str],
    rotation_plans: list[RotationPlan],
    available_tickers: set[str],
) -> tuple[list[str], list[RotationPlan]]:
    """OHLCV 다운로드에 실패한 종목을 유니버스/교체 계획에서 제외한다."""
    clean_universe = [t for t in initial_universe if t in available_tickers]

    clean_plans: list[RotationPlan] = []
    for plan in rotation_plans:
        clean_exits = [t for t in plan.exits if t in available_tickers]
        clean_entries = [t for t in plan.entries if t in available_tickers]
        if clean_exits or clean_entries:
            clean_plans.append(RotationPlan(
                review_date=plan.review_date,
                exits=clean_exits,
                entries=clean_entries,
                force_exit_days=plan.force_exit_days,
                reason=plan.reason,
            ))

    return clean_universe, clean_plans


def build_fa_published_universe(
    db: PostgreDB,
    strategy_name: str,
    start_date: date,
    end_date: date,
) -> tuple[list[str], list[RotationPlan], set[str]]:
    """Build point-in-time rotation plans from PUBLISHED FA selections."""
    rows = fetch_published_fa_selections(db, strategy_name, end_date)
    late = [
        row for row in rows
        if row["latest_available_date"] is None
        or row["latest_available_date"] > row["cutoff_date"]
    ]
    if late:
        raise ValueError("PUBLISHED FA history contains point-in-time violations")

    selections: dict[date, set[str]] = {}
    for row in rows:
        selections.setdefault(row["effective_date"], set()).add(row["stock_code"])
    eligible_initial_dates = [item for item in selections if item <= start_date]
    if not eligible_initial_dates:
        raise ValueError("no PUBLISHED FA universe exists on or before backtest start")
    initial_date = max(eligible_initial_dates)
    initial_universe = sorted(selections[initial_date])
    if len(initial_universe) > MAX_FA_UNIVERSE_SIZE:
        raise ValueError(
            f"PUBLISHED FA initial universe exceeds {MAX_FA_UNIVERSE_SIZE} companies"
        )

    current = set(initial_universe)
    all_tickers = set(current)
    plans: list[RotationPlan] = []
    for effective_date in sorted(item for item in selections if start_date < item <= end_date):
        selected = selections[effective_date]
        if len(selected) > MAX_FA_UNIVERSE_SIZE:
            raise ValueError(
                f"PUBLISHED FA universe exceeds {MAX_FA_UNIVERSE_SIZE} companies: {effective_date}"
            )
        exits = sorted(current - selected)
        entries = sorted(selected - current)
        if exits or entries:
            plans.append(RotationPlan(
                review_date=effective_date,
                exits=exits,
                entries=entries,
                force_exit_days=20,
                reason=f"PUBLISHED FA rotation ({effective_date})",
            ))
        current = set(selected)
        all_tickers |= selected
    return initial_universe, plans, all_tickers
