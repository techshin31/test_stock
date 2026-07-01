from datetime import date
from types import SimpleNamespace

import pandas as pd

import apps.worker.__main__ as worker_main
from apps.worker.collector import company_job, macro_job, wics_industry_job, wics_job
from apps.worker.__main__ import (
    _resolve_collect_end,
    _resolve_collect_start,
    _wics_date_list,
    run_collect,
)
from data.collectors.dart_collector import _classify_regular_report
from data.collectors.fred_collector import _parse_vintage_observations
from data.collectors.wics_collector import parse_wics_companies
from data.loaders.company_data import _df_to_records
from data.collectors.kto_collector import _parse_kto_tourist_items
from data.preprocess.macro_signals import _series_to_records, _series_to_records_release_date
from storage.postgres.repositories.dart_event_repo import (
    fetch_event_date_bounds,
    fetch_latest_regular_report,
)
from storage.postgres.repositories.company_repo import fetch_analysis_companies


class FakeDB:
    def __init__(self, row=None):
        self.row = row
        self.calls = []

    def fetch_one(self, query, params=None):
        self.calls.append((query, params))
        return self.row

    def fetch_all(self, query, params=None):
        self.calls.append((query, params))
        return self.row or []


def test_fred_vintages_preserve_release_and_revision_order():
    rows = _parse_vintage_observations([
        {"date": "2026-01-01", "realtime_start": "2026-02-10", "value": "321.0"},
        {"date": "2026-01-01", "realtime_start": "2026-03-12", "value": "321.2"},
        {"date": "2026-02-01", "realtime_start": "2026-03-12", "value": "."},
    ])
    assert [row["revision_no"] for row in rows] == [0, 1]
    assert rows[0]["observation_date"] == date(2026, 1, 1)
    assert rows[1]["available_date"] == date(2026, 3, 12)


def test_dart_generic_quarter_report_names_map_by_period_month():
    assert _classify_regular_report("분기보고서 (2025.03)") == (
        "REGULAR_REPORT", "Q1_REPORT"
    )


def test_wics_requested_code_is_saved_as_industry_not_parent_sector():
    data = {
        "list": [{
            "CMP_CD": "5930",
            "SEC_CD": "G45",
            "MKT_VAL": 100,
            "TRD_AMT": 10,
        }],
        "sector": [{"SEC_CD": "G45", "SEC_RATE": 20.0, "IDX_RATE": 30.0}],
    }
    row = parse_wics_companies("20260529", 4530, data).iloc[0]
    assert row["sector_code"] == "G45"
    assert row["industry_code"] == "G4530"
    assert _classify_regular_report("[기재정정]분기보고서 (2025.09)") == (
        "REGULAR_REPORT", "Q3_REPORT"
    )


def test_market_macro_is_available_on_next_krx_session():
    series = pd.Series(
        [100.0], index=pd.DatetimeIndex(["2026-06-19"], tz="UTC")
    )
    record = _series_to_records(series, "SOX", "RISK", "DAILY")[0]
    assert record["observation_date"] == date(2026, 6, 19)
    assert record["available_date"] == date(2026, 6, 22)
    assert record["source_value_key"] == "^SOX"


def test_source_release_macro_uses_collection_date_for_availability():
    series = pd.Series([101.0], index=pd.DatetimeIndex(["2026-05-01"]))
    record = _series_to_records_release_date(
        series,
        "GPR",
        "RISK",
        "MONTHLY",
        collected_date=date(2026, 6, 19),
    )[0]
    assert record["observation_date"] == date(2026, 5, 1)
    assert record["available_date"] == date(2026, 6, 22)
    assert record["source_code"] == "GPR"


def test_kto_tourist_parser_accepts_common_monthly_keys():
    series = _parse_kto_tourist_items([
        {"baseYmd": "202605", "touristCnt": "1,234"},
        {"stdYm": "202606", "inbnd_touris_num": 1500},
    ])
    assert series.loc[pd.Timestamp("2026-05-01")] == 1234
    assert series.loc[pd.Timestamp("2026-06-01")] == 1500


def test_financial_raw_record_keeps_receipt_period_and_cumulative_values():
    frame = pd.DataFrame([{
        "account_id": "ifrs-full_Revenue",
        "account_nm": "Revenue",
        "thstrm_amount": "10,000",
        "thstrm_add_amount": "30,000",
    }])
    report = {
        "rcept_no": "202605150001",
        "rcept_dt": date(2026, 5, 15),
        "period_start": date(2026, 1, 1),
        "period_end": date(2026, 3, 31),
        "revision_no": 0,
    }
    record = _df_to_records(
        frame, "005930", "00126380", 2026, "11013", "CFS", "IS", report
    )[0]
    assert record["source_rcept_no"] == "202605150001"
    assert record["available_date"] == date(2026, 5, 15)
    assert record["thstrm_add_amount"] == 30000


