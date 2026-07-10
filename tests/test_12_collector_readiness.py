from datetime import date, timedelta

from apps.worker.collector.readiness import ReadinessSnapshot, evaluate_readiness
from apps.worker.fa_contract import (
    REQUIRED_MACRO_CODES,
    SOURCE_INPUT_COLUMNS,
    SUPPORTED_INDUSTRIES,
)


def _passing_snapshot() -> ReadinessSnapshot:
    cutoff = date(2026, 5, 31)
    return ReadinessSnapshot(
        cutoff_date=cutoff,
        source_columns={
            table: tuple(columns) for table, columns in SOURCE_INPUT_COLUMNS.items()
        },
        macro_rows=tuple(
            {
                "signal_name_code": code,
                "latest_available_date": cutoff - timedelta(days=30 if code == "CPI" else 3),
                "legacy_count": 0,
            }
            for code in REQUIRED_MACRO_CODES
        ),
        finance_industry_rows=tuple(
            {
                "industry_code": code,
                "large_company_count": 2,
                "eligible_company_count": 2,
            }
            for code in SUPPORTED_INDUSTRIES
        ),
        latest_wics_date=date(2026, 5, 29),
        earliest_wics_date=date(2023, 5, 1),
        wics_snapshot_count=150,
        industry_price_rows=(),
        constituent_earliest_date=date(2023, 5, 1),
        constituent_required_count=100,
        constituent_covered_count=98,
        duplicate_counts={
            "macro_signals": 0,
            "wics_companies": 0,
            "financial_statements": 0,
        },
    )


def test_readiness_passes_complete_point_in_time_sources():
    report = evaluate_readiness(_passing_snapshot())
    assert report.status == "PASS"
    assert all(check.passed for check in report.checks)
    assert len(report.input_hash) == 64


def test_readiness_fails_missing_columns_without_analyzer_fallback():
    snapshot = _passing_snapshot()
    columns = dict(snapshot.source_columns)
    columns["macro_signals"] = tuple(
        column for column in columns["macro_signals"] if column != "available_date"
    )
    broken = ReadinessSnapshot(**{**snapshot.__dict__, "source_columns": columns})
    report = evaluate_readiness(broken)
    assert report.status == "FAIL"
    check = next(item for item in report.checks if item.name == "source_columns")
    assert "available_date" in check.detail


def test_readiness_fails_stale_macro_and_insufficient_financial_history():
    snapshot = _passing_snapshot()
    macro_rows = list(snapshot.macro_rows)
    macro_rows[0] = {**macro_rows[0], "latest_available_date": date(2026, 5, 1)}
    finance_rows = list(snapshot.finance_industry_rows)
    finance_rows[0] = {**finance_rows[0], "eligible_company_count": 1}
    broken = ReadinessSnapshot(**{
        **snapshot.__dict__,
        "macro_rows": tuple(macro_rows),
        "finance_industry_rows": tuple(finance_rows),
    })
    report = evaluate_readiness(broken)
    assert report.status == "WARNING"
    failed = {check.name for check in report.checks if not check.passed}
    assert failed == {"macro_coverage", "financial_quarter_coverage"}
    assert {
        check.severity for check in report.checks if not check.passed
    } == {"WARNING"}


def test_readiness_ignores_optional_macro_freshness():
    snapshot = _passing_snapshot()
    macro_rows = [
        (
            {**row, "latest_available_date": date(2026, 4, 12)}
            if row["signal_name_code"] == "KR_TOURIST" else row
        )
        for row in snapshot.macro_rows
    ]
    report = evaluate_readiness(ReadinessSnapshot(**{
        **snapshot.__dict__,
        "macro_rows": tuple(macro_rows),
    }))
    check = next(item for item in report.checks if item.name == "macro_coverage")
    assert "KR_TOURIST" not in check.detail
    assert check.passed

    stale_rows = [
        (
            {**row, "latest_available_date": date(2026, 4, 10)}
            if row["signal_name_code"] == "KR_TOURIST" else row
        )
        for row in snapshot.macro_rows
    ]
    report = evaluate_readiness(ReadinessSnapshot(**{
        **snapshot.__dict__,
        "macro_rows": tuple(stale_rows),
    }))
    check = next(item for item in report.checks if item.name == "macro_coverage")
    assert check.passed
    assert report.status == "PASS"
    assert "KR_TOURIST" not in check.detail


def test_readiness_hash_is_stable_for_identical_inputs():
    snapshot = _passing_snapshot()
    assert evaluate_readiness(snapshot).input_hash == evaluate_readiness(snapshot).input_hash


def test_readiness_hash_changes_with_company_risk_state():
    snapshot = _passing_snapshot()
    changed = ReadinessSnapshot(**{
        **snapshot.__dict__,
        "company_risk_rows": ({
            "stock_code": "005930", "risk_action_code": "BLOCK_BUY",
            "reason_code": "CONVERTIBLE_BOND",
        },),
    })
    assert evaluate_readiness(snapshot).input_hash != evaluate_readiness(changed).input_hash
