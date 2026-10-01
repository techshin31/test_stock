"""Report parsing, summaries and freshness policy, independent of HTTP routes."""
import datetime as dt
import json
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from core.analytics.trading_kpis import sanitize_incident_error
from core.utils.trading_calendar import is_krx_trading_day, previous_krx_trading_day

SEOUL = ZoneInfo("Asia/Seoul")
ReportMode = Literal["DRY_RUN", "PAPER", "REAL"]


def _read_json(path: Path) -> dict:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"Not found: {path.name}") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=500, detail=f"Invalid JSON: {path.name}") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=500, detail=f"Invalid object: {path.name}")
    return payload

def _report_summary(payload: dict, *, filename: str | None = None) -> dict:
    validation = payload.get("validation") or {}
    promotion = payload.get("promotion") or {}
    performance = payload.get("performance") or {}
    operations = payload.get("operations") or {}
    incidents = (
        payload.get("critical_incidents_detail")
        or operations.get("critical_incidents_detail")
        or []
    )
    incident_summary = {
        "total": len(incidents),
        "active": sum(
            incident.get("resolution_status") == "ACTIVE"
            for incident in incidents
            if isinstance(incident, dict)
        ),
        "resolved": sum(
            incident.get("resolution_status") == "RESOLVED"
            for incident in incidents
            if isinstance(incident, dict)
        ),
        "protective": sum(
            incident.get("event_class") == "SAFETY_CONTROL"
            for incident in incidents
            if isinstance(incident, dict)
        ),
        "historical_unclassified": sum(
            not incident.get("resolution_status")
            for incident in incidents
            if isinstance(incident, dict)
        ),
    }
    report_date = str(payload.get("report_date", ""))
    return {
        "filename": filename or f"{report_date}.md",
        "date": report_date,
        "generated_at": payload.get("generated_at"),
        "report_status": payload.get("report_status", "UNKNOWN"),
        "mode": payload.get("mode", "UNKNOWN"),
        "executive_summary": payload.get("executive_summary", ""),
        "validation_status": validation.get(
            "status", performance.get("validation_status", "UNKNOWN")
        ),
        "promotion_target": promotion.get("target_mode"),
        "promotion_ready": bool(promotion.get("ready", False)),
        "blocker_count": len(promotion.get("blockers") or []),
        "incident_summary": incident_summary,
        "performance": {
            "ending_total_asset": performance.get("ending_total_asset"),
            "starting_capital_reference": performance.get(
                "starting_capital_reference"
            ),
            "pnl_vs_starting_capital": performance.get(
                "pnl_vs_starting_capital"
            ),
            "return_vs_starting_capital": performance.get(
                "return_vs_starting_capital"
            ),
            "baseline_date": performance.get("baseline_date"),
            "post_baseline_pnl": performance.get("post_baseline_pnl"),
            "net_return": performance.get("net_return"),
            "benchmark_return": performance.get("benchmark_return"),
            "excess_return": performance.get("excess_return"),
            "max_drawdown": performance.get("max_drawdown"),
        },
        "operations": {
            "scan_count": operations.get("scan_count"),
            "data_freshness_rate": operations.get("data_freshness_rate"),
            "risk_check_coverage": operations.get("risk_check_coverage"),
            "order_reconciliation_rate": operations.get("order_reconciliation_rate"),
            "critical_incidents": operations.get("critical_incidents"),
        },
    }

def _expected_report_date(now: dt.datetime) -> dt.date:
    today = now.date()
    if is_krx_trading_day(today.isoformat()) and now.time() >= dt.time(15, 30):
        return today
    return previous_krx_trading_day(today)

def _report_freshness(
    mode: ReportMode,
    now: dt.datetime,
    latest: dict | None,
    eod_status: dict | None = None,
) -> dict:
    expected = _expected_report_date(now)
    latest_date = None
    if latest and latest.get("report_date"):
        try:
            latest_date = dt.date.fromisoformat(str(latest["report_date"]))
        except ValueError:
            latest_date = None

    due_at = dt.datetime.combine(expected, dt.time(15, 30), tzinfo=SEOUL)
    grace_ends_at = due_at + dt.timedelta(minutes=10)
    is_valid_report = bool(
        latest
        and latest.get("report_status") == "FINAL"
        and (latest.get("validation") or {}).get("status") == "READY"
    )
    if (
        eod_status
        and eod_status.get("status") == "FAILED"
        and (
            eod_status.get("report_date") == expected.isoformat()
            or (latest_date is not None and latest_date >= expected)
        )
    ):
        state = "FAILED"
        diagnostic = next(
            (
                sanitize_incident_error(line.strip()) or "unspecified EOD failure"
                for line in reversed(
                    str(
                        eod_status.get("stderr_tail")
                        or eod_status.get("stdout_tail")
                        or ""
                    ).splitlines()
                )
                if line.strip()
            ),
            "상세 원인은 scheduler 로그를 확인하세요.",
        )
        message = f"공식 EOD 리포트 생성에 실패했습니다: {diagnostic}"
    elif latest_date is not None and latest_date >= expected and is_valid_report:
        state = "CURRENT"
        message = "공식 EOD 리포트가 최신 완료 거래일까지 갱신되었습니다."
    elif latest_date is not None and latest_date >= expected and not is_valid_report:
        state = "FAILED"
        errors = (latest.get("validation") or {}).get("errors") or []
        if errors:
            message = f"공식 EOD 리포트가 차단되었습니다 (BLOCKED): {'; '.join(errors)}"
        else:
            message = "공식 EOD 리포트 검증이 완료되지 않았습니다 (BLOCKED)."
    elif expected == now.date() and now < grace_ends_at:
        state = "GENERATING"
        message = "오늘 공식 EOD 리포트 생성 시간입니다. 15:40까지 자동 갱신을 기다립니다."
    else:
        state = "OVERDUE" if latest_date else "MISSING"
        message = "공식 EOD 리포트가 예정 거래일까지 갱신되지 않았습니다."
    return {
        "state": state,
        "expected_report_date": expected.isoformat(),
        "latest_report_date": latest_date.isoformat() if latest_date else None,
        "due_at": due_at.isoformat(),
        "message": message,
        "mode": mode,
    }
