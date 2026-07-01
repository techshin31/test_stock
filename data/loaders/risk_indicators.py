"""Risk indicator loaders.

위험 지표: 필라델피아 반도체 지수(^SOX), 건화물 운임 ETF(BDRY),
시장 공포지수(^VIX), 지정학적 리스크 지수(GPR)
"""
from __future__ import annotations

import time
from typing import Optional

import pandas as pd

from data.collectors.gpr_collector import fetch_gpr_monthly
from data.collectors.yfinance_collector import fetch_yfinance_close

_SOX  = "^SOX"
_BDRY = "BDRY"
_VIX  = "^VIX"


def download_sox(start: str, end: Optional[str] = None) -> pd.Series:
    """필라델피아 반도체 지수(^SOX) 일별 종가."""
    return fetch_yfinance_close(_SOX, start, end)


def download_bdry(start: str, end: Optional[str] = None) -> pd.Series:
    """Breakwave Dry Bulk Shipping ETF(BDRY) 일별 종가.

    BDI(발틱 드라이 지수) 선물을 추종하는 ETF로, BDI 대체 지표로 사용한다.
    """
    return fetch_yfinance_close(_BDRY, start, end)


def download_vix(start: str, end: Optional[str] = None) -> pd.Series:
    """CBOE 변동성 지수(^VIX) 일별 종가."""
    return fetch_yfinance_close(_VIX, start, end)


def download_gpr(start: str, end: Optional[str] = None) -> pd.Series:
    """Caldara & Iacoviello 지정학적 리스크 지수 월간 시리즈."""
    return fetch_gpr_monthly(start, end)


def download_all_risk_indicators(
    start: str,
    end: Optional[str] = None,
    sleep_seconds: float = 0.5,
) -> dict[str, pd.Series]:
    """위험 지표 전체를 일괄 다운로드한다.

    Returns
    -------
    dict[str, pd.Series]
        키: 'sox', 'bdry', 'vix', 'gpr' / 수집 실패한 항목은 제외됩니다.
    """
    fetchers = {
        "sox":  lambda: download_sox(start, end),
        "bdry": lambda: download_bdry(start, end),
        "vix":  lambda: download_vix(start, end),
        "gpr":  lambda: download_gpr(start, end),
    }
    result: dict[str, pd.Series] = {}
    for name, fn in fetchers.items():
        time.sleep(sleep_seconds)
        try:
            result[name] = fn()  # type: ignore[operator]
        except Exception as exc:
            print(f"[risk_indicators] {name} 수집 실패: {exc}")
    return result
