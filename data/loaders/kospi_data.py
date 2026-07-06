"""
KOSPI 주가 데이터 수집 유틸리티
================================

yfinance를 이용해 KOSPI 지수 및 개별 종목 OHLCV 데이터를 수집한다.
코어 백테스트 엔진(core/backtest/engine.py)이 요구하는
  - ohlcv_store : dict[str, pd.DataFrame]  (columns: open·high·low·close·volume)
  - market_index : pd.Series               (KOSPI 종가)
형식으로 변환해 반환한다.

References
----------
obsidian/투자성향/위험중립형_전략.md
"""
from __future__ import annotations

import time
from typing import Optional

import pandas as pd

try:
    from tqdm import tqdm as _tqdm
    _HAS_TQDM = True
except ImportError:
    _HAS_TQDM = False

from core.constant.types import Market, Tickers
from data.collectors import fetch_market_index, fetch_stock


# ── 시장 상수 ──────────────────────────────────────────────────────────────────
# KOSPI 대형주 종목 풀 (ticker → 한글 이름)
# 백테스팅에서 랜덤 유니버스 생성 시 이 풀에서 선택한다.
KOSPI_LARGE_CAP_POOL: dict[str, str] = {
    "005930.KS": "삼성전자",
    "000660.KS": "SK하이닉스",
    "035420.KS": "NAVER",
    "005380.KS": "현대차",
    "051910.KS": "LG화학",
    "006400.KS": "삼성SDI",
    "000270.KS": "기아",
    "068270.KS": "셀트리온",
    "035720.KS": "카카오",
    "105560.KS": "KB금융",
    "055550.KS": "신한지주",
    "086790.KS": "하나금융지주",
    "032830.KS": "삼성생명",
    "017670.KS": "SK텔레콤",
    "030200.KS": "KT",
    "066570.KS": "LG전자",
    "096770.KS": "SK이노베이션",
    "010950.KS": "S-Oil",
    "012330.KS": "현대모비스",
    "028260.KS": "삼성물산",
}

BOND_ANNUAL_RATES: dict[int, float] = {
    2017: 0.016,
    2018: 0.018,
    2019: 0.015,
    2020: 0.010,
    2021: 0.010,
    2022: 0.025,
    2023: 0.035,
    2024: 0.035,
    2025: 0.030,
    2026: 0.030,
}

DEFAULT_BOND_ANNUAL_RATE = 0.030

def get_kospi_top_n(n: int = 200) -> dict[str, str]:
    """FinanceDataReader를 이용해 코스피 시가총액 상위 N개 종목(Yahoo 티커 맵핑)을 가져온다."""
    try:
        import FinanceDataReader as fdr
        df = fdr.StockListing('KOSPI')
        # Marcap(시가총액) 기준으로 내림차순 정렬 후 상위 n개 추출
        top_n = df.sort_values(by='Marcap', ascending=False).head(n)
        
        pool = {}
        for _, row in top_n.iterrows():
            ticker = f"{row['Code']}.KS"
            pool[ticker] = row['Name']
        return pool
    except Exception as e:
        print(f"FinanceDataReader 로딩 중 에러 발생: {e}")
        return KOSPI_LARGE_CAP_POOL

# ── 개별 함수 ──────────────────────────────────────────────────────────────────

def _split_ticker(ticker: str) -> tuple[str, Market]:
    """야후 풀티커를 (종목코드, Market)으로 분리한다."""
    for market in Market:
        if ticker.endswith(market.suffix):
            return ticker[: -len(market.suffix)], market
    raise ValueError(f"지원하지 않는 티커 형식입니다: {ticker}")


def download_kospi_index(start: str, end: str) -> pd.Series:
    """KOSPI 지수 종가 시리즈를 다운로드한다.

    Parameters
    ----------
    start : str
        시작일 (예: '2017-01-01')
    end : str
        종료일 (예: '2026-01-01')

    Returns
    -------
    pd.Series
        DatetimeIndex 기반 KOSPI 종가 시리즈.
    """
    close = fetch_market_index(Market.KOSPI, start=start, end=end)
    close = close.tz_convert(None).dropna()
    if close.empty:
        raise ValueError(
            f"KOSPI 지수 데이터를 가져올 수 없습니다. (티커: {Tickers.KOSPI_INDEX.ticker})"
        )
    return close


def download_stock_ohlcv(
    ticker: str,
    start: str,
    end: str,
) -> Optional[pd.DataFrame]:
    """단일 종목 OHLCV DataFrame을 다운로드한다.

    Parameters
    ----------
    ticker : str
        Yahoo Finance 티커 (예: '005930.KS')
    start : str
        시작일
    end : str
        종료일

    Returns
    -------
    pd.DataFrame or None
        columns: open · high · low · close · volume
        데이터 수집 실패 시 None 반환.
    """
    try:
        code, market = _split_ticker(ticker)
        raw = fetch_stock(code, market, start=start, end=end)
    except Exception:
        return None

    if raw.empty:
        return None

    df = raw[["Open", "High", "Low", "Close", "Volume"]].copy()
    df.columns = ["open", "high", "low", "close", "volume"]
    df.index = df.index.tz_convert(None)
    df = df.dropna(subset=["close"])
    return df if not df.empty else None


