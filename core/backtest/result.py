"""Backtest output data model."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import pandas as pd

from core.optimization.walk_forward import WalkForwardWindow
from .config import BacktestConfig


@dataclass
class BacktestResult:
    config: BacktestConfig
    equity_curve: pd.Series
    daily_returns: pd.Series
    cost_series: pd.Series
    weights: pd.DataFrame
    values: pd.DataFrame
    signals: pd.DataFrame
    regime_dict: dict[str, pd.DataFrame]
    wf_windows: dict[str, list[WalkForwardWindow]]
    universe_snapshots: list[tuple[date, list[str]]]
    signal_metadata: dict[str, pd.DataFrame] | None = None
    excluded_tickers: dict[str, str] | None = None
    trade_ledger: pd.DataFrame | None = None
    gross_return_contributions: pd.DataFrame | None = None
    cost_contributions: pd.DataFrame | None = None
    net_return_contributions: pd.DataFrame | None = None
    lookahead_warnings: dict[str, str] | None = None
