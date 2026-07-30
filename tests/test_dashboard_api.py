import datetime as dt
import json
import sys
from types import SimpleNamespace

import pandas as pd
import pytest
from fastapi import HTTPException

from api import main as dashboard_api


def _write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _seed(tmp_path, report_date="2026-07-21"):
    log_root = tmp_path / "logs"
    report_root = tmp_path / "reports" / "promotion"
    _write_json(
        log_root / "paper" / "dashboard_state.json",
        {
            "execution_mode": "PAPER",
            "positions": ["005930.KS"],
            "updated_at": "2026-07-22 09:00:00",
        },
    )
    (log_root / "paper" / "operational_health.jsonl").write_text(
        json.dumps({"timestamp": "2026-07-22T09:00:00+09:00"}) + "\n",
        encoding="utf-8",
    )
    payload = {
        "report_date": report_date,
        "generated_at": f"{report_date}T15:30:05+09:00",
        "report_status": "FINAL",
        "mode": "PAPER",
        "executive_summary": "정상",
        "performance": {"net_return": 0.01},
        "operations": {"scan_count": 12},
        "validation": {"status": "READY"},
        "promotion": {"target_mode": "REAL", "ready": False, "blockers": ["sample"]},
    }
    _write_json(report_root / "paper" / "latest.json", payload)
    _write_json(report_root / "paper" / "daily" / f"{report_date}.json", payload)
    markdown = report_root / "paper" / "daily" / f"{report_date}.md"
    markdown.write_text("# 공식 보고서", encoding="utf-8")
    analysis_root = tmp_path / "reports" / "analysis"
    _write_json(
        analysis_root / "automated_trading_system_readiness.json",
        {
            "generated_at": "2026-07-22T13:30:33+09:00",
            "paper_runtime_safe": True,
            "full_system_complete": False,
            "real_execution_authorized": False,
            "progress": {
                "execution_samples": {"buy": 5, "sell": 4, "required_per_side": 30},
                "shadow_sessions": {"completed": 1, "required": 10},
                "paper_sessions": {"completed": 1, "required": 60},
                "final_daily_reports": {"completed": 1, "required": 60},
                "evidence_checks": {"passed": 8, "total": 12},
            },
            "blockers": ["execution_stress_robustness: sample_ready=False"],
        },
    )
    return log_root, report_root, analysis_root


def test_overview_uses_mode_scoped_official_report(monkeypatch, tmp_path):
    log_root, report_root, analysis_root = _seed(tmp_path)
    monkeypatch.setattr(dashboard_api, "LOG_ROOT", log_root)
    monkeypatch.setattr(dashboard_api, "REPORT_ROOT", report_root)
    monkeypatch.setattr(dashboard_api, "ANALYSIS_ROOT", analysis_root)
    monkeypatch.setattr(
        dashboard_api, "_load_stock_names", lambda: {"005930": "삼성전자"}
    )

    body = dashboard_api.get_overview(mode="PAPER")

    assert body["mode"] == "PAPER"
    assert body["dashboard"]["positions"][0]["avg_price"] == 0.0
    assert body["dashboard"]["positions"][0]["name"] == "삼성전자"
    assert body["latest_report"]["date"] == "2026-07-21"
    assert body["system_readiness"]["progress"]["paper_sessions"]["completed"] == 1


def test_overview_exposes_the_paper_inverse_hedge_snapshot(monkeypatch, tmp_path):
    log_root, report_root, analysis_root = _seed(tmp_path)
    dashboard_path = log_root / "paper" / "dashboard_state.json"
    dashboard = json.loads(dashboard_path.read_text(encoding="utf-8"))
    dashboard["inverse_hedge"] = {
        "ticker": "114800.KS",
        "status": "WAIT_CONFIRMATION",
        "target_weight": 0.0,
        "confirmed_downtrend_sessions": 1,
        "required_confirmations": 2,
    }
    _write_json(dashboard_path, dashboard)
    monkeypatch.setattr(dashboard_api, "LOG_ROOT", log_root)
    monkeypatch.setattr(dashboard_api, "REPORT_ROOT", report_root)
    monkeypatch.setattr(dashboard_api, "ANALYSIS_ROOT", analysis_root)

    body = dashboard_api.get_overview(mode="PAPER")

    assert body["dashboard"]["inverse_hedge"] == dashboard["inverse_hedge"]


