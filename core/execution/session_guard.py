"""Recheck exchange hours and operator controls immediately before submission."""
from datetime import datetime, time
import json
import os
from pathlib import Path
from zoneinfo import ZoneInfo
from core.utils.trading_calendar import is_krx_trading_day

KST = ZoneInfo("Asia/Seoul")


def now_kst():
    return datetime.now(KST)


def submission_blocker(side, *, session=None, now=None):
    now = now or now_kst()
    if session is not None and now.date() != session:
        return "ORDER_SESSION_CHANGED"
    if not is_krx_trading_day(now.date().isoformat()) or not time(9) <= now.time() < time(15, 20):
        return "OUTSIDE_ORDER_WINDOW"
    control = Path(os.getenv("TRADING_CONTROL_PATH") or
                   Path(__file__).resolve().parents[2] / "logs/system/trading-control.json")
    try:
        state = json.loads(control.read_text()) if control.exists() else {}
        if not isinstance(state, dict):
            return "INVALID_TRADING_CONTROL"
        if state.get("orders_paused"):
            return "ORDERS_PAUSED"
        if side.upper() == "BUY" and (state.get("entries_paused") or
                os.getenv("TRADING_KILL_SWITCH", "false").lower() == "true"):
            return "ENTRIES_PAUSED"
    except (OSError, ValueError):
        return "INVALID_TRADING_CONTROL"
    return None
