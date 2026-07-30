from datetime import date

import pandas as pd

from apps.worker.analyzer.company_job import (
    _add_derived_metrics,
    build_quarter_fundamentals,
    score_quarter_fundamentals,
)
from apps.worker.analyzer.config import load_config
from apps.worker.fa_contract import MODEL_VERSION


def _flow_row(receipt, report_code, account_id, amount, cumulative, year=2025):
    quarter_end = {
        "11013": date(year, 3, 31),
        "11012": date(year, 6, 30),
        "11014": date(year, 9, 30),
        "11011": date(year, 12, 31),
    }[report_code]
    return {
        "stock_code": "005930",
        "source_rcept_no": receipt,
        "bsns_year": year,
        "reprt_code": report_code,
        "fs_div": "CFS",
        "sj_div": "IS",
        "account_id": account_id,
        "account_nm": "Revenue",
        "thstrm_amount": amount,
        "thstrm_add_amount": cumulative,
        "period_end": quarter_end,
        "available_date": quarter_end,
    }


def test_cumulative_income_is_converted_to_individual_quarters():
    rows = [
        _flow_row("r1", "11013", "ifrs-full_Revenue", 10, 10),
        _flow_row("r2", "11012", "ifrs-full_Revenue", 20, 30),
        _flow_row("r3", "11014", "ifrs-full_Revenue", 30, 60),
        _flow_row("r4", "11011", "ifrs-full_Revenue", 100, None),
    ]
    result = build_quarter_fundamentals(rows)
    assert [row["revenue"] for row in result] == [10.0, 20.0, 30.0, 40.0]


def test_correction_keeps_original_information_set_and_prior_quarter_flow():
    original_q1 = _flow_row("q1-original", "11013", "ifrs-full_Revenue", 10, 10)
    original_q1["available_date"] = date(2025, 5, 15)
    original_q2 = _flow_row("q2-original", "11012", "ifrs-full_Revenue", 20, 30)
    original_q2["available_date"] = date(2025, 8, 15)
    corrected_q1 = _flow_row("q1-correction", "11013", "ifrs-full_Revenue", 20, 20)
    corrected_q1["available_date"] = date(2025, 9, 15)

    rows = {
        row["source_rcept_no"]: row
        for row in build_quarter_fundamentals([original_q1, original_q2, corrected_q1])
    }

    assert set(rows) == {"q1-original", "q2-original", "q1-correction"}
    assert rows["q2-original"]["revenue"] == 20.0
    assert rows["q1-correction"]["revenue"] == 20.0


def test_yoy_uses_same_quarter_not_previous_quarter():
    records = [
        {
            "stock_code": "005930", "fiscal_year": 2024, "quarter_no": 1,
            "revenue": 100.0, "operating_income": 10.0, "operating_cashflow": 8.0,
            "total_assets": 100.0, "total_equity": 50.0,
        },
        {
            "stock_code": "005930", "fiscal_year": 2025, "quarter_no": 1,
            "revenue": 120.0, "operating_income": 15.0, "operating_cashflow": 10.0,
            "total_assets": 100.0, "total_equity": 50.0,
        },
    ]
    frame = _add_derived_metrics(records)
    latest = frame[frame["fiscal_year"] == 2025].iloc[0]
    assert latest["revenue_growth_yoy"] == 0.2
    assert latest["operating_income_growth_yoy"] == 0.5


def test_yoy_uses_prior_value_available_on_the_same_date():
    base = {
        "stock_code": "005930", "quarter_no": 1, "fs_div": "CFS",
        "operating_income": 10.0, "operating_cashflow": 8.0,
        "total_assets": 100.0, "total_equity": 50.0,
        "total_liabilities": 50.0, "current_assets": 50.0,
        "current_liabilities": 25.0, "net_income": 8.0,
        "source_rcept_no": "prior-original",
    }
    records = [
        {**base, "fiscal_year": 2024, "available_date": date(2024, 5, 15), "revenue": 100.0},
        {**base, "fiscal_year": 2025, "available_date": date(2025, 5, 15), "revenue": 120.0, "source_rcept_no": "current"},
        {**base, "fiscal_year": 2024, "available_date": date(2025, 6, 15), "revenue": 200.0, "source_rcept_no": "prior-correction"},
    ]

    frame = _add_derived_metrics(records)
    current = frame[frame["source_rcept_no"] == "current"].iloc[0]

    assert current["revenue_growth_yoy"] == 0.2


