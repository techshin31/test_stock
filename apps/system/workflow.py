"""Prepare verified FA inputs and run bounded, serialized trading cycles."""
from __future__ import annotations

from contextlib import contextmanager
from datetime import date, datetime, time, timedelta
import json
import os
from pathlib import Path
import subprocess
import sys
from zoneinfo import ZoneInfo

from core.utils.io import write_json
from core.utils.process_lock import ProcessInstanceLock
from core.utils.trading_calendar import is_krx_trading_day, previous_krx_trading_day

KST = ZoneInfo("Asia/Seoul")
PROJECT_ROOT = Path(__file__).resolve().parents[2]
STRATEGY = "aggressive"  # FaTaMomentumStrategy's persisted investment type.
MODES = {"dry-run": "DRY_RUN", "simulate": "SIMULATE", "paper": "PAPER"}


class WorkflowBlocked(RuntimeError):
    pass


def now_kst():
    return datetime.now(KST)


@contextmanager
def locked(path, mode):
    lock = ProcessInstanceLock(path, mode, label="automated trading workflow").acquire()
    try:
        yield
    finally:
        lock.release()


def upcoming_session(now):
    candidate = now.date()
    if now.time() >= time(8, 30):
        candidate += timedelta(days=1)
    for _ in range(15):
        if is_krx_trading_day(candidate.isoformat()):
            return candidate
        candidate += timedelta(days=1)
    raise WorkflowBlocked("NO_UPCOMING_KRX_SESSION")


def run_process(arguments, *, timeout=900):
    """Bound each child; raw dependency exceptions may contain credentials."""
    env = dict(os.environ, PYTHONPATH=str(PROJECT_ROOT), PYTHONUTF8="1")
    env.pop("DART_API_KEY", None)
    env.pop("COMPANY_DATA_SOURCE", None)
    from apps.system.processes import run_bounded
    return run_bounded([sys.executable, *arguments], cwd=PROJECT_ROOT, env=env, timeout=timeout)


def prepare(*, effective_date: date | None = None, collect=False,
            output=Path("logs/system/preparation.json")):
    """Publish only a current/future PASS analysis, preserving stage evidence."""
    from apps.worker.__main__ import _init
    from apps.worker.analyzer.config import load_config
    from apps.worker.analyzer import pipeline, universe_job
    from apps.worker.analyzer.operations import audit_operational_state
    from apps.worker.collector.readiness import run as readiness

    output = PROJECT_ROOT / output
    with locked(PROJECT_ROOT / "logs/system/prepare.lock", "PREPARE"):
        now = now_kst()
        report = {"status": "RUNNING", "stage": "VALIDATE_SESSION",
                  "started_at": now.isoformat(), "strategy": STRATEGY, "orders_submitted": False}
        db = None
        try:
            write_json(output, report)
            session = effective_date or upcoming_session(now)
            cutoff = previous_krx_trading_day(session)
            report.update(effective_date=session, cutoff_date=cutoff)
            if (session < now.date() or cutoff >= now.date()
                    or not is_krx_trading_day(session.isoformat())):
                raise WorkflowBlocked("SESSION_REQUIRES_COMPLETED_INPUTS")
            if collect:
                report["stage"] = "COLLECT"
                write_json(output, report)
                source_report = output.with_name(output.stem + "-collection.json").resolve()
                # Do not mistake an old successful report for this child's output.
                source_report.unlink(missing_ok=True)
                rc = run_process(["-m", "apps.worker", "collect", "all",
                                  "--start", cutoff.isoformat(), "--end", cutoff.isoformat(),
                                  "--company-report", str(source_report), "--no-progress"])
                collection = json.loads(source_report.read_text()) if source_report.exists() else {}
                report["collection"] = {"exit_code": rc, "status": collection.get("status"),
                                        "report": str(source_report)}
                # Known missing CFS originals are explicit partial coverage. The
                # per-company eight-quarter gate and strict readiness still apply.
                failures = (collection.get("finance") or {}).get("failures") or []
                known_gaps = {"XBRL_CONFLICTING_DUPLICATE_FACT", "XBRL_CFS_BALANCE_MISSING",
                              "NO_ELIGIBLE_FINANCIAL_FILINGS"}
                partial = (rc == 2 and collection.get("status") == "PARTIAL"
                           and collection.get("risk_disclosure_coverage") == "POLICY_SCOPE_ONLY"
                           and bool(failures)
                           and all(item.get("reason") in known_gaps for item in failures))
                if rc != 0 and not partial:
                    raise WorkflowBlocked("COLLECTION_FAILED")
            _, db = _init()
            report["stage"] = "READINESS"
            report["readiness"] = readiness(db, cutoff).to_dict()
            write_json(output, report)
            if report["readiness"]["status"] != "PASS":
                raise WorkflowBlocked("INPUTS_NOT_READY")
            report["stage"] = "ANALYZE"
            write_json(output, report)
            config = load_config(STRATEGY)
            context = pipeline.run(db, pipeline.build_request(
                target="all", cutoff_date=cutoff, effective_date=session,
            ), config, show_progress=False)
            report.update(run_id=context.run_id, model_version=context.model_version)
            status = db.fetch_one("SELECT status_code FROM fa_analysis_runs WHERE id=%s", (context.run_id,))
            if not status or status["status_code"] not in {"PASS", "PUBLISHED"}:
                raise WorkflowBlocked("ANALYSIS_NOT_PASS")
            report["stage"] = "PUBLISH"
            write_json(output, report)
            published = universe_job.publish(db, context.run_id, config)
            report["publication"] = {"run_id": published.run_id,
                                     "active_count": len(published.active_symbols),
                                     "already_published": published.already_published}
            report["stage"] = "AUDIT"
            report["audit"] = audit_operational_state(db).to_dict()
            if report["audit"]["status"] != "PASS":
                raise WorkflowBlocked("PUBLICATION_AUDIT_FAILED")
            report.update(status="PASS", stage="PREPARED")
            return report
        except Exception as exc:
            report.update(status="BLOCKED", error_type=type(exc).__name__,
                          reason=str(exc) if isinstance(exc, WorkflowBlocked) else "DEPENDENCY_FAILED")
            raise WorkflowBlocked(f"{report['stage']}: {report['reason']}") from None
        finally:
            try:
                if db is not None:
                    db.close()
            finally:
                report["finished_at"] = now_kst().isoformat()
                write_json(output, report)


