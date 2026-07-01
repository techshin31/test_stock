"""Run a strategy across a portfolio universe."""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from core.strategy.base import AbstractStrategy


@dataclass
class PortfolioSignals:
    """Strategy signals and metadata for multiple tickers."""

    signals: pd.DataFrame
    metadata: dict[str, pd.DataFrame]


def make_portfolio_signals(
    strategy: AbstractStrategy,
    ohlcv_store: dict[str, pd.DataFrame],
    regime_dict: dict[str, pd.DataFrame],
    calendar: pd.DatetimeIndex,
) -> PortfolioSignals:
    """Run ``strategy`` for each ticker and align outputs to ``calendar``."""
    tickers = list(ohlcv_store.keys())
    signals = pd.DataFrame(index=calendar, columns=tickers, dtype=float)
    metadata: dict[str, pd.DataFrame] = {}

    for ticker, ohlcv in ohlcv_store.items():
        ticker_signals, ticker_metadata = strategy.make_signals_with_metadata(
            ohlcv,
            regime_dict[ticker].reindex(ohlcv.index),
        )
        signals[ticker] = ticker_signals.reindex(calendar)
        metadata[ticker] = ticker_metadata.reindex(calendar)

    return PortfolioSignals(signals=signals, metadata=metadata)

