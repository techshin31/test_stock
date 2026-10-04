"""Provider failures must never masquerade as absent or complete source data."""
import io
import json
import traceback
import zipfile
from datetime import date
from types import SimpleNamespace

import pytest
import requests
import pandas as pd

import apps.worker.__main__ as worker_main
from apps.worker.collector import company_job
from data.collectors import dart_collector as dart
from data.loaders import company_data


TEST_KEY = "test-only-dart-key-do-not-log"


def response(payload=None, *, body=None, status=200):
    result = requests.Response()
    result.status_code = status
    result.url = f"https://opendart.fss.or.kr/api/company.json?crtfc_key={TEST_KEY}"
    result._content = body if body is not None else json.dumps(payload).encode()
    result.encoding = "utf-8"
    return result


@pytest.fixture(autouse=True)
def isolate_dart(monkeypatch):
    monkeypatch.setenv("DART_API_KEY", TEST_KEY)

    def unexpected_request(*args, **kwargs):
        pytest.fail("Test attempted an unmocked external request")

    monkeypatch.setattr(dart.requests, "get", unexpected_request)


def fetch(endpoint):
    if endpoint == "company":
        return dart.fetch_company_detail("00126380")
    if endpoint == "financial":
        return dart.fetch_financial_statements("00126380", 2025)
    return dart.fetch_dart_events("00126380", "20250101", "20251231", sleep_seconds=0)


@pytest.mark.parametrize("endpoint", ["company", "financial", "events"])
@pytest.mark.parametrize("status,kind", [
    ("020", "RATE_LIMIT"), ("010", "AUTHENTICATION"),
    ("011", "AUTHENTICATION"), ("012", "AUTHENTICATION"), ("800", "API"),
])
def test_api_failure_stops_after_one_call_without_exposing_message(monkeypatch, endpoint, status, kind):
    calls = []

    def get(*args, **kwargs):
        calls.append(kwargs)
        return response({"status": status, "message": f"server echoed {TEST_KEY}"})

    monkeypatch.setattr(dart.requests, "get", get)
    with pytest.raises(dart.DartAPIError) as caught:
        fetch(endpoint)
    assert caught.value.kind == kind
    assert caught.value.dart_status == status
    assert TEST_KEY not in str(caught.value)
    assert len(calls) == 1


@pytest.mark.parametrize("endpoint", ["company", "financial", "events"])
def test_no_data_is_distinct_from_provider_failure(monkeypatch, endpoint):
    monkeypatch.setattr(dart.requests, "get", lambda *args, **kwargs: response({"status": "013"}))
    result = fetch(endpoint)
    assert result is None if endpoint == "company" else result.empty


@pytest.mark.parametrize("status,body,kind", [
    (502, b"Bad Gateway: upstream proxy failure\n", "PROXY"),
    (429, b"Too many requests", "RATE_LIMIT"),
    (503, b"Unavailable", "HTTP"),
])
def test_http_diagnostics_remove_key_from_traceback(monkeypatch, status, body, kind):
    monkeypatch.setattr(dart.requests, "get", lambda *args, **kwargs: response(body=body, status=status))
    with pytest.raises(dart.DartAPIError) as caught:
        fetch("company")
    assert caught.value.kind == kind
    assert caught.value.http_status == status
    formatted = "".join(traceback.format_exception(type(caught.value), caught.value, caught.value.__traceback__))
    assert TEST_KEY not in formatted
    assert "crtfc_key=" not in formatted


def test_connection_failure_does_not_leak_request_exception(monkeypatch):
    def timeout(*args, **kwargs):
        raise requests.Timeout(f"request URL contained crtfc_key={TEST_KEY}")

    monkeypatch.setattr(dart.requests, "get", timeout)
    with pytest.raises(dart.DartAPIError) as caught:
        fetch("financial")
    assert caught.value.kind == "CONNECTION"
    assert TEST_KEY not in "".join(traceback.format_exception(type(caught.value), caught.value, caught.value.__traceback__))


