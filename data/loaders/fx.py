"""FX loaders.

외환/달러: 달러 인덱스 선물(DX=F), 원/달러 환율(KRW=X)
"""
from __future__ import annotations

import time
from typing import Optional

import pandas as pd

from data.collectors.yfinance_collector import fetch_yfinance_close

_DXY = "DX-Y.NYB"
_USDKRW = "KRW=X"


def download_dollar_index(start: str, end: Optional[str] = None) -> pd.Series:
    """달러 인덱스 선물(DX=F) 일별 종가."""
    return fetch_yfinance_close(_DXY, start, end)


def download_usdkrw(start: str, end: Optional[str] = None) -> pd.Series:
    """원/달러 환율(KRW=X) 일별 종가."""
    return fetch_yfinance_close(_USDKRW, start, end)


def download_all_fx(
    start: str,
    end: Optional[str] = None,
    sleep_seconds: float = 0.5,
) -> dict[str, pd.Series]:
    """FX 시리즈 전체를 일괄 다운로드한다.

    Returns
    -------
    dict[str, pd.Series]
        키: 'dxy', 'usdkrw' / 수집 실패한 항목은 제외됩니다.
    """
    fetchers = {
        "dxy":    lambda: download_dollar_index(start, end),
        "usdkrw": lambda: download_usdkrw(start, end),
    }
    result: dict[str, pd.Series] = {}
    for name, fn in fetchers.items():
        time.sleep(sleep_seconds)
        try:
            result[name] = fn()  # type: ignore[operator]
        except Exception as exc:
            print(f"[fx] {name} 수집 실패: {exc}")
    return result
