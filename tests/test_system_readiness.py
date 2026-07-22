import datetime as dt
import json
import os

from core.analytics.system_readiness import KST, audit_system_readiness

_ACTIVE_FIXTURE_LOCKS = {}


def _write(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _append_jsonl(path, payloads):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(json.dumps(payload) for payload in payloads) + "\n",
        encoding="utf-8",
    )


def _fixture(tmp_path, *, complete=False):
    session_count = 60 if complete else 1
    session_dates = [
        dt.date(2026, 7, 21) - dt.timedelta(days=offset)
        for offset in reversed(range(session_count))
    ]
    _write(
        tmp_path / "logs/paper/dashboard_state.json",
        {
            "updated_at": "2026-07-22T10:00:00+09:00",
            "execution_mode": "PAPER",
            "account_scope": "***1234-01",
            "last_error": None,
            "daily_orders": {"open": 0},
            "actual_orders": {"open": 0},
            "data_health": {
                "expected_count": 2,
                "fresh_count": 2,
                "stale_tickers": [],
                "missing_tickers": [],
                "dependency_errors": [],
                "held_stale_tickers": [],
                "risk_checks_total": 2,
                "risk_checks_completed": 2,
                "risk_check_coverage": 1.0,
                "entry_circuit_breaker": None,
                "execution_ledger": {
                    "status": "READY",
                    "execution_link_coverage": 1.0,
                    "quantity_match_rate": 1.0,
                }
            },
        },
    )
    _write(
        tmp_path / "logs/paper/shadow_reentry_state.json",
        {
            "observe_only": True,
            "order_permission": "DENIED_BY_DESIGN",
            "completed_observation_sessions": 10 if complete else 1,
            "required_observation_sessions": 10,
            "observed_sessions": [
                item.isoformat()
                for item in session_dates[-(10 if complete else 1):]
            ],
        },
    )
    from core.utils.process_lock import ProcessInstanceLock

    lock1 = ProcessInstanceLock(
        tmp_path / "logs/scheduler.instance.lock", "PAPER", label="scheduler"
    ).acquire()
    lock2 = ProcessInstanceLock(
        tmp_path / "logs/scheduler.supervisor.instance.lock",
        "PAPER",
        label="scheduler-supervisor",
    ).acquire()
    _ACTIVE_FIXTURE_LOCKS[str(tmp_path)] = (lock1, lock2)

    _append_jsonl(
        tmp_path / "logs/paper/scheduler_supervisor.jsonl",
        [
            {
                "mode": "PAPER",
                "event": "ATTACHED_TO_EXISTING",
                "detail": f"pid={os.getpid()}, poll_seconds=5",
            }
        ],
    )
    _write(
        tmp_path / "reports/promotion/paper/baseline.json",
        {"account_scope": "***1234-01"},
    )
    _write(
        tmp_path / "reports/promotion/paper/latest.json",
        {
            "report_date": "2026-07-21",
            "report_status": "FINAL",
            "validation": {"status": "READY"},
            "operations": {
                "observed_trading_days": 60 if complete else 1,
                "data_freshness_rate": 1.0,
                "risk_check_coverage": 1.0,
                "order_reconciliation_rate": 1.0,
                "operational_integrity": 1.0,
            },
            "trading": {"open_order_count": 0},
            "ledger_quality": {
                "order_result_replay": {"orders": 547},
                "data_quality": {
                    "execution_table_coverage_of_filled_orders": 1.0 if complete else 0.625
                },
                "reconciliation": {
                    "endpoint_held_position_match_rate": 1.0 if complete else 0.5
                },
            },
        },
    )
    _append_jsonl(
        tmp_path / "logs/paper/operational_health.jsonl",
        [
            {
                "timestamp": f"{session_date.isoformat()}T15:20:00+09:00",
                "operational_status": "NORMAL",
            }
            for session_date in session_dates
        ],
    )
    for session_date in session_dates:
        _write(
            tmp_path
            / "reports/promotion/paper/daily"
            / f"{session_date.isoformat()}.json",
            {
                "report_date": session_date.isoformat(),
                "mode": "PAPER",
                "report_status": "FINAL",
                "validation": {"status": "READY"},
                "operations": {
                    "data_freshness_rate": 1.0,
                    "risk_check_coverage": 1.0,
                    "order_reconciliation_rate": 1.0,
                    "operational_integrity": 1.0,
                },
                "trading": {"open_order_count": 0},
            },
        )
    _write(
        tmp_path / "reports/analysis/paper_broker_history/latest.json",
        {
            "account_scope": "***1234-01",
            "audit_complete": True,
            "end_date": "2026-07-22",
            "unresolved_db_filled_rows": [],
        },
    )
    _write(
        tmp_path / "reports/analysis/scheduler_recovery_evidence.json",
        {
            "status": "READY",
            "broker_loaded": False,
            "order_permission": "DENIED_BY_DESIGN",
            "tested_mode": "PAPER",
            "real_auto_restart_allowed": False,
            "attempts": 2,
            "process_exit_codes": [1, 0],
            "final_exit_code": 0,
        },
    )
    _write(
        tmp_path / "reports/analysis/paper_order_result_replay_2026-07-22/summary.json",
        {
            "data_quality": {"priced_fill_event_coverage": 1.0 if complete else 0.96},
            "promotion_gate": {
                "exact_endpoint_parity": True,
                "calibration_free_from_500m": complete,
            },
        },
    )
    _write(
        tmp_path / "reports/analysis/paper_execution_stress_2026-07-22/summary.json",
        {
            "ledger_evidence": {"order_count": 547},
            "execution_samples": {
                "BUY": {"orders": 30 if complete else 5},
                "SELL": {"orders": 30 if complete else 4},
            },
            "promotion_gate": {
                "minimum_side_sample": 30,
                "sample_ready": complete,
                "all_execution_scenarios_pass": complete,
            },
            "risk_control_gate": {
                "fallback_available": complete,
                "robust_variants": ["C_CAP10"] if complete else [],
            },
        },
    )


