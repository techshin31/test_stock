"""KRX 거래일 유틸리티."""
from __future__ import annotations

from datetime import date, timedelta

import exchange_calendars as xcals

_KRX = xcals.get_calendar("XKRX")


def is_krx_trading_day(date_str: str) -> bool:
    """주어진 날짜가 KRX 개장일인지 반환한다.

    Parameters
    ----------
    date_str : str
        날짜 문자열 (YYYYMMDD 또는 YYYY-MM-DD)

    Returns
    -------
    bool
        개장일이면 True, 주말·공휴일이면 False
    """
    if len(date_str) == 8:
        date_str = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:]}"
    return _KRX.is_session(date_str)


def previous_krx_trading_day(execution_date: date) -> date:
    """Return the last completed KRX session strictly before execution_date."""
    candidate = execution_date - timedelta(days=1)
    for _ in range(14):
        if is_krx_trading_day(candidate.isoformat()):
            return candidate
        candidate -= timedelta(days=1)
    raise ValueError(f"no prior KRX session found before {execution_date}")
