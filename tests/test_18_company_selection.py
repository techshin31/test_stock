from datetime import date

import pytest

from apps.worker.analyzer.company_job import select_companies
from apps.worker.analyzer.config import load_config


def _fa(stock_code, fa_id, score, confidence=1.0):
    return {
        "id": fa_id, "stock_code": stock_code, "fa_score": score,
        "score_confidence": confidence, "is_eligible": True, "valid_financial_quarters": 8,
        "total_equity": 100, "available_date": "2026-05-15",
        "excluded_reason_code": None,
    }


def test_company_selection_applies_filters_ranking_and_lineage():
    sectors = [{"id": 77, "sector_code": "G45", "industry_code": "G4530"}]
    snapshot = [
        {"stock_code": "A", "sector_code": "G45", "industry_code": "G4530", "company_size_code": "LARGE", "trd_amt": 500},
        {"stock_code": "B", "sector_code": "G45", "industry_code": "G4530", "company_size_code": "LARGE", "trd_amt": 400},
        {"stock_code": "C", "sector_code": "G45", "industry_code": "G4530", "company_size_code": "LARGE", "trd_amt": 300},
        {"stock_code": "D", "sector_code": "G45", "industry_code": "G4530", "company_size_code": "MID", "trd_amt": 900},
    ]
    fa = [_fa("A", 1, 80), _fa("B", 2, 80), _fa("C", 3, 80), _fa("D", 4, 99)]
    statuses = [
        {"stock_code": code, "status_code": "ACTIVE", "market_type_code": "KOSPI"}
        for code in "ABCD"
    ]
    rows = select_companies(
        sectors, snapshot, fa, statuses, load_config(), buy_blocked_codes={"A"}
    )
    selected = [row for row in rows if row["is_selected"]]
    assert [row["stock_code"] for row in sorted(selected, key=lambda row: row["industry_rank"])] == ["B", "C"]
    assert all(row["company_quarter_fa_id"] in {2, 3} for row in selected)
    assert next(row for row in rows if row["stock_code"] == "A")["exclusion_reason_code"] == "BUY_BLOCKED"
    assert next(row for row in rows if row["stock_code"] == "D")["exclusion_reason_code"] == "NOT_LARGE"


def test_company_tie_break_is_stock_code_and_deterministic():
    sectors = [{"id": 77, "sector_code": "G45", "industry_code": "G4530"}]
    snapshot = [
        {"stock_code": code, "sector_code": "G45", "industry_code": "G4530", "company_size_code": "LARGE", "trd_amt": 100}
        for code in ("C", "A", "B")
    ]
    fa = [_fa(code, index, 80) for index, code in enumerate(("C", "A", "B"), 1)]
    statuses = [
        {"stock_code": code, "status_code": "ACTIVE", "market_type_code": "KOSPI"}
        for code in "ABC"
    ]
    rows = select_companies(sectors, snapshot, fa, statuses, load_config())
    ranked = sorted((row for row in rows if row["is_eligible"]), key=lambda row: row["industry_rank"])
    assert [row["stock_code"] for row in ranked] == ["A", "B", "C"]


def test_company_risk_state_is_saved_as_exclusion_lineage():
    sectors = [{"id": 77, "sector_code": "G45", "industry_code": "G4530"}]
    snapshot = [{
        "stock_code": "A", "sector_code": "G45", "industry_code": "G4530",
        "company_size_code": "LARGE", "trd_amt": 100,
    }]
    statuses = [{"stock_code": "A", "status_code": "ACTIVE", "market_type_code": "KOSPI"}]
    risk = [{
        "stock_code": "A", "risk_action_code": "BLOCK_BUY",
        "reason_code": "CONVERTIBLE_BOND", "source_dart_event_id": 9,
        "effective_date": "2026-05-01", "expires_at": "2026-07-30",
        "policy_version": "dart-dilution-v1.0.0",
    }]
    rows = select_companies(
        sectors, snapshot, [_fa("A", 1, 80)], statuses, load_config(),
        company_risk_rows=risk,
    )
    assert rows[0]["exclusion_reason_code"] == "BUY_BLOCKED"
    assert rows[0]["selection_detail"]["risk_state"]["source_dart_event_id"] == 9


def test_company_selection_excludes_stale_fundamental_scores():
    sectors = [{"id": 77, "sector_code": "G45", "industry_code": "G4530"}]
    snapshot = [{
        "stock_code": "A", "sector_code": "G45", "industry_code": "G4530",
        "company_size_code": "LARGE", "trd_amt": 100,
    }]
    statuses = [{"stock_code": "A", "status_code": "ACTIVE", "market_type_code": "KOSPI"}]
    stale = _fa("A", 1, 80)
    stale["available_date"] = "2025-12-01"

    rows = select_companies(
        sectors, snapshot, [stale], statuses, load_config(),
        as_of_date=date(2026, 6, 1),
    )

    assert rows[0]["is_selected"] is False
    assert rows[0]["exclusion_reason_code"] == "STALE_FA"
    assert rows[0]["selection_detail"]["fa_age_days"] == 182


def test_unregistered_member_is_audited_without_inserting_invalid_foreign_key(monkeypatch):
    from apps.worker.analyzer import company_job as job
    sectors=[{'id':1,'industry_code':'G4530'}]
    members=[{'stock_code':'UNKNOWN','industry_code':'G4530','sector_code':'G45','company_size_code':'LARGE'}]
    monkeypatch.setattr(job,'fetch_sector_results',lambda *a,**k:sectors)
    monkeypatch.setattr(job,'fetch_latest_wics_snapshot',lambda *a:members)
    monkeypatch.setattr(job,'fetch_latest_company_fa_as_of',lambda *a,**k:[])
    monkeypatch.setattr(job,'fetch_company_statuses',lambda *a:[])
    monkeypatch.setattr(job,'fetch_active_company_risk_states',lambda *a,**k:[])
    writes=[]
    monkeypatch.setattr(job,'insert_company_results',lambda db,run_id,rows:writes.append(rows))
    results=job.run(None,1,date(2026,5,31),load_config())
    assert writes==[[]]
    assert results[0]['identity_registered'] is False
    assert results[0]['exclusion_reason_code']=='MAPPING_ERROR'
    assert results[0]['is_selected'] is False


@pytest.mark.parametrize("quarters, selected", [(8, True), (7, False), (0, False), (None, False)])
def test_financial_history_is_a_hard_filter_even_for_high_scores(quarters, selected):
    fa = _fa("A", 1, 100)
    if quarters is None:
        fa.pop("valid_financial_quarters")
    else:
        fa["valid_financial_quarters"] = quarters
    rows = select_companies(
        [{"id": 77, "industry_code": "G4530"}],
        [{"stock_code": "A", "sector_code": "G45", "industry_code": "G4530",
          "company_size_code": "LARGE"}],
        [fa], [{"stock_code": "A", "status_code": "ACTIVE", "market_type_code": "KOSPI"}],
        load_config(), as_of_date=date(2026, 5, 31),
    )
    assert rows[0]["is_selected"] is selected
    assert rows[0]["exclusion_reason_code"] == (None if selected else "INSUFFICIENT_FINANCIAL_HISTORY")
    detail = rows[0]["selection_detail"]
    assert detail["valid_financial_quarters"] == (quarters or 0)
    assert detail["minimum_financial_quarters"] == 8
    assert detail["financial_history_cutoff"] == date(2026, 5, 31)