def test_runtime_can_be_safe_while_completion_evidence_is_pending(tmp_path):
    _fixture(tmp_path, complete=False)

    result = audit_system_readiness(
        tmp_path,
        now=dt.datetime(2026, 7, 22, 10, 2, tzinfo=KST),
        environ={},
    )

    assert result["paper_runtime_safe"] is True
    assert result["full_system_complete"] is False
    assert any("historical_fill_evidence" in item for item in result["blockers"])
    assert result["real_execution_authorized"] is False


def test_completion_requires_all_safety_and_evidence_checks(tmp_path):
    _fixture(tmp_path, complete=True)

    result = audit_system_readiness(
        tmp_path,
        now=dt.datetime(2026, 7, 22, 10, 2, tzinfo=KST),
        environ={},
    )

    assert result["paper_runtime_safe"] is True
    assert result["full_system_complete"] is True
    assert result["blockers"] == []


def test_real_environment_marker_fails_runtime_safety(tmp_path):
    _fixture(tmp_path, complete=True)

    result = audit_system_readiness(
        tmp_path,
        now=dt.datetime(2026, 7, 22, 10, 2, tzinfo=KST),
        environ={"KIS_ENV": "real", "ALLOW_LIVE_ORDER": "true"},
    )

    assert result["paper_runtime_safe"] is False
    assert result["full_system_complete"] is False


def test_runtime_data_risk_order_and_error_state_are_independent_safety_gates(
    tmp_path,
):
    _fixture(tmp_path, complete=True)
    path = tmp_path / "logs/paper/dashboard_state.json"
    dashboard = json.loads(path.read_text(encoding="utf-8"))
    dashboard["data_health"].update(
        {
            "fresh_count": 1,
            "stale_tickers": ["005930.KS"],
            "risk_checks_completed": 1,
            "risk_check_coverage": 0.5,
            "entry_circuit_breaker": "STALE_HELD_POSITION",
        }
    )
    dashboard["actual_orders"]["open"] = 1
    dashboard["last_error"] = "broker timeout"
    _write(path, dashboard)

    result = audit_system_readiness(
        tmp_path,
        now=dt.datetime(2026, 7, 22, 10, 2, tzinfo=KST),
        environ={},
    )

    assert result["paper_runtime_safe"] is False
    assert result["progress"]["safety_checks"] == {"passed": 8, "total": 12}
    for name in (
        "market_data_health",
        "held_position_risk_coverage",
        "no_unresolved_runtime_orders",
        "runtime_error_free",
    ):
        assert any(item.startswith(f"{name}:") for item in result["blockers"])


def test_daily_report_requires_operational_rates_and_zero_open_orders(tmp_path):
    _fixture(tmp_path, complete=True)
    report_path = tmp_path / "reports/promotion/paper/daily/2026-07-21.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    report["operations"]["order_reconciliation_rate"] = 0.9
    report["trading"]["open_order_count"] = 1
    _write(report_path, report)

    result = audit_system_readiness(
        tmp_path,
        now=dt.datetime(2026, 7, 22, 10, 2, tzinfo=KST),
        environ={},
    )

    assert result["full_system_complete"] is False
    assert any(
        item.startswith("latest_final_report:") for item in result["blockers"]
    )
    assert any(
        item.startswith("daily_final_report_coverage:")
        for item in result["blockers"]
    )


