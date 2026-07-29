import datetime as dt
import json
import math
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

from core.analytics.trading_kpis import sanitize_incident_error
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
    return _sanitize_runtime_errors(data)


def _sanitize_runtime_errors(payload: dict) -> dict:
    """Do not expose append-only broker diagnostics through the local API."""
    safe = dict(payload)
    safe_error = sanitize_incident_error(safe.get("last_error"))
    if safe_error is not None:
        safe["last_error"] = safe_error
    health = safe.get("data_health")
    if isinstance(health, dict):
        safe_health = dict(health)
        dependency_errors = safe_health.get("dependency_errors")
        if isinstance(dependency_errors, list):
            safe_health["dependency_errors"] = [
                sanitize_incident_error(item) or "UNSPECIFIED_DEPENDENCY_ERROR"
                for item in dependency_errors
            ]
        safe["data_health"] = safe_health
    return safe


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
                    rows.append(_sanitize_runtime_errors(payload))
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


@app.get("/api/dashboard")
def get_dashboard_state(mode: ReportMode = "PAPER"):
    return _dashboard(mode)


@app.get("/api/health")
def get_health_logs(
    mode: ReportMode = "PAPER",
    limit: int = Query(default=50, ge=1, le=500),
):
    return _health(mode, limit)


@app.get("/api/healthz", include_in_schema=False)
def get_service_health():
    """Container liveness/readiness probe backed by an actual DB round trip."""
    conn = _db_connect()
    if conn is None:
        raise HTTPException(status_code=503, detail="PostgreSQL is unavailable")
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1 AS ok")
                row = cur.fetchone()
    except (OSError, psycopg.Error):
        raise HTTPException(status_code=503, detail="PostgreSQL is unavailable") from None
    if not isinstance(row, dict) or row.get("ok") != 1:
        raise HTTPException(status_code=503, detail="PostgreSQL health check failed")
    return {"status": "ok", "database": "ready"}


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


def _db_connect():
    """Create a short-lived DB connection for dashboard queries. Returns None on failure."""
    load_dotenv(PROJECT_ROOT / ".env", override=False)
    password = os.getenv("POSTGRES_PASSWORD")
    if not password:
        return None
    try:
        return psycopg.connect(
            host=os.getenv("POSTGRES_HOST", "localhost"),
            port=int(os.getenv("POSTGRES_PORT", "5433")),
            dbname=os.getenv("POSTGRES_DB", "quantpilot_db"),
            user=os.getenv("POSTGRES_USER", "admin"),
            password=password,
            connect_timeout=2,
            row_factory=psycopg.rows.dict_row,
        )
    except (OSError, psycopg.Error):
        return None


# In-memory caches for externally fetched market data.  Values are always
# labelled with their source at the endpoint boundary.
_MARKET_CACHE = {"timestamp": 0, "indices": None, "exchange": None}
_BREADTH_CACHE = {"timestamp": 0, "payload": None, "last_attempt": 0}
_BREADTH_CACHE_SECONDS = 300
_BREADTH_FAILURE_CACHE_SECONDS = 60
_BREADTH_YFINANCE_TIMEOUT_SECONDS = 8


def _finite_float(value: object) -> float | None:
    """Return a finite numeric value without coercing missing data to zero."""
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _latest_volume(frame: object) -> int | None:
    """Read the latest reported volume, preserving unavailable values as None."""
    try:
        if "Volume" not in frame:
            return None
        value = _finite_float(frame["Volume"].iloc[-1])
    except (AttributeError, IndexError, KeyError, TypeError):
        return None
    return int(value) if value is not None and value >= 0 else None