@pytest.mark.parametrize("payload", [None, [], {}, {"status": TEST_KEY}, {"status": "000"},
                                         {"status": "000", "list": "invalid"}])
def test_malformed_json_is_not_empty_financial_data(monkeypatch, payload):
    monkeypatch.setattr(dart.requests, "get", lambda *args, **kwargs: response(payload))
    with pytest.raises(dart.DartAPIError) as caught:
        fetch("financial")
    assert caught.value.kind == "INVALID_RESPONSE"
    assert TEST_KEY not in str(caught.value)


def test_html_response_is_not_empty_financial_data(monkeypatch):
    monkeypatch.setattr(dart.requests, "get", lambda *args, **kwargs: response(body=b"<html>gateway</html>"))
    with pytest.raises(dart.DartAPIError, match="INVALID_RESPONSE"):
        fetch("financial")


def test_corp_download_reports_xml_quota_error_instead_of_bad_zip(monkeypatch):
    body = f"<result><status>020</status><message>{TEST_KEY}</message></result>".encode()
    monkeypatch.setattr(dart.requests, "get", lambda *args, **kwargs: response(body=body))
    with pytest.raises(dart.DartAPIError) as caught:
        dart.fetch_corp_codes()
    assert caught.value.kind == "RATE_LIMIT"
    assert caught.value.dart_status == "020"
    assert TEST_KEY not in str(caught.value)


def test_valid_corp_download_keeps_real_mapping(monkeypatch):
    raw = io.BytesIO()
    with zipfile.ZipFile(raw, "w") as archive:
        archive.writestr("CORPCODE.xml", """<result>
        <list><stock_code>005930</stock_code><corp_code>00126380</corp_code><corp_name>Samsung</corp_name></list>
        <list><stock_code> </stock_code><corp_code>00000001</corp_code><corp_name>Unlisted</corp_name></list>
        </result>""")
    monkeypatch.setattr(dart.requests, "get", lambda *args, **kwargs: response(body=raw.getvalue()))
    assert dart.fetch_corp_codes() == {"005930": {"corp_code": "00126380", "company_name": "Samsung"}}


def event_row(receipt):
    return {"rcept_no": receipt, "rcept_dt": "20250515", "report_nm": "분기보고서 (2025.03)"}


def test_later_page_failure_does_not_return_partial_events(monkeypatch):
    calls = []

    def get(*args, **kwargs):
        calls.append((kwargs["params"]["pblntf_ty"], kwargs["params"]["page_no"]))
        if len(calls) == 1:
            return response({"status": "000", "total_page": 2, "list": [event_row("first-page")]})
        return response({"status": "020"})

    monkeypatch.setattr(dart.requests, "get", get)
    with pytest.raises(dart.DartAPIError, match="RATE_LIMIT"):
        fetch("events")
    assert calls == [("A", 1), ("A", 2)]


def test_successful_pagination_collects_both_report_types(monkeypatch):
    calls = []

    def get(*args, **kwargs):
        kind, page = kwargs["params"]["pblntf_ty"], kwargs["params"]["page_no"]
        calls.append((kind, page))
        if kind == "B":
            return response({"status": "013"})
        return response({"status": "000", "total_page": 2, "list": [event_row(str(page))]})

    monkeypatch.setattr(dart.requests, "get", get)
    result = fetch("events")
    assert result["rcept_no"].tolist() == ["1", "2"]
    assert calls == [("A", 1), ("A", 2), ("B", 1)]


def test_successful_financial_response_preserves_rows(monkeypatch):
    row = {"rcept_no": "20250515000001", "sj_div": "BS", "account_id": "ifrs-full_Assets", "thstrm_amount": "100"}
    monkeypatch.setattr(dart.requests, "get", lambda *args, **kwargs: response({"status": "000", "list": [row]}))
    assert fetch("financial").to_dict("records") == [row]