def download_multiple_stocks(
    tickers: list[str],
    start: str,
    end: str,
    show_progress: bool = True,
    sleep_seconds: float = 0.5,
) -> dict[str, pd.DataFrame]:
    """여러 종목 OHLCV 데이터를 일괄 다운로드한다.

    Parameters
    ----------
    tickers : list[str]
        다운로드할 티커 목록
    start, end : str
        기간
    show_progress : bool
        True이면 tqdm 진행 바 표시.
    sleep_seconds : float
        API 호출 간 대기 시간 (rate limit 방지).

    Returns
    -------
    dict[str, pd.DataFrame]
        ohlcv_store 형태의 딕셔너리. 실패 종목은 제외된다.
    """
    iterator = (
        _tqdm(tickers, desc="종목 데이터 수집")
        if (show_progress and _HAS_TQDM)
        else tickers
    )
    ohlcv_store: dict[str, pd.DataFrame] = {}
    for ticker in iterator:
        time.sleep(sleep_seconds)
        df = download_stock_ohlcv(ticker, start, end)
        if df is not None:
            ohlcv_store[ticker] = df
    return ohlcv_store


def _resolve_ticker(ticker: Tickers | str) -> tuple[str, str]:
    """Yahoo Finance 티커와 백테스트 컬럼명을 함께 반환한다."""
    if isinstance(ticker, Tickers):
        return ticker.ticker, ticker.name

    ticker_value = str(ticker)
    for registered in Tickers:
        if ticker_value in {registered.name, registered.ticker}:
            return registered.ticker, registered.name
    return ticker_value, ticker_value


def _is_bond_etf(ticker: Tickers | str) -> bool:
    """단기채 ETF 여부를 등록된 Tickers 기준으로 판별한다."""
    _, name = _resolve_ticker(ticker)
    return name == Tickers.BOND_ETF.name


def download_etf_returns(
    index: pd.DatetimeIndex,
    ticker: Tickers | str = Tickers.BOND_ETF,
) -> Optional[pd.Series]:
    """실제 ETF 가격으로 일별 수익률을 계산한다.

    ETF 종가를 백테스트 캘린더에 맞춰 forward-fill한 뒤
    pct_change()로 일별 수익률을 계산한다. ETF 상장 전처럼 실제
    가격이 없는 구간은 NaN으로 남겨 호출부가 fallback 여부를
    결정할 수 있게 한다.

    Parameters
    ----------
    index : pd.DatetimeIndex
        수익률을 생성할 날짜 인덱스 (거래일 기준).
    ticker : Tickers or str
        등록된 Tickers enum 또는 Yahoo Finance ETF 티커.

    Returns
    -------
    pd.Series or None
        일별 ETF 수익률 시리즈. 다운로드 실패 시 None.
    """
    yahoo_ticker, series_name = _resolve_ticker(ticker)
    if len(index) == 0:
        return pd.Series(dtype=float, index=index, name=series_name)

    start = pd.Timestamp(index.min()).strftime("%Y-%m-%d")
    # yfinance의 end는 exclusive이므로 마지막 거래일 다음 날까지 요청한다.
    end = (pd.Timestamp(index.max()) + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    df = download_stock_ohlcv(yahoo_ticker, start=start, end=end)
    if df is None or df.empty:
        return None

    close = df["close"].astype(float).sort_index()
    if isinstance(close.index, pd.DatetimeIndex) and close.index.tz is not None:
        close.index = close.index.tz_convert(None)

    aligned_close = close.reindex(index).ffill()
    returns = aligned_close.pct_change()
    listed = aligned_close.notna()
    if listed.any():
        returns.loc[listed.idxmax()] = 0.0
    returns.name = series_name
    return returns


def make_bond_returns(index: pd.DatetimeIndex) -> pd.Series:
    """단기채 ETF 일별 수익률을 만들고, 없으면 연도별 추정치로 대체한다."""
    index = pd.DatetimeIndex(index)
    if len(index) == 0:
        return pd.Series(dtype=float, index=index, name=Tickers.BOND_ETF.name)

    actual_returns = download_etf_returns(index, ticker=Tickers.BOND_ETF)
    if actual_returns is not None and actual_returns.notna().any():
        return actual_returns.fillna(0.0)

    daily_returns = [
        (1 + BOND_ANNUAL_RATES.get(pd.Timestamp(day).year, DEFAULT_BOND_ANNUAL_RATE)) ** (1 / 252) - 1
        for day in index
    ]
    return pd.Series(daily_returns, index=index, dtype=float, name=Tickers.BOND_ETF.name)


def make_defensive_asset_returns(
    index: pd.DatetimeIndex,
    ticker: Tickers | str
) -> pd.Series:
    """전략 방어 ETF의 일별 수익률 시리즈를 생성한다.

    기본적으로 실제 ETF 시세를 다운로드해 일별 수익률을 계산한다.
    단기채 ETF는 다운로드 실패 또는 상장 전 구간을 기존 연도별
    단기금리 추정치로 보완할 수 있다.

    Parameters
    ----------
    index : pd.DatetimeIndex
        수익률을 생성할 날짜 인덱스 (거래일 기준).
    ticker : Tickers or str
        등록된 Tickers enum 또는 Yahoo Finance ETF 티커.
    fallback_to_estimate : bool
        True이면 단기채 ETF의 실제 데이터가 없는 구간을 기존 추정치로 메운다.

    Returns
    -------
    pd.Series
        일별 방어 ETF 수익률 시리즈.
    """
    index = pd.DatetimeIndex(index)
    yahoo_ticker, series_name = _resolve_ticker(ticker)
    if len(index) == 0:
        return pd.Series(dtype=float, index=index, name=series_name)

    if _is_bond_etf(ticker):
        return make_bond_returns(index)

    actual_returns = download_etf_returns(index, ticker=ticker)
    if actual_returns is not None and actual_returns.notna().any():
        return actual_returns.fillna(0.0)

    raise ValueError(f"ETF 데이터를 가져올 수 없습니다. (티커: {yahoo_ticker})")



def get_ticker_name(ticker: str) -> str:
    """티커의 한글 이름을 반환한다. 풀에 없으면 티커 그대로 반환."""
    return KOSPI_LARGE_CAP_POOL.get(ticker, ticker)
