"""Commodity futures loaders.

원자재 선물: 구리(HG=F), 금(GC=F), WTI 원유(CL=F)
"""
from __future__ import annotations

import time
from typing import Optional

import pandas as pd

from data.collectors.yfinance_collector import fetch_yfinance_close

_COPPER = "HG=F"
_GOLD   = "GC=F"
_WTI    = "CL=F"


def download_copper(start: str, end: Optional[str] = None) -> pd.Series:
    """구리 선물(HG=F) 일별 종가."""
    return fetch_yfinance_close(_COPPER, start, end)


def download_gold(start: str, end: Optional[str] = None) -> pd.Series:
    """금 선물(GC=F) 일별 종가."""
    return fetch_yfinance_close(_GOLD, start, end)


def download_wti(start: str, end: Optional[str] = None) -> pd.Series:
    """WTI 원유 선물(CL=F) 일별 종가."""
    return fetch_yfinance_close(_WTI, start, end)


def download_all_commodities(
    start: str,
    end: Optional[str] = None,
    sleep_seconds: float = 0.5,
) -> dict[str, pd.Series]:
    """원자재 선물 전체를 일괄 다운로드한다.

    Returns
    -------
    dict[str, pd.Series]
        키: 'copper', 'gold', 'wti' / 수집 실패한 항목은 제외됩니다.
    """
    fetchers = {
        "copper": lambda: download_copper(start, end),
        "gold":   lambda: download_gold(start, end),
        "wti":    lambda: download_wti(start, end),
    }
    result: dict[str, pd.Series] = {}
    for name, fn in fetchers.items():
        time.sleep(sleep_seconds)
        try:
            result[name] = fn()  # type: ignore[operator]
        except Exception as exc:
            print(f"[commodities] {name} 수집 실패: {exc}")
    return result