def _index_history_points(kospi: object, kosdaq: object) -> list[dict]:
    """Build only overlapping, observed KOSPI/KOSDAQ closes for the UI chart."""
    try:
        if "Close" not in kospi or "Close" not in kosdaq:
            return []
        common_dates = kospi.index.intersection(kosdaq.index)
    except (AttributeError, TypeError):
        return []

    history: list[dict] = []
    for value_date in common_dates[-5:]:
        try:
            kospi_close = _finite_float(kospi.loc[value_date, "Close"])
            kosdaq_close = _finite_float(kosdaq.loc[value_date, "Close"])
        except (KeyError, TypeError):
            continue
        if kospi_close is None or kosdaq_close is None:
            continue
        date_text = (
            value_date.strftime("%Y-%m-%d")
            if hasattr(value_date, "strftime")
            else str(value_date)[:10]
        )
        history.append(
            {
                "date": date_text,
                "KOSPI": round(kospi_close, 2),
                "KOSDAQ": round(kosdaq_close, 2),
            }
        )
    return history


def _latest_paper_decision() -> dict | None:
    """Read the latest complete PAPER decision without treating a partial write as data."""
    path = LOG_ROOT / "paper" / "decision_history.jsonl"
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    for line in reversed(lines[-100:]):
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            return payload
    return None


def _paper_universe_tickers() -> tuple[list[str], str | None]:
    """Return the actual current strategy universe from its decision record."""
    decision = _latest_paper_decision() or {}
    decisions = decision.get("decisions")
    if not isinstance(decisions, list):
        return [], None
    tickers: list[str] = []
    for item in decisions:
        if not isinstance(item, dict):
            continue
        ticker = str(item.get("ticker") or "").strip()
        if ticker and ticker not in tickers:
            tickers.append(ticker)
    return tickers, decision.get("updated_at")


def _fetch_paper_universe_breadth() -> dict | None:
    """Calculate one-session breadth from the live PAPER strategy universe.

    This is deliberately not a whole-market breadth figure: the caller labels it
    as the PAPER universe and exposes coverage so partial vendor responses remain
    visible to the operator.
    """
    now_ts = time.time()
    cached = _BREADTH_CACHE.get("payload")
    if cached and now_ts - float(_BREADTH_CACHE["timestamp"]) < _BREADTH_CACHE_SECONDS:
        return cached
    # A failed vendor query is real operational state, but retrying it for
    # every dashboard panel makes the UI unresponsive.  Briefly cache only the
    # failure outcome; no market values are fabricated.
    if now_ts - float(_BREADTH_CACHE.get("last_attempt", 0)) < _BREADTH_FAILURE_CACHE_SECONDS:
        return None
    _BREADTH_CACHE["last_attempt"] = now_ts

    tickers, decision_updated_at = _paper_universe_tickers()
    if len(tickers) < 10:
        return None

    try:
        import yfinance as yf

        quotes = yf.download(
            tickers=tickers,
            period="5d",
            group_by="ticker",
            auto_adjust=False,
            progress=False,
            threads=True,
            timeout=_BREADTH_YFINANCE_TIMEOUT_SECONDS,
        )
    except Exception:
        return None
    if getattr(quotes, "empty", True):
        return None

    advancing = declining = unchanged = coverage = 0
    volume_sum = 0
    volume_available = False
    as_of_dates: list[str] = []
    for ticker in tickers:
        try:
            if getattr(quotes.columns, "nlevels", 1) > 1:
                if ticker in quotes.columns.get_level_values(0):
                    frame = quotes[ticker]
                elif ticker in quotes.columns.get_level_values(1):
                    frame = quotes.xs(ticker, axis=1, level=1)
                else:
                    continue
            else:
                frame = quotes
            closes = frame["Close"].dropna().tail(2)
        except (AttributeError, KeyError, TypeError):
            continue
        if len(closes) < 2:
            continue
        previous = _finite_float(closes.iloc[-2])
        current = _finite_float(closes.iloc[-1])
        if previous is None or current is None or previous <= 0:
            continue

        coverage += 1
        if current > previous:
            advancing += 1
        elif current < previous:
            declining += 1
        else:
            unchanged += 1
        latest_volume = _latest_volume(frame)
        if latest_volume is not None:
            volume_sum += latest_volume
            volume_available = True
        value_date = closes.index[-1]
        as_of_dates.append(
            value_date.strftime("%Y-%m-%d")
            if hasattr(value_date, "strftime")
            else str(value_date)[:10]
        )

    minimum_coverage = max(10, math.ceil(len(tickers) * 0.8))
    if coverage < minimum_coverage:
        return None

    payload = {
        "advancing": advancing,
        "declining": declining,
        "unchanged": unchanged,
        "total": coverage,
        "advance_ratio": round(advancing / coverage, 6),
        "trading_volume": volume_sum if volume_available else None,
        "universe_size": len(tickers),
        "coverage": coverage,
        "coverage_rate": round(coverage / len(tickers), 6),
        "as_of_date": max(as_of_dates) if as_of_dates else None,
        "decision_updated_at": decision_updated_at,
        "updated_at": dt.datetime.now(SEOUL).strftime("%Y-%m-%d %H:%M"),
    }
    _BREADTH_CACHE["timestamp"] = now_ts
    _BREADTH_CACHE["payload"] = payload
    return payload