def test_scheduler_scope_and_recovery_evidence_cannot_be_claimed_by_real(tmp_path):
    _fixture(tmp_path, complete=True)
    _write(
        tmp_path / "logs/scheduler.instance.lock.json",
        {"pid": 9876, "mode": "REAL", "label": "scheduler"},
    )
    recovery_path = (
        tmp_path / "reports/analysis/scheduler_recovery_evidence.json"
    )
    recovery = json.loads(recovery_path.read_text(encoding="utf-8"))
    recovery["real_auto_restart_allowed"] = True
    _write(recovery_path, recovery)

    result = audit_system_readiness(
        tmp_path,
        now=dt.datetime(2026, 7, 22, 10, 2, tzinfo=KST),
        environ={},
    )

    assert result["paper_runtime_safe"] is False
    assert any(
        item.startswith("scheduler_instance_scope:")
        for item in result["blockers"]
    )
    assert any(
        item.startswith("scheduler_recovery_self_test:")
        for item in result["blockers"]
    )


def test_scheduler_supervisor_must_match_paper_scheduler(tmp_path):
    _fixture(tmp_path, complete=True)
    _write(
        tmp_path / "logs/scheduler.supervisor.instance.lock.json",
        {"pid": 5678, "mode": "REAL", "label": "scheduler-supervisor"},
    )
    _append_jsonl(
        tmp_path / "logs/paper/scheduler_supervisor.jsonl",
        [
            {
                "mode": "PAPER",
                "event": "ATTACHED_TO_EXISTING",
                "detail": "pid=9999, poll_seconds=5",
            }
        ],
    )

    result = audit_system_readiness(
        tmp_path,
        now=dt.datetime(2026, 7, 22, 10, 2, tzinfo=KST),
        environ={},
    )

    assert result["paper_runtime_safe"] is False
    assert any(
        item.startswith("scheduler_supervisor_runtime:")
        for item in result["blockers"]
    )


def test_canonical_latest_evidence_takes_precedence_over_dated_fallback(tmp_path):
    _fixture(tmp_path, complete=True)
    _write(
        tmp_path / "reports/analysis/paper_ledger_latest/summary.json",
        {
            "data_quality": {
                "execution_table_coverage_of_filled_orders": 0.75,
            },
            "reconciliation": {"endpoint_held_position_match_rate": 0.5},
        },
    )
    _write(
        tmp_path
        / "reports/analysis/paper_order_result_replay/latest/summary.json",
        {
            "data_quality": {"priced_fill_event_coverage": 0.9},
            "promotion_gate": {
                "exact_endpoint_parity": True,
                "calibration_free_from_500m": False,
            },
        },
    )

    result = audit_system_readiness(
        tmp_path,
        now=dt.datetime(2026, 7, 22, 10, 2, tzinfo=KST),
        environ={},
    )

    assert result["full_system_complete"] is False
    assert any("historical_fill_evidence: 75.00%" in row for row in result["blockers"])
    assert any("priced_coverage=90.00%" in row for row in result["blockers"])


def test_after_close_requires_same_day_final_report(tmp_path):
    _fixture(tmp_path, complete=True)
    _append_jsonl(
        tmp_path / "logs/paper/operational_health.jsonl",
        [
            {
                "timestamp": "2026-07-21T15:20:00+09:00",
                "operational_status": "NORMAL",
            },
            {
                "timestamp": "2026-07-22T15:20:00+09:00",
                "operational_status": "NORMAL",
            },
        ],
    )
    dashboard = json.loads(
        (tmp_path / "logs/paper/dashboard_state.json").read_text(encoding="utf-8")
    )
    dashboard["updated_at"] = "2026-07-22T15:31:00+09:00"
    _write(tmp_path / "logs/paper/dashboard_state.json", dashboard)

    result = audit_system_readiness(
        tmp_path,
        now=dt.datetime(2026, 7, 22, 15, 32, tzinfo=KST),
        environ={},
    )

    assert result["full_system_complete"] is False
    assert any("latest_final_report" in row for row in result["blockers"])
    assert any("daily_final_report_coverage" in row for row in result["blockers"])


