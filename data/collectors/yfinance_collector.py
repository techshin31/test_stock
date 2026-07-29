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


def _yf_download_with_retry(
    *,
    max_attempts: int = _MAX_ATTEMPTS,
    backoff_base: float = _BACKOFF_BASE,
    **kwargs,
) -> pd.DataFrame:
    """Download Yahoo data with a caller-configurable bounded retry budget."""
    if max_attempts < 1:
        raise ValueError("max_attempts must be positive")
    if backoff_base < 0:
        raise ValueError("backoff_base must be non-negative")
    for attempt in range(max_attempts):
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                return yf.download(**kwargs)
        except _TRANSIENT_ERRORS:
            if attempt >= max_attempts - 1:
                raise
            time.sleep(backoff_base * (2 ** attempt))
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


def _before_end(
    frame: pd.DataFrame | pd.Series,
    end: str | date | None,
) -> pd.DataFrame | pd.Series:
    """Keep the loaders' end-exclusive contract across data providers."""
    if end is None:
        return frame
    end_ts = pd.Timestamp(end)
    end_ts = (
        end_ts.tz_localize("UTC")
        if end_ts.tz is None
        else end_ts.tz_convert("UTC")
    )
    return frame[frame.index < end_ts]


def _normalise_stock_frame(frame: pd.DataFrame, ticker: str) -> pd.DataFrame:
    """Convert a Yahoo or FinanceDataReader frame to one canonical OHLCV shape."""
    if isinstance(frame.columns, pd.MultiIndex):
        frame = frame.copy()
        frame.columns = frame.columns.get_level_values(0)
    expected = ["Open", "High", "Low", "Close", "Volume"]
    missing = [column for column in expected if column not in frame.columns]
    if missing:
        raise ValueError(f"missing OHLCV columns for {ticker}: {missing}")
    normalized = frame[expected].copy()
    normalized["Adj Close"] = (
        frame["Adj Close"] if "Adj Close" in frame.columns else normalized["Close"]
    )
    return _ensure_utc_index(
        normalized[["Open", "High", "Low", "Close", "Adj Close", "Volume"]]
    )


def _stock_data_is_stale(frame: pd.DataFrame, end: str | date | None) -> bool:
    """Request the secondary provider only when Yahoo cannot reach the requested day."""
    if frame.empty:
        return True
    if end is None:
        return False
    expected_date = (pd.Timestamp(end) - pd.Timedelta(days=1)).date()
    return frame.index.max().date() < expected_date


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
    """Fetch Korean-stock OHLCV with FinanceDataReader as a bounded fallback.

    Yahoo remains the primary provider.  The secondary request is made only when
    the primary request failed or did not reach the requested end-exclusive day;
    it does not silently replace available Yahoo rows.
    """
    ticker = f"{code}{market.suffix}"
    yahoo = None
    errors = []
    try:
        yahoo = _normalise_stock_frame(
            _yf_download_with_retry(
                tickers=ticker,
                start=start,
                end=_normalize_end(end),
                auto_adjust=True,
                progress=False,
                actions=False,
                group_by="column",
            ),
            ticker,
        )
    except Exception as exc:
        errors.append(f"yfinance: {exc}")

    fallback = None
    if yahoo is None or _stock_data_is_stale(yahoo, end):
        try:
            fallback = _before_end(
                _normalise_stock_frame(fdr.DataReader(code, start, end), ticker), end
            )
        except Exception as exc:
            errors.append(f"FinanceDataReader: {exc}")

    if yahoo is None and fallback is None:
        raise ValueError(f"stock OHLCV unavailable for {ticker}: {'; '.join(errors)}")
    if yahoo is None:
        logging.warning("using FinanceDataReader fallback for %s", ticker)
        return fallback
    if fallback is None:
        return yahoo

    combined = yahoo.combine_first(fallback)
    combined = combined[~combined.index.duplicated(keep="first")].sort_index().dropna(
        subset=["Close"]
    )
    if fallback.index.max() > yahoo.index.max():
        logging.warning(
            "yfinance %s was stale at %s; extended through %s with FinanceDataReader",
            ticker,
            yahoo.index.max().date(),
            fallback.index.max().date(),
        )
    return combined


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
        fdr_close = _before_end(fdr_close, end)
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

