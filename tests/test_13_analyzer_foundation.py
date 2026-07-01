import ast
from datetime import date
from pathlib import Path

import pytest

from apps.worker.analyzer.config import load_config
from apps.worker.analyzer.models import AnalysisRunContext, MacroDirection, MacroResult
from apps.worker.analyzer.pipeline import build_request
from apps.worker.fa_contract import MACRO_SIGNALS
from storage.postgres.repositories.fa_analysis_repo import get_or_create_analysis_run
from storage.postgres.repositories.fa_analysis_repo import fail_stale_analysis_runs


ROOT = Path(__file__).resolve().parents[1]


class QueueDB:
    def __init__(self, fetch_rows):
        self.fetch_rows = list(fetch_rows)
        self.calls = []

    def fetch_one(self, query, params=None):
        self.calls.append(("fetch_one", query, params))
        return self.fetch_rows.pop(0)

    def execute(self, query, params=None):
        self.calls.append(("execute", query, params))
        return 1


def test_fa_schema_contains_all_phase4_ledgers_and_safety_constraints():
    sql = (ROOT / "storage/postgres/schema/06_fa_analysis_schema.sql").read_text(encoding="utf-8")
    for table in (
        "company_quarter_fa",
        "fa_analysis_runs",
        "fa_macro_results",
        "fa_sector_results",
        "fa_company_results",
    ):
        assert f"CREATE TABLE IF NOT EXISTS {table}" in sql
    assert "cutoff_date <= effective_date" in sql
    assert "WHERE status_code = 'PUBLISHED'" in sql
    assert "source_fa_company_result_id" in sql
    assert "cohort_quality_penalty" in sql


def test_analyzer_config_is_versioned_and_deterministic(monkeypatch):
    monkeypatch.setenv("STRATEGY_NAME", "risk_neutral")
    first = load_config()
    second = load_config()
    assert first.model_version == "topdown-fa-v1.0.0"
    assert first.fingerprint == second.fingerprint
    assert len(first.fingerprint) == 64


def test_build_request_normalizes_month_and_validates_publish_scope():
    request = build_request(
        target="all",
        analysis_month="2026-06",
        cutoff_date="2026-06-01",
        effective_date="2026-06-01",
        publish=True,
    )
    assert request.analysis_month == date(2026, 6, 1)
    assert request.cutoff_date == date(2026, 6, 1)
    with pytest.raises(ValueError, match="publish"):
        build_request(target="macro", analysis_month="2026-06", publish=True)


def test_build_request_defaults_to_today_for_cutoff_and_effective_date(monkeypatch):
    from apps.worker.analyzer import pipeline

    monkeypatch.setattr(pipeline, "_today_kst", lambda: date(2026, 6, 27))
    request = build_request(target="all")
    assert request.analysis_month == date(2026, 6, 1)
    assert request.cutoff_date == date(2026, 6, 27)
    assert request.effective_date == date(2026, 6, 27)

    cutoff_only = build_request(target="all", cutoff_date="2026-07-01")
    assert cutoff_only.analysis_month == date(2026, 7, 1)
    assert cutoff_only.cutoff_date == date(2026, 7, 1)
    assert cutoff_only.effective_date == date(2026, 7, 1)


def test_get_or_create_reuses_non_failed_identical_run():
    existing = {"id": 11, "run_version": 1, "status_code": "PASS"}
    db = QueueDB([existing])
    row, created = get_or_create_analysis_run(
        db,
        strategy_id=1,
        analysis_month=date(2026, 6, 1),
        cutoff_date=date(2026, 5, 31),
        effective_date=date(2026, 6, 1),
        model_version="v1",
        input_hash="a" * 64,
    )
    assert row == existing
    assert created is False
    assert len(db.calls) == 1


def test_get_or_create_assigns_next_version_and_running_status():
    inserted = {"id": 12, "run_version": 3, "status_code": "RUNNING"}
    db = QueueDB([None, {"next_version": 3}, inserted])
    row, created = get_or_create_analysis_run(
        db,
        strategy_id=1,
        analysis_month=date(2026, 6, 1),
        cutoff_date=date(2026, 5, 31),
        effective_date=date(2026, 6, 1),
        model_version="v1",
        input_hash="b" * 64,
    )
    assert created is True
    assert row["run_version"] == 3
    assert "'RUNNING'" in db.calls[-1][1]


