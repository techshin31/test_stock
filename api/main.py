import datetime as dt
import json
import os
import re
import threading
import time
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo

import psycopg
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from core.utils.trading_calendar import (
    is_krx_trading_day,
    previous_krx_trading_day,
)


PROJECT_ROOT = Path(__file__).resolve().parent.parent
REPORT_ROOT = PROJECT_ROOT / "reports" / "promotion"
ANALYSIS_ROOT = PROJECT_ROOT / "reports" / "analysis"
LOG_ROOT = PROJECT_ROOT / "logs"
SEOUL = ZoneInfo("Asia/Seoul")
REPORT_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
ReportMode = Literal["DRY_RUN", "PAPER", "REAL"]
STOCK_NAME_CACHE_SECONDS = 60 * 60
_stock_name_cache: dict[str, str] = {}
_stock_name_cache_loaded_at = 0.0
_stock_name_cache_lock = threading.Lock()

app = FastAPI(
    title="QuantPilot Operations API",
    description="Read-only, mode-scoped PAPER operations and EOD report API.",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=False,
    allow_methods=["GET"],
    allow_headers=["*"],
)


def _mode_key(mode: ReportMode) -> str:
    return mode.lower()


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


def _normalize_position(item: object) -> dict:
    if isinstance(item, str):
        return {
            "ticker": item,
            "name": item,
            "qty": 0,
            "current_price": 0.0,
            "avg_price": 0.0,
            "profit_rate": 0.0,
        }
    if not isinstance(item, dict):
        return {
            "ticker": "",
            "name": "",
            "qty": 0,
            "current_price": 0.0,
            "avg_price": 0.0,
            "profit_rate": 0.0,
        }
    ticker = str(item.get("ticker", ""))
    return {
        **item,
        "ticker": ticker,
        "name": str(item.get("name") or ticker),
        "qty": item.get("qty", 0),
        "current_price": item.get("current_price", 0.0),
        "avg_price": item.get("avg_price", 0.0),
        "profit_rate": item.get("profit_rate", 0.0),
    }


def _load_stock_names() -> dict[str, str]:
    """Load company names from local PostgreSQL without making the API depend on it."""
    global _stock_name_cache_loaded_at
    now = time.monotonic()
    if _stock_name_cache and now - _stock_name_cache_loaded_at < STOCK_NAME_CACHE_SECONDS:
        return _stock_name_cache
    with _stock_name_cache_lock:
        now = time.monotonic()
        if _stock_name_cache and now - _stock_name_cache_loaded_at < STOCK_NAME_CACHE_SECONDS:
            return _stock_name_cache
        load_dotenv(PROJECT_ROOT / ".env", override=False)
        password = os.getenv("POSTGRES_PASSWORD")
        if not password:
            return _stock_name_cache
        try:
            with psycopg.connect(
                host=os.getenv("POSTGRES_HOST", "localhost"),
                port=int(os.getenv("POSTGRES_PORT", "5433")),
                dbname=os.getenv("POSTGRES_DB", "quantpilot_db"),
                user=os.getenv("POSTGRES_USER", "admin"),
                password=password,
                connect_timeout=2,
            ) as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        "SELECT stock_code, company_name FROM companies "
                        "WHERE company_name IS NOT NULL AND company_name <> ''"
                    )
                    _stock_name_cache.clear()
                    _stock_name_cache.update(
                        {
                            str(stock_code): str(company_name)
                            for stock_code, company_name in cursor.fetchall()
                        }
                    )
                    _stock_name_cache_loaded_at = now
        except (OSError, psycopg.Error):
            # Account monitoring must stay available even if the metadata DB is down.
            return _stock_name_cache
    return _stock_name_cache


def _dashboard(mode: ReportMode) -> dict:
    path = LOG_ROOT / _mode_key(mode) / "dashboard_state.json"
    data = _read_json(path)
    positions = [
        _normalize_position(item) for item in data.get("positions", [])
    ]
    stock_names = _load_stock_names()
    for position in positions:
        ticker = position["ticker"]
        current_name = position.get("name")
        if not current_name or current_name == ticker:
            position["name"] = stock_names.get(ticker.split(".")[0], ticker)
    data["positions"] = positions
    return data


