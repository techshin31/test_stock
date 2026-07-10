from dataclasses import replace

import pytest

from apps.worker.analyzer.config import load_config
from apps.worker.analyzer.models import MacroDirection, MacroResult
from apps.worker.analyzer.sector_job import score_and_select_sectors
from apps.worker.fa_contract import MACRO_SIGNALS


def _macro(relationships):
    return MacroResult(
        signal_name_code="SOX", last_observation_date=None,
        last_available_date=None, direction_code=MacroDirection.UP,
        trend_raw=1.0, trend_strength=1.0, data_point_count=160,
        confidence=1.0, calculation_detail={"relationships": relationships},
    )


def _inputs():
    industries = ["G1010", "G1510", "G2010", "G2020", "G2510", "G4510"]
    sectors = ["G10", "G15", "G20", "G20", "G25", "G45"]
    snapshot = []
    fa = []
    statuses = []
    relationships = []
    for rank, (industry, sector) in enumerate(zip(industries, sectors), 1):
        relationships.append({
            "signal_name_code": "SOX", "industry_code": industry,
            "frequency_code": "WEEKLY", "correlation": 1.0 - rank / 20,
            "beta": 1.0, "sample_count": 156, "sign_stability": 1.0,
            "relationship_confidence": 1.0,
            "contribution": (1.0 - rank / 20) / len(MACRO_SIGNALS),
            "is_eligible": True,
        })
        company_count = 1 if industry == "G1010" else 2
        for number in range(company_count):
            stock = f"{rank}{number}"
            snapshot.append({
                "stock_code": stock, "sector_code": sector,
                "industry_code": industry, "company_size_code": "LARGE",
                "trd_amt": 1000 - rank, "mkt_val": 100,
            })
            fa.append({
                "stock_code": stock, "fa_score": 70, "score_confidence": 1.0,
                "is_eligible": True, "revenue_growth_yoy": 1,
                "operating_income_growth_yoy": 1,
                "operating_margin_change_yoy": 1,
                "operating_cashflow_change_yoy": 1,
            })
            statuses.append({
                "stock_code": stock, "status_code": "ACTIVE", "market_type_code": "KOSPI"
            })
    return [_macro(relationships)], snapshot, fa, statuses


def _single_industry_inputs():
    snapshot = []
    fa = []
    statuses = []
    for number in range(2):
        stock = f"150{number}"
        snapshot.append({
            "stock_code": stock,
            "sector_code": "G15",
            "industry_code": "G1510",
            "company_size_code": "LARGE",
            "trd_amt": 1000,
            "mkt_val": 100,
        })
        fa.append({
            "stock_code": stock,
            "fa_score": 70,
            "score_confidence": 1.0,
            "is_eligible": True,
            "revenue_growth_yoy": 1,
            "operating_income_growth_yoy": 1,
            "operating_margin_change_yoy": 1,
            "operating_cashflow_change_yoy": 1,
        })
        statuses.append({
            "stock_code": stock,
            "status_code": "ACTIVE",
            "market_type_code": "KOSPI",
        })
    return snapshot, fa, statuses


def _macro_with_contribution(signal_name_code, contribution):
    return MacroResult(
        signal_name_code=signal_name_code,
        last_observation_date=None,
        last_available_date=None,
        direction_code=MacroDirection.UP,
        trend_raw=1.0,
        trend_strength=1.0,
        data_point_count=160,
        confidence=1.0,
        calculation_detail={
            "relationships": [{
                "signal_name_code": signal_name_code,
                "industry_code": "G1510",
                "frequency_code": "WEEKLY",
                "correlation": 1.0,
                "beta": 1.0,
                "sample_count": 156,
                "sign_stability": 1.0,
                "relationship_confidence": 1.0,
                "contribution": contribution,
                "is_eligible": True,
            }],
        },
    )


def test_sector_candidates_and_selection_are_deterministic_and_diversified():
    inputs = _inputs()
    first = score_and_select_sectors(*inputs, load_config())
    second = score_and_select_sectors(*inputs, load_config())
    assert first == second
    assert sum(row["is_candidate"] for row in first) == 6
    candidates = [row for row in first if row["is_candidate"]]
    assert sum(row["candidate_source_code"] == "UP" for row in candidates) == 5
    assert sum(row["candidate_source_code"] == "DOWN" for row in candidates) == 1
    assert all(row["candidate_rank"] is not None for row in candidates)
    selected = [row for row in first if row["is_selected"]]
    assert len(selected) == 5
    assert all(row["is_candidate"] for row in selected)


def test_industry_with_fewer_than_two_eligible_large_companies_is_excluded():
    results = score_and_select_sectors(*_inputs(), load_config())
    energy = next(row for row in results if row["industry_code"] == "G1010")
    assert energy["is_candidate"]
    assert not energy["is_selected"]
    assert energy["reason_code"] == "INSUFFICIENT_LARGE"


def test_company_risk_block_reduces_sector_eligible_large_count():
    macro, snapshot, fa, statuses = _inputs()
    target = next(row for row in snapshot if row["industry_code"] == "G1510")
    results = score_and_select_sectors(
        macro, snapshot, fa, statuses, load_config(),
        company_risk_rows=[{
            "stock_code": target["stock_code"],
            "risk_action_code": "BLOCK_BUY",
        }],
    )
    industry = next(row for row in results if row["industry_code"] == "G1510")
    assert industry["eligible_large_count"] == 1


def test_macro_category_contribution_cap_limits_sector_macro_fit():
    snapshot, fa, statuses = _single_industry_inputs()
    macro = [
        _macro_with_contribution(signal, 0.20)
        for signal in ("SOX", "BDRY", "VIX", "GPR")
    ]
    results = score_and_select_sectors(macro, snapshot, fa, statuses, load_config())

    industry = next(row for row in results if row["industry_code"] == "G1510")
    capped_total = sum(
        item["contribution"] for item in industry["macro_contributions"]
        if item["is_eligible"]
    )
    assert capped_total == pytest.approx(0.30)
    assert industry["macro_fit_score"] == pytest.approx(65.0)
    assert any(
        item.get("category_cap_applied")
        for item in industry["macro_contributions"]
    )


def test_low_cohort_quality_adds_sector_risk_penalty():
    snapshot, fa, statuses = _single_industry_inputs()
    macro = [_macro_with_contribution("SOX", 0.20)]
    base_config = load_config()
    no_penalty_config = replace(
        base_config,
        scoring=replace(base_config.scoring, cohort_quality_threshold=0.0),
    )
    penalty_config = replace(
        base_config,
        scoring=replace(
            base_config.scoring,
            cohort_quality_threshold=80.0,
            cohort_quality_penalty_rate=0.2,
            maximum_cohort_quality_penalty=12.0,
        ),
    )

    baseline = score_and_select_sectors(
        macro, snapshot, fa, statuses, no_penalty_config
    )[0]
    penalized = score_and_select_sectors(
        macro, snapshot, fa, statuses, penalty_config
    )[0]

    assert penalized["cohort_quality_penalty"] == pytest.approx(2.0)
    assert penalized["sector_risk_penalty"] == pytest.approx(
        baseline["sector_risk_penalty"] + 2.0
    )
    assert penalized["sector_score"] == pytest.approx(
        baseline["sector_score"] - 2.0
    )
