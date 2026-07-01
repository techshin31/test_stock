"""Rates & inflation loaders.

금리/인플레이션: 미국 10년 국채금리(^TNX), 미국 2년물 금리(^IRX),
미국 CPI(FRED CPIAUCSL)
"""
from __future__ import annotations

import time
from typing import Optional

import pandas as pd

from data.collectors.fred_collector import fetch_fred_series
from data.collectors.yfinance_collector import fetch_yfinance_close

_TNX      = "^TNX"
_US2Y     = "^IRX"
_FRED_CPI = "CPIAUCSL"


def download_tnx(start: str, end: Optional[str] = None) -> pd.Series:
    """미국 10년 국채금리(^TNX) 일별 종가 (단위: %)."""
    return fetch_yfinance_close(_TNX, start, end)


def download_us2y(start: str, end: Optional[str] = None) -> pd.Series:
    """미국 2년물 국채금리 대체 시리즈(^IRX) 일별 종가 (단위: %)."""
    return fetch_yfinance_close(_US2Y, start, end)


def download_cpi(
    start: str,
    end: Optional[str] = None,
    api_key: Optional[str] = None,
) -> pd.Series:
    """미국 소비자물가지수(CPI) 월별 시리즈.

    Parameters
    ----------
    api_key : str, optional
        FRED API 키. 미입력 시 FRED_API_KEY 환경변수 참조.
    """
    return fetch_fred_series(_FRED_CPI, start, end, api_key)


def download_all_rates(
    start: str,
    end: Optional[str] = None,
    fred_api_key: Optional[str] = None,
    sleep_seconds: float = 0.5,
) -> dict[str, pd.Series]:
    """금리/인플레이션 시리즈 전체를 일괄 다운로드한다.

    Returns
    -------
    dict[str, pd.Series]
        키: 'tnx', 'us2y', 'cpi' / 수집 실패한 항목은 제외됩니다.
    """
    fetchers = {
        "tnx":  lambda: download_tnx(start, end),
        "us2y": lambda: download_us2y(start, end),
        "cpi":  lambda: download_cpi(start, end, fred_api_key),
    }
    result: dict[str, pd.Series] = {}
    for name, fn in fetchers.items():
        time.sleep(sleep_seconds)
        try:
            result[name] = fn()  # type: ignore[operator]
        except Exception as exc:
            print(f"[rates] {name} 수집 실패: {exc}")
    return result
