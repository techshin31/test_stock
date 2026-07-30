"""Keep the dashboard's completed-session WICS sector data current.

This worker is deliberately separate from the trading scheduler: it only
collects public market data and reconstructs the derived WICS industry series.
It never imports the trader or broker order path.
"""
from __future__ import annotations

import argparse
import json
import time
from datetime import date, datetime, time as clock_time
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from core.utils.io import write_json
from core.utils.trading_calendar import (
    is_krx_trading_day,
    previous_krx_trading_day,
)


KST = ZoneInfo("Asia/Seoul")
PROJECT_ROOT = Path(__file__).resolve().parents[2]
STATUS_PATH = PROJECT_ROOT / "logs" / "paper" / "wics_sector_refresh_status.json"
DERIVED_SOURCE_CODE = "DERIVED"
DERIVED_METHOD_VERSION = "mcap-v1.1"
REQUIRED_INDUSTRY_COUNT = 25
CURRENT_SESSION_READY_AT = clock_time(15, 40)


def required_wics_session_date(now: datetime | None = None) -> date:
    """Return the newest session whose sector snapshot is expected to exist.

    The current session is eligible only after the post-close collection window;
    before then, the prior completed KRX session remains the required snapshot.
    """
    current = (now or datetime.now(KST)).astimezone(KST)
    if (
        is_krx_trading_day(current.date().isoformat())
        and current.time() >= CURRENT_SESSION_READY_AT
    ):
        return current.date()
    return previous_krx_trading_day(current.date())


def _derived_sector_state(db: Any, session_date: date) -> dict[str, Any]:
    row = db.fetch_one(
        """
        SELECT MAX(price_date) AS latest_date,
               COUNT(DISTINCT industry_code) FILTER (WHERE price_date = %s) AS industry_count
        FROM wics_industry_prices
        WHERE source_code = %s AND method_version = %s
        """,
        (session_date, DERIVED_SOURCE_CODE, DERIVED_METHOD_VERSION),
    ) or {}
    latest_date = row.get("latest_date")
    industry_count = int(row.get("industry_count") or 0)
    return {
        "latest_date": latest_date,
        "industry_count": industry_count,
        "current": latest_date == session_date and industry_count >= REQUIRED_INDUSTRY_COUNT,
    }


def _status_payload(
    *,
    status: str,
    target_date: date,
    sector_state: dict[str, Any] | None = None,
    refresh_result: dict[str, Any] | None = None,
    error: object | None = None,
) -> dict[str, Any]:
    refresh = refresh_result or {}
    price_refresh = refresh.get("price_refresh") or {}
    failed_codes = [
        str(code)
        for code in (price_refresh.get("failed_stock_codes") or [])
    ]
    derived_status = price_refresh.get("derived_rebuild_status")
    input_quality = {
        "status": (
            "PARTIAL"
            if derived_status == "PARTIAL_INPUT"
            else "DEFERRED"
            if derived_status == "DEFERRED"
            else "COMPLETE"
            if derived_status == "COMPLETE"
            else "UNKNOWN"
        ),
        "failed_stock_count": len(failed_codes),
        "failed_stock_codes": failed_codes[:50],
        "derived_rows": int(price_refresh.get("derived_rows") or 0),
        "coverage_guard": "PER_INDUSTRY_MINIMUM",
        "minimum_industry_coverage": 0.80,
    }
    return {
        "schema_version": 2,
        "updated_at": datetime.now(KST).isoformat(timespec="seconds"),
        "mode": "PAPER",
        "status": status,
        "target_date": target_date.isoformat(),
        "source": f"{DERIVED_SOURCE_CODE}:{DERIVED_METHOD_VERSION}",
        "latest_date": (
            sector_state.get("latest_date").isoformat()
            if sector_state and sector_state.get("latest_date")
            else None
        ),
        "industry_count": sector_state.get("industry_count") if sector_state else 0,
        "refresh_result": refresh,
        "input_quality": input_quality,
        "error": str(error)[:1000] if error else None,
    }


def _reusable_refresh_result(
    status_path: Path,
    target_date: date,
) -> dict[str, Any] | None:
    """Keep same-session input quality visible after the data becomes current."""
    try:
        raw = json.loads(status_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return None
    if not isinstance(raw, dict) or raw.get("target_date") != target_date.isoformat():
        return None
    quality = raw.get("input_quality")
    refresh_result = raw.get("refresh_result")
    if (
        not isinstance(quality, dict)
        or quality.get("status") not in {"COMPLETE", "PARTIAL"}
        or not isinstance(refresh_result, dict)
    ):
        return None
    return refresh_result


def refresh_once(*, now: datetime | None = None, project_root: Path = PROJECT_ROOT) -> dict[str, Any]:
    """Bring the derived WICS sector series through the latest safe session."""
    from apps.worker.collector import wics_job
    from apps.worker.config import build_db_config, load_config
    from storage.postgres.connection import PostgreDB

    target_date = required_wics_session_date(now)
    status_path = project_root / "logs" / "paper" / STATUS_PATH.name
    load_config()
    db = PostgreDB(build_db_config())
    try:
        before = _derived_sector_state(db, target_date)
        reusable_result = _reusable_refresh_result(status_path, target_date)
        if before["current"] and reusable_result is not None:
            payload = _status_payload(
                status="READY",
                target_date=target_date,
                sector_state=before,
                refresh_result=reusable_result,
            )
            write_json(status_path, payload)
            return payload

        result = wics_job.run(
            db,
            date_list=[target_date.strftime("%Y%m%d")],
            show_progress=False,
            force_refresh=False,
            price_start=target_date.isoformat(),
            price_end=target_date.isoformat(),
            collect_prices=True,
            return_details=True,
        )
        after = _derived_sector_state(db, target_date)
        status = "READY" if after["current"] else "DEGRADED"
        payload = _status_payload(
            status=status,
            target_date=target_date,
            sector_state=after,
            refresh_result=result,
        )
        write_json(status_path, payload)
        return payload
    except Exception as exc:
        payload = _status_payload(status="FAILED", target_date=target_date, error=exc)
        write_json(status_path, payload)
        return payload
    finally:
        db.close()


def run_forever(*, poll_seconds: int = 300) -> None:
    """Retry stale or failed refreshes without touching the trading process."""
    if poll_seconds < 60:
        raise ValueError("poll_seconds must be at least 60")
    while True:
        print(json.dumps(refresh_once(), ensure_ascii=False, default=str), flush=True)
        time.sleep(poll_seconds)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Refresh completed-session WICS sector data")
    parser.add_argument("--once", action="store_true", help="Run one refresh attempt and exit")
    parser.add_argument("--poll-seconds", type=int, default=300)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    if args.once:
        payload = refresh_once()
        print(json.dumps(payload, ensure_ascii=False, default=str))
        return 0 if payload["status"] == "READY" else 1
    run_forever(poll_seconds=args.poll_seconds)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
