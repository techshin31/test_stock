import datetime as dt
import json

import pandas as pd
import pytest

from core.analytics.trading_performance import (
    BASELINE_CONFIRMATION,
    _benchmark_anchor_freshness,
    _publish_latest_if_not_older,
    _refresh_canonical_paper_evidence,
    build_end_of_day_report,
    calculate_performance,
    check_baseline,
    initialize_baseline,
    load_account_snapshots,
    write_end_of_day_report,
)


def test_historical_backfill_never_regresses_canonical_latest(tmp_path):
    latest = tmp_path / "latest.json"
    latest.write_text(
        json.dumps({"report_date": "2026-07-22", "marker": "current"}),
        encoding="utf-8",
    )

    assert _publish_latest_if_not_older(
        latest, {"report_date": "2026-07-21", "marker": "backfill"}
    ) is False
    assert json.loads(latest.read_text(encoding="utf-8"))["marker"] == "current"

    assert _publish_latest_if_not_older(
        latest, {"report_date": "2026-07-23", "marker": "new"}
    ) is True
    assert json.loads(latest.read_text(encoding="utf-8"))["marker"] == "new"


def test_refresh_canonical_paper_evidence_uses_latest_directories(
    tmp_path, monkeypatch
):
    calls = {}

    def fake_write_outputs(summary, frames, output_dir):
        calls["ledger"] = output_dir

    def fake_write_report(report, output_dir):
        calls["parity"] = output_dir

    def fake_run_stress(db, *, ledger_path, ideal_metrics_path, output_dir):
        calls["stress"] = output_dir
        calls["stress_ledger"] = ledger_path
        calls["ideal"] = ideal_metrics_path
        return {"promotion_gate": {"ready": False}}

    monkeypatch.setattr(
        "core.analytics.paper_ledger_reconstruction.write_outputs",
        fake_write_outputs,
    )
    monkeypatch.setattr(
        "apps.backtester.paper_order_result_replay.write_report",
        fake_write_report,
    )
    monkeypatch.setattr(
        "apps.backtester.paper_execution_stress.run_stress_suite",
        fake_run_stress,
    )

    result = _refresh_canonical_paper_evidence(
        analysis_root=tmp_path,
        active_db=object(),
        ledger_quality={"ok": True},
        ledger_frames={"orders": pd.DataFrame()},
        parity_report={"ok": True},
    )

    assert result["status"] == "READY"
    assert result["execution_stress_ready"] is False
    assert calls["ledger"] == tmp_path / "paper_ledger_latest"
    assert calls["parity"] == tmp_path / "paper_order_result_replay" / "latest"
    assert calls["stress"] == tmp_path / "paper_execution_stress" / "latest"
    assert calls["stress_ledger"] == calls["ledger"] / "order_lifecycle.csv"


def _snapshot(timestamp, total_asset, *, account="1234****", mode="PAPER"):
    return {
        "timestamp": dt.datetime.fromisoformat(timestamp),
        "mode": mode,
        "strategy": "aggressive",
        "account_scope": account,
        "cash": 500.0,
        "total_asset": float(total_asset),
        "position_count": 1,
    }


def _write_jsonl(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(json.dumps(row, default=str) for row in rows) + "\n",
        encoding="utf-8",
    )


def _operational_row(timestamp, *, orders=None):
    return {
        "timestamp": timestamp,
        "operational_status": "NORMAL",
        "data_health": {
            "expected_count": 2,
            "fresh_count": 2,
            "stale_count": 0,
            "missing_count": 0,
            "risk_checks_total": 1,
            "risk_checks_completed": 1,
        },
        "actual_orders": orders or {},
    }


class FakeDB:
    def fetch_all(self, query, params):
        if "GROUP BY o.order_status_code" in query:
            return [{"order_status_code": "FILLED", "count": 1}]
        return [{
            "order_id": "order-1",
            "order_side_code": "BUY",
            "amount": 100_000.0,
            "commission": 0.0,
            "tax": 0.0,
            "slippage": 20.0,
            "executed_at": dt.datetime(2026, 7, 20, 9, 1),
        }]


def test_load_account_snapshots_rejects_legacy_unscoped_rows(tmp_path):
    path = tmp_path / "snapshots.jsonl"
    _write_jsonl(path, [{
        "timestamp": "2026-07-20T09:00:00+09:00",
        "mode": "PAPER",
        "strategy": "aggressive",
        "account_scope": "UNKNOWN",
        "cash": 1_000,
        "total_asset": 1_000,
    }])

    with pytest.raises(ValueError, match="unscoped"):
        load_account_snapshots(
            path, mode="PAPER", through_date=dt.date(2026, 7, 20)
        )