def _fetch_live_yfinance():
    """Fetch live KOSPI, KOSDAQ, USD/KRW data from yfinance with 5-min caching."""
    now_ts = time.time()
    if _MARKET_CACHE["indices"] and (now_ts - _MARKET_CACHE["timestamp"]) < 300:
        return _MARKET_CACHE["indices"], _MARKET_CACHE["exchange"]

    try:
        import yfinance as yf
        now_str = dt.datetime.now(SEOUL).strftime("%Y-%m-%d %H:%M")
        
        # KOSPI & KOSDAQ
        kospi_t = yf.Ticker("^KS11").history(period="5d")
        kosdaq_t = yf.Ticker("^KQ11").history(period="5d")
        usd_t = yf.Ticker("KRW=X").history(period="5d")

        indices = None
        if not kospi_t.empty and not kosdaq_t.empty:
            k_price = float(kospi_t["Close"].iloc[-1])
            k_prev = float(kospi_t["Close"].iloc[-2]) if len(kospi_t) > 1 else k_price
            k_change = k_price - k_prev
            k_rate = (k_change / k_prev * 100) if k_prev else 0

            kq_price = float(kosdaq_t["Close"].iloc[-1])
            kq_prev = float(kosdaq_t["Close"].iloc[-2]) if len(kosdaq_t) > 1 else kq_price
            kq_change = kq_price - kq_prev
            kq_rate = (kq_change / kq_prev * 100) if kq_prev else 0

            indices = {
                "kospi": {
                    "price": round(k_price, 2),
                    "change": round(k_change, 2),
                    "change_rate": round(k_rate, 2),
                    "volume": _latest_volume(kospi_t),
                },
                "kosdaq": {
                    "price": round(kq_price, 2),
                    "change": round(kq_change, 2),
                    "change_rate": round(kq_rate, 2),
                    "volume": _latest_volume(kosdaq_t),
                },
                "history": _index_history_points(kospi_t, kosdaq_t),
                "updated_at": now_str,
            }

        exchange = None
        if not usd_t.empty:
            u_price = float(usd_t["Close"].iloc[-1])
            u_prev = float(usd_t["Close"].iloc[-2]) if len(usd_t) > 1 else u_price
            u_change = u_price - u_prev
            u_rate = (u_change / u_prev * 100) if u_prev else 0
            exchange = {
                "usd_krw": round(u_price, 2),
                "change": round(u_change, 2),
                "change_rate": round(u_rate, 2),
                "updated_at": now_str,
            }

        if indices and exchange:
            _MARKET_CACHE["indices"] = indices
            _MARKET_CACHE["exchange"] = exchange
            _MARKET_CACHE["timestamp"] = now_ts
            return indices, exchange
    except Exception:
        pass

    return None, None


