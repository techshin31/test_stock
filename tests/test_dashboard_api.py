import datetime as dt
import json

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
