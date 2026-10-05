"""Finish observed trading sessions and expose watcher progress separately from liveness."""
from datetime import time
import json
from pathlib import Path

from core.utils.io import write_json
from core.utils.trading_calendar import is_krx_trading_day


def finish_session(now, mode):
    from apps.system.workflow import PROJECT_ROOT, run_process, WorkflowBlocked
    if not is_krx_trading_day(now.date().isoformat()) or now.time() < time(15, 30):
        return None
    log_dir = PROJECT_ROOT / "logs" / mode.lower()
    health = log_dir / "operational_health.jsonl"
    rows = []
    if health.exists():
        for line in health.read_text().splitlines():
            try:
                row = json.loads(line)
                if str(row.get("timestamp", ""))[:10] == now.date().isoformat():
                    rows.append(row)
            except (ValueError, AttributeError):
                continue
    if not rows:
        return None  # Never manufacture an operational day that was not observed.
    receipt = log_dir / "eod_report_status.json"
    try:
        old = json.loads(receipt.read_text())
        if old.get("report_date") == now.date().isoformat() and old.get("status") == "READY":
            return dict(old, already_generated=True)
    except (OSError, ValueError, AttributeError):
        pass
    report_dir = PROJECT_ROOT / "reports/promotion" / mode.lower()
    try:
        if mode == "PAPER":
            rc = run_process(["-m", "core.analytics.trading_performance", "--mode", mode,
                              "--date", now.date().isoformat()], timeout=600)
            if rc:
                raise WorkflowBlocked("EOD_GENERATION_FAILED")
        else:
            report = {"mode": mode, "report_date": now.date().isoformat(), "report_status": "FINAL",
                      "generated_at": now.isoformat(), "operations": {"scan_count": len(rows)},
                      "promotion_gate": {"ready": False}, "performance": {}}
            if mode == "SIMULATE":
                from core.execution.simulation_report import build_simulation_report, _markdown
                simulated = build_simulation_report(log_dir, now.date())
                report.update(simulated)
                report["validation"] = {"status": "READY" if simulated["health"] == "PASS" else "BLOCKED"}
                report["performance"].update(ending_total_asset=simulated["account"]["total_asset"],
                                              net_return=simulated["performance"]["cumulative_return"])
                markdown = _markdown(simulated)
            else:
                report["validation"] = {"status": "OBSERVED"}
                markdown = f"# DRY_RUN {now.date()}\n\nObserved scans: {len(rows)}. Hypothetical planning only; no account return.\n"
            daily = report_dir / "daily"
            daily.mkdir(parents=True, exist_ok=True)
            (daily / (now.date().isoformat() + ".md")).write_text(markdown)
            write_json(daily / (now.date().isoformat() + ".json"), report)
            write_json(report_dir / "latest.json", report)
        result = {"status": "READY", "report_date": now.date().isoformat(), "mode": mode,
                  "updated_at": now.isoformat(), "already_generated": False}
        write_json(receipt, result)
        return result
    except Exception:
        write_json(receipt, {"status": "FAILED", "report_date": now.date().isoformat(),
                             "mode": mode, "updated_at": now.isoformat()})
        raise
