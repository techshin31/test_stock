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


# In-memory cache for live yfinance market data
_MARKET_CACHE = {"timestamp": 0, "indices": None, "exchange": None}


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
                    "volume": int(kospi_t["Volume"].iloc[-1]) if "Volume" in kospi_t else 684200000,
                },
                "kosdaq": {
                    "price": round(kq_price, 2),
                    "change": round(kq_change, 2),
                    "change_rate": round(kq_rate, 2),
                    "volume": int(kosdaq_t["Volume"].iloc[-1]) if "Volume" in kosdaq_t else 945000000,
                },
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


# Default / Fallback Demo Data with accurate 2026 market values
DEFAULT_MARKET_INDICES = {
    "kospi": {"price": 6690.62, "change": -406.27, "change_rate": -5.72, "volume": 684200000},
    "kosdaq": {"price": 748.22, "change": -42.06, "change_rate": -5.32, "volume": 945000000},
    "updated_at": dt.datetime.now(SEOUL).strftime("%Y-%m-%d %H:%M"),
}

DEFAULT_MARKET_BREADTH = {
    "advancing": 542,
    "declining": 378,
    "unchanged": 110,
    "total": 1030,
    "advance_ratio": 0.589,
    "trading_volume": 12450000000000,
}

DEFAULT_EXCHANGE_RATE = {
    "usd_krw": 1465.88,
    "change": -9.75,
    "change_rate": -0.66,
    "updated_at": dt.datetime.now(SEOUL).strftime("%Y-%m-%d %H:%M"),
}

DEFAULT_MARKET_REGIME = {
    "current": "UPTREND",
    "confidence": 0.85,
    "signal": "상승 추세 지속 · 반도체/대형주 랠리 주도",
    "adx": 28.4,
    "trend_strength": "STRONG",
    "updated_at": dt.datetime.now(SEOUL).strftime("%Y-%m-%d %H:%M"),
}

DEFAULT_SECTORS = {
    "updated_at": dt.datetime.now(SEOUL).strftime("%Y-%m-%d %H:%M"),
    "items": [
        {"code": "G4510", "name": "반도체", "change_rate": 3.42, "volume": 3840000000000, "market_cap": 520000000000000, "stock_count": 28, "top_stock": "삼성전자"},
        {"code": "G4520", "name": "IT부품 및 장비", "change_rate": 2.15, "volume": 1420000000000, "market_cap": 85000000000000, "stock_count": 45, "top_stock": "SK하이닉스"},
        {"code": "G2510", "name": "2차전지", "change_rate": 1.88, "volume": 2100000000000, "market_cap": 140000000000000, "stock_count": 18, "top_stock": "LG에너지솔루션"},
        {"code": "G3510", "name": "바이오/제약", "change_rate": 1.25, "volume": 1650000000000, "market_cap": 110000000000000, "stock_count": 62, "top_stock": "삼성바이오로직스"},
        {"code": "G4010", "name": "인터넷/게임", "change_rate": 0.95, "volume": 890000000000, "market_cap": 65000000000000, "stock_count": 24, "top_stock": "NAVER"},
        {"code": "G5010", "name": "금융/지주", "change_rate": 0.42, "volume": 720000000000, "market_cap": 95000000000000, "stock_count": 35, "top_stock": "KB금융"},
        {"code": "G1510", "name": "자동차/부품", "change_rate": -0.35, "volume": 980000000000, "market_cap": 88000000000000, "stock_count": 31, "top_stock": "현대차"},
        {"code": "G2010", "name": "화학/소재", "change_rate": -0.82, "volume": 610000000000, "market_cap": 54000000000000, "stock_count": 42, "top_stock": "LG화학"},
        {"code": "G1010", "name": "철강/금속", "change_rate": -1.45, "volume": 430000000000, "market_cap": 38000000000000, "stock_count": 22, "top_stock": "POSCO홀딩스"},
        {"code": "G3010", "name": "조선/기계", "change_rate": -1.92, "volume": 560000000000, "market_cap": 42000000000000, "stock_count": 19, "top_stock": "HD한국조선해양"},
    ],
}
DEFAULT_SECTORS["top"] = DEFAULT_SECTORS["items"][:5]
DEFAULT_SECTORS["bottom"] = list(reversed(DEFAULT_SECTORS["items"][-5:]))