def _available_market_payload(payload: dict, source: str) -> dict:
    """Mark market data with an explicit authoritative source."""
    return {**payload, "available": True, "source": source}


def _unavailable_market_payload(message: str, **payload: object) -> dict:
    """Return an explicit empty state instead of invented market numbers."""
    return {
        **payload,
        "available": False,
        "source": "UNAVAILABLE",
        "updated_at": None,
        "message": message,
    }


@app.get("/api/market-indices")
def get_market_indices():
    """KOSPI / KOSDAQ latest index values via live yfinance, dashboard state, or DB."""
    # 1. Try live yfinance fetch
    live_indices, _ = _fetch_live_yfinance()
    if live_indices:
        return _available_market_payload(live_indices, "YFINANCE_LIVE")

    result = {"kospi": None, "kosdaq": None}
    # 2. Try reading from dashboard state
    for mode_key in ("paper", "dry_run"):
        path = LOG_ROOT / mode_key / "dashboard_state.json"
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                market = data.get("market_indices") or data.get("market") or {}
                if market:
                    result["kospi"] = market.get("kospi")
                    result["kosdaq"] = market.get("kosdaq")
                    result["updated_at"] = data.get("updated_at")
                    return _available_market_payload(result, "DASHBOARD_STATE")
            except (OSError, json.JSONDecodeError):
                pass

    # Fallback: try DB for macro_signals
    conn = _db_connect()
    if conn:
        try:
            with conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT signal_name, signal_value, signal_date "
                        "FROM macro_signals "
                        "WHERE signal_name IN ('kospi_close', 'kosdaq_close', "
                        "'kospi_change', 'kosdaq_change', 'kospi_change_rate', 'kosdaq_change_rate', "
                        "'kospi_volume', 'kosdaq_volume') "
                        "AND signal_date = (SELECT MAX(signal_date) FROM macro_signals "
                        "WHERE signal_name = 'kospi_close') "
                        "ORDER BY signal_name"
                    )
                    rows = cur.fetchall()
                    signals = {r["signal_name"]: float(r["signal_value"]) for r in rows}
                    if signals:
                        result["kospi"] = {
                            "price": signals.get("kospi_close", 0),
                            "change": signals.get("kospi_change", 0),
                            "change_rate": signals.get("kospi_change_rate", 0),
                            "volume": signals.get("kospi_volume", 0),
                        }
                        result["kosdaq"] = {
                            "price": signals.get("kosdaq_close", 0),
                            "change": signals.get("kosdaq_change", 0),
                            "change_rate": signals.get("kosdaq_change_rate", 0),
                            "volume": signals.get("kosdaq_volume", 0),
                        }
                        result["updated_at"] = str(rows[0]["signal_date"]) if rows else None
                        return _available_market_payload(result, "DB_MACRO_SIGNALS")
        except (OSError, psycopg.Error):
            pass
    return _unavailable_market_payload(
        "Authoritative KOSPI/KOSDAQ data is not available.",
        kospi=None,
        kosdaq=None,
    )


@app.get("/api/market-breadth")
def get_market_breadth():
    """Advancing / declining / unchanged stock counts from latest dashboard state."""
    for mode_key in ("paper", "dry_run"):
        path = LOG_ROOT / mode_key / "dashboard_state.json"
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                breadth = data.get("market_breadth") or data.get("breadth") or {}
                required = {
                    "advancing",
                    "declining",
                    "unchanged",
                    "total",
                    "advance_ratio",
                    "trading_volume",
                }
                if required.issubset(breadth) and int(breadth["total"] or 0) > 0:
                    return _available_market_payload(breadth, "DASHBOARD_STATE")
            except (OSError, json.JSONDecodeError):
                pass
    paper_breadth = _fetch_paper_universe_breadth()
    if paper_breadth:
        return _available_market_payload(paper_breadth, "YFINANCE_PAPER_UNIVERSE")

    return _unavailable_market_payload(
        "Market breadth has not been collected and the PAPER universe could not be quoted.",
        advancing=None,
        declining=None,
        unchanged=None,
        total=None,
        advance_ratio=None,
        trading_volume=None,
        universe_size=None,
        coverage=None,
        coverage_rate=None,
    )


