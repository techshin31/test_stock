"""Manufacturing indicator loaders."""
from __future__ import annotations

import time
from typing import Optional

import pandas as pd

from data.collectors.fred_collector import fetch_fred_series

_FRED_ISM_PMI = "NAPMPMI"
_FRED_SEMIPROD = "IPG3344S"  # Industrial Production: Semiconductor and Other Electronic Component (NAICS=3344)


def download_ism_pmi(
    start: str,
    end: Optional[str] = None,
    fred_api_key: Optional[str] = None,
) -> pd.Series:
    """ISM 제조업 PMI(FRED: NAPMPMI) 월간 시리즈."""
    return fetch_fred_series(_FRED_ISM_PMI, start, end, api_key=fred_api_key)


def download_semiprod(
    start: str,
    end: Optional[str] = None,
    fred_api_key: Optional[str] = None,
) -> pd.Series:
    """반도체 및 전자부품 산업생산지수(FRED: IPGMFGS) 월간 시리즈."""
    return fetch_fred_series(_FRED_SEMIPROD, start, end, api_key=fred_api_key)


def download_all_manufacturing_indicators(
    start: str,
    end: Optional[str] = None,
    fred_api_key: Optional[str] = None,
    sleep_seconds: float = 0.5,
) -> dict[str, pd.Series]:
    """제조업 지표 전체를 일괄 다운로드한다."""
    fetchers = {
        "ism_pmi": lambda: download_ism_pmi(start, end, fred_api_key),
        "semiprod": lambda: download_semiprod(start, end, fred_api_key),
    }
    result: dict[str, pd.Series] = {}
    for name, fn in fetchers.items():
        time.sleep(sleep_seconds)
        try:
            result[name] = fn()
        except Exception as exc:
            print(f"[manufacturing_indicators] {name} 수집 실패: {exc}")
    return result
