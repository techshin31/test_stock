"""Backtest input configuration."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Literal

import pandas as pd

from core.constant.types import Market, StockCap
from core.portfolio.rotation import RotationPlan
from core.strategy.base import AbstractStrategy

from .enum import InsufficientHistoryPolicy

@dataclass
class BacktestConfig:
    strategy: AbstractStrategy
    start_date: date
    end_date: date
    initial_capital: float
    initial_universe: list[str]
    market: Market
    cap: StockCap
    market_index: pd.Series
    rotation_plans: list[RotationPlan] = field(default_factory=list)
    benchmark_returns: pd.Series | None = None
    defensive_asset_returns: pd.Series | None = None
    min_history_days: int = 252
    insufficient_history_policy: str = InsufficientHistoryPolicy.EXCLUDE.value