def test_calculate_performance_adjusts_declared_external_cash_flow():
    baseline = {
        "baseline_timestamp": "2026-07-20T08:30:00+09:00",
        "baseline_total_asset": 1_000.0,
        "benchmark_date": "2026-07-17",
        "benchmark_close": 100.0,
        "account_scope": "1234****",
        "strategy": "aggressive",
    }
    rows = [
        _snapshot("2026-07-20T15:20:00+09:00", 1_100),
        _snapshot("2026-07-21T15:20:00+09:00", 1_211),
    ]
    metrics, trend, errors = calculate_performance(
        rows,
        baseline=baseline,
        benchmark_closes={
            dt.date(2026, 7, 17): 100.0,
            dt.date(2026, 7, 20): 102.0,
            dt.date(2026, 7, 21): 105.0,
        },
        cash_flows=[{
            "date": dt.date(2026, 7, 21), "amount": 100.0, "reason": "deposit"
        }],
        total_costs=11.1,
    )

    assert errors == []
    assert metrics["net_return"] == pytest.approx(0.111)
    assert metrics["benchmark_return"] == pytest.approx(0.05)
    assert metrics["cost_drag"] == pytest.approx(0.0111)
    assert trend[1]["daily_return"] == pytest.approx(0.01)


def test_dry_run_report_is_operational_only_and_ready_after_one_day(tmp_path):
    log_dir = tmp_path / "logs" / "dry_run"
    _write_jsonl(
        log_dir / "operational_health.jsonl",
        [_operational_row("2026-07-20T15:20:00+09:00")],
    )

    report = build_end_of_day_report(
        mode="DRY_RUN",
        report_date=dt.date(2026, 7, 20),
        log_dir=log_dir,
        promotion_dir=tmp_path / "reports" / "promotion",
    )

    assert report["performance"]["validation_status"] == "NOT_APPLICABLE"
    assert report["promotion"]["target_mode"] == "PAPER"
    assert report["promotion"]["ready"] is True
    assert report["operations"]["observed_trading_days"] == 1


def test_paper_report_writes_flat_real_readiness_snapshot(tmp_path):
    report_date = dt.date(2026, 7, 20)
    log_dir = tmp_path / "logs" / "paper"
    promotion_dir = tmp_path / "reports" / "promotion"
    paper_dir = promotion_dir / "paper"
    _write_jsonl(
        log_dir / "operational_health.jsonl",
        [_operational_row("2026-07-20T15:20:00+09:00")],
    )
    _write_jsonl(log_dir / "account_snapshots.jsonl", [
        {
            **_snapshot("2026-07-20T08:30:00+09:00", 1_000),
            "timestamp": "2026-07-20T08:30:00+09:00",
        },
        {
            **_snapshot("2026-07-20T15:20:00+09:00", 1_020),
            "timestamp": "2026-07-20T15:20:00+09:00",
        },
    ])
    paper_dir.mkdir(parents=True)
    (paper_dir / "baseline.json").write_text(json.dumps({
        "baseline_timestamp": "2026-07-20T08:30:00+09:00",
        "baseline_total_asset": 1_000.0,
        "benchmark_date": "2026-07-17",
        "benchmark_close": 100.0,
        "mode": "PAPER",
        "strategy": "aggressive",
        "account_scope": "1234****",
    }), encoding="utf-8")
    (paper_dir / "cash_flows.json").write_text(json.dumps({
        "account_scope": "1234****", "entries": []
    }), encoding="utf-8")

    def benchmark_loader(start, end):
        return pd.Series(
            [100.0, 101.0],
            index=pd.to_datetime(["2026-07-17", "2026-07-20"]),
        )

    report = write_end_of_day_report(
        mode="PAPER",
        report_date=report_date,
        log_dir=log_dir,
        promotion_dir=promotion_dir,
        benchmark_loader=benchmark_loader,
        db=FakeDB(),
        as_of=dt.datetime(2026, 7, 20, 16, 0, tzinfo=dt.timezone(dt.timedelta(hours=9))),
    )
    readiness = json.loads(
        (promotion_dir / "real_readiness.json").read_text(encoding="utf-8")
    )

    assert report["validation"]["status"] == "READY"
    assert report["performance"]["net_return"] == pytest.approx(0.02)
    assert readiness["validation_status"] == "READY"
    assert readiness["net_return"] == pytest.approx(0.02)
    assert (paper_dir / "daily" / "2026-07-20.md").exists()


