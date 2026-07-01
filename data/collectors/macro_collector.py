"""Backward-compatibility shim. Use fred_collector or yfinance_collector directly."""
from .fred_collector import fetch_fred_series
from .yfinance_collector import fetch_yfinance_close

__all__ = ["fetch_yfinance_close", "fetch_fred_series"]