def _expected_completed_krx_date(now: dt.datetime | None = None) -> dt.date:
    """Return the latest KRX session expected to have a completed close."""
    current = (now or dt.datetime.now(SEOUL)).astimezone(SEOUL)
    today = current.date()
    if is_krx_trading_day(today.isoformat()) and current.time() >= dt.time(15, 30):
        return today
    return previous_krx_trading_day(today)


def _sector_payload_from_prices(
    cur: object,
    *,
    source_code: str,
    method_version: str,
    source_label: str,
) -> dict | None:
    """Build a current WICS sector payload from one clearly identified source."""
    cur.execute(
        "SELECT DISTINCT price_date FROM wics_industry_prices "
        "WHERE source_code = %s AND method_version = %s "
        "ORDER BY price_date DESC LIMIT 2",
        (source_code, method_version),
    )
    dates = [row["price_date"] for row in cur.fetchall()]
    if len(dates) < 2:
        return None
    latest_date, previous_date = dates[0], dates[1]
    if latest_date != _expected_completed_krx_date():
        return None

    cur.execute(
        "SELECT code, name FROM codes "
        "WHERE code_group = 'WICS_INDUSTRY_CODE' "
        "AND name IS NOT NULL"
    )
    industry_names = {row["code"]: row["name"] for row in cur.fetchall()}
    cur.execute(
        "SELECT industry_code, price_date, index_value "
        "FROM wics_industry_prices "
        "WHERE source_code = %s AND method_version = %s "
        "AND price_date IN (%s, %s) "
        "ORDER BY industry_code, price_date",
        (source_code, method_version, latest_date, previous_date),
    )
    by_industry: dict[str, dict] = {}
    for row in cur.fetchall():
        by_industry.setdefault(row["industry_code"], {})[row["price_date"]] = float(
            row["index_value"]
        )

    items: list[dict] = []
    for code, prices in by_industry.items():
        previous_value = prices.get(previous_date)
        latest_value = prices.get(latest_date)
        if previous_value is None or latest_value is None or previous_value <= 0:
            continue
        items.append(
            {
                "code": code,
                "name": industry_names.get(code, code),
                "change_rate": round(
                    (latest_value - previous_value) / previous_value * 100, 2
                ),
                "index_value": round(latest_value, 2),
                "prev_value": round(previous_value, 2),
            }
        )
    if not items:
        return None
    items.sort(key=lambda item: item["change_rate"], reverse=True)

    cur.execute(
        "SELECT MAX(base_date) AS base_date FROM wics_companies "
        "WHERE base_date <= %s",
        (latest_date,),
    )
    snapshot = cur.fetchone() or {}
    snapshot_date = snapshot.get("base_date")
    if snapshot_date:
        cur.execute(
            "SELECT industry_code, SUM(NULLIF(trd_amt, 'NaN'::numeric)) AS volume, "
            "SUM(NULLIF(mkt_val, 'NaN'::numeric)) AS market_cap, "
            "COUNT(*) AS stock_count FROM wics_companies WHERE base_date = %s "
            "GROUP BY industry_code",
            (snapshot_date,),
        )
        metrics = {row["industry_code"]: row for row in cur.fetchall()}
        cur.execute(
            "SELECT wc.industry_code, c.company_name, wc.stock_code "
            "FROM wics_companies wc JOIN companies c ON wc.stock_code = c.stock_code "
            "WHERE wc.base_date = %s AND wc.mkt_val IS NOT NULL "
            "ORDER BY wc.industry_code, wc.mkt_val DESC",
            (snapshot_date,),
        )
        top_stocks: dict[str, str] = {}
        for row in cur.fetchall():
            top_stocks.setdefault(
                row["industry_code"], row["company_name"] or row["stock_code"]
            )
    else:
        metrics = {}
        top_stocks = {}
    for item in items:
        metric = metrics.get(item["code"], {})
        volume = _finite_float(metric.get("volume"))
        market_cap = _finite_float(metric.get("market_cap"))
        stock_count = _finite_float(metric.get("stock_count"))
        item["volume"] = int(volume) if volume is not None else None
        item["market_cap"] = int(market_cap) if market_cap is not None else None
        item["stock_count"] = int(stock_count) if stock_count is not None else None
        item["top_stock"] = top_stocks.get(item["code"], "")

    return _available_market_payload(
        {
            "items": items,
            "updated_at": latest_date.isoformat(),
            "constituent_snapshot_date": (
                snapshot_date.isoformat() if snapshot_date else None
            ),
            "top": items[:5],
            "bottom": list(reversed(items[-5:])) if len(items) >= 5 else list(reversed(items)),
        },
        source_label,
    )