def test_service_healthz_requires_a_successful_database_round_trip(monkeypatch):
    class Cursor:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def execute(self, query):
            assert query == "SELECT 1 AS ok"

        def fetchone(self):
            return {"ok": 1}

    class Connection:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def cursor(self):
            return Cursor()

    monkeypatch.setattr(dashboard_api, "_db_connect", lambda: Connection())

    assert dashboard_api.get_service_health() == {
        "status": "ok",
        "database": "ready",
    }


def test_service_healthz_returns_503_when_database_is_unavailable(monkeypatch):
    monkeypatch.setattr(dashboard_api, "_db_connect", lambda: None)

    with pytest.raises(HTTPException) as exc_info:
        dashboard_api.get_service_health()

    assert exc_info.value.status_code == 503


def test_report_list_and_content_share_the_same_daily_artifact(monkeypatch, tmp_path):
    log_root, report_root, _ = _seed(tmp_path)
    monkeypatch.setattr(dashboard_api, "LOG_ROOT", log_root)
    monkeypatch.setattr(dashboard_api, "REPORT_ROOT", report_root)
    listing = dashboard_api.list_reports(mode="PAPER")
    detail = dashboard_api.get_report("2026-07-21", mode="PAPER")

    assert listing[0]["report_status"] == "FINAL"
    assert listing[0]["blocker_count"] == 1
    assert detail["content"] == "# 공식 보고서"


def test_report_path_rejects_traversal(monkeypatch, tmp_path):
    log_root, report_root, _ = _seed(tmp_path)
    monkeypatch.setattr(dashboard_api, "LOG_ROOT", log_root)
    monkeypatch.setattr(dashboard_api, "REPORT_ROOT", report_root)

    with pytest.raises(HTTPException) as exc_info:
        dashboard_api.get_report("not-a-date", mode="PAPER")

    assert exc_info.value.status_code == 400


def test_report_freshness_allows_generation_grace_period():
    now = dt.datetime(2026, 7, 22, 15, 35, tzinfo=dashboard_api.SEOUL)
    latest = {"report_date": "2026-07-21"}

    result = dashboard_api._report_freshness("PAPER", now, latest)

    assert result["state"] == "GENERATING"
    assert result["expected_report_date"] == "2026-07-22"


def test_report_freshness_surfaces_redacted_eod_failure():
    now = dt.datetime(2026, 7, 22, 15, 35, tzinfo=dashboard_api.SEOUL)
    latest = {"report_date": "2026-07-21"}
    status = {
        "report_date": "2026-07-22",
        "status": "FAILED",
        "stderr_tail": "trace\nbenchmark download failed",
    }

    result = dashboard_api._report_freshness("PAPER", now, latest, status)

    assert result["state"] == "FAILED"
    assert "benchmark download failed" in result["message"]


def test_runtime_api_payload_redacts_broker_transport_details():
    payload = {
        "last_error": (
            "500 Server Error for url: "
            "https://openapivts.koreainvestment.com/order?"
            "CANO=12345678&appkey=secret-value"
        ),
        "data_health": {
            "dependency_errors": [
                "request timed out at https://openapivts.koreainvestment.com/order"
            ],
        },
    }

    result = dashboard_api._sanitize_runtime_errors(payload)

    assert result["last_error"] == "BROKER_HTTP_500"
    assert result["data_health"]["dependency_errors"] == ["BROKER_TIMEOUT"]
    assert "openapivts" not in json.dumps(result).lower()
    assert "12345678" not in json.dumps(result)
    assert "secret-value" not in json.dumps(result)


def test_report_freshness_requires_final_and_ready_for_current():
    now = dt.datetime(2026, 7, 22, 16, 0, tzinfo=dashboard_api.SEOUL)
    latest_ready = {
        "report_date": "2026-07-22",
        "report_status": "FINAL",
        "validation": {"status": "READY"},
    }

    result = dashboard_api._report_freshness("PAPER", now, latest_ready)

    assert result["state"] == "CURRENT"


def test_report_freshness_does_not_hide_failed_automation_behind_current_file():
    now = dt.datetime(2026, 7, 22, 16, 0, tzinfo=dashboard_api.SEOUL)
    latest_ready = {
        "report_date": "2026-07-22",
        "report_status": "FINAL",
        "validation": {"status": "READY"},
    }
    failed_status = {
        "report_date": "2026-07-22",
        "status": "FAILED",
        "stdout_tail": "container EOD failed",
    }

    result = dashboard_api._report_freshness(
        "PAPER", now, latest_ready, failed_status
    )

    assert result["state"] == "FAILED"
    assert "container EOD failed" in result["message"]


