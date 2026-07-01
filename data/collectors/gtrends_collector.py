"""Google Trends collector."""
from __future__ import annotations

import random
import time
from typing import Optional

import pandas as pd

_MAX_ATTEMPTS = 5
_BACKOFF_BASE = 10.0


def _trend_req():
    try:
        from pytrends.request import TrendReq
    except ImportError as exc:
        raise ImportError(
            "pytrends 패키지가 필요합니다. `uv sync --dev` 또는 `pip install pytrends` 후 다시 실행하세요."
        ) from exc
    return TrendReq(hl="en-US", tz=540, timeout=(10, 30))


def _fetch_chunk_with_retry(pytrends, keyword: str, timeframe: str, geo: str) -> pd.DataFrame:
    """429 등 일시적 오류 시 지수 백오프로 재시도."""
    for attempt in range(_MAX_ATTEMPTS):
        try:
            pytrends.build_payload([keyword], cat=0, timeframe=timeframe, geo=geo)
            return pytrends.interest_over_time()
        except Exception as exc:
            is_last = attempt >= _MAX_ATTEMPTS - 1
            err_str = str(exc)
            is_rate_limit = "429" in err_str or "Too Many Requests" in err_str.lower()
            if is_last or not is_rate_limit:
                raise
            delay = _BACKOFF_BASE * (2 ** attempt) + random.uniform(0, 5)
            print(f"[gtrends] 429 rate limit, {delay:.0f}초 후 재시도 ({attempt + 1}/{_MAX_ATTEMPTS})...")
            time.sleep(delay)
    return pd.DataFrame()


def fetch_google_trends_monthly(
    keyword: str,
    geo: str = "",
    start: str = "2020-01-01",
    end: Optional[str] = None,
) -> pd.Series:
    """Google Trends 월간 관심도 지수(0~100)를 가져온다."""
    pytrends = _trend_req()
    end_dt = pd.Timestamp(end) if end else pd.Timestamp.today()
    start_dt = pd.Timestamp(start)

    chunks: list[pd.Series] = []
    chunk_start = start_dt
    while chunk_start < end_dt:
        chunk_end = min(chunk_start + pd.DateOffset(years=5), end_dt)
        timeframe = f"{chunk_start:%Y-%m-%d} {chunk_end:%Y-%m-%d}"
        frame = _fetch_chunk_with_retry(pytrends, keyword, timeframe, geo)
        if not frame.empty and keyword in frame.columns:
            chunks.append(frame[keyword].rename(keyword))
        chunk_start = chunk_end + pd.DateOffset(days=1)
        time.sleep(5.0 + random.uniform(0, 3))

    if not chunks:
        return pd.Series(dtype=float, name=keyword)

    series = pd.concat(chunks)
    series = series[~series.index.duplicated(keep="last")]
    series.index = pd.to_datetime(series.index)
    monthly = series.resample("MS").mean().rename(keyword)
    return monthly.loc[start_dt:end_dt].dropna()