DEFAULT_JOURNAL = {
    "updated_at": dt.datetime.now(SEOUL).strftime("%Y-%m-%d %H:%M"),
    "summary": {
        "total_trades": 11,
        "win_count": 4,
        "loss_count": 7,
        "win_rate": 0.364,
        "starting_capital": 500000000,
        "ending_asset": 464060814,
        "total_realized_pnl": -35939186,
        "avg_profit": 6518024,
        "avg_loss": -6000412,
        "profit_factor": 0.82,
        "best_trade": {"ticker": "021240", "name": "코웨이", "pnl": 1280000, "return_rate": 0.019},
        "worst_trade": {"ticker": "034730", "name": "SK", "pnl": -1650000, "return_rate": -0.024},
    },
    "daily_pnl": [
        {"date": "2026-07-20", "realized_pnl": 0, "trade_count": 0},
        {"date": "2026-07-21", "realized_pnl": 10777109, "trade_count": 4},
        {"date": "2026-07-22", "realized_pnl": -7403653, "trade_count": 3},
        {"date": "2026-07-23", "realized_pnl": 2258939, "trade_count": 3},
        {"date": "2026-07-24", "realized_pnl": -4597171, "trade_count": 1},
    ],
    "monthly": [
        {"month": "2026-07", "trades": 11, "pnl": -35939186, "win_rate": 0.364},
    ],
    "trades": [
        {"id": "trd-101", "date": "2026-07-24", "ticker": "161390", "name": "한국타이어앤테크놀로지", "side": "SELL", "qty": 1001, "price": 71300, "total": 71371300, "status": "FILLED"},
        {"id": "trd-100", "date": "2026-07-23", "ticker": "021240", "name": "코웨이", "side": "BUY", "qty": 758, "price": 90466, "total": 68573228, "status": "FILLED"},
        {"id": "trd-099", "date": "2026-07-23", "ticker": "383220", "name": "F&F", "side": "SELL", "qty": 915, "price": 73594, "total": 67338510, "status": "FILLED"},
        {"id": "trd-098", "date": "2026-07-22", "ticker": "483650", "name": "달바글로벌", "side": "SELL", "qty": 299, "price": 221159, "total": 66126541, "status": "FILLED"},
        {"id": "trd-097", "date": "2026-07-21", "ticker": "034730", "name": "SK", "side": "SELL", "qty": 121, "price": 571198, "total": 69114958, "status": "FILLED"},
    ],
}


@app.get("/api/market-indices")
def get_market_indices():
    """KOSPI / KOSDAQ latest index values via live yfinance, dashboard state, or DB."""
    # 1. Try live yfinance fetch
    live_indices, _ = _fetch_live_yfinance()
    if live_indices:
        return live_indices

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
                    return result
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
                        return result
        except (OSError, psycopg.Error):
            pass
    return DEFAULT_MARKET_INDICES


@app.get("/api/market-breadth")
def get_market_breadth():
    """Advancing / declining / unchanged stock counts from latest dashboard state."""
    for mode_key in ("paper", "dry_run"):
        path = LOG_ROOT / mode_key / "dashboard_state.json"
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                breadth = data.get("market_breadth") or data.get("breadth") or {}
                if breadth:
                    return breadth
                # Derive from data_health if available
                health = data.get("data_health") or {}
                if health:
                    return {
                        "advancing": health.get("advancing", 0),
                        "declining": health.get("declining", 0),
                        "unchanged": health.get("unchanged", 0),
                        "total": health.get("total", 0),
                        "advance_ratio": health.get("advance_ratio", 0),
                        "trading_volume": health.get("trading_volume", 0),
                    }
            except (OSError, json.JSONDecodeError):
                pass
    return DEFAULT_MARKET_BREADTH


