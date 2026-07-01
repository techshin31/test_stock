from datetime import date

from storage.postgres.repositories.financial_repo import (
    fetch_financial_statements_as_of,
    upsert_financial_statements,
)
from storage.postgres.repositories.macro_signal_repo import (
    fetch_latest_signal_dates,
    fetch_macro_signals_as_of,
    upsert_macro_signals,
)
from storage.postgres.repositories.wics_industry_repo import (
    fetch_wics_industry_prices,
    upsert_wics_industry_prices,
)
from storage.postgres.repositories.wics_repo import fetch_latest_wics_snapshot


class FakeDB:
    def __init__(self, rows=None):
        self.rows = rows or []
        self.calls = []

    def execute_many(self, query, params):
        self.calls.append((query, params))

    def fetch_all(self, query, params=None):
        self.calls.append((query, params))
        return self.rows


def test_macro_upsert_preserves_revision_identity():
    db = FakeDB()
    base = {
        "signal_name_code": "CPI",
        "category_code": "RATES",
        "observation_date": date(2026, 4, 1),
        "available_date": date(2026, 5, 12),
        "value": 320.1,
        "frequency_code": "MONTHLY",
        "source_code": "FRED",
        "source_value_key": "CPIAUCSL",
    }
    upsert_macro_signals(db, [base, {**base, "revision_no": 1, "value": 320.2}])
    query, params = db.calls[0]
    assert "observation_date, revision_no" in query
    assert params[0][-1] == 0
    assert params[1][-1] == 1


def test_macro_as_of_query_filters_availability_and_selects_latest_revision():
    db = FakeDB()
    fetch_macro_signals_as_of(db, date(2026, 5, 31), signal_names=["CPI"])
    query, params = db.calls[0]
    assert "available_date <= %s::date" in query
    assert "DISTINCT ON (signal_name_code, observation_date)" in query
    assert "revision_no DESC" in query
    assert params == (["CPI"], "2026-05-31")


def test_macro_incremental_cursor_ignores_unverified_legacy_rows():
    db = FakeDB()
    fetch_latest_signal_dates(db)
    query, _ = db.calls[0]
    assert "source_code <> 'LEGACY'" in query
    assert "HAVING" in query


def test_latest_wics_snapshot_is_bounded_by_cutoff():
    db = FakeDB()
    fetch_latest_wics_snapshot(db, date(2026, 5, 31))
    query, params = db.calls[0]
    assert "MAX(base_date)" in query
    assert "base_date <= %s::date" in query
    assert params == ("2026-05-31",)


def test_wics_price_source_is_deterministic_and_idempotent():
    db = FakeDB()
    rows = [{
        "industry_code": "G4530",
        "price_date": date(2026, 5, 29),
        "index_value": 1234.5,
        "source_code": "WISEINDEX",
    }]
    assert upsert_wics_industry_prices(db, rows) == 1
    assert "ON CONFLICT" in db.calls[0][0]

    fetch_wics_industry_prices(db, date(2026, 5, 31), ["G4530"])
    query, params = db.calls[1]
    assert "array_position" in query
    assert params[-1] == ["WISEINDEX", "DERIVED"]


def test_financial_receipts_keep_corrections_separate():
    db = FakeDB()
    base = {
        "stock_code": "005930",
        "corp_code": "00126380",
        "bsns_year": 2025,
        "reprt_code": "11011",
        "fs_div": "CFS",
        "sj_div": "IS",
        "account_id": "ifrs-full_Revenue",
        "account_nm": "Revenue",
        "available_date": date(2026, 3, 10),
        "source_rcept_no": "202603100001",
    }
    upsert_financial_statements(
        db,
        [base, {**base, "source_rcept_no": "202603150001", "revision_no": 1}],
    )
    query, params = db.calls[0]
    assert "source_rcept_no" in query
    assert params[0][8] != params[1][8]
    assert params[1][-1] == 1


def test_financial_as_of_excludes_unverifiable_legacy_rows():
    db = FakeDB()
    fetch_financial_statements_as_of(db, date(2026, 5, 31), ["005930"])
    query, params = db.calls[0]
    assert "available_date <= %s::date" in query
    assert "source_rcept_no NOT LIKE 'LEGACY:%%'" in query
    assert params == ("2026-05-31", ["005930"])