def test_paper_eod_failure_retries_when_readiness_audit_fails(
    tmp_path, monkeypatch
):
    report_date = dt.date(2026, 7, 20)
    promotion_dir = tmp_path / "reports" / "promotion"
    dashboard = tmp_path / "logs" / "paper" / "dashboard_state.json"
    dashboard.parent.mkdir(parents=True, exist_ok=True)
    dashboard.write_text("{}", encoding="utf-8")
    report = {
        "report_date": report_date.isoformat(),
        "generated_at": "2026-07-20T16:00:00+09:00",
        "report_status": "FINAL",
        "mode": "PAPER",
        "performance": {"validation_status": "READY"},
        "promotion": {"target_mode": "REAL", "ready": False},
        "validation": {"status": "READY", "checks": [], "errors": []},
        "operations": {},
        "trading": {},
        "ledger_quality": {},
        "shadow_reentry": {},
        "strategy_change_gate": {},
        "performance_trend": [],
        "sources": [],
    }
    monkeypatch.setattr(
        "core.analytics.trading_performance.build_end_of_day_report",
        lambda **kwargs: report,
    )
    monkeypatch.setattr(
        "core.analytics.system_readiness.audit_system_readiness",
        lambda project_root: (_ for _ in ()).throw(RuntimeError("audit boom")),
    )

    with pytest.raises(RuntimeError, match="system readiness audit failed"):
        write_end_of_day_report(
            mode="PAPER",
            report_date=report_date,
            log_dir=tmp_path / "logs" / "paper",
            promotion_dir=promotion_dir,
        )

    blocked = json.loads(
        (
            tmp_path
            / "reports"
            / "analysis"
            / "automated_trading_system_readiness.json"
        ).read_text(encoding="utf-8")
    )
    assert blocked["paper_runtime_safe"] is False
    assert "audit boom" in blocked["blockers"][0]
    assert (promotion_dir / "paper" / "daily" / "2026-07-20.json").exists()


def test_paper_eod_failure_retries_when_system_report_refresh_fails(
    tmp_path, monkeypatch
):
    report_date = dt.date(2026, 7, 20)
    promotion_dir = tmp_path / "reports" / "promotion"
    dashboard = tmp_path / "logs" / "paper" / "dashboard_state.json"
    dashboard.parent.mkdir(parents=True, exist_ok=True)
    dashboard.write_text("{}", encoding="utf-8")
    report = {
        "report_date": report_date.isoformat(),
        "generated_at": "2026-07-20T16:00:00+09:00",
        "report_status": "FINAL",
        "mode": "PAPER",
        "performance": {"validation_status": "READY"},
        "promotion": {"target_mode": "REAL", "ready": False},
        "validation": {"status": "READY", "checks": [], "errors": []},
        "operations": {},
        "trading": {},
        "ledger_quality": {},
        "shadow_reentry": {},
        "strategy_change_gate": {},
        "performance_trend": [],
        "sources": [],
    }
    monkeypatch.setattr(
        "core.analytics.trading_performance.build_end_of_day_report",
        lambda **kwargs: report,
    )
    monkeypatch.setattr(
        "core.analytics.system_readiness.audit_system_readiness",
        lambda project_root: {
            "paper_runtime_safe": True,
            "full_system_complete": False,
        },
    )
    analysis_root = tmp_path / "reports" / "analysis"
    builder = analysis_root / "build_paper_ledger_reentry_artifact.py"
    builder.parent.mkdir(parents=True, exist_ok=True)
    builder.write_text("raise SystemExit(3)\n", encoding="utf-8")
    for path in (
        analysis_root / "paper_ledger_latest" / "summary.json",
        analysis_root / "paper_order_result_replay" / "latest" / "summary.json",
        analysis_root / "paper_execution_stress" / "latest" / "summary.json",
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}", encoding="utf-8")

    with pytest.raises(
        RuntimeError, match="PAPER system report artifact refresh failed"
    ):
        write_end_of_day_report(
            mode="PAPER",
            report_date=report_date,
            log_dir=tmp_path / "logs" / "paper",
            promotion_dir=promotion_dir,
        )

    assert (promotion_dir / "paper" / "daily" / "2026-07-20.json").exists()


