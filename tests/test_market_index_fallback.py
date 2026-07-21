import pandas as pd

from core.constant.types import Market
from data.collectors import yfinance_collector


def test_market_index_extends_stale_yahoo_with_fdr(monkeypatch):
    yahoo = pd.DataFrame(
        {"Close": [6800.0]},
        index=pd.DatetimeIndex(["2026-07-16"]),
    )
    fdr = pd.DataFrame(
        {"Close": [6800.0, 6516.27, 6400.0]},
        index=pd.DatetimeIndex(["2026-07-16", "2026-07-20", "2026-07-21"]),
    )
    monkeypatch.setattr(yfinance_collector, "_yf_download_with_retry", lambda **kwargs: yahoo)
    monkeypatch.setattr(yfinance_collector.fdr, "DataReader", lambda *args: fdr)

    result = yfinance_collector.fetch_market_index(
        Market.KOSPI,
        start="2026-07-01",
        end="2026-07-21",
    )

    assert result.index[-1] == pd.Timestamp("2026-07-20", tz="UTC")
    assert result.iloc[-1] == 6516.27


def test_market_index_uses_yahoo_when_fdr_fails(monkeypatch):
    yahoo = pd.DataFrame(
        {"Close": [6800.0]},
        index=pd.DatetimeIndex(["2026-07-20"]),
    )
    monkeypatch.setattr(yfinance_collector, "_yf_download_with_retry", lambda **kwargs: yahoo)
    monkeypatch.setattr(
        yfinance_collector.fdr,
        "DataReader",
        lambda *args: (_ for _ in ()).throw(RuntimeError("fdr unavailable")),
    )

    result = yfinance_collector.fetch_market_index(
        Market.KOSPI,
        start="2026-07-01",
        end="2026-07-21",
    )

    assert result.index[-1] == pd.Timestamp("2026-07-20", tz="UTC")


def test_market_index_uses_fdr_when_yahoo_fails(monkeypatch):
    fdr = pd.DataFrame(
        {"Close": [6516.27]},
        index=pd.DatetimeIndex(["2026-07-20"]),
    )
    monkeypatch.setattr(
        yfinance_collector,
        "_yf_download_with_retry",
        lambda **kwargs: (_ for _ in ()).throw(RuntimeError("yahoo unavailable")),
    )
    monkeypatch.setattr(yfinance_collector.fdr, "DataReader", lambda *args: fdr)

    result = yfinance_collector.fetch_market_index(
        Market.KOSPI,
        start="2026-07-01",
        end="2026-07-21",
    )

    assert result.iloc[-1] == 6516.27