@app.get("/api/sectors")
def get_sectors():
    """Current WICS sector performance, preferring official over derived levels."""
    conn = _db_connect()
    if conn:
        try:
            with conn:
                with conn.cursor() as cur:
                    for source_code, method_version, source_label in (
                        ("WISEINDEX", "OFFICIAL", "WICS_OFFICIAL"),
                        ("DERIVED", "mcap-v1", "WICS_DERIVED_MCAP_V1"),
                    ):
                        payload = _sector_payload_from_prices(
                            cur,
                            source_code=source_code,
                            method_version=method_version,
                            source_label=source_label,
                        )
                        if payload:
                            return payload
        except (OSError, psycopg.Error):
            pass
    return _unavailable_market_payload(
        "Current official or derived WICS sector data is not available.",
        items=[],
        top=[],
        bottom=[],
    )


@app.get("/api/exchange-rate")
def get_exchange_rate():
    """USD/KRW exchange rate from yfinance or macro_signals."""
    _, live_exchange = _fetch_live_yfinance()
    if live_exchange:
        return _available_market_payload(live_exchange, "YFINANCE_LIVE")

    conn = _db_connect()
    if conn:
        try:
            with conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT signal_value, signal_date FROM macro_signals "
                        "WHERE signal_name = 'usd_krw' "
                        "ORDER BY signal_date DESC LIMIT 2"
                    )
                    rows = cur.fetchall()
                    if rows:
                        latest = float(rows[0]["signal_value"])
                        prev = float(rows[1]["signal_value"]) if len(rows) > 1 else latest
                        change = latest - prev
                        change_rate = (change / prev * 100) if prev != 0 else 0
                        return _available_market_payload({
                            "usd_krw": round(latest, 2),
                            "change": round(change, 2),
                            "change_rate": round(change_rate, 2),
                            "updated_at": rows[0]["signal_date"].isoformat() if rows[0].get("signal_date") else None,
                        }, "DB_MACRO_SIGNALS")
        except (OSError, psycopg.Error):
            pass
    return _unavailable_market_payload(
        "Authoritative USD/KRW data is not available.",
        usd_krw=None,
        change=None,
        change_rate=None,
    )


