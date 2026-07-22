"""Read-only completion audit for the automated PAPER trading system."""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
from pathlib import Path
from typing import Mapping
from zoneinfo import ZoneInfo


KST = ZoneInfo("Asia/Seoul")
MARKET_CLOSE = dt.time(15, 30)


def _load(path: Path, *, required: bool = True) -> dict:
    if not path.exists():
        if required:
            raise FileNotFoundError(str(path))
        return {}
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _load_first(paths: list[Path]) -> tuple[dict, Path | None]:
    for path in paths:
        if path.exists():
            return _load(path), path
    return {}, None


def _load_latest_jsonl(path: Path) -> dict:
    """Load the last valid JSON object without mutating an operational log."""
    if not path.exists():
        return {}
    for line in reversed(path.read_text(encoding="utf-8-sig").splitlines()):
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            return {}
        return payload if isinstance(payload, dict) else {}
    return {}


def _timestamp(value: object) -> dt.datetime:
    parsed = dt.datetime.fromisoformat(str(value))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=KST)
    return parsed.astimezone(KST)


def _completed_operational_dates(log_path: Path, now: dt.datetime) -> list[dt.date]:
    """Return PAPER session dates whose 15:30 KST close has completed."""
    if not log_path.exists():
        raise FileNotFoundError(str(log_path))
    dates: set[dt.date] = set()
    for line_number, line in enumerate(
        log_path.read_text(encoding="utf-8-sig").splitlines(), 1
    ):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
            timestamp = _timestamp(row["timestamp"])
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ValueError(
                f"invalid operational log record at line {line_number}"
            ) from exc
        if row.get("operational_status") != "SCANNING" and timestamp.date() <= now.date():
            dates.add(timestamp.date())
    if now.time().replace(tzinfo=None) < MARKET_CLOSE:
        dates.discard(now.date())
    return sorted(dates)


def _final_daily_report_dates(daily_dir: Path) -> tuple[set[dt.date], list[str]]:
    """Validate immutable PAPER daily reports and return operationally complete dates."""
    if not daily_dir.exists():
        return set(), [f"daily report directory unavailable: {daily_dir}"]
    valid: set[dt.date] = set()
    issues: list[str] = []
    for path in sorted(daily_dir.glob("*.json")):
        try:
            payload = _load(path)
            report_date = dt.date.fromisoformat(str(payload["report_date"]))
            if path.stem != report_date.isoformat():
                raise ValueError("filename/report_date mismatch")
            if str(payload.get("mode") or "").upper() != "PAPER":
                raise ValueError("mode is not PAPER")
            if payload.get("report_status") != "FINAL":
                raise ValueError("report_status is not FINAL")
            if (payload.get("validation") or {}).get("status") != "READY":
                raise ValueError("validation status is not READY")
            operations = payload.get("operations") or {}
            trading = payload.get("trading") or {}
            required_rates = {
                "data_freshness_rate": operations.get("data_freshness_rate"),
                "risk_check_coverage": operations.get("risk_check_coverage"),
                "order_reconciliation_rate": operations.get(
                    "order_reconciliation_rate"
                ),
                "operational_integrity": operations.get("operational_integrity"),
            }
            incomplete_rates = [
                name for name, value in required_rates.items() if value != 1.0
            ]
            if incomplete_rates:
                raise ValueError(
                    "operational rates are not complete: "
                    + ", ".join(incomplete_rates)
                )
            if trading.get("open_order_count") != 0:
                raise ValueError("open_order_count is not zero")
            valid.add(report_date)
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            issues.append(f"{path.name}: {exc}")
    return valid, issues