def test_initialize_baseline_requires_same_day_scoped_snapshot(tmp_path):
    report_date = dt.date(2026, 7, 20)
    log_dir = tmp_path / "logs" / "paper"
    promotion_dir = tmp_path / "reports" / "promotion"
    _write_jsonl(log_dir / "account_snapshots.jsonl", [{
        **_snapshot("2026-07-20T08:30:00+09:00", 1_000),
        "timestamp": "2026-07-20T08:30:00+09:00",
    }])

    def benchmark_loader(start, end):
        return pd.Series(
            [2_900.0], index=pd.to_datetime(["2026-07-16"])
        )

    baseline = initialize_baseline(
        mode="PAPER",
        report_date=report_date,
        log_dir=log_dir,
        promotion_dir=promotion_dir,
        confirmation=BASELINE_CONFIRMATION,
        benchmark_loader=benchmark_loader,
    )

    assert baseline["account_scope"] == "1234****"
    assert baseline["benchmark_date"] == "2026-07-16"
    with pytest.raises(FileExistsError):
        initialize_baseline(
            mode="PAPER",
            report_date=report_date,
            log_dir=log_dir,
            promotion_dir=promotion_dir,
            confirmation=BASELINE_CONFIRMATION,
            benchmark_loader=benchmark_loader,
        )


def test_initialize_baseline_after_close_uses_same_day_benchmark(tmp_path):
    report_date = dt.date(2026, 7, 20)
    log_dir = tmp_path / "logs" / "paper"
    promotion_dir = tmp_path / "reports" / "promotion"
    _write_jsonl(log_dir / "account_snapshots.jsonl", [{
        **_snapshot("2026-07-20T16:00:00+09:00", 1_000),
        "timestamp": "2026-07-20T16:00:00+09:00",
    }])

    def benchmark_loader(start, end):
        return pd.Series(
            [2_900.0, 3_000.0],
            index=pd.to_datetime(["2026-07-16", "2026-07-20"]),
        )

    baseline = initialize_baseline(
        mode="PAPER",
        report_date=report_date,
        log_dir=log_dir,
        promotion_dir=promotion_dir,
        confirmation=BASELINE_CONFIRMATION,
        benchmark_loader=benchmark_loader,
    )

    assert baseline["benchmark_date"] == "2026-07-20"
    assert baseline["benchmark_close"] == 3_000.0
    assert baseline["benchmark_anchor_policy"] == (
        "LATEST_CLOSED_SESSION_AT_SNAPSHOT"
    )


def test_after_close_stale_benchmark_anchor_is_rejected():
    fresh, detail = _benchmark_anchor_freshness(
        {
            "baseline_timestamp": "2026-07-20T17:46:10+09:00",
            "benchmark_date": "2026-07-16",
        },
        {
            dt.date(2026, 7, 16): 2_900.0,
            dt.date(2026, 7, 20): 3_000.0,
        },
    )

    assert fresh is False
    assert "expected=2026-07-20" in detail

def test_baseline_check_rejects_current_account_mismatch(tmp_path):
    report_date = dt.date(2026, 7, 20)
    promotion_dir = tmp_path / "reports" / "promotion"
    paper_dir = promotion_dir / "paper"
    paper_dir.mkdir(parents=True)
    (paper_dir / "baseline.json").write_text(json.dumps({
        "mode": "PAPER",
        "account_scope": "BASE****",
        "strategy": "aggressive",
        "baseline_timestamp": "2026-07-20T08:30:00+09:00",
        "baseline_total_asset": 1_000,
        "benchmark_date": "2026-07-16",
        "benchmark_close": 2_900,
    }), encoding="utf-8")
    (paper_dir / "cash_flows.json").write_text(json.dumps({
        "account_scope": "BASE****", "entries": []
    }), encoding="utf-8")
    log_dir = tmp_path / "logs" / "paper"
    _write_jsonl(log_dir / "account_snapshots.jsonl", [{
        **_snapshot("2026-07-20T09:00:00+09:00", 1_000, account="OTHER****"),
        "timestamp": "2026-07-20T09:00:00+09:00",
    }])

    with pytest.raises(ValueError, match="does not match"):
        check_baseline(
            "PAPER",
            promotion_dir,
            log_dir=log_dir,
            through_date=report_date,
            require_latest_snapshot=True,
        )


