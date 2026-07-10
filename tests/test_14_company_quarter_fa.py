from datetime import date

import pandas as pd

from apps.worker.analyzer.company_job import (
    _add_derived_metrics,
    build_quarter_fundamentals,
    score_quarter_fundamentals,
)
from apps.worker.analyzer.config import load_config


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
            "model_version": "topdown-fa-v1.0.0",
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
