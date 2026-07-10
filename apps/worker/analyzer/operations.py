"""Operational audit for point-in-time safety and published-universe integrity."""
from __future__ import annotations

from dataclasses import asdict, dataclass

from storage.postgres.connection import PostgreDB
from storage.postgres.repositories.fa_analysis_repo import (
    fetch_audit_counts,
    fetch_published_run_selections,
    fetch_published_universe_mismatch,
)


@dataclass(frozen=True)
class OperationsReport:
    status: str
    macro_point_in_time_violations: int
    company_point_in_time_violations: int
    stale_running_count: int
    published_universe_mismatches: int
    published_run_count: int
    average_monthly_turnover: float | None

    def to_dict(self) -> dict:
        return asdict(self)


def _average_turnover(run_rows: list[dict]) -> float | None:
    selections: dict[int, set[str]] = {}
    order: list[int] = []
    for row in run_rows:
        run_id = int(row["run_id"])
        if run_id not in selections:
            selections[run_id] = set()
            order.append(run_id)
        selections[run_id].add(row["stock_code"])
    if len(order) < 2:
        return None
    values = []
    for previous_id, current_id in zip(order, order[1:]):
        previous = selections[previous_id]
        current = selections[current_id]
        denominator = max(len(previous), len(current), 1)
        values.append(1.0 - len(previous & current) / denominator)
    return sum(values) / len(values)


def audit_operational_state(db: PostgreDB) -> OperationsReport:
    counts = fetch_audit_counts(db)
    mismatch = fetch_published_universe_mismatch(db)
    published_rows = fetch_published_run_selections(db)
    macro_late = int(counts.get("macro_late") or 0)
    company_late = int(counts.get("company_late") or 0)
    stale = int(counts.get("stale_running") or 0)
    mismatches = int(mismatch.get("mismatch_count") or 0)
    status = "PASS" if not any((macro_late, company_late, stale, mismatches)) else "FAIL"
    return OperationsReport(
        status=status,
        macro_point_in_time_violations=macro_late,
        company_point_in_time_violations=company_late,
        stale_running_count=stale,
        published_universe_mismatches=mismatches,
        published_run_count=int(mismatch.get("published_count") or 0),
        average_monthly_turnover=_average_turnover(published_rows),
    )
