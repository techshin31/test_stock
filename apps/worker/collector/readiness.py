"""Collector completion gate for the monthly FA analyzer."""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import date, timedelta
from typing import Mapping

from apps.worker.fa_contract import (
    REQUIRED_MACRO_CODES,
    SOURCE_INPUT_COLUMNS,
    SUPPORTED_INDUSTRIES,
    missing_source_columns,
)
from storage.postgres.connection import PostgreDB
from storage.postgres.repositories.readiness_repo import (
    fetch_active_company_risk_snapshot,
    fetch_constituent_coverage,
    fetch_finance_industry_coverage,
    fetch_industry_price_coverage,
    fetch_macro_signal_coverage,
    fetch_schema_columns,
    fetch_source_duplicate_counts,
    fetch_wics_summary,
)

_SIGNAL_MAX_AGE_DAYS: dict[str, int] = {
    "CPI": 62,
    "GPR": 40,
    "ISM_PMI": 40,
    "GTREND_KPOP": 40,
    "GTREND_KDRAMA": 40,
    "SEMIPROD": 50,
    "KR_TOURIST": 50,
}


@dataclass(frozen=True)
class ReadinessSnapshot:
    cutoff_date: date
    source_columns: Mapping[str, tuple[str, ...]]
    macro_rows: tuple[dict, ...]
    finance_industry_rows: tuple[dict, ...]
    latest_wics_date: date | None
    earliest_wics_date: date | None
    wics_snapshot_count: int
    industry_price_rows: tuple[dict, ...]
    constituent_earliest_date: date | None
    constituent_required_count: int
    constituent_covered_count: int
    duplicate_counts: Mapping[str, int]
    company_risk_rows: tuple[dict, ...] = ()


@dataclass(frozen=True)
class ReadinessCheck:
    name: str
    passed: bool
    detail: str
    severity: str = "PASS"


@dataclass(frozen=True)
class ReadinessReport:
    status: str
    cutoff_date: date
    input_hash: str
    checks: tuple[ReadinessCheck, ...]

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "cutoff_date": self.cutoff_date.isoformat(),
            "input_hash": self.input_hash,
            "checks": [asdict(check) for check in self.checks],
        }


