"""OHLCV preprocessing utilities."""
from __future__ import annotations

import warnings

import pandas as pd


_REQUIRED = ["open", "high", "low", "close", "volume"]


def _normalize_index(index: pd.Index) -> pd.DatetimeIndex:
    dt_index = pd.DatetimeIndex(pd.to_datetime(index))
    if dt_index.tz is not None:
        dt_index = dt_index.tz_convert(None)
    return dt_index


def clean_ohlcv(df: pd.DataFrame) -> pd.DataFrame:
    """Convert a yfinance OHLCV frame to the core schema."""
    if df.empty:
        return pd.DataFrame(columns=_REQUIRED, index=pd.DatetimeIndex([]))

    result = df.copy()
    if isinstance(result.columns, pd.MultiIndex):
        result.columns = result.columns.get_level_values(0)

    result.columns = [str(col).lower() for col in result.columns]
    result.index = _normalize_index(result.index)

    result = result.sort_index()
    result = result[~result.index.duplicated(keep="last")]
    result = result.dropna(subset=["close"]) # close가 NaN인 행 자체를 제거

    for col in ["open", "high", "low"]:
        if col in result.columns:
            result[col] = result[col].ffill(limit=2)
    if "volume" in result.columns:
        result["volume"] = result["volume"].fillna(0)

    result = result[[col for col in _REQUIRED if col in result.columns]]
    validate_ohlcv(result)
    return result


def align_index(
    ohlcv: pd.DataFrame,
    market_index: pd.Series,
) -> pd.Series:
    """Align a market index series to an OHLCV trading calendar."""
    series = market_index.copy()
    series.index = _normalize_index(series.index)
    aligned = series.sort_index().reindex(ohlcv.index).ffill()
    aligned.name = market_index.name
    return aligned


def validate_ohlcv(df: pd.DataFrame) -> None:
    """Validate the core OHLCV schema and warn on suspicious values."""
    missing = [col for col in _REQUIRED if col not in df.columns]
    if missing:
        raise ValueError(f"missing OHLCV columns: {missing}")
    if not isinstance(df.index, pd.DatetimeIndex):
        raise ValueError("OHLCV index must be a DatetimeIndex")
    if df.index.has_duplicates:
        warnings.warn("OHLCV index contains duplicated dates", RuntimeWarning)
    if len(df) < 120:
        warnings.warn("OHLCV has fewer than 120 rows; long moving averages may be unstable", RuntimeWarning)

    invalid_range = (df["high"] < df["low"]) | (df["high"] < df["close"]) | (df["close"] < df["low"])
    if bool(invalid_range.fillna(False).any()):
        warnings.warn("OHLCV contains rows where high/close/low ordering is invalid", RuntimeWarning)

    non_positive_price = (df[["open", "high", "low", "close"]] <= 0).any(axis=1)
    if bool(non_positive_price.fillna(False).any()):
        warnings.warn("OHLCV contains non-positive prices", RuntimeWarning)

    if bool((df["volume"] < 0).fillna(False).any()):
        warnings.warn("OHLCV contains negative volume", RuntimeWarning)