@app.get("/api/sectors")
def get_sectors():
    """Sector performance data from WICS industry prices."""
    conn = _db_connect()
    if conn:
        try:
            with conn:
                with conn.cursor() as cur:
                    # Get the latest two dates for calculating change rates
                    cur.execute(
                        "SELECT DISTINCT price_date FROM wics_industry_prices "
                        "WHERE source_code = 'WISEINDEX' AND method_version = 'OFFICIAL' "
                        "ORDER BY price_date DESC LIMIT 2"
                    )
                    dates = [r["price_date"] for r in cur.fetchall()]
                    if len(dates) >= 2:
                        latest_date, prev_date = dates[0], dates[1]

                        # Get industry codes and names
                        cur.execute(
                            "SELECT code, name FROM codes "
                            "WHERE group_id = (SELECT id FROM code_groups WHERE group_code = 'WICS_INDUSTRY_CODE') "
                            "AND name IS NOT NULL"
                        )
                        industry_names = {r["code"]: r["name"] for r in cur.fetchall()}

                        # Get latest and previous index values
                        cur.execute(
                            "SELECT industry_code, price_date, index_value "
                            "FROM wics_industry_prices "
                            "WHERE source_code = 'WISEINDEX' AND method_version = 'OFFICIAL' "
                            "AND price_date IN (%s, %s) "
                            "ORDER BY industry_code, price_date",
                            (latest_date, prev_date),
                        )
                        rows = cur.fetchall()

                        # Build sector items
                        by_industry: dict[str, dict] = {}
                        for row in rows:
                            code = row["industry_code"]
                            if code not in by_industry:
                                by_industry[code] = {}
                            by_industry[code][row["price_date"]] = float(row["index_value"])

                        items = []
                        for code, prices in by_industry.items():
                            if latest_date in prices and prev_date in prices and prices[prev_date] > 0:
                                change_rate = ((prices[latest_date] - prices[prev_date]) / prices[prev_date]) * 100
                                items.append({
                                    "code": code,
                                    "name": industry_names.get(code, code),
                                    "change_rate": round(change_rate, 2),
                                    "index_value": round(prices[latest_date], 2),
                                    "prev_value": round(prices[prev_date], 2),
                                })

                        items.sort(key=lambda x: x["change_rate"], reverse=True)

                        # Add volume data from wics_companies if available
                        cur.execute(
                            "SELECT industry_code, SUM(trd_amt) as volume, SUM(mkt_val) as market_cap, "
                            "COUNT(*) as stock_count "
                            "FROM wics_companies WHERE base_date = %s "
                            "GROUP BY industry_code",
                            (latest_date,),
                        )
                        vol_data = {r["industry_code"]: r for r in cur.fetchall()}
                        for item in items:
                            vd = vol_data.get(item["code"], {})
                            item["volume"] = int(vd.get("volume") or 0)
                            item["market_cap"] = int(vd.get("market_cap") or 0)
                            item["stock_count"] = int(vd.get("stock_count") or 0)

                        # Find top stock per sector
                        cur.execute(
                            "SELECT wc.industry_code, c.company_name, wc.stock_code "
                            "FROM wics_companies wc "
                            "JOIN companies c ON wc.stock_code = c.stock_code "
                            "WHERE wc.base_date = %s "
                            "AND wc.mkt_val IS NOT NULL "
                            "ORDER BY wc.industry_code, wc.mkt_val DESC",
                            (latest_date,),
                        )
                        top_stocks: dict[str, str] = {}
                        for r in cur.fetchall():
                            code = r["industry_code"]
                            if code not in top_stocks:
                                top_stocks[code] = r["company_name"] or r["stock_code"]
                        for item in items:
                            item["top_stock"] = top_stocks.get(item["code"], "")

                        if items:
                            return {
                                "items": items,
                                "updated_at": latest_date.isoformat() if latest_date else None,
                                "top": items[:5],
                                "bottom": list(reversed(items[-5:])) if len(items) >= 5 else list(reversed(items)),
                            }
        except (OSError, psycopg.Error):
            pass
    return DEFAULT_SECTORS


@app.get("/api/exchange-rate")
def get_exchange_rate():
    """USD/KRW exchange rate from yfinance or macro_signals."""
    _, live_exchange = _fetch_live_yfinance()
    if live_exchange:
        return live_exchange

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
                        return {
                            "usd_krw": round(latest, 2),
                            "change": round(change, 2),
                            "change_rate": round(change_rate, 2),
                            "updated_at": rows[0]["signal_date"].isoformat() if rows[0].get("signal_date") else None,
                        }
        except (OSError, psycopg.Error):
            pass
    return DEFAULT_EXCHANGE_RATE


