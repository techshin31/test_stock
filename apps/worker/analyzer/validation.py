"""Analyzer input and result validation boundaries."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date
import re

from apps.worker.collector.readiness import ReadinessReport, run as run_readiness
from storage.postgres.connection import PostgreDB
from apps.worker.analyzer.config import AnalyzerConfig
from apps.worker.analyzer.models import RunStatus
from apps.worker.fa_contract import REQUIRED_MACRO_CODES
from storage.postgres.repositories.company_risk_repo import (
    fetch_buy_blocked_stock_codes,
)
from storage.postgres.repositories.fa_analysis_repo import (
    fetch_analysis_run,
    fetch_macro_results_for_run,
    fetch_sector_summary_for_run,
    fetch_selected_companies_with_company_info,
)


class SourceReadinessError(RuntimeError):
    def __init__(self, report: ReadinessReport):
        self.report = report
        failed = [
            check.name for check in report.checks
            if check.severity == "FAIL" and not check.passed
        ]
        super().__init__(f"collector readiness failed: {', '.join(failed)}")


def validate_source_readiness(db: PostgreDB, cutoff_date: date) -> ReadinessReport:
    report = run_readiness(db, cutoff_date)
    if any(check.severity == "FAIL" and not check.passed for check in report.checks):
        raise SourceReadinessError(report)
    return report


@dataclass(frozen=True)
class ResultCheck:
    name: str
    passed: bool
    detail: str


@dataclass(frozen=True)
class RunValidationResult:
    status: str
    checks: tuple[ResultCheck, ...]

    @property
    def summary(self) -> dict:
        return {
            "status": self.status,
            "checks": [asdict(check) for check in self.checks],
        }


_CRITICAL_CHECKS = frozenset({
    "macro_point_in_time",
})

_WARNING_CHECKS = frozenset({
    "macro_results",
    "sector_selection",
    "company_selection",
    "company_contract",
    "company_risk",
})


def validate_run(
    db: PostgreDB,
    run_id: int,
    config: AnalyzerConfig,
) -> RunValidationResult:
    run = fetch_analysis_run(db, run_id)
    if run is None:
        raise ValueError(f"analysis run not found: {run_id}")
    checks: list[ResultCheck] = []

    macro_rows = fetch_macro_results_for_run(db, run_id)
    macro_codes = {row["signal_name_code"] for row in macro_rows}
    missing_macros = sorted(set(REQUIRED_MACRO_CODES) - macro_codes)
    checks.append(ResultCheck(
        "macro_results",
        bool(macro_rows) and not missing_macros,
        f"count={len(macro_rows)}, used={sorted(macro_codes)}, missing={missing_macros}",
    ))
    late_macros = sorted(
        row["signal_name_code"] for row in macro_rows
        if row["last_available_date"] > run["cutoff_date"]
    )
    checks.append(ResultCheck("macro_point_in_time", not late_macros, str(late_macros or "complete")))

    sector_counts = fetch_sector_summary_for_run(db, run_id)
    selected_sectors = int(sector_counts.get("selected") or 0)
    checks.append(ResultCheck(
        "sector_selection",
        selected_sectors >= 0,
        f"selected={selected_sectors}, count_limit=none",
    ))

    company_rows = fetch_selected_companies_with_company_info(db, run_id)
    industry_counts: dict[str, int] = {}
    for row in company_rows:
        industry_counts[row["industry_code"]] = industry_counts.get(row["industry_code"], 0) + 1
    company_shape_ok = len(company_rows) == len({row["stock_code"] for row in company_rows})
    checks.append(ResultCheck(
        "company_selection",
        company_shape_ok,
        f"count={len(company_rows)}, count_limit=none, by_industry={industry_counts}",
    ))

    invalid_companies = sorted(
        row["stock_code"] for row in company_rows
        if not row["is_eligible"]
        or row["company_size_code"] != config.scoring.allowed_company_size
        or row["company_status_code"] != "ACTIVE"
        or row["market_type_code"] not in config.scoring.enabled_market_types
        or not re.fullmatch(r"\d{6}", row["stock_code"])
        or row["latest_available_date"] is None
        or row["latest_available_date"] > run["cutoff_date"]
    )
    checks.append(ResultCheck(
        "company_contract", not invalid_companies,
        str(invalid_companies or "complete"),
    ))
    blocked = fetch_buy_blocked_stock_codes(
        db, run["effective_date"], [row["stock_code"] for row in company_rows]
    )
    checks.append(ResultCheck(
        "company_risk", not blocked, str(sorted(blocked) or "complete")
    ))

    critical_fail = any(
        not check.passed
        for check in checks
        if check.name in _CRITICAL_CHECKS
    )
    warning_fail = any(
        not check.passed
        for check in checks
        if check.name in _WARNING_CHECKS
    )
    unclassified_fail = any(
        not check.passed
        for check in checks
        if check.name not in _CRITICAL_CHECKS | _WARNING_CHECKS
    )
    if critical_fail or unclassified_fail:
        status = RunStatus.FAIL.value
    elif warning_fail:
        status = RunStatus.WARNING.value
    else:
        status = RunStatus.PASS.value
    return RunValidationResult(status=status, checks=tuple(checks))