@pytest.mark.parametrize("target", ["events", "financial"])
@pytest.mark.parametrize("kind", ["RATE_LIMIT", "PROXY"])
def test_loader_stops_before_next_company_or_writes(monkeypatch, target, kind):
    companies = [{"stock_code": "005930", "corp_code": "00126380", "company_name": "Samsung"},
                 {"stock_code": "000660", "corp_code": "00164779", "company_name": "SK"}]
    monkeypatch.setattr(company_data, "fetch_analysis_companies", lambda *args: companies)
    monkeypatch.setattr(company_data, "fetch_event_date_bounds", lambda *args: {})
    monkeypatch.setattr(company_data, "fetch_collected_receipts", lambda *args: set())
    monkeypatch.setattr(company_data, "_fetch_company_detail", lambda *args: {"acc_mt": 12})
    monkeypatch.setattr(company_data, "fetch_latest_regular_report", lambda *args: {
        "rcept_no": "20250515000001", "rcept_dt": date(2025, 5, 15), "revision_no": 0,
    })
    writes = []
    calls = []

    def fail(*args, **kwargs):
        calls.append(args)
        raise dart.DartAPIError("list.json", kind)

    monkeypatch.setattr(company_data, "_fetch_dart_events", fail)
    monkeypatch.setattr(company_data, "_fetch_fs", fail)
    monkeypatch.setattr(company_data, "upsert_dart_events", lambda *args: writes.append(args))
    monkeypatch.setattr(company_data, "upsert_financial_statements", lambda *args: writes.append(args))
    with pytest.raises(dart.DartAPIError) as caught:
        if target == "events":
            company_data.collect_dart_events(object(), "20250101", "20251231", show_progress=False, sleep_seconds=0)
        else:
            company_data.collect_financial_statements(object(), [2025], show_progress=False, sleep_seconds=0)
    assert caught.value.kind == kind
    assert len(calls) == 1
    assert writes == []


def test_company_job_skips_downstream_work_after_event_failure(monkeypatch):
    monkeypatch.setattr(company_job, "collect_companies_from_wics", lambda *args, **kwargs: 0)
    monkeypatch.setattr(company_job, "sync_company_status", lambda *args, **kwargs: 0)

    def fail(*args, **kwargs):
        raise dart.DartAPIError("list.json", "RATE_LIMIT", dart_status="020")

    monkeypatch.setattr(company_job, "collect_dart_events", fail)
    downstream = []
    for name in ["refresh_company_risk_states", "collect_financial_statements", "rebuild_annual_fa_metrics"]:
        monkeypatch.setattr(company_job, name, lambda *args, **kwargs: downstream.append(args))
    with pytest.raises(dart.DartAPIError):
        company_job.run(object(), years=[2025], dart_end_date="20251231", show_progress=False, source="api")
    assert downstream == []


def test_cli_exits_nonzero_and_closes_db_on_collection_failure(monkeypatch, capsys):
    db = SimpleNamespace(closed=False)
    db.close = lambda: setattr(db, "closed", True)
    monkeypatch.setattr(worker_main, "_init", lambda: (SimpleNamespace(dart_start_date="20250101"), db))
    monkeypatch.setattr(worker_main, "_parse_args", lambda: SimpleNamespace(
        category="collect", target="company", no_progress=True, start="2025-01-01",
        end="2025-12-31", years=[2025], company_size=["LARGE"], check_readiness=False,
    ))

    def fail(*args, **kwargs):
        raise dart.DartAPIError("list.json", "RATE_LIMIT", dart_status="020")

    monkeypatch.setattr(company_job, "run", fail)
    with pytest.raises(SystemExit) as caught:
        worker_main.main()
    assert caught.value.code == 1
    assert db.closed
    output = capsys.readouterr()
    assert "COLLECT FAILED" in output.err
    assert "status=020" in output.err
    assert "완료" not in output.out
    assert TEST_KEY not in output.err