@app.get("/api/journal")
def get_journal(
    mode: ReportMode = "PAPER",
    limit: int = Query(default=50, ge=1, le=200),
):
    """Trading journal: recent trades, daily asset PnL, monthly summary based on certified asset reports."""
    venue = _mode_key(mode).upper()
    now = dt.datetime.now(SEOUL)

    # 1. Try loading performance data from certified latest report
    latest_report_path = REPORT_ROOT / _mode_key(mode) / "latest.json"
    summary = None
    daily_pnl = []
    monthly = []
    benchmark_history = []

    if latest_report_path.exists():
        try:
            report_data = json.loads(latest_report_path.read_text(encoding="utf-8"))
            perf = report_data.get("performance") or {}
            trend = report_data.get("performance_trend") or []

            starting_cap = float(perf["starting_capital_reference"])
            ending_asset = float(perf["ending_total_asset"])
            total_realized_pnl = float(
                perf.get("pnl_vs_starting_capital", ending_asset - starting_cap)
            )

            # Calculate daily asset changes
            if trend:
                for i in range(len(trend)):
                    d_item = trend[i]
                    d_date = d_item.get("date", "")
                    curr_asset = float(d_item.get("total_asset", 0))
                    prev_asset = float(trend[i-1].get("total_asset", starting_cap)) if i > 0 else starting_cap
                    d_pnl = curr_asset - prev_asset
                    daily_pnl.append({
                        "date": d_date,
                        "realized_pnl": round(d_pnl),
                        "trade_count": 0,
                    })
                    benchmark_return = d_item.get("benchmark_return")
                    cumulative_return = d_item.get("cumulative_return")
                    if isinstance(benchmark_return, (int, float)) and isinstance(
                        cumulative_return, (int, float)
                    ):
                        benchmark_history.append(
                            {
                                "date": d_date,
                                "portfolio_return": round(cumulative_return * 100, 2),
                                "benchmark_return": round(benchmark_return * 100, 2),
                            }
                        )

            pos_days = [dp for dp in daily_pnl if dp["realized_pnl"] > 0]
            neg_days = [dp for dp in daily_pnl if dp["realized_pnl"] < 0]

            total_pos = sum(dp["realized_pnl"] for dp in pos_days)
            total_neg = abs(sum(dp["realized_pnl"] for dp in neg_days))

            avg_profit = round(total_pos / len(pos_days)) if pos_days else 0
            avg_loss = round(-total_neg / len(neg_days)) if neg_days else 0
            profit_factor = round(total_pos / total_neg, 2) if total_neg > 0 else None

            win_rate = round(len(pos_days) / len(daily_pnl), 3) if daily_pnl else None

            summary = {
                "observed_sessions": len(daily_pnl),
                "positive_sessions": len(pos_days),
                "negative_sessions": len(neg_days),
                "win_rate": win_rate,
                "starting_capital": starting_cap,
                "ending_asset": ending_asset,
                "pnl_vs_starting_capital": round(total_realized_pnl),
                "avg_profit": avg_profit,
                "avg_loss": avg_loss,
                "profit_factor": profit_factor,
            }

            monthly = [{
                "month": now.strftime("%Y-%m"),
                "sessions": len(daily_pnl),
                "pnl": round(total_realized_pnl),
                "win_rate": win_rate,
            }]
        except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
            pass

    # 2. Get executed trades from DB orders
    trades = []
    conn = _db_connect()
    if conn:
        try:
            with conn:
                with conn.cursor() as cur:
                    stock_names = _load_stock_names()
                    cur.execute(
                        "SELECT o.id, o.symbol, o.order_side_code, o.qty, o.price, "
                        "o.filled_qty, o.avg_fill_price, o.order_status_code, "
                        "o.created_at, o.filled_at, "
                        "COALESCE(o.avg_fill_price * o.filled_qty, 0) as total_amount "
                        "FROM orders o "
                        "WHERE o.execution_venue_code = %s "
                        "AND o.order_status_code IN ('FILLED', 'PARTIALLY_FILLED', 'PENDING') "
                        "ORDER BY o.created_at DESC LIMIT %s",
                        (venue, limit),
                    )
                    raw_trades = cur.fetchall()
                    for t in raw_trades:
                        symbol = str(t["symbol"])
                        trades.append({
                            "id": str(t["id"]),
                            "date": t["created_at"].strftime("%Y-%m-%d") if t["created_at"] else "",
                            "ticker": symbol,
                            "name": stock_names.get(symbol.split(".")[0], symbol),
                            "side": t["order_side_code"],
                            "qty": int(float(t["filled_qty"] or t["qty"] or 0)),
                            "price": float(t["avg_fill_price"] or t["price"] or 0),
                            "total": float(t["total_amount"] or 0),
                            "status": t["order_status_code"],
                        })
        except (OSError, psycopg.Error):
            pass

    if summary:
        return {
            "available": True,
            "source": "CERTIFIED_EOD_REPORT",
            "trades": trades,
            "daily_pnl": list(reversed(daily_pnl)),
            "monthly": monthly,
            "benchmark_history": benchmark_history,
            "summary": summary,
            "updated_at": now.isoformat(),
        }

    return {
        "available": False,
        "source": "UNAVAILABLE",
        "message": "A certified EOD performance report is not available.",
        "trades": [],
        "daily_pnl": [],
        "monthly": [],
        "benchmark_history": [],
        "summary": None,
        "updated_at": None,
    }