def test_stale_running_run_is_failed_before_reuse():
    db = QueueDB([])
    fail_stale_analysis_runs(db, 1, date(2026, 6, 1))
    query = db.calls[0][1]
    assert "STALE_RUNNING_TIMEOUT" in query
    assert "created_at" in query
    assert "started_at" not in query
    assert "INTERVAL '1 hour'" in query


def test_prepare_run_stops_before_strategy_or_run_write_when_readiness_fails(monkeypatch):
    from apps.worker.analyzer import pipeline

    request = build_request(
        target="all",
        analysis_month="2026-06",
        cutoff_date="2026-05-31",
        effective_date="2026-06-01",
    )
    monkeypatch.setattr(
        pipeline,
        "validate_source_readiness",
        lambda db, cutoff: (_ for _ in ()).throw(RuntimeError("not ready")),
    )
    called = []
    monkeypatch.setattr(
        pipeline,
        "fetch_active_strategy",
        lambda *args: called.append("strategy"),
    )
    with pytest.raises(RuntimeError, match="not ready"):
        pipeline.prepare_run(object(), request, load_config("risk_neutral"))
    assert called == []


def test_macro_target_records_phase7_success(monkeypatch):
    from apps.worker.analyzer import pipeline

    context = AnalysisRunContext(
        run_id=7,
        target="macro",
        strategy_id=1,
        analysis_month=date(2026, 6, 1),
        cutoff_date=date(2026, 5, 31),
        effective_date=date(2026, 6, 1),
        input_hash="c" * 64,
        model_version="v1",
        created=True,
    )
    monkeypatch.setattr(pipeline, "prepare_run", lambda *args: context)
    monkeypatch.setattr(pipeline, "refresh_quarterly_scores", lambda *args: 10)
    monkeypatch.setattr(
        pipeline,
        "run_macro_analysis",
        lambda *args: [
            MacroResult(
                signal_name_code=signal.code,
                last_observation_date=date(2026, 5, 30),
                last_available_date=date(2026, 5, 31),
                direction_code=MacroDirection.UP,
                trend_raw=1.0,
                trend_strength=1.0,
                data_point_count=160,
                confidence=1.0,
                calculation_detail={},
            )
            for signal in MACRO_SIGNALS
        ],
    )
    updates = []
    monkeypatch.setattr(
        pipeline,
        "update_analysis_run_status",
        lambda *args, **kwargs: updates.append((args, kwargs)),
    )
    request = build_request(
        target="macro",
        analysis_month="2026-06",
        cutoff_date="2026-05-31",
        effective_date="2026-06-01",
    )
    pipeline.run(object(), request, load_config("risk_neutral"))
    assert updates[0][0][2] == "PASS"
    assert updates[0][1]["validation_summary"]["macro_result_count"] == len(MACRO_SIGNALS)


def test_analyzer_records_unexpected_job_failure(monkeypatch):
    from apps.worker.analyzer import pipeline

    context = AnalysisRunContext(
        run_id=8, target="macro", strategy_id=1,
        analysis_month=date(2026, 6, 1), cutoff_date=date(2026, 5, 31),
        effective_date=date(2026, 6, 1), input_hash="d" * 64,
        model_version="v1", created=True,
    )
    monkeypatch.setattr(pipeline, "prepare_run", lambda *args: context)
    monkeypatch.setattr(
        pipeline, "refresh_quarterly_scores",
        lambda *args: (_ for _ in ()).throw(ValueError("broken input")),
    )
    updates = []
    monkeypatch.setattr(
        pipeline, "update_analysis_run_status",
        lambda *args, **kwargs: updates.append((args, kwargs)),
    )
    request = build_request(
        target="macro", analysis_month="2026-06",
        cutoff_date="2026-05-31", effective_date="2026-06-01",
    )
    with pytest.raises(ValueError, match="broken input"):
        pipeline.run(object(), request, load_config("risk_neutral"))
    assert updates[0][0][2] == "FAIL"
    assert updates[0][1]["failure_reason"] == "ValueError:broken input"


def test_analyzer_does_not_import_external_clients_or_collector_jobs():
    analyzer_dir = ROOT / "apps/worker/analyzer"
    forbidden = ("requests", "yfinance", "data.collectors", "data.loaders")
    for path in analyzer_dir.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        imports = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.append(node.module)
        assert not [name for name in imports if name.startswith(forbidden)]
        assert not [
            name for name in imports
            if name.startswith("apps.worker.collector") and name != "apps.worker.collector.readiness"
        ]