def audit_system_readiness(
    project_root: Path,
    *,
    now: dt.datetime | None = None,
    environ: Mapping[str, str] | None = None,
) -> dict:
    now = (now or dt.datetime.now(KST)).astimezone(KST)
    env = environ if environ is not None else os.environ
    dashboard = _load(project_root / "logs" / "paper" / "dashboard_state.json")
    baseline = _load(
        project_root / "reports" / "promotion" / "paper" / "baseline.json"
    )
    latest = _load(
        project_root / "reports" / "promotion" / "paper" / "latest.json"
    )
    shadow = _load(
        project_root / "logs" / "paper" / "shadow_reentry_state.json",
        required=False,
    )
    scheduler_instance = _load(
        project_root / "logs" / "scheduler.instance.lock.json",
        required=False,
    )
    scheduler_supervisor = _load(
        project_root / "logs" / "scheduler.supervisor.instance.lock.json",
        required=False,
    )
    scheduler_supervisor_event = _load_latest_jsonl(
        project_root / "logs" / "paper" / "scheduler_supervisor.jsonl"
    )
    analysis_root = project_root / "reports" / "analysis"
    standalone_parity, parity_path = _load_first([
        analysis_root / "paper_order_result_replay" / "latest" / "summary.json",
        analysis_root / "paper_order_result_replay_2026-07-22" / "summary.json",
    ])
    standalone_ledger, ledger_path = _load_first([
        analysis_root / "paper_ledger_latest" / "summary.json",
        analysis_root / "paper_ledger_2026-07-22" / "summary.json",
    ])
    execution_stress, stress_path = _load_first([
        analysis_root / "paper_execution_stress" / "latest" / "summary.json",
        analysis_root / "paper_execution_stress_2026-07-22" / "summary.json",
    ])
    broker_history = _load(
        analysis_root / "paper_broker_history" / "latest.json",
        required=False,
    )
    scheduler_recovery = _load(
        analysis_root / "scheduler_recovery_evidence.json",
        required=False,
    )
    # The official EOD report is intentionally one session behind intraday.  The
    # canonical read-only evidence is therefore authoritative when it exists.
    ledger = standalone_ledger or latest.get("ledger_quality") or {}
    parity = standalone_parity or ledger.get("observed_order_result_parity") or {}
    operations = latest.get("operations") or {}

    operational_log = project_root / "logs" / "paper" / "operational_health.jsonl"
    daily_report_dir = project_root / "reports" / "promotion" / "paper" / "daily"
    operational_error = None
    try:
        completed_dates = _completed_operational_dates(operational_log, now)
    except (FileNotFoundError, ValueError) as exc:
        completed_dates = []
        operational_error = str(exc)
    final_report_dates, daily_report_issues = _final_daily_report_dates(
        daily_report_dir
    )
    expected_latest_date = completed_dates[-1] if completed_dates else None
    try:
        latest_report_date = dt.date.fromisoformat(str(latest.get("report_date")))
    except (TypeError, ValueError):
        latest_report_date = None
    try:
        broker_history_end_date = dt.date.fromisoformat(
            str(broker_history.get("end_date"))
        )
    except (TypeError, ValueError):
        broker_history_end_date = None
    completed_date_set = set(completed_dates)
    covered_report_dates = completed_date_set & final_report_dates
    missing_report_dates = sorted(completed_date_set - final_report_dates)
    relevant_daily_report_issues = [
        issue
        for issue in daily_report_issues
        if any(issue.startswith(item.isoformat()) for item in completed_dates)
    ]

    safety_checks: list[dict] = []
    evidence_checks: list[dict] = []

    def add(target: list[dict], name: str, passed: bool, detail: str) -> None:
        target.append({"name": name, "passed": bool(passed), "detail": detail})

    mode = str(dashboard.get("execution_mode") or "").upper()
    add(safety_checks, "paper_mode", mode == "PAPER", mode or "unavailable")
    from core.utils.process_lock import is_process_runtime_live

    scheduler_pid = scheduler_instance.get("pid")
    scheduler_lock_file = project_root / "logs" / "scheduler.instance.lock"
    scheduler_runtime_live, scheduler_runtime_evidence = is_process_runtime_live(
        scheduler_instance,
        scheduler_lock_file,
        project_root / "logs" / "paper" / "scheduler_runtime.json",
        now=now,
    )
    add(
        safety_checks,
        "scheduler_instance_scope",
        scheduler_instance.get("mode") == "PAPER"
        and scheduler_instance.get("label") == "scheduler"
        and scheduler_runtime_live,
        (
            f"pid={scheduler_pid or 'unavailable'}, "
            f"mode={scheduler_instance.get('mode', 'unavailable')}, "
            f"label={scheduler_instance.get('label', 'unavailable')}, "
            f"runtime_live={scheduler_runtime_live}, "
            f"evidence={scheduler_runtime_evidence}"
        ),
    )
    supervisor_pid = scheduler_supervisor.get("pid")
    supervisor_lock_file = project_root / "logs" / "scheduler.supervisor.instance.lock"
    supervisor_runtime_live, supervisor_runtime_evidence = is_process_runtime_live(
        scheduler_supervisor,
        supervisor_lock_file,
        project_root / "logs" / "paper" / "scheduler_supervisor_runtime.json",
        now=now,
    )
    supervisor_event = str(scheduler_supervisor_event.get("event") or "")
    supervisor_detail = str(scheduler_supervisor_event.get("detail") or "")
    attached_pid_matches = (
        supervisor_event != "ATTACHED_TO_EXISTING"
        or supervisor_detail.startswith(f"pid={scheduler_pid},")
    )
    add(
        safety_checks,
        "scheduler_supervisor_runtime",
        scheduler_supervisor.get("mode") == "PAPER"
        and scheduler_supervisor.get("label") == "scheduler-supervisor"
        and supervisor_runtime_live
        and scheduler_supervisor_event.get("mode") == "PAPER"
        and supervisor_event
        in {
            "SUPERVISOR_STARTED",
            "ATTACHED_TO_EXISTING",
            "ATTACHED_PROCESS_EXITED",
            "PROCESS_EXIT",
            "AUTO_RESTART_SCHEDULED",
        }
        and attached_pid_matches,
        (
            f"pid={supervisor_pid or 'unavailable'}, "
            f"mode={scheduler_supervisor.get('mode', 'unavailable')}, "
            f"event={supervisor_event or 'unavailable'}, "
            f"detail={supervisor_detail or 'unavailable'}, "
            f"runtime_live={supervisor_runtime_live}, "
            f"evidence={supervisor_runtime_evidence}"
        ),
    )
    account_scope = str(dashboard.get("account_scope") or "")
    baseline_scope = str(baseline.get("account_scope") or "")
    add(
        safety_checks,
        "certified_account_scope",
        bool(account_scope and account_scope == baseline_scope and account_scope != "UNKNOWN"),
        f"dashboard={account_scope or 'unavailable'}, baseline={baseline_scope or 'unavailable'}",
    )
    execution_ledger = (dashboard.get("data_health") or {}).get(
        "execution_ledger"
    ) or {}
    data_health = dashboard.get("data_health") or {}
    add(
        safety_checks,
        "daily_execution_ledger",
        execution_ledger.get("status") == "READY"
        and float(execution_ledger.get("execution_link_coverage", 0)) == 1.0
        and float(execution_ledger.get("quantity_match_rate", 0)) == 1.0,
        (
            f"status={execution_ledger.get('status', 'unavailable')}, "
            f"link={float(execution_ledger.get('execution_link_coverage', 0)):.2%}, "
            f"qty={float(execution_ledger.get('quantity_match_rate', 0)):.2%}"
        ),
    )
    expected_count = int(data_health.get("expected_count") or 0)
    fresh_count = int(data_health.get("fresh_count") or 0)
    stale_tickers = data_health.get("stale_tickers") or []
    missing_tickers = data_health.get("missing_tickers") or []
    dependency_errors = data_health.get("dependency_errors") or []
    held_stale_tickers = data_health.get("held_stale_tickers") or []
    add(
        safety_checks,
        "market_data_health",
        expected_count > 0
        and fresh_count == expected_count
        and not stale_tickers
        and not missing_tickers
        and not dependency_errors
        and not held_stale_tickers,
        (
            f"fresh={fresh_count}/{expected_count}, stale={len(stale_tickers)}, "
            f"missing={len(missing_tickers)}, dependencies={len(dependency_errors)}, "
            f"held_stale={len(held_stale_tickers)}"
        ),
    )
    risk_checks_total = int(data_health.get("risk_checks_total") or 0)
    risk_checks_completed = int(data_health.get("risk_checks_completed") or 0)
    risk_check_coverage = float(data_health.get("risk_check_coverage") or 0)
    add(
        safety_checks,
        "held_position_risk_coverage",
        risk_checks_total > 0
        and risk_checks_completed == risk_checks_total
        and risk_check_coverage == 1.0,
        (
            f"completed={risk_checks_completed}/{risk_checks_total}, "
            f"coverage={risk_check_coverage:.2%}"
        ),
    )
    dashboard_open_orders = int((dashboard.get("daily_orders") or {}).get("open") or 0)
    actual_open_orders = int((dashboard.get("actual_orders") or {}).get("open") or 0)
    add(
        safety_checks,
        "no_unresolved_runtime_orders",
        dashboard_open_orders == 0 and actual_open_orders == 0,
        f"daily_open={dashboard_open_orders}, actual_open={actual_open_orders}",
    )
    last_error = dashboard.get("last_error")
    entry_circuit_breaker = data_health.get("entry_circuit_breaker")
    add(
        safety_checks,
        "runtime_error_free",
        not last_error and not dependency_errors and not entry_circuit_breaker,
        (
            f"last_error={last_error or 'none'}, "
            f"dependency_errors={len(dependency_errors)}, "
            f"entry_circuit_breaker={entry_circuit_breaker or 'none'}"
        ),
    )
    updated = _timestamp(dashboard.get("updated_at"))
    age_seconds = max((now - updated).total_seconds(), 0.0)
    during_market = (now.hour, now.minute) >= (9, 0) and (now.hour, now.minute) <= (
        15,
        30,
    )
    freshness_limit = 5 * 60 if during_market else 24 * 60 * 60
    add(
        safety_checks,
        "dashboard_freshness",
        age_seconds <= freshness_limit,
        f"age_seconds={age_seconds:.0f}, limit={freshness_limit}",
    )
    kis_env = str(env.get("KIS_ENV") or "").strip().lower()
    allow_live = str(env.get("ALLOW_LIVE_ORDER") or "").strip().lower()
    add(
        safety_checks,
        "real_environment_disabled",
        kis_env != "real" and allow_live != "true",
        f"KIS_ENV={kis_env or 'unset'}, ALLOW_LIVE_ORDER={allow_live or 'unset'}",
    )
    add(
        safety_checks,
        "shadow_order_disconnected",
        shadow.get("observe_only") is True
        and shadow.get("order_permission") == "DENIED_BY_DESIGN",
        (
            f"observe_only={shadow.get('observe_only')}, "
            f"permission={shadow.get('order_permission', 'unavailable')}"
        ),
    )

    add(
        evidence_checks,
        "latest_final_report",
        latest.get("report_status") == "FINAL"
        and (latest.get("validation") or {}).get("status") == "READY"
        and latest_report_date == expected_latest_date
        and latest_report_date in final_report_dates,
        (
            f"date={latest.get('report_date', 'unavailable')}, "
            f"expected={expected_latest_date or 'unavailable'}, "
            f"status={latest.get('report_status', 'unavailable')}, "
            f"validation={(latest.get('validation') or {}).get('status', 'unavailable')}"
        ),
    )
    add(
        evidence_checks,
        "daily_final_report_coverage",
        operational_error is None
        and not relevant_daily_report_issues
        and not missing_report_dates,
        (
            f"covered={len(covered_report_dates)}/{len(completed_dates)}, "
            f"missing={[item.isoformat() for item in missing_report_dates[:5]]}, "
            f"invalid={len(relevant_daily_report_issues)}"
            if operational_error is None
            else operational_error
        ),
    )
    latest_operations = latest.get("operations") or {}
    latest_trading = latest.get("trading") or {}
    latest_operational_rates = {
        "data": latest_operations.get("data_freshness_rate"),
        "risk": latest_operations.get("risk_check_coverage"),
        "reconciliation": latest_operations.get("order_reconciliation_rate"),
        "integrity": latest_operations.get("operational_integrity"),
    }
    latest_open_orders = latest_trading.get("open_order_count")
    latest_critical_incidents = int(latest_operations.get("critical_incidents") or 0)
    add(
        evidence_checks,
        "latest_eod_operational_integrity",
        all(value == 1.0 for value in latest_operational_rates.values())
        and latest_open_orders == 0
        and latest_critical_incidents == 0,
        (
            f"data={latest_operational_rates['data']}, "
            f"risk={latest_operational_rates['risk']}, "
            f"reconciliation={latest_operational_rates['reconciliation']}, "
            f"integrity={latest_operational_rates['integrity']}, "
            f"open_orders={latest_open_orders}, "
            f"critical_incidents={latest_critical_incidents}"
        ),
    )
    recovery_exit_codes = scheduler_recovery.get("process_exit_codes") or []
    add(
        evidence_checks,
        "scheduler_recovery_self_test",
        scheduler_recovery.get("status") == "READY"
        and scheduler_recovery.get("broker_loaded") is False
        and scheduler_recovery.get("order_permission") == "DENIED_BY_DESIGN"
        and scheduler_recovery.get("tested_mode") == "PAPER"
        and scheduler_recovery.get("real_auto_restart_allowed") is False
        and int(scheduler_recovery.get("attempts") or 0) >= 2
        and len(recovery_exit_codes) >= 2
        and recovery_exit_codes[0] != 0
        and recovery_exit_codes[-1] == 0
        and scheduler_recovery.get("final_exit_code") == 0,
        (
            f"status={scheduler_recovery.get('status', 'unavailable')}, "
            f"attempts={scheduler_recovery.get('attempts', 0)}, "
            f"exit_codes={recovery_exit_codes}, "
            f"REAL_auto_restart={scheduler_recovery.get('real_auto_restart_allowed')}"
        ),
    )
    add(
        evidence_checks,
        "broker_history_audit",
        broker_history.get("audit_complete") is True
        and not (broker_history.get("unresolved_db_filled_rows") or [])
        and str(broker_history.get("account_scope") or "") == baseline_scope
        and (
            expected_latest_date is not None
            and broker_history_end_date is not None
            and broker_history_end_date >= expected_latest_date
        ),
        (
            f"complete={broker_history.get('audit_complete')}, "
            f"unresolved={len(broker_history.get('unresolved_db_filled_rows') or [])}, "
            f"through={broker_history.get('end_date', 'unavailable')}"
        ),
    )
    quality = ledger.get("data_quality") or {}
    reconciliation = ledger.get("reconciliation") or {}
    execution_coverage = quality.get(
        "auditable_fill_evidence_coverage",
        quality.get("execution_table_coverage_of_filled_orders"),
    )
    held_match = reconciliation.get("endpoint_held_position_match_rate")
    add(
        evidence_checks,
        "historical_fill_evidence",
        execution_coverage == 1.0,
        "unavailable" if execution_coverage is None else f"{execution_coverage:.2%}",
    )
    add(
        evidence_checks,
        "historical_held_quantity_match",
        held_match == 1.0,
        "unavailable" if held_match is None else f"{held_match:.2%}",
    )
    parity_gate = parity.get("promotion_gate") or {}
    inception_reconciled = parity_gate.get("reconciled_from_500m_within_tolerance")
    if inception_reconciled is None:
        inception_reconciled = parity_gate.get("calibration_free_from_500m")
    parity_coverage = (parity.get("data_quality") or {}).get(
        "priced_fill_event_coverage"
    )
    add(
        evidence_checks,
        "order_result_parity",
        parity_gate.get("exact_endpoint_parity") is True
        and inception_reconciled is True
        and parity_coverage == 1.0,
        (
            f"exact={parity_gate.get('exact_endpoint_parity')}, "
            f"inception_reconciled={inception_reconciled}, "
            f"priced_coverage={'unavailable' if parity_coverage is None else f'{parity_coverage:.2%}'}"
        ),
    )
    stress_gate = execution_stress.get("promotion_gate") or {}
    risk_control_gate = execution_stress.get("risk_control_gate") or {}
    stress_samples = execution_stress.get("execution_samples") or {}
    minimum_side_sample = int(stress_gate.get("minimum_side_sample") or 30)
    buy_sample = int((stress_samples.get("BUY") or {}).get("orders") or 0)
    sell_sample = int((stress_samples.get("SELL") or {}).get("orders") or 0)
    derived_sample_ready = (
        buy_sample >= minimum_side_sample and sell_sample >= minimum_side_sample
    )
    ledger_order_count = (ledger.get("order_result_replay") or {}).get("orders")
    stress_order_count = (execution_stress.get("ledger_evidence") or {}).get(
        "order_count"
    )
    stress_integrity = (
        ledger_order_count is not None
        and stress_order_count is not None
        and int(ledger_order_count) == int(stress_order_count)
        and stress_gate.get("sample_ready") is derived_sample_ready
    )
    add(
        evidence_checks,
        "execution_stress_evidence_integrity",
        stress_integrity,
        (
            f"ledger_orders={ledger_order_count}, stress_orders={stress_order_count}, "
            f"BUY={buy_sample}/{minimum_side_sample}, "
            f"SELL={sell_sample}/{minimum_side_sample}, "
            f"declared_ready={stress_gate.get('sample_ready')}"
        ),
    )
    add(
        evidence_checks,
        "execution_stress_robustness",
        stress_integrity
        and derived_sample_ready
        and risk_control_gate.get("fallback_available") is True,
        (
            f"sample_ready={stress_gate.get('sample_ready')}, "
            f"risk_fallbacks={risk_control_gate.get('robust_variants', [])}"
        ),
    )
    declared_completed_sessions = int(
        shadow.get("completed_observation_sessions") or 0
    )
    required_sessions = int(shadow.get("required_observation_sessions") or 10)
    raw_observed_sessions = shadow.get("observed_sessions") or []
    parsed_observed_sessions: list[dt.date] = []
    shadow_session_errors: list[str] = []
    if not isinstance(raw_observed_sessions, list):
        shadow_session_errors.append("observed_sessions is not a list")
    else:
        for value in raw_observed_sessions:
            try:
                parsed_observed_sessions.append(dt.date.fromisoformat(str(value)))
            except ValueError:
                shadow_session_errors.append(f"invalid session date: {value}")
    unique_shadow_sessions = set(parsed_observed_sessions)
    shadow_integrity = (
        not shadow_session_errors
        and len(parsed_observed_sessions) == len(unique_shadow_sessions)
        and declared_completed_sessions == len(unique_shadow_sessions)
        and unique_shadow_sessions <= completed_date_set
        and unique_shadow_sessions <= final_report_dates
    )
    add(
        evidence_checks,
        "shadow_observation_integrity",
        shadow_integrity,
        (
            f"declared={declared_completed_sessions}, "
            f"unique={len(unique_shadow_sessions)}, "
            f"covered_by_operations={len(unique_shadow_sessions & completed_date_set)}, "
            f"covered_by_reports={len(unique_shadow_sessions & final_report_dates)}, "
            f"errors={shadow_session_errors}"
        ),
    )
    add(
        evidence_checks,
        "shadow_observation_window",
        shadow_integrity and len(unique_shadow_sessions) >= required_sessions,
        f"{len(unique_shadow_sessions)}/{required_sessions} verified sessions",
    )
    observed_days = len(completed_dates)
    add(
        evidence_checks,
        "paper_operating_window",
        operational_error is None and observed_days >= 60,
        operational_error or f"{observed_days}/60 completed PAPER sessions",
    )
    add(
        evidence_checks,
        "paper_final_report_window",
        len(covered_report_dates) >= 60,
        f"{len(covered_report_dates)}/60 FINAL/READY daily reports",
    )

    paper_runtime_safe = all(item["passed"] for item in safety_checks)
    full_system_complete = paper_runtime_safe and all(
        item["passed"] for item in evidence_checks
    )
    blockers = [
        f"{item['name']}: {item['detail']}"
        for item in [*safety_checks, *evidence_checks]
        if not item["passed"]
    ]
    return {
        "schema_version": 1,
        "generated_at": now.isoformat(timespec="seconds"),
        "scope": "PAPER_AUTOMATED_TRADING_SYSTEM",
        "paper_runtime_safe": paper_runtime_safe,
        "full_system_complete": full_system_complete,
        "real_execution_authorized": False,
        "progress": {
            "execution_samples": {
                "buy": buy_sample,
                "sell": sell_sample,
                "required_per_side": minimum_side_sample,
            },
            "shadow_sessions": {
                "completed": len(unique_shadow_sessions),
                "required": required_sessions,
            },
            "paper_sessions": {
                "completed": observed_days,
                "required": 60,
            },
            "final_daily_reports": {
                "completed": len(covered_report_dates),
                "required": 60,
            },
            "evidence_checks": {
                "passed": sum(item["passed"] for item in evidence_checks),
                "total": len(evidence_checks),
            },
            "safety_checks": {
                "passed": sum(item["passed"] for item in safety_checks),
                "total": len(safety_checks),
            },
        },
        "safety_checks": safety_checks,
        "completion_evidence_checks": evidence_checks,
        "blockers": blockers,
        "sources": [
            "logs/paper/dashboard_state.json",
            "logs/paper/operational_health.jsonl",
            "logs/paper/shadow_reentry_state.json",
            "logs/scheduler.instance.lock.json",
            "logs/scheduler.supervisor.instance.lock.json",
            "logs/paper/scheduler_runtime.json",
            "logs/paper/scheduler_supervisor_runtime.json",
            "logs/paper/scheduler_supervisor.jsonl",
            "reports/promotion/paper/baseline.json",
            "reports/promotion/paper/latest.json",
            "reports/promotion/paper/daily/*.json",
            "reports/analysis/paper_broker_history/latest.json",
            "reports/analysis/scheduler_recovery_evidence.json",
            str(ledger_path.relative_to(project_root)) if ledger_path else "paper ledger unavailable",
            str(parity_path.relative_to(project_root)) if parity_path else "order-result parity unavailable",
            str(stress_path.relative_to(project_root)) if stress_path else "execution stress unavailable",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Audit PAPER runtime safety and full-system completion evidence."
    )
    parser.add_argument("--project-root", default=str(Path(__file__).resolve().parents[2]))
    parser.add_argument(
        "--output",
        default="reports/analysis/automated_trading_system_readiness.json",
    )
    parser.add_argument("--require-complete", action="store_true")
    parser.add_argument(
        "--for-real-activation",
        action="store_true",
        help=(
            "Recompute PAPER completion while treating the caller's REAL env markers "
            "as pending manual activation. This never authorizes or starts REAL."
        ),
    )
    args = parser.parse_args()
    root = Path(args.project_root).resolve()
    result = audit_system_readiness(
        root,
        environ={} if args.for_real_activation else None,
    )
    output = Path(args.output)
    if not output.is_absolute():
        output = root / output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 2 if args.require_complete and not result["full_system_complete"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
