"""yfinance based Korean market data collector."""
from __future__ import annotations

import contextlib
import io
import logging
import time
from datetime import date

import FinanceDataReader as fdr
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
    """Fetch an index series, filling stale Yahoo rows from FinanceDataReader."""
    ticker = market.ticker
    sources = []
    errors = []
    try:
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
        sources.append(_ensure_utc_index(df["Close"].rename(market.name)))
    except Exception as exc:
        errors.append(f"yfinance: {exc}")

    fdr_symbol = "KS11" if market == Market.KOSPI else "KQ11"
    try:
        fdr_frame = fdr.DataReader(fdr_symbol, start, end)
        if "Close" not in fdr_frame.columns:
            raise ValueError(f"missing FinanceDataReader Close column for {fdr_symbol}")
        fdr_close = _ensure_utc_index(fdr_frame["Close"].rename(market.name))
        if end is not None:
            end_ts = pd.Timestamp(end)
            end_ts = end_ts.tz_localize("UTC") if end_ts.tz is None else end_ts.tz_convert("UTC")
            fdr_close = fdr_close[fdr_close.index < end_ts]
        sources.append(fdr_close)
    except Exception as exc:
        errors.append(f"FinanceDataReader: {exc}")

    if not sources:
        raise ValueError(
            f"market index unavailable for {market.name}: {'; '.join(errors)}"
        )
    combined = sources[0]
    for fallback in sources[1:]:
        combined = combined.combine_first(fallback)
    combined = combined[~combined.index.duplicated(keep="last")].sort_index().dropna()
    if len(sources) > 1 and sources[1].index.max() > sources[0].index.max():
        logging.warning(
            "yfinance %s index is stale at %s; extended through %s with FinanceDataReader",
            market.name,
            sources[0].index.max().date(),
            sources[1].index.max().date(),
        )
    return combined.rename(market.name)

