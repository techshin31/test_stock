"""한류 지표 로더: Google Trends, 외국인 관광객."""
from __future__ import annotations

import time
from typing import Optional

import pandas as pd

from data.collectors.gtrends_collector import fetch_google_trends_monthly
from data.collectors.kto_collector import fetch_kto_tourist_monthly

_KPOP_KEYWORD = "K-pop"
_KDRAMA_KEYWORD = "Korean drama"


def download_gtrend_kpop(start: str, end: Optional[str] = None) -> pd.Series:
    """Google Trends 글로벌 K-pop 월간 관심도."""
    return fetch_google_trends_monthly(_KPOP_KEYWORD, geo="", start=start, end=end)


def download_gtrend_kdrama(start: str, end: Optional[str] = None) -> pd.Series:
    """Google Trends 글로벌 Korean drama 월간 관심도."""
    return fetch_google_trends_monthly(_KDRAMA_KEYWORD, geo="", start=start, end=end)


def download_kr_tourist(
    start: str,
    end: Optional[str] = None,
    kto_api_key: Optional[str] = None,
) -> pd.Series:
    """외국인 관광객 월별 입국자 수."""
    return fetch_kto_tourist_monthly(start, end, api_key=kto_api_key)


def download_all_hallyu_indicators(
    start: str,
    end: Optional[str] = None,
    kto_api_key: Optional[str] = None,
    sleep_seconds: float = 2.0,
) -> dict[str, pd.Series]:
    """한류 지표 전체를 일괄 다운로드한다."""
    fetchers = {
        "gtrend_kpop":   lambda: download_gtrend_kpop(start, end),
        "gtrend_kdrama": lambda: download_gtrend_kdrama(start, end),
        "kr_tourist":    lambda: download_kr_tourist(start, end, kto_api_key),
    }
    result: dict[str, pd.Series] = {}
    for name, fn in fetchers.items():
        time.sleep(sleep_seconds)
        try:
            result[name] = fn()
        except Exception as exc:
            print(f"[hallyu_indicators] {name} 수집 실패: {exc}")
    return result