def _health(mode: ReportMode, limit: int) -> list[dict]:
    path = LOG_ROOT / _mode_key(mode) / "operational_health.jsonl"
    if not path.exists():
        return []
    rows: list[dict] = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines()[-limit:]:
            if line.strip():
                payload = json.loads(line)
                if isinstance(payload, dict):
                    rows.append(payload)
    except (OSError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=500, detail="Operational health log is invalid") from exc
    return rows


def _report_summary(payload: dict, *, filename: str | None = None) -> dict:
    validation = payload.get("validation") or {}
    promotion = payload.get("promotion") or {}
    performance = payload.get("performance") or {}
    operations = payload.get("operations") or {}
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


def _latest_report(mode: ReportMode) -> tuple[dict | None, dict | None]:
    path = REPORT_ROOT / _mode_key(mode) / "latest.json"
    if not path.exists():
        return None, None
    payload = _read_json(path)
    return payload, _report_summary(payload)


def _system_readiness(mode: ReportMode) -> dict | None:
    if mode != "PAPER":
        return None
    path = ANALYSIS_ROOT / "automated_trading_system_readiness.json"
    if not path.exists():
        return None
    return _read_json(path)


def _eod_report_status(mode: ReportMode) -> dict | None:
    path = LOG_ROOT / _mode_key(mode) / "eod_report_status.json"
    if not path.exists():
        return None
    return _read_json(path)


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
                line.strip()
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


@app.get("/api/dashboard")
def get_dashboard_state(mode: ReportMode = "PAPER"):
    return _dashboard(mode)


@app.get("/api/health")
def get_health_logs(
    mode: ReportMode = "PAPER",
    limit: int = Query(default=50, ge=1, le=500),
):
    return _health(mode, limit)


@app.get("/api/overview")
def get_overview(mode: ReportMode = "PAPER"):
    now = dt.datetime.now(SEOUL)
    latest_payload, latest_summary = _latest_report(mode)
    eod_status = _eod_report_status(mode)
    return {
        "mode": mode,
        "server_time": now.isoformat(),
        "dashboard": _dashboard(mode),
        "health": _health(mode, 30),
        "latest_report": latest_summary,
        "report_freshness": _report_freshness(
            mode, now, latest_payload, eod_status
        ),
        "eod_report_status": eod_status,
        "system_readiness": _system_readiness(mode),
    }


@app.get("/api/system-readiness")
def get_system_readiness(mode: ReportMode = "PAPER"):
    readiness = _system_readiness(mode)
    if readiness is None:
        raise HTTPException(status_code=404, detail="System readiness is unavailable")
    return readiness


@app.get("/api/reports")
def list_reports(mode: ReportMode = "PAPER"):
    daily_dir = REPORT_ROOT / _mode_key(mode) / "daily"
    if not daily_dir.exists():
        return []
    reports = []
    for json_path in daily_dir.glob("*.json"):
        if not REPORT_DATE_RE.fullmatch(json_path.stem):
            continue
        try:
            payload = json.loads(json_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(payload, dict):
            reports.append(_report_summary(payload, filename=f"{json_path.stem}.md"))
    return sorted(reports, key=lambda item: item["date"], reverse=True)


@app.get("/api/reports/{report_date}")
def get_report(report_date: str, mode: ReportMode = "PAPER"):
    normalized = report_date.removesuffix(".md")
    if not REPORT_DATE_RE.fullmatch(normalized):
        raise HTTPException(status_code=400, detail="Report date must be YYYY-MM-DD")
    try:
        dt.date.fromisoformat(normalized)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid report date") from exc
    daily_dir = (REPORT_ROOT / _mode_key(mode) / "daily").resolve()
    markdown_path = (daily_dir / f"{normalized}.md").resolve()
    json_path = (daily_dir / f"{normalized}.json").resolve()
    if markdown_path.parent != daily_dir or json_path.parent != daily_dir:
        raise HTTPException(status_code=400, detail="Invalid report path")
    if not markdown_path.exists() or not json_path.exists():
        raise HTTPException(status_code=404, detail="Report not found")
    try:
        content = markdown_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise HTTPException(status_code=500, detail="Report could not be read") from exc
    payload = _read_json(json_path)
    return {
        "content": content,
        "report": _report_summary(payload, filename=markdown_path.name),
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("api.main:app", host="127.0.0.1", port=8000, reload=True)