def test_regular_report_lookup_is_versioned_and_period_specific():
    db = FakeDB({"rcept_no": "1", "revision_no": 1})
    fetch_latest_regular_report(db, "005930", "Q1_REPORT", "2026.03")
    query, params = db.calls[0]
    assert "ROW_NUMBER()" in query
    assert "ORDER BY rcept_dt DESC" in query
    assert params == ("005930", "Q1_REPORT", "%2026.03%")


def test_event_bounds_support_historical_gap_detection():
    db = FakeDB({"earliest": date(2025, 1, 1), "latest": date(2026, 1, 1)})
    result = fetch_event_date_bounds(db, "005930")
    assert result["earliest"] == date(2025, 1, 1)
    assert db.calls[0][1] == ("005930",)


def test_wics_constituent_job_is_incremental_and_reports_failures(monkeypatch):
    frame = pd.DataFrame(
        {"close": [100.0, 101.0]},
        index=pd.DatetimeIndex(["2026-06-18", "2026-06-19"]),
    )
    monkeypatch.setattr(wics_industry_job, "fetch_kospi_wics_stock_codes", lambda db: ["005930", "000001"])
    monkeypatch.setattr(
        wics_industry_job,
        "fetch_latest_constituent_price_dates",
        lambda db: {"005930": date(2026, 6, 17)},
    )
    monkeypatch.setattr(
        wics_industry_job,
        "download_stock_ohlcv",
        lambda ticker, start, end: frame if ticker == "005930.KS" else None,
    )
    saved = []
    monkeypatch.setattr(
        wics_industry_job,
        "upsert_wics_constituent_prices",
        lambda db, rows: saved.extend(rows) or len(rows),
    )

    result = wics_industry_job.run(
        object(), start="2026-06-01", end="2026-06-19", show_progress=False
    )
    assert result == {"saved_rows": 2, "failed_stock_codes": ["000001"]}
    assert saved[0]["source_code"] == "YAHOO"


def test_wics_constituent_job_uses_tqdm_for_progress(monkeypatch):
    frame = pd.DataFrame(
        {"close": [100.0]},
        index=pd.DatetimeIndex(["2026-06-19"]),
    )
    tqdm_calls = []

    monkeypatch.setattr(wics_industry_job, "_HAS_TQDM", True)
    monkeypatch.setattr(
        wics_industry_job,
        "_tqdm",
        lambda items, **kwargs: tqdm_calls.append(kwargs) or items,
    )
    monkeypatch.setattr(
        wics_industry_job,
        "fetch_kospi_wics_stock_codes",
        lambda db: ["005930"],
    )
    monkeypatch.setattr(
        wics_industry_job,
        "fetch_latest_constituent_price_dates",
        lambda db: {},
    )
    monkeypatch.setattr(wics_industry_job, "download_stock_ohlcv", lambda *args: frame)
    monkeypatch.setattr(
        wics_industry_job,
        "upsert_wics_constituent_prices",
        lambda db, rows: len(rows),
    )

    result = wics_industry_job.run(
        object(), start="2026-06-19", end="2026-06-19", show_progress=True
    )
    assert result == {"saved_rows": 1, "failed_stock_codes": []}
    assert tqdm_calls == [{"desc": "WICS 가격", "unit": "종목"}]


def test_wics_job_passes_date_window_to_price_collection(monkeypatch):
    import data.loaders.wics_data as wics_data

    calls = []
    monkeypatch.setattr(wics_data, "collect_wics_companies", lambda *args, **kwargs: 1)
    monkeypatch.setattr(
        wics_industry_job,
        "run",
        lambda db, start=None, end=None, show_progress=True: calls.append(
            (start, end, show_progress)
        ) or {},
    )

    result = wics_job.run(
        object(),
        date_list=["20260622"],
        show_progress=False,
        price_start="2026-06-22",
        price_end="2026-06-23",
    )
    assert result == 1
    assert calls == [("2026-06-22", "2026-06-23", False)]


def test_wics_job_does_not_fallback_to_today_for_empty_explicit_range(monkeypatch):
    import data.loaders.wics_data as wics_data

    calls = []
    monkeypatch.setattr(
        wics_data,
        "collect_wics_companies",
        lambda *args, **kwargs: calls.append(args) or 1,
    )

    result = wics_job.run(object(), date_list=[], show_progress=False)
    assert result == 0
    assert calls == []


def test_macro_job_uses_end_date_as_source_release_collection_date(monkeypatch):
    import data.preprocess.macro_signals as macro_signals

    calls = []
    monkeypatch.setattr(
        macro_signals,
        "collect_and_save",
        lambda *args, **kwargs: calls.append(kwargs) or {"GPR": 1},
    )

    result = macro_job.run(
        object(), start="2026-06-22", end="2026-06-22", show_progress=False
    )
    assert result == {"GPR": 1}
    assert calls[0]["source_release_collected_date"] == date(2026, 6, 22)


