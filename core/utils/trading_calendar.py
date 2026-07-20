"""KRX 거래일 유틸리티.

``exchange_calendars``는 기본 달력으로 사용하되, 라이브러리 배포 이후 확정된
임시공휴일/제도 변경은 보수적인 로컬 휴장일 오버레이로 즉시 차단한다.
"""
from __future__ import annotations

import os
from datetime import date, timedelta

import exchange_calendars as xcals

_KRX = xcals.get_calendar("XKRX")

# exchange_calendars 4.11.1에는 2026년에 다시 공휴일이 된 제헌절이 거래일로
# 남아 있다. 거래소는 공휴일에 휴장하므로 라이브러리가 갱신되기 전까지
# 명시적으로 차단한다. 추가 임시 휴장일은 환경변수로 무배포 대응할 수 있다.
_KNOWN_KRX_ADDITIONAL_HOLIDAYS = {
    date(2026, 7, 17),
}


def _configured_additional_holidays() -> set[date]:
    raw = os.getenv("KRX_ADDITIONAL_HOLIDAYS", "")
    holidays = set(_KNOWN_KRX_ADDITIONAL_HOLIDAYS)
    for value in filter(None, (item.strip() for item in raw.split(","))):
        try:
            holidays.add(date.fromisoformat(value))
        except ValueError as exc:
            raise ValueError(
                "KRX_ADDITIONAL_HOLIDAYS must contain comma-separated YYYY-MM-DD values"
            ) from exc
    return holidays


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
    session_date = date.fromisoformat(date_str)
    if session_date in _configured_additional_holidays():
        return False
    return bool(_KRX.is_session(session_date.isoformat()))


def previous_krx_trading_day(execution_date: date) -> date:
    """Return the last completed KRX session strictly before execution_date."""
    candidate = execution_date - timedelta(days=1)
    for _ in range(14):
        if is_krx_trading_day(candidate.isoformat()):
            return candidate
        candidate -= timedelta(days=1)
    raise ValueError(f"no prior KRX session found before {execution_date}")
