from apps.worker.analyzer.company_job import select_companies
from apps.worker.analyzer.config import load_config


def _fa(stock_code, fa_id, score, confidence=1.0):
    return {
        "id": fa_id, "stock_code": stock_code, "fa_score": score,
        "score_confidence": confidence, "is_eligible": True,
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