def _stable_hash(snapshot: ReadinessSnapshot) -> str:
    payload = json.dumps(asdict(snapshot), default=str, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def evaluate_readiness(snapshot: ReadinessSnapshot) -> ReadinessReport:
    checks: list[ReadinessCheck] = []

    missing = missing_source_columns(snapshot.source_columns)
    checks.append(ReadinessCheck(
        "source_columns",
        not missing,
        str(missing or "complete"),
        "PASS" if not missing else "FAIL",
    ))

    macro_by_code = {row["signal_name_code"]: row for row in snapshot.macro_rows}
    missing_macros = sorted(set(REQUIRED_MACRO_CODES) - set(macro_by_code))
    stale_macros: list[str] = []
    legacy_macros: list[str] = []
    for code, row in macro_by_code.items():
        latest = row.get("latest_available_date")
        max_age = _SIGNAL_MAX_AGE_DAYS.get(code, 10)
        if latest is None or (snapshot.cutoff_date - latest).days > max_age:
            stale_macros.append(code)
        if int(row.get("legacy_count") or 0) > 0:
            legacy_macros.append(code)
    macro_ok = not missing_macros and not stale_macros and not legacy_macros
    checks.append(ReadinessCheck(
        "macro_coverage",
        macro_ok,
        f"missing={missing_macros}, stale={sorted(stale_macros)}, legacy={sorted(legacy_macros)}",
        "PASS" if macro_ok else "WARNING",
    ))

    supported_finance_rows = [
        row for row in snapshot.finance_industry_rows
        if row["industry_code"] in SUPPORTED_INDUSTRIES
    ]
    total_large = sum(int(row.get("large_company_count") or 0) for row in supported_finance_rows)
    eligible_large = sum(int(row.get("eligible_company_count") or 0) for row in supported_finance_rows)
    coverage_rate = eligible_large / total_large if total_large else 0.0
    insufficient = sorted(
        row["industry_code"] for row in supported_finance_rows
        if int(row.get("large_company_count") or 0) >= 2
        and int(row.get("eligible_company_count") or 0) < 2
    )
    finance_ok = coverage_rate >= 0.90 and not insufficient
    checks.append(ReadinessCheck(
        "financial_quarter_coverage",
        finance_ok,
        f"large_8q_coverage={coverage_rate:.3f}, viable_industries_below_two={insufficient}",
        "PASS" if finance_ok else "WARNING",
    ))

    history_start = snapshot.cutoff_date - timedelta(days=365 * 3)
    wics_ok = (
        snapshot.latest_wics_date is not None
        and snapshot.latest_wics_date <= snapshot.cutoff_date
        and snapshot.earliest_wics_date is not None
        and snapshot.earliest_wics_date <= history_start
        and snapshot.wics_snapshot_count >= 100
    )
    checks.append(ReadinessCheck(
        "wics_snapshot_history",
        wics_ok,
        f"earliest={snapshot.earliest_wics_date}, latest={snapshot.latest_wics_date}, count={snapshot.wics_snapshot_count}",
        "PASS" if wics_ok else "WARNING",
    ))

    official_by_industry = {
        row["industry_code"]: row.get("earliest_date")
        for row in snapshot.industry_price_rows
        if row.get("source_code") == "WISEINDEX"
    }
    official_ok = all(
        official_by_industry.get(code) is not None
        and official_by_industry[code] <= history_start
        for code in SUPPORTED_INDUSTRIES
    )
    constituent_rate = (
        snapshot.constituent_covered_count / snapshot.constituent_required_count
        if snapshot.constituent_required_count else 0.0
    )
    derived_ok = (
        snapshot.constituent_earliest_date is not None
        and snapshot.constituent_earliest_date <= history_start
        and constituent_rate >= 0.95
    )
    checks.append(ReadinessCheck(
        "wics_price_history",
        official_ok or derived_ok,
        f"official={official_ok}, derived={derived_ok}, constituent_coverage={constituent_rate:.3f}",
        "PASS" if (official_ok or derived_ok) else "WARNING",
    ))

    duplicates = {name: count for name, count in snapshot.duplicate_counts.items() if count}
    checks.append(ReadinessCheck(
        "source_duplicates",
        not duplicates,
        str(duplicates or "none"),
        "PASS" if not duplicates else "FAIL",
    ))

    if any(check.severity == "FAIL" and not check.passed for check in checks):
        status = "FAIL"
    elif any(check.severity == "WARNING" and not check.passed for check in checks):
        status = "WARNING"
    else:
        status = "PASS"
    return ReadinessReport(status, snapshot.cutoff_date, _stable_hash(snapshot), tuple(checks))


def load_readiness_snapshot(db: PostgreDB, cutoff_date: date) -> ReadinessSnapshot:
    table_names = list(SOURCE_INPUT_COLUMNS)
    column_rows = fetch_schema_columns(db, table_names)
    columns: dict[str, list[str]] = {}
    for row in column_rows:
        columns.setdefault(row["table_name"], []).append(row["column_name"])

    macro_rows = fetch_macro_signal_coverage(db, cutoff_date)
    finance_rows = fetch_finance_industry_coverage(db, cutoff_date)
    wics_summary = fetch_wics_summary(db, cutoff_date)
    industry_price_rows = fetch_industry_price_coverage(db, cutoff_date)
    constituent_summary = fetch_constituent_coverage(db, cutoff_date)
    duplicate_counts = fetch_source_duplicate_counts(db)
    company_risk_rows = fetch_active_company_risk_snapshot(db, cutoff_date)

    return ReadinessSnapshot(
        cutoff_date=cutoff_date,
        source_columns={table: tuple(names) for table, names in columns.items()},
        macro_rows=tuple(macro_rows),
        finance_industry_rows=tuple(finance_rows),
        latest_wics_date=wics_summary.get("latest_date"),
        earliest_wics_date=wics_summary.get("earliest_date"),
        wics_snapshot_count=int(wics_summary.get("snapshot_count") or 0),
        industry_price_rows=tuple(industry_price_rows),
        constituent_earliest_date=constituent_summary.get("earliest_date"),
        constituent_required_count=int(constituent_summary.get("required_count") or 0),
        constituent_covered_count=int(constituent_summary.get("covered_count") or 0),
        duplicate_counts={key: int(value or 0) for key, value in duplicate_counts.items()},
        company_risk_rows=tuple(company_risk_rows),
    )


def run(db: PostgreDB, cutoff_date: date) -> ReadinessReport:
    return evaluate_readiness(load_readiness_snapshot(db, cutoff_date))
