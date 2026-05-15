"""시장 데이터 수집 — config.py의 티커로 yfinance에서 OHLCV 로드"""

import pandas as pd
import yfinance as yf

from ..config import TICKERS, KOSPI_TICKER, CASH_ETF_TICKER, CASH_ETF_NAME


def load_data(
    start: str,
    end: str,
    tickers: dict = None,
    kospi_ticker: str = None,
    cash_etf_ticker: str = None,
) -> dict:
    """yfinance에서 멀티 종목 OHLCV + KOSPI + 단기채 ETF 로드

    Parameters
    ----------
    start : 'YYYY-MM-DD'
    end   : 'YYYY-MM-DD'
    tickers, kospi_ticker, cash_etf_ticker : None이면 config 기본값 사용

    Returns
    -------
    dict with keys:
      'close', 'high', 'low', 'volume' : 종목 DataFrame
      'kospi'                           : KOSPI Series
      'cash_etf'                        : 단기채 ETF Series
    """
    _tickers        = tickers        or TICKERS
    _kospi_ticker   = kospi_ticker   or KOSPI_TICKER
    _cash_etf_ticker = cash_etf_ticker or CASH_ETF_TICKER

    names    = list(_tickers.keys())
    codes    = list(_tickers.values())
    name_map = {v: k for k, v in _tickers.items()}

    all_codes = codes + [_kospi_ticker, _cash_etf_ticker]
    raw = yf.download(all_codes, start=start, end=end, auto_adjust=True, progress=False)

    close  = raw["Close"][codes].rename(columns=name_map)[names].ffill().dropna()
    high   = raw["High"][codes].rename(columns=name_map)[names].ffill().dropna()
    low    = raw["Low"][codes].rename(columns=name_map)[names].ffill().dropna()
    volume = raw["Volume"][codes].rename(columns=name_map)[names].fillna(0)

    kospi    = raw["Close"][_kospi_ticker].reindex(close.index, method="ffill")
    cash_etf = raw["Close"][_cash_etf_ticker].reindex(close.index, method="ffill")

    kospi.name    = "KOSPI"
    cash_etf.name = CASH_ETF_NAME

    return {
        "close":    close,
        "high":     high,
        "low":      low,
        "volume":   volume,
        "kospi":    kospi,
        "cash_etf": cash_etf,
    }