def test_company_job_collects_receipts_before_financials(monkeypatch):
    calls = []
    monkeypatch.setattr(company_job, "collect_companies_from_wics", lambda *args, **kwargs: 1)
    monkeypatch.setattr(company_job, "sync_company_status", lambda *args, **kwargs: 1)
    monkeypatch.setattr(
        company_job,
        "collect_dart_events",
        lambda db, start, end, **kwargs: calls.append(("events", start, end)) or 2,
    )
    monkeypatch.setattr(
        company_job,
        "collect_financial_statements",
        lambda *args, **kwargs: calls.append("financials") or 3,
    )
    monkeypatch.setattr(
        company_job,
        "refresh_company_risk_states",
        lambda db, as_of_date: calls.append(("risk_states", as_of_date)) or 1,
    )
    result = company_job.run(
        object(),
        years=[2025],
        dart_start_date="20250101",
        dart_end_date="20250622",
        show_progress=False,
    )
    assert calls == [
        ("events", "20250101", "20250622"),
        ("risk_states", date(2025, 6, 22)),
        "financials",
    ]
    assert result == {
        "financial_statements": 3,
        "dart_events": 2,
        "company_risk_states": 1,
    }


def test_wics_weekly_range_uses_last_krx_session_per_week():
    assert _wics_date_list("2026-06-15", "2026-06-22", "weekly") == [
        "20260619",
        "20260622",
    ]


def test_wics_weekly_range_returns_empty_list_when_no_krx_session():
    assert _wics_date_list("2026-06-28", "2026-06-28", "weekly") == []


def test_collect_all_defaults_start_to_previous_day():
    assert _resolve_collect_start(
        "all", None, None, today=date(2026, 6, 23)
    ) == "2026-06-22"
    assert _resolve_collect_start(
        "all", None, "2026-05-31", today=date(2026, 6, 23)
    ) == "2026-05-30"
    assert _resolve_collect_start(
        "wics", None, None, today=date(2026, 6, 23)
    ) is None


def test_collect_all_defaults_end_to_previous_day():
    assert _resolve_collect_end(
        "all", None, today=date(2026, 6, 23)
    ) == "2026-06-22"
    assert _resolve_collect_end(
        "all", "2026-05-31", today=date(2026, 6, 23)
    ) == "2026-05-31"
    assert _resolve_collect_end(
        "wics", None, today=date(2026, 6, 23)
    ) is None


def test_collect_all_passes_previous_day_end_to_all_jobs(monkeypatch):
    class FakeDBWithClose:
        closed = False

        def close(self):
            self.closed = True

    db = FakeDBWithClose()
    cfg = SimpleNamespace(
        fred_api_key=None,
        kto_api_key=None,
        company_years=[2024, 2025, 2026],
        dart_start_date="20200101",
    )
    calls = []

    monkeypatch.setattr(worker_main, "_init", lambda: (cfg, db))
    monkeypatch.setattr(worker_main, "_today_kst", lambda: date(2026, 6, 23))
    monkeypatch.setattr(
        macro_job,
        "run",
        lambda db, **kwargs: calls.append(("macro", kwargs)) or {},
    )
    monkeypatch.setattr(
        wics_job,
        "run",
        lambda db, **kwargs: calls.append(("wics", kwargs)) or 1,
    )
    monkeypatch.setattr(
        company_job,
        "run",
        lambda db, **kwargs: calls.append(("company", kwargs)) or {},
    )
    monkeypatch.setattr(
        wics_industry_job,
        "run",
        lambda db, **kwargs: calls.append(("wics_price", kwargs)) or {},
    )

    args = SimpleNamespace(
        target="all",
        start=None,
        end=None,
        years=None,
        no_progress=True,
        check_readiness=False,
        wics_snapshot_frequency="weekly",
        company_size=None,
        force_refresh=False,
    )
    run_collect(args)

    assert db.closed
    assert calls[0] == (
        "macro",
        {
            "start": "2026-06-22",
            "end": "2026-06-22",
            "fred_api_key": None,
            "kto_api_key": None,
            "show_progress": False,
        },
    )
    assert calls[1][0] == "wics"
    assert calls[1][1]["date_list"] == ["20260622"]
    assert calls[1][1]["price_start"] == "2026-06-22"
    assert calls[1][1]["price_end"] == "2026-06-22"
    assert calls[2][0] == "company"
    assert calls[2][1]["years"] == [2026]
    assert calls[2][1]["dart_start_date"] == "20260622"
    assert calls[2][1]["dart_end_date"] == "20260622"
    assert calls[3] == (
        "wics_price",
        {"start": "2026-06-22", "end": "2026-06-22", "show_progress": False},
    )


def test_analysis_companies_are_scoped_to_latest_active_kospi_snapshot():
    db = FakeDB([])
    fetch_analysis_companies(db, ["LARGE"])
    query, params = db.calls[0]
    assert "MAX(base_date)" in query
    assert "c.status_code = 'ACTIVE'" in query
    assert "c.market_type_code = 'KOSPI'" in query
    assert "w.company_size_code = ANY(%s)" in query
    assert params == (["LARGE"],)