def test_report_summary_separates_inception_and_certified_baseline_returns():
    result = dashboard_api._report_summary(
        {
            "report_date": "2026-07-22",
            "performance": {
                "starting_capital_reference": 500_000_000,
                "pnl_vs_starting_capital": -33_600_954,
                "return_vs_starting_capital": -0.067201908,
                "baseline_date": "2026-07-20",
                "post_baseline_pnl": 3_373_456,
                "net_return": 0.007285679,
            },
        }
    )

    performance = result["performance"]
    assert performance["return_vs_starting_capital"] == -0.067201908
    assert performance["net_return"] == 0.007285679
    assert performance["baseline_date"] == "2026-07-20"


def test_report_freshness_surfaces_blocked_latest_as_failed():
    now = dt.datetime(2026, 7, 22, 16, 0, tzinfo=dashboard_api.SEOUL)
    latest_blocked = {
        "report_date": "2026-07-22",
        "report_status": "FINAL",
        "validation": {"status": "BLOCKED", "errors": ["baseline missing"]},
    }

    result = dashboard_api._report_freshness("PAPER", now, latest_blocked)

    assert result["state"] == "FAILED"
    assert "BLOCKED" in result["message"]
    assert "baseline missing" in result["message"]


def test_system_readiness_endpoint_is_read_only_and_mode_scoped(
    monkeypatch, tmp_path
):
    _, _, analysis_root = _seed(tmp_path)
    monkeypatch.setattr(dashboard_api, "ANALYSIS_ROOT", analysis_root)

    payload = dashboard_api.get_system_readiness(mode="PAPER")

    assert payload["paper_runtime_safe"] is True
    assert payload["full_system_complete"] is False
    with pytest.raises(HTTPException) as exc_info:
        dashboard_api.get_system_readiness(mode="REAL")
    assert exc_info.value.status_code == 404


def test_market_breadth_does_not_turn_missing_values_into_zeroes(monkeypatch, tmp_path):
    log_root, _, _ = _seed(tmp_path)
    monkeypatch.setattr(dashboard_api, "LOG_ROOT", log_root)

    payload = dashboard_api.get_market_breadth()

    assert payload["available"] is False
    assert payload["total"] is None