@app.get("/api/market-regime")
def get_market_regime():
    """Current market regime classification, retaining only observed model output."""
    valid_regimes = {"UPTREND", "DOWNTREND", "SIDEWAYS", "TRANSITION"}

    def payload_for(
        current: object,
        source: str,
        *,
        confidence: object = None,
        signal: object = None,
        adx: object = None,
        trend_strength: object = None,
        updated_at: object = None,
    ) -> dict | None:
        normalized = str(current or "").upper()
        if normalized not in valid_regimes:
            return None
        return _available_market_payload(
            {
                "current": normalized,
                "confidence": _finite_float(confidence),
                "signal": str(signal) if signal else None,
                "adx": _finite_float(adx),
                "trend_strength": str(trend_strength) if trend_strength else None,
                "updated_at": updated_at,
            },
            source,
        )

    # Try analysis report first
    regime_path = ANALYSIS_ROOT / "market_regime.json"
    if regime_path.exists():
        try:
            data = json.loads(regime_path.read_text(encoding="utf-8"))
            payload = payload_for(
                data.get("regime") or data.get("current"),
                "MARKET_REGIME_ANALYSIS",
                confidence=data.get("confidence"),
                signal=data.get("signal"),
                adx=data.get("adx"),
                trend_strength=data.get("trend_strength"),
                updated_at=data.get("updated_at") or data.get("analysis_date"),
            )
            if payload:
                return payload
        except (OSError, json.JSONDecodeError):
            pass

    # Try dashboard state
    for mode_key in ("paper", "dry_run"):
        path = LOG_ROOT / mode_key / "dashboard_state.json"
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                regime = data.get("market_regime") or data.get("regime")
                if regime:
                    if isinstance(regime, str):
                        payload = payload_for(
                            regime,
                            "DASHBOARD_STATE",
                            updated_at=data.get("updated_at"),
                        )
                    elif isinstance(regime, dict):
                        payload = payload_for(
                            regime.get("current") or regime.get("regime"),
                            "DASHBOARD_STATE",
                            confidence=regime.get("confidence"),
                            signal=regime.get("signal"),
                            adx=regime.get("adx"),
                            trend_strength=regime.get("trend_strength"),
                            updated_at=regime.get("updated_at") or data.get("updated_at"),
                        )
                    else:
                        payload = None
                    if payload:
                        return payload
            except (OSError, json.JSONDecodeError):
                pass

    decision = _latest_paper_decision()
    if decision:
        payload = payload_for(
            decision.get("market_regime"),
            "PAPER_DECISION_HISTORY",
            updated_at=decision.get("updated_at"),
        )
        if payload:
            return payload

    return _unavailable_market_payload(
        "Market regime analysis is not available.",
        current=None,
        confidence=None,
        signal=None,
        adx=None,
        trend_strength=None,
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("api.main:app", host="127.0.0.1", port=8000, reload=True)