def _scoring_frame(equity=100.0, missing_revenue_growth=False):
    rows = []
    for index in range(10):
        value = float(index + 1)
        rows.append({
            "stock_code": f"{index:06d}",
            "source_rcept_no": f"r{index}",
            "fiscal_year": 2025,
            "quarter_no": 1,
            "fiscal_quarter": "2025Q1",
            "reprt_code": "11013",
            "fs_div": "CFS",
            "period_end": date(2025, 3, 31),
            "available_date": date(2025, 5, 15),
            "model_version": MODEL_VERSION,
            "score_model_code": "GENERAL_V1",
            "company_status_code": "ACTIVE",
            "revenue": 100.0,
            "operating_income": value,
            "net_income": value,
            "total_assets": 200.0,
            "total_liabilities": 100.0,
            "total_equity": equity,
            "current_assets": 100.0,
            "current_liabilities": 50.0,
            "operating_cashflow": value,
            "capex": 1.0,
            "fcf": value - 1,
            "market_cap": 1000.0,
            "operating_margin": value / 100,
            "roe": value / equity if equity else None,
            "roa": value / 200,
            "debt_ratio": 1.0,
            "current_ratio": 2.0,
            "ocf_to_revenue": value / 100,
            "ocf_to_net_income": 1.0,
            "per_proxy": 1000 / value,
            "pbr_proxy": 10.0,
            "revenue_growth_yoy": None if missing_revenue_growth else value / 100,
            "operating_income_growth_yoy": value / 100,
            "operating_margin_change_yoy": value / 1000,
            "operating_cashflow_change_yoy": value / 100,
        })
    return pd.DataFrame(rows)


def test_missing_metric_reduces_confidence_instead_of_becoming_zero_score():
    config = load_config("risk_neutral")
    complete = score_quarter_fundamentals(_scoring_frame(), config)[-1]
    missing = score_quarter_fundamentals(
        _scoring_frame(missing_revenue_growth=True), config
    )[-1]
    assert missing["change_confidence"] < complete["change_confidence"]
    assert missing["change_score"] > 0


def test_non_positive_equity_is_hard_excluded():
    result = score_quarter_fundamentals(
        _scoring_frame(equity=0.0), load_config("risk_neutral")
    )[0]
    assert result["is_eligible"] is False
    assert result["excluded_reason_code"] == "CAPITAL_IMPAIRMENT"


def test_scoring_is_deterministic_for_same_input():
    frame = _scoring_frame()
    config = load_config("risk_neutral")
    first = score_quarter_fundamentals(frame, config)
    second = score_quarter_fundamentals(frame, config)
    assert [row["fa_score"] for row in first] == [row["fa_score"] for row in second]


def test_later_disclosure_cannot_change_earlier_point_in_time_scores():
    early = _scoring_frame()
    early["available_date"] = date(2025, 5, 15)
    baseline = {
        row["stock_code"]: row
        for row in score_quarter_fundamentals(early, load_config("risk_neutral"))
    }

    late = early.iloc[[0]].copy()
    late["stock_code"] = "999999"
    late["source_rcept_no"] = "late-disclosure"
    late["available_date"] = date(2025, 6, 14)
    late["operating_income"] = 10000.0
    late["net_income"] = 10000.0
    late["operating_cashflow"] = 10000.0
    late["fcf"] = 9999.0
    late["roe"] = 100.0
    late["roa"] = 50.0
    late["per_proxy"] = 0.1
    combined = pd.concat([early, late], ignore_index=True)
    rescored = {
        row["stock_code"]: row
        for row in score_quarter_fundamentals(combined, load_config("risk_neutral"))
    }

    for stock_code, baseline_row in baseline.items():
        assert rescored[stock_code]["fa_score"] == baseline_row["fa_score"]
        assert rescored[stock_code]["score_detail"]["point_in_time"] == {
            "score_as_of_date": "2025-05-15",
            "cohort_size": 10,
        }


def test_correction_replaces_prior_cohort_observation_instead_of_duplicating_it():
    initial = _scoring_frame()
    initial["available_date"] = date(2025, 5, 15)
    baseline = {
        row["source_rcept_no"]: row
        for row in score_quarter_fundamentals(initial, load_config("risk_neutral"))
    }
    correction = initial.iloc[[0]].copy()
    correction["source_rcept_no"] = "r0-correction"
    correction["available_date"] = date(2025, 6, 14)
    correction["operating_income"] = 10000.0
    correction["net_income"] = 10000.0
    correction["operating_cashflow"] = 10000.0
    correction["fcf"] = 9999.0
    correction["roe"] = 100.0
    correction["roa"] = 50.0
    correction["per_proxy"] = 0.1

    scored = {
        row["source_rcept_no"]: row
        for row in score_quarter_fundamentals(
            pd.concat([initial, correction], ignore_index=True),
            load_config("risk_neutral"),
        )
    }

    assert scored["r0-correction"]["score_detail"]["point_in_time"]["cohort_size"] == 10
    for receipt, baseline_row in baseline.items():
        assert scored[receipt]["fa_score"] == baseline_row["fa_score"]