@pytest.fixture
def financial_loader(monkeypatch):
    receipt = {"rcept_no": "20260515000001", "rcept_dt": date(2026, 5, 15), "revision_no": 0}
    monkeypatch.setattr(company_data, "fetch_analysis_companies", lambda *args: [
        {"stock_code": "005930", "corp_code": "00126380", "company_name": "test"},
    ])
    monkeypatch.setattr(company_data, "fetch_collected_receipts", lambda *args: set())
    monkeypatch.setattr(company_data, "_fetch_company_detail", lambda *args: {"acc_mt": 12})
    monkeypatch.setattr(company_data, "fetch_latest_regular_report", lambda *args: receipt)
    writes = []
    monkeypatch.setattr(company_data, "upsert_financial_statements", lambda db, rows: writes.extend(rows))

    def collect(frame):
        monkeypatch.setattr(company_data, "_fetch_fs", lambda *args, **kwargs: frame)
        return company_data.collect_financial_statements(
            object(), [2026], reprt_codes=("11013",), sleep_seconds=0, show_progress=False,
        )

    frame = pd.DataFrame([
        {"rcept_no": receipt["rcept_no"], "corp_code": "00126380", "bsns_year": "2026",
         "reprt_code": "11013", "fs_div": "CFS", "sj_div": kind,
         "account_id": "account_" + kind, "account_nm": kind, "thstrm_amount": "100"}
        for kind in ["BS", "IS", "CF"]
    ])
    return collect, frame, writes


@pytest.mark.parametrize("column,value", [
    ("rcept_no", "20261003000001"), ("corp_code", "00164779"),
    ("bsns_year", "2025"), ("reprt_code", "11012"), ("fs_div", "OFS"),
])
def test_financial_loader_rejects_response_for_wrong_filing(financial_loader, column, value):
    collect, frame, writes = financial_loader
    frame[column] = value
    with pytest.raises(dart.DartAPIError, match="SOURCE_MISMATCH"):
        collect(frame)
    assert writes == []


@pytest.mark.parametrize("column", ["rcept_no", "corp_code", "bsns_year", "reprt_code"])
def test_financial_loader_requires_source_identifiers(financial_loader, column):
    collect, frame, writes = financial_loader
    with pytest.raises(dart.DartAPIError, match="INVALID_RESPONSE"):
        collect(frame.drop(columns=column))
    assert writes == []


def test_financial_loader_checks_every_account_before_writing(financial_loader):
    collect, frame, writes = financial_loader
    frame.loc[1, "rcept_no"] = "20261003000001"
    with pytest.raises(dart.DartAPIError, match="SOURCE_MISMATCH"):
        collect(frame)
    assert writes == []


def test_financial_loader_saves_verified_receipt_and_availability(financial_loader):
    collect, frame, writes = financial_loader
    assert collect(frame) == 1
    assert len(writes) == 3
    assert {row["source_rcept_no"] for row in writes} == {"20260515000001"}
    assert {row["available_date"] for row in writes} == {date(2026, 5, 15)}
    assert {row["period_end"] for row in writes} == {date(2026, 3, 31)}


def test_financial_loader_uses_requested_fs_div_when_not_echoed(financial_loader):
    collect, frame, writes = financial_loader
    assert collect(frame.drop(columns="fs_div")) == 1
    assert {row["fs_div"] for row in writes} == {"CFS"}


@pytest.mark.parametrize("fs_div", ["CFS", "OFS"])
def test_financial_request_selects_statement_scope(monkeypatch, fs_div):
    calls = []
    row = {"rcept_no": "20250515000001", "corp_code": "00126380",
           "reprt_code": "11013", "bsns_year": "2025", "sj_div": "BS"}

    def get(*args, **kwargs):
        calls.append(kwargs["params"])
        return response({"status": "000", "list": [row]})

    monkeypatch.setattr(dart.requests, "get", get)
    result = dart.fetch_financial_statements("00126380", 2025, reprt_code="11013", fs_div=fs_div)
    assert result.to_dict("records") == [row]
    assert calls[0]["fs_div"] == fs_div