def test_completion_requires_60_final_ready_daily_reports(tmp_path):
    _fixture(tmp_path, complete=True)
    missing_date = dt.date(2026, 7, 1)
    (tmp_path / "reports/promotion/paper/daily" / f"{missing_date}.json").unlink()

    result = audit_system_readiness(
        tmp_path,
        now=dt.datetime(2026, 7, 22, 10, 2, tzinfo=KST),
        environ={},
    )

    assert result["full_system_complete"] is False
    assert any("daily_final_report_coverage" in row for row in result["blockers"])
    assert any("paper_final_report_window: 59/60" in row for row in result["blockers"])


def test_shadow_summary_cannot_claim_more_than_verified_sessions(tmp_path):
    _fixture(tmp_path, complete=True)
    path = tmp_path / "logs/paper/shadow_reentry_state.json"
    shadow = json.loads(path.read_text(encoding="utf-8"))
    shadow["observed_sessions"] = shadow["observed_sessions"][:1]
    _write(path, shadow)

    result = audit_system_readiness(
        tmp_path,
        now=dt.datetime(2026, 7, 22, 10, 2, tzinfo=KST),
        environ={},
    )

    assert result["full_system_complete"] is False
    assert any("shadow_observation_integrity" in row for row in result["blockers"])


def test_execution_stress_summary_must_match_counts_and_ledger(tmp_path):
    _fixture(tmp_path, complete=True)
    path = (
        tmp_path
        / "reports/analysis/paper_execution_stress_2026-07-22/summary.json"
    )
    stress = json.loads(path.read_text(encoding="utf-8"))
    stress["ledger_evidence"]["order_count"] = 546
    stress["execution_samples"]["SELL"]["orders"] = 4
    _write(path, stress)

    result = audit_system_readiness(
        tmp_path,
        now=dt.datetime(2026, 7, 22, 10, 2, tzinfo=KST),
        environ={},
    )

    assert result["full_system_complete"] is False
    assert any(
        "execution_stress_evidence_integrity" in row
        for row in result["blockers"]
    )


def test_is_process_lock_held_detects_active_unheld_and_stale_locks(tmp_path):
    from core.utils.process_lock import (
        ProcessInstanceLock,
        is_process_alive,
        is_process_lock_held,
    )

    lock_file = tmp_path / "test.lock"
    meta_file = tmp_path / "test.lock.json"

    assert is_process_alive(os.getpid()) is True
    assert is_process_alive(999999) is False

    assert is_process_lock_held(lock_file) is False

    lock = ProcessInstanceLock(lock_file, "PAPER", label="test").acquire()
    assert is_process_lock_held(lock_file) is True

    lock.release()
    assert is_process_lock_held(lock_file) is False

    _write(meta_file, {"pid": 999999, "mode": "PAPER", "label": "test"})
    _write(lock_file, {"dummy": "data"})
    assert is_process_lock_held(lock_file) is False


def test_stale_scheduler_lock_causes_paper_runtime_safe_false(tmp_path):
    _fixture(tmp_path, complete=True)
    # Release the active scheduler lock and overwrite metadata with dead PID 999999
    _ACTIVE_FIXTURE_LOCKS[str(tmp_path)][0].release()
    _write(
        tmp_path / "logs/scheduler.instance.lock.json",
        {"pid": 999999, "mode": "PAPER", "label": "scheduler"},
    )
    _write(tmp_path / "logs/scheduler.instance.lock", {"dummy": 1})

    result = audit_system_readiness(
        tmp_path,
        now=dt.datetime(2026, 7, 22, 10, 2, tzinfo=KST),
        environ={},
    )

    assert result["paper_runtime_safe"] is False
    assert any(
        "scheduler_instance_scope" in blocker for blocker in result["blockers"]
    )


def test_stale_supervisor_lock_causes_paper_runtime_safe_false(tmp_path):
    _fixture(tmp_path, complete=True)
    # Release supervisor lock and overwrite metadata with dead PID 999999
    _ACTIVE_FIXTURE_LOCKS[str(tmp_path)][1].release()
    _write(
        tmp_path / "logs/scheduler.supervisor.instance.lock.json",
        {"pid": 999999, "mode": "PAPER", "label": "scheduler-supervisor"},
    )
    _write(tmp_path / "logs/scheduler.supervisor.instance.lock", {"dummy": 1})

    result = audit_system_readiness(
        tmp_path,
        now=dt.datetime(2026, 7, 22, 10, 2, tzinfo=KST),
        environ={},
    )

    assert result["paper_runtime_safe"] is False
    assert any(
        "scheduler_supervisor_runtime" in blocker
        for blocker in result["blockers"]
    )

