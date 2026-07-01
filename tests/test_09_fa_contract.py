from datetime import date

import pytest

from apps.worker.fa_contract import (
    ALL_WICS_INDUSTRIES,
    ANALYZE_TARGET_STEPS,
    DEFAULT_CONFIG,
    MACRO_SIGNALS,
    SOURCE_INPUT_COLUMNS,
    SUPPORTED_INDUSTRIES,
    UNSUPPORTED_INDUSTRIES,
    UnsupportedIndustryError,
    missing_source_columns,
    monthly_run_dates,
    score_model_for,
)


def test_v1_config_has_required_output_counts_and_weights():
    DEFAULT_CONFIG.validate()
    assert DEFAULT_CONFIG.candidate_up_count + DEFAULT_CONFIG.candidate_down_count == 8
    assert DEFAULT_CONFIG.final_industry_count * DEFAULT_CONFIG.companies_per_industry == 10
    assert sum(DEFAULT_CONFIG.sector_score_weights) == pytest.approx(1.0)
    assert DEFAULT_CONFIG.cohort_quality_threshold == 60.0
    assert DEFAULT_CONFIG.maximum_cohort_quality_penalty == 12.0


def test_macro_contract_covers_extended_signals_and_special_transforms():
    by_code = {signal.code: signal for signal in MACRO_SIGNALS}
    assert len(by_code) == 17
    assert by_code["TNX"].transform == "YIELD_CHANGE"
    assert by_code["CPI"].transform == "CPI_YOY_PRESSURE"
    assert by_code["CPI"].available_date_rule == "SOURCE_RELEASE_DATE"
    assert by_code["VIX"].source_value_key == "^VIX"
    assert by_code["USDKRW"].category == "FX"
    assert by_code["US2Y"].transform == "YIELD_CHANGE"
    assert by_code["GPR"].available_date_rule == "SOURCE_RELEASE_DATE"
    assert by_code["SEMIPROD"].transform == "YOY_CHANGE"
    assert by_code["GTREND_KPOP"].category == "HALLYU"
    assert by_code["GTREND_KPOP"].eligible_industry_codes == ("G2550", "G5010", "G2560")
    assert by_code["GTREND_KPOP"].minimum_abs_correlation_override == 0.25
    assert by_code["GTREND_KDRAMA"].minimum_abs_correlation_override == 0.25
    assert by_code["KR_TOURIST"].eligible_industry_codes == ("G2550", "G2530", "G5010", "G5020")
    assert by_code["KR_TOURIST"].minimum_abs_correlation_override == 0.20
    assert by_code["KR_TOURIST"].available_date_rule == "SOURCE_RELEASE_DATE"


def test_all_25_wics_industries_are_explicitly_supported_or_rejected():
    assert len(ALL_WICS_INDUSTRIES) == 25
    assert set(SUPPORTED_INDUSTRIES) | set(UNSUPPORTED_INDUSTRIES) == set(ALL_WICS_INDUSTRIES)
    assert not (set(SUPPORTED_INDUSTRIES) & set(UNSUPPORTED_INDUSTRIES))
    assert score_model_for("G4530") == "GENERAL_V1"
    assert score_model_for("G4010") == "FINANCIAL_V1"
    with pytest.raises(UnsupportedIndustryError, match="UNKNOWN_WICS_INDUSTRY"):
        score_model_for("G9999")


def test_monthly_dates_use_previous_month_end_and_first_session():
    sessions = {"2026-06-01"}
    result = monthly_run_dates(date(2026, 6, 22), sessions.__contains__)
    assert result.analysis_month == date(2026, 6, 1)
    assert result.cutoff_date == date(2026, 5, 31)
    assert result.effective_date == date(2026, 6, 1)


def test_monthly_dates_skip_non_trading_days():
    sessions = {"2026-08-03"}
    result = monthly_run_dates(date(2026, 8, 1), sessions.__contains__)
    assert result.effective_date == date(2026, 8, 3)


def test_source_contract_reports_missing_columns_by_table():
    actual = {table: columns for table, columns in SOURCE_INPUT_COLUMNS.items()}
    actual["macro_signals"] = actual["macro_signals"] - {"available_date"}
    assert missing_source_columns(actual) == {"macro_signals": ("available_date",)}


def test_analyze_targets_include_all_required_predecessors():
    assert ANALYZE_TARGET_STEPS["sector"][-2:] == ("macro", "sector")
    assert ANALYZE_TARGET_STEPS["all"][-2:] == ("validation", "publish_optional")