def test_market_breadth_uses_and_labels_the_actual_paper_universe(monkeypatch, tmp_path):
    log_root, _, _ = _seed(tmp_path)
    tickers = [f"{index:06d}.KS" for index in range(10)]
    (log_root / "paper" / "decision_history.jsonl").write_text(
        json.dumps(
            {
                "updated_at": "2026-07-28T15:20:00",
                "market_regime": "UPTREND",
                "decisions": [{"ticker": ticker} for ticker in tickers],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    index = pd.to_datetime(["2026-07-27", "2026-07-28"])
    quotes = pd.DataFrame(
        {
            (ticker, "Close"): [100.0, 101.0 if position < 5 else 99.0]
            for position, ticker in enumerate(tickers)
        }
        | {(ticker, "Volume"): [1000, 2000] for ticker in tickers},
        index=index,
    )
    quotes.columns = pd.MultiIndex.from_tuples(quotes.columns)
    monkeypatch.setattr(dashboard_api, "LOG_ROOT", log_root)
    monkeypatch.setattr(
        dashboard_api,
        "_BREADTH_CACHE",
        {"timestamp": 0, "payload": None},
    )
    download_kwargs = {}
    monkeypatch.setitem(
        sys.modules,
        "yfinance",
        SimpleNamespace(download=lambda **kwargs: download_kwargs.update(kwargs) or quotes),
    )

    payload = dashboard_api.get_market_breadth()

    assert payload["available"] is True
    assert payload["source"] == "YFINANCE_PAPER_UNIVERSE"
    assert payload["advancing"] == 5
    assert payload["declining"] == 5
    assert payload["coverage"] == 10
    assert payload["universe_size"] == 10
    assert download_kwargs["threads"] is True
    assert download_kwargs["timeout"] == dashboard_api._BREADTH_YFINANCE_TIMEOUT_SECONDS


def test_sector_payload_reads_wics_names_from_the_current_codes_schema(monkeypatch):
    latest = dt.date(2026, 7, 28)
    previous = dt.date(2026, 7, 27)

    class Cursor:
        def __init__(self):
            self.queries = []
            self.step = 0

        def execute(self, query, _params=None):
            self.queries.append(query)
            self.step += 1

        def fetchall(self):
            responses = {
                1: [{"price_date": latest}, {"price_date": previous}],
                2: [{"code": "G4530", "name": "반도체와반도체장비"}],
                3: [
                    {"industry_code": "G4530", "price_date": previous, "index_value": 1000.0},
                    {"industry_code": "G4530", "price_date": latest, "index_value": 1025.0},
                ],
                5: [{"industry_code": "G4530", "volume": 100, "market_cap": 200, "stock_count": 3}],
                6: [{"industry_code": "G4530", "company_name": "테스트", "stock_code": "005930"}],
            }
            return responses[self.step]

        def fetchone(self):
            assert self.step == 4
            return {"base_date": latest}

    monkeypatch.setattr(dashboard_api, "_expected_completed_sector_date", lambda: latest)
    cursor = Cursor()

    payload = dashboard_api._sector_payload_from_prices(
        cursor,
        source_code="DERIVED",
        method_version="mcap-v1",
        source_label="WICS_DERIVED_MCAP_V1",
    )

    assert "code_group = 'WICS_INDUSTRY_CODE'" in cursor.queries[1]
    assert payload["source"] == "WICS_DERIVED_MCAP_V1"
    assert payload["as_of_date"] == latest.isoformat()
    assert payload["expected_as_of_date"] == latest.isoformat()
    assert payload["summary"] == {
        "positive_count": 1,
        "negative_count": 0,
        "unchanged_count": 0,
        "total_count": 1,
    }
    assert payload["top_positive"] == payload["items"]
    assert payload["bottom_negative"] == []
    assert payload["items"] == [{
        "code": "G4530",
        "name": "반도체와반도체장비",
        "change_rate": 2.5,
        "index_value": 1025.0,
        "prev_value": 1000.0,
        "volume": 100,
        "market_cap": 200,
        "stock_count": 3,
        "top_stock": "테스트",
    }]


@pytest.mark.parametrize(
    ("snapshot_date", "expected_status"),
    [
        ("2026-07-29", "REFRESH_PENDING"),
        ("2026-07-30", "READY"),
    ],
)
def test_sector_refresh_monitor_checks_the_post_1540_date_contract(
    monkeypatch, tmp_path, snapshot_date, expected_status
):
    log_root = tmp_path / "logs"
    _write_json(
        log_root / "paper" / "wics_sector_refresh_status.json",
        {
            "updated_at": "2026-07-30T15:45:00+09:00",
            "status": "READY",
            "target_date": snapshot_date,
            "latest_date": snapshot_date,
            "industry_count": 25,
        },
    )
    monkeypatch.setattr(dashboard_api, "LOG_ROOT", log_root)

    result = dashboard_api._sector_refresh_monitor(
        dt.datetime(2026, 7, 30, 15, 45, tzinfo=dashboard_api.SEOUL)
    )

    assert result["status"] == expected_status
    assert result["expected_as_of_date"] == "2026-07-30"
    assert result["latest_date"] == snapshot_date


def test_unavailable_sector_payload_exposes_refresh_pending_state(monkeypatch):
    monkeypatch.setattr(dashboard_api, "_db_connect", lambda: None)
    monkeypatch.setattr(
        dashboard_api,
        "_sector_refresh_monitor",
        lambda: {
            "status": "REFRESH_PENDING",
            "expected_as_of_date": "2026-07-30",
            "target_date": "2026-07-29",
            "latest_date": "2026-07-29",
            "industry_count": 25,
            "worker_status": "READY",
            "worker_updated_at": "2026-07-30T15:39:00+09:00",
        },
    )

    payload = dashboard_api.get_sectors()

    assert payload["available"] is False
    assert payload["observation_status"] == "REFRESH_PENDING"
    assert payload["as_of_date"] == "2026-07-29"
    assert payload["expected_as_of_date"] == "2026-07-30"


def test_finite_float_rejects_database_nan_values():
    assert dashboard_api._finite_float(float("nan")) is None


def test_index_history_contains_only_overlapping_observed_closes():
    index = pd.to_datetime(["2026-07-24", "2026-07-25", "2026-07-28"])
    kospi = pd.DataFrame({"Close": [3200.0, 3210.0, 3220.0]}, index=index)
    kosdaq = pd.DataFrame({"Close": [800.0, 805.0]}, index=index[1:])

    history = dashboard_api._index_history_points(kospi, kosdaq)

    assert history == [
        {"date": "2026-07-25", "KOSPI": 3210.0, "KOSDAQ": 800.0},
        {"date": "2026-07-28", "KOSPI": 3220.0, "KOSDAQ": 805.0},
    ]


def test_market_trend_helpers_preserve_observed_closes_and_require_full_window():
    dates = pd.date_range("2026-06-01", periods=21, freq="B")
    closes = [100.0 + (3.0 if index % 2 else 0.0) for index in range(21)]
    frame = pd.DataFrame({"Close": closes}, index=dates)

    history = dashboard_api._close_history_points(frame, limit=3)

    assert history == [
        {"date": dates[-3].strftime("%Y-%m-%d"), "close": closes[-3]},
        {"date": dates[-2].strftime("%Y-%m-%d"), "close": closes[-2]},
        {"date": dates[-1].strftime("%Y-%m-%d"), "close": closes[-1]},
    ]
    assert dashboard_api._annualized_realized_volatility(frame) > 0
    assert dashboard_api._annualized_realized_volatility(frame.iloc[:20]) is None


def test_intraday_market_bar_is_excluded_from_close_based_series(monkeypatch):
    now = dt.datetime(2026, 7, 30, 11, 0, tzinfo=dashboard_api.SEOUL)
    dates = pd.to_datetime(["2026-07-28", "2026-07-29", "2026-07-30"])
    frame = pd.DataFrame({"Close": [100.0, 101.0, 106.0]}, index=dates)

    monkeypatch.setattr(dashboard_api, "is_krx_trading_day", lambda _date: True)
    monkeypatch.setattr(
        dashboard_api,
        "_expected_completed_krx_date",
        lambda _now=None: dt.date(2026, 7, 29),
    )

    assert dashboard_api._market_observation_status(dt.date(2026, 7, 30), now) == "INTRADAY"
    completed = dashboard_api._completed_market_frame(frame, now)
    assert dashboard_api._close_history_points(completed) == [
        {"date": "2026-07-28", "close": 100.0},
        {"date": "2026-07-29", "close": 101.0},
    ]


def test_market_regime_falls_back_to_latest_paper_decision_without_defaults(
    monkeypatch, tmp_path
):
    log_root, _, analysis_root = _seed(tmp_path)
    (log_root / "paper" / "decision_history.jsonl").write_text(
        json.dumps(
            {
                "updated_at": "2026-07-28T15:20:00",
                "market_regime": "DOWNTREND",
                "decisions": [],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(dashboard_api, "LOG_ROOT", log_root)
    monkeypatch.setattr(dashboard_api, "ANALYSIS_ROOT", analysis_root)

    payload = dashboard_api.get_market_regime()

    assert payload["available"] is True
    assert payload["source"] == "PAPER_DECISION_HISTORY"
    assert payload["current"] == "DOWNTREND"
    assert payload["confidence"] is None
    assert payload["signal"] is None


def test_journal_reads_the_mode_scoped_certified_report(monkeypatch, tmp_path):
    _, report_root, _ = _seed(tmp_path)
    payload = {
        "report_date": "2026-07-21",
        "report_status": "FINAL",
        "mode": "PAPER",
        "performance": {
            "starting_capital_reference": 500_000_000,
            "ending_total_asset": 510_000_000,
            "pnl_vs_starting_capital": 10_000_000,
        },
        "performance_trend": [
            {
                "date": "2026-07-20",
                "total_asset": 500_000_000,
                "cumulative_return": 0.0,
                "benchmark_return": 0.0,
            },
            {
                "date": "2026-07-21",
                "total_asset": 510_000_000,
                "cumulative_return": 0.02,
                "benchmark_return": 0.01,
            },
        ],
    }
    _write_json(report_root / "paper" / "latest.json", payload)
    monkeypatch.setattr(dashboard_api, "REPORT_ROOT", report_root)
    monkeypatch.setattr(dashboard_api, "_db_connect", lambda: None)

    journal = dashboard_api.get_journal(mode="PAPER")

    assert journal["available"] is True
    assert journal["source"] == "CERTIFIED_EOD_REPORT"
    assert journal["summary"]["observed_sessions"] == 2
    assert journal["benchmark_history"][-1]["benchmark_return"] == 1.0