def run_cycle(*, mode="dry-run", collect=False, output=None, paper_policy=False):
    """One session-aware cycle; PAPER is explicit, REAL is not an option here."""
    if mode not in MODES:
        raise ValueError("mode must be dry-run, simulate or paper")
    output = PROJECT_ROOT / (output or f"logs/system/{mode}/cycle.json")
    with locked(PROJECT_ROOT / "logs/system/cycle.lock", MODES[mode]):
        now = now_kst()
        report = {"status": "RUNNING", "stage": "SESSION_GATE", "mode": MODES[mode],
                  "started_at": now.isoformat(), "broker_orders_enabled": mode == "paper"}
        flag = {"dry-run": "--dry-run", "simulate": "--simulate", "paper": "--mock"}[mode]
        policy_flags = ["--paper-policy"] if paper_policy and mode != "paper" else []
        try:
            write_json(output, report)
            from apps.system.operations import finish_session
            eod = finish_session(now, MODES[mode])
            if eod is not None:
                report.update(status="PASS", stage="EOD_FINISHED", eod=eod)
                return report
            if not is_krx_trading_day(now.date().isoformat()) or not time(8, 0) <= now.time() < time(15, 20):
                report.update(status="WAITING", reason="OUTSIDE_KRX_SESSION")
                return report
            report["stage"] = "PREPARE"
            write_json(output, report)
            receipt = PROJECT_ROOT / "logs/system/collection-session.json"
            try:
                collected = json.loads(receipt.read_text()).get("session") == now.date().isoformat()
            except (OSError, ValueError, AttributeError):
                collected = False
            collect_now = collect and not collected
            report["preparation"] = prepare(effective_date=now.date(), collect=collect_now,
                                            output=output.with_name("preparation.json"))
            if collect_now:
                write_json(receipt, {"session": now.date().isoformat(),
                                     "prepared_at": now_kst().isoformat()})
            report["stage"] = "PREMARKET"
            write_json(output, report)
            rc = run_process([str(PROJECT_ROOT / "run_live_trader.py"), flag, *policy_flags, "--premarket"])
            if rc:
                raise WorkflowBlocked(f"PREMARKET_EXIT_{rc}")
            current = now_kst()
            if current.date() != now.date() or not time(9, 0) <= current.time() < time(15, 20):
                report.update(status="PREPARED", reason="OUTSIDE_ORDER_WINDOW")
                return report
            report["stage"] = "TRADE_CYCLE"
            write_json(output, report)
            dashboard = PROJECT_ROOT / "logs" / MODES[mode].lower() / "dashboard_state.json"
            previous_mtime = dashboard.stat().st_mtime_ns if dashboard.exists() else None
            rc = run_process([str(PROJECT_ROOT / "run_live_trader.py"), flag, *policy_flags])
            if rc:
                raise WorkflowBlocked(f"TRADER_EXIT_{rc}")
            if not dashboard.exists() or dashboard.stat().st_mtime_ns == previous_mtime:
                raise WorkflowBlocked("TRADER_EVIDENCE_NOT_UPDATED")
            state = json.loads(dashboard.read_text())
            if state.get("execution_mode") != MODES[mode]:
                raise WorkflowBlocked("TRADER_EVIDENCE_MODE_MISMATCH")
            report["operational_status"] = state.get("operational_status", "UNKNOWN")
            if report["operational_status"] not in {"NORMAL", "ORDER_DEDUPLICATION"}:
                raise WorkflowBlocked("TRADER_REQUIRES_ATTENTION")
            report.update(status="PASS", stage="CYCLE_FINISHED")
            return report
        except Exception as exc:
            report.update(status="BLOCKED", error_type=type(exc).__name__,
                          reason=str(exc) if isinstance(exc, WorkflowBlocked) else "DEPENDENCY_FAILED")
            current = now_kst()
            if (report["stage"] in {"PREPARE", "PREMARKET"}
                    and current.date() == now.date()
                    and time(9) <= current.time() < time(15, 20)):
                try:
                    rc = run_process([str(PROJECT_ROOT / "run_live_trader.py"), flag,
                                      *policy_flags, "--risk-only"])
                    report["risk_management"] = {"status": "COMPLETED" if rc == 0 else "BLOCKED",
                                                  "exit_code": rc}
                    if rc == 0:
                        dashboard = PROJECT_ROOT / "logs" / MODES[mode].lower() / "dashboard_state.json"
                        state = json.loads(dashboard.read_text()) if dashboard.exists() else {}
                        coverage = (state.get("data_health") or {}).get("risk_check_coverage")
                        report["risk_management"].update(risk_check_coverage=coverage,
                            status="COMPLETED" if coverage == 1 else "PARTIAL" if coverage is not None else "UNVERIFIED")
                except Exception as risk_error:
                    report["risk_management"] = {"status": "BLOCKED", "error_type": type(risk_error).__name__}
            raise WorkflowBlocked(f"{report['stage']}: {report['reason']}") from None
        finally:
            report["finished_at"] = now_kst().isoformat()
            write_json(output, report)