def test_paper_eod_blocked_report_raises_runtime_error_and_saves_daily(
    tmp_path, monkeypatch
):
    report_date = dt.date(2026, 7, 20)
    promotion_dir = tmp_path / "reports" / "promotion"
    report = {
        "report_date": report_date.isoformat(),
        "generated_at": "2026-07-20T16:00:00+09:00",
        "report_status": "FINAL",
        "mode": "PAPER",
        "executive_summary": "Blocked summary",
        "performance": {"validation_status": "BLOCKED"},
        "promotion": {"target_mode": "REAL", "ready": False, "blockers": ["baseline missing"]},
        "validation": {"status": "BLOCKED", "checks": [], "errors": ["baseline missing"]},
        "operations": {},
        "trading": {},
        "ledger_quality": {},
        "shadow_reentry": {},
        "strategy_change_gate": {},
        "performance_trend": [],
        "sources": [],
        "caveats": [],
    }
    monkeypatch.setattr(
        "core.analytics.trading_performance.build_end_of_day_report",
        lambda **kwargs: report,
    )

    with pytest.raises(RuntimeError, match="EOD report is not FINAL/READY"):
        write_end_of_day_report(
            mode="PAPER",
            report_date=report_date,
            log_dir=tmp_path / "logs" / "paper",
            promotion_dir=promotion_dir,
        )

    daily_json = promotion_dir / "paper" / "daily" / "2026-07-20.json"
    daily_md = promotion_dir / "paper" / "daily" / "2026-07-20.md"
    latest_json = promotion_dir / "paper" / "latest.json"

    assert daily_json.exists()
    assert daily_md.exists()
    assert not latest_json.exists()


def test_main_cli_returns_exit_code_2_on_blocked_eod(tmp_path, monkeypatch):
    from core.analytics.trading_performance import main

    def fake_write_eod(**kwargs):
        raise RuntimeError("EOD report is not FINAL/READY: test failure")

    monkeypatch.setattr(
        "core.analytics.trading_performance.write_end_of_day_report",
        fake_write_eod,
    )

    exit_code = main([
        "--mode", "PAPER",
        "--date", "2026-07-20",
        "--log-dir", str(tmp_path / "logs" / "paper"),
        "--promotion-dir", str(tmp_path / "reports" / "promotion"),
    ])

    assert exit_code == 2


def test_historical_backfill_integration_preserves_latest_and_readiness(
    tmp_path, monkeypatch
):
    report_date_21 = dt.date(2026, 7, 21)
    promotion_dir = tmp_path / "reports" / "promotion"
    paper_dir = promotion_dir / "paper"
    paper_dir.mkdir(parents=True)

    # Seed latest.json (2026-07-22 READY)
    latest_payload = {
        "report_date": "2026-07-22",
        "generated_at": "2026-07-22T16:00:00+09:00",
        "report_status": "FINAL",
        "mode": "PAPER",
        "performance": {"net_return": 0.05, "validation_status": "READY"},
        "promotion": {"target_mode": "REAL", "ready": True},
        "validation": {"status": "READY", "checks": [], "errors": []},
    }
    (paper_dir / "latest.json").write_text(
        json.dumps(latest_payload), encoding="utf-8"
    )

    # Seed real_readiness.json (2026-07-22)
    readiness_payload = {
        "as_of": "2026-07-22",
        "net_return": 0.05,
        "mode": "PAPER",
    }
    (promotion_dir / "real_readiness.json").write_text(
        json.dumps(readiness_payload), encoding="utf-8"
    )

    backfill_report = {
        "report_date": "2026-07-21",
        "generated_at": "2026-07-21T16:00:00+09:00",
        "report_status": "FINAL",
        "mode": "PAPER",
        "performance": {"net_return": 0.03, "validation_status": "READY"},
        "promotion": {"target_mode": "REAL", "ready": True},
        "validation": {"status": "READY", "checks": [], "errors": []},
    }
    monkeypatch.setattr(
        "core.analytics.trading_performance.build_end_of_day_report",
        lambda **kwargs: backfill_report,
    )

    write_end_of_day_report(
        mode="PAPER",
        report_date=report_date_21,
        log_dir=tmp_path / "logs" / "paper",
        promotion_dir=promotion_dir,
    )

    assert (paper_dir / "daily" / "2026-07-21.json").exists()
    latest_after = json.loads(
        (paper_dir / "latest.json").read_text(encoding="utf-8")
    )
    assert latest_after["report_date"] == "2026-07-22"
    readiness_after = json.loads(
        (promotion_dir / "real_readiness.json").read_text(encoding="utf-8")
    )
    assert readiness_after["as_of"] == "2026-07-22"
