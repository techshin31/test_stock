from __future__ import annotations

import os
import time
from datetime import datetime, time as dtime
from zoneinfo import ZoneInfo

from core.utils.trading_calendar import is_krx_trading_day

KST = ZoneInfo("Asia/Seoul")

PRE_MARKET_START = dtime(8, 30)   # 장전 포지션 동기화, 게이트 점검
MARKET_OPEN      = dtime(9, 0)    # 장중 루프 시작
MARKET_CLOSE     = dtime(15, 20)  # 장중 루프 종료 (동시호가 전)
EOD_START        = dtime(15, 40)  # 장마감 reconcile 시작

def _skip_wait() -> bool:
    """TRADER_SKIP_WAIT=true 이면 True. 호출 시점에 읽어야 CLI --test 파라미터가 반영된다."""
    return os.getenv("TRADER_SKIP_WAIT", "false").lower() == "true"


def now_kst() -> datetime:
    return datetime.now(KST)


def is_pre_market() -> bool:
    t = now_kst().time()
    return PRE_MARKET_START <= t < MARKET_OPEN


def is_eod_window() -> bool:
    t = now_kst().time()
    return EOD_START <= t < dtime(16, 30)


def is_trading_day() -> bool:
    """Return whether today is an actual KRX session."""
    if _skip_wait():
        return True
    return is_krx_trading_day(now_kst().date().isoformat())


def is_market_hours() -> bool:
    if _skip_wait():
        return True
    t = now_kst().time()
    return MARKET_OPEN <= t < MARKET_CLOSE


def seconds_until(target: dtime) -> float:
    """현재 KST 기준으로 오늘의 target 시각까지 남은 초를 반환한다."""
    now = now_kst()
    target_dt = now.replace(hour=target.hour, minute=target.minute, second=0, microsecond=0)
    return max(0.0, (target_dt - now).total_seconds())


def wait_until(target: dtime, poll_sec: float = 5.0) -> None:
    """target 시각까지 대기한다."""
    if _skip_wait():
        print(f"[SCHEDULER] TRADER_SKIP_WAIT=true — {target.strftime('%H:%M')} 대기 건너뜀")
        return
    remaining = seconds_until(target)
    if remaining > 0:
        print(f"[SCHEDULER] {target.strftime('%H:%M')} KST까지 {remaining:.0f}초 대기")
        time.sleep(remaining)
