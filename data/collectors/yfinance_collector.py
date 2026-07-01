"""yfinance based Korean market data collector."""
from __future__ import annotations

import contextlib
import io
import time
from datetime import date

import pandas as pd
import yfinance as yf
from requests.exceptions import (
    ChunkedEncodingError,
    ConnectionError as RequestsConnectionError,
    Timeout as RequestsTimeout,
)

from core.constant.types import Market

_MAX_ATTEMPTS = 4
_BACKOFF_BASE = 3.0
_TRANSIENT_ERRORS = (
    RequestsTimeout,
    RequestsConnectionError,
    ChunkedEncodingError,
)


def _yf_download_with_retry(**kwargs) -> pd.DataFrame:
    for attempt in range(_MAX_ATTEMPTS):
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                return yf.download(**kwargs)
        except _TRANSIENT_ERRORS:
            if attempt >= _MAX_ATTEMPTS - 1:
                raise
            time.sleep(_BACKOFF_BASE * (2 ** attempt))
    return pd.DataFrame()


def _normalize_end(end: str | date | None) -> str | date | None:
    return end


def _ensure_utc_index(obj: pd.DataFrame | pd.Series) -> pd.DataFrame | pd.Series:
    if not isinstance(obj.index, pd.DatetimeIndex):
        obj.index = pd.to_datetime(obj.index)
    if obj.index.tz is None:
        obj.index = obj.index.tz_localize("UTC")
    else:
        obj.index = obj.index.tz_convert("UTC")
    return obj


def fetch_yfinance_close(
    ticker: str,
    start: str,
    end: str | date | None = None,
) -> pd.Series:
    """yfinance에서 일별 종가 시리즈를 가져온다."""
    df = _yf_download_with_retry(
        tickers=ticker,
        start=start,
        end=end,
        auto_adjust=True,
        progress=False,
        actions=False,
        group_by="column",
    )
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    if "Close" not in df.columns:
        raise ValueError(f"missing Close column for ticker: {ticker}")
    series = df["Close"].rename(ticker)
    return _ensure_utc_index(series)


def fetch_stock(
    code: str,
    market: Market,
    start: str,
    end: str | date | None = None,
) -> pd.DataFrame:
    """Fetch raw OHLCV data for a Korean stock from yfinance."""
    ticker = f"{code}{market.suffix}"
    df = _yf_download_with_retry(
        tickers=ticker,
        start=start,
        end=_normalize_end(end),
        auto_adjust=True,
        progress=False,
        actions=False,
        group_by="column",
    )

    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    expected = ["Open", "High", "Low", "Close", "Volume"]
    missing = [col for col in expected if col not in df.columns]
    if missing:
        raise ValueError(f"missing yfinance columns for {ticker}: {missing}")

    if "Adj Close" not in df.columns:
        df["Adj Close"] = df["Close"]

    return _ensure_utc_index(df[["Open", "High", "Low", "Close", "Adj Close", "Volume"]])


def fetch_market_index(
    market: Market,
    start: str,
    end: str | date | None = None,
) -> pd.Series:
    """Fetch KOSPI or KOSDAQ close index series from yfinance."""
    ticker = market.ticker
    df = _yf_download_with_retry(
        tickers=ticker,
        start=start,
        end=_normalize_end(end),
        auto_adjust=True,
        progress=False,
        actions=False,
        group_by="column",
    )

    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    if "Close" not in df.columns:
        raise ValueError(f"missing yfinance Close column for {ticker}")

    series = df["Close"].rename(market.name)
    return _ensure_utc_index(series)