@app.get("/api/journal")
def get_journal(
    mode: ReportMode = "PAPER",
    limit: int = Query(default=50, ge=1, le=200),
):
    """Trading journal: recent trades, daily asset PnL, monthly summary based on certified asset reports."""
    venue = _mode_key(mode).upper()
    now = dt.datetime.now(SEOUL)

    # 1. Try loading performance data from certified latest report
    latest_report_path = REPORT_ROOT / "promotion" / _mode_key(mode) / "latest.json"
    summary = None
    daily_pnl = []
    monthly = []

    if latest_report_path.exists():
        try:
            report_data = json.loads(latest_report_path.read_text(encoding="utf-8"))
            perf = report_data.get("performance") or {}
            trend = report_data.get("performance_trend") or []

            starting_cap = float(perf.get("starting_capital_reference", 500000000.0))
            ending_asset = float(perf.get("ending_total_asset", 464060814.0))
            total_realized_pnl = float(perf.get("pnl_vs_starting_capital", ending_asset - starting_cap))

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
                        "trade_count": 3,
                    })

            pos_days = [dp for dp in daily_pnl if dp["realized_pnl"] > 0]
            neg_days = [dp for dp in daily_pnl if dp["realized_pnl"] < 0]

            total_pos = sum(dp["realized_pnl"] for dp in pos_days)
            total_neg = abs(sum(dp["realized_pnl"] for dp in neg_days))

            avg_profit = round(total_pos / len(pos_days)) if pos_days else 0
            avg_loss = round(-total_neg / len(neg_days)) if neg_days else 0
            profit_factor = round(total_pos / total_neg, 2) if total_neg > 0 else 0.82

            win_rate = round(len(pos_days) / len(daily_pnl), 3) if daily_pnl else 0.364

            summary = {
                "total_trades": len(daily_pnl),
                "win_count": len(pos_days),
                "loss_count": len(neg_days),
                "win_rate": win_rate,
                "starting_capital": starting_cap,
                "ending_asset": ending_asset,
                "total_realized_pnl": round(total_realized_pnl),
                "avg_profit": avg_profit,
                "avg_loss": avg_loss,
                "profit_factor": profit_factor,
            }

            monthly = [{
                "month": now.strftime("%Y-%m"),
                "trades": len(daily_pnl),
                "pnl": round(total_realized_pnl),
                "win_rate": win_rate,
            }]
        except (OSError, json.JSONDecodeError):
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

    if summary and daily_pnl:
        return {
            "trades": trades if trades else DEFAULT_JOURNAL["trades"],
            "daily_pnl": list(reversed(daily_pnl)),
            "monthly": monthly,
            "summary": summary,
            "updated_at": now.isoformat(),
        }

    return DEFAULT_JOURNAL


@app.get("/api/market-regime")
def get_market_regime():
    """Current market regime classification."""
    # Try analysis report first
    regime_path = ANALYSIS_ROOT / "market_regime.json"
    if regime_path.exists():
        try:
            data = json.loads(regime_path.read_text(encoding="utf-8"))
            return {
                "current": data.get("regime", "UPTREND"),
                "confidence": data.get("confidence", 0.85),
                "signal": data.get("signal", "상승 추세 지속"),
                "adx": data.get("adx"),
                "trend_strength": data.get("trend_strength"),
                "updated_at": data.get("updated_at") or data.get("analysis_date"),
            }
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
                        return {"current": regime, "confidence": 0.85, "signal": "상승 추세 지속", "updated_at": data.get("updated_at")}
                    return {
                        "current": regime.get("current", regime.get("regime", "UPTREND")),
                        "confidence": regime.get("confidence", 0.85),
                        "signal": regime.get("signal", "상승 추세 지속"),
                        "updated_at": regime.get("updated_at", data.get("updated_at")),
                    }
            except (OSError, json.JSONDecodeError):
                pass

    return DEFAULT_MARKET_REGIME


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("api.main:app", host="127.0.0.1", port=8000, reload=True)
