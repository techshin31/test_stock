"""데이터 로딩 유틸리티 — yfinance 다운로드 및 사용자 CSV 파일 지원"""

from pathlib import Path

import pandas as pd
import yfinance as yf


def load_stock(ticker: str, start: str = "2018-01-01", end: str = "2024-12-31") -> pd.DataFrame:
    """yfinance로 단일 종목 OHLCV 데이터 로드"""
    df = yf.download(ticker, start=start, end=end, auto_adjust=True, progress=False)
    df.columns = df.columns.droplevel(1) if isinstance(df.columns, pd.MultiIndex) else df.columns
    return df[["Open", "High", "Low", "Close", "Volume"]].dropna()


def load_close(ticker: str, start: str = "2018-01-01", end: str = "2024-12-31") -> pd.Series:
    """yfinance로 단일 종목 종가 시리즈 로드"""
    return load_stock(ticker, start, end)["Close"].rename(ticker)


def load_kospi(start: str = "2019-01-01", end: str = "2024-12-31") -> pd.Series:
    """KOSPI 지수 종가 시리즈 로드 (^KS11) — 포트폴리오 벤치마크용"""
    return load_close("^KS11", start, end).rename("KOSPI")


def load_cash_etf(start: str = "2019-01-01", end: str = "2024-12-31") -> pd.Series:
    """KODEX 단기채권 ETF 종가 시리즈 로드 (153130.KS) — 현금 대체 운용용"""
    return load_close("153130.KS", start, end).rename("단기채")


def load_csv(
    path: str,
    date_col: str = "Date",
    close_col: str = "Close",
    name: str | None = None,
) -> pd.Series:
    """
    사용자 CSV 파일에서 종가 시리즈 로드

    Parameters
    ----------
    path      : CSV 파일 경로
    date_col  : 날짜 컬럼명 (기본값 'Date')
    close_col : 종가 컬럼명 (기본값 'Close')
    name      : 시리즈 이름. 미지정 시 파일명(확장자 제외) 사용

    Examples
    --------
    >>> close = load_csv("data/samsung.csv")
    >>> close = load_csv("data/btc.csv", date_col="timestamp", close_col="close")
    """
    df = pd.read_csv(path, parse_dates=[date_col], index_col=date_col)
    df.index = pd.to_datetime(df.index)
    series = df[close_col].dropna().sort_index()
    return series.rename(name or Path(path).stem)


def load_csv_ohlcv(
    path: str,
    date_col: str = "Date",
    col_map: dict[str, str] | None = None,
) -> pd.DataFrame:
    """
    사용자 CSV 파일에서 OHLCV DataFrame 로드

    Parameters
    ----------
    path    : CSV 파일 경로
    date_col: 날짜 컬럼명
    col_map : 컬럼명 매핑 (예: {"open": "Open", "high": "High", ...})
              미지정 시 Open/High/Low/Close/Volume 컬럼명 그대로 사용

    Examples
    --------
    >>> df = load_csv_ohlcv("data/samsung.csv")
    >>> df = load_csv_ohlcv("data/btc.csv", col_map={"open":"Open", "close":"Close"})
    """
    df = pd.read_csv(path, parse_dates=[date_col], index_col=date_col)
    df.index = pd.to_datetime(df.index)
    df = df.sort_index()
    if col_map:
        df = df.rename(columns=col_map)
    return df[["Open", "High", "Low", "Close", "Volume"]].dropna()
