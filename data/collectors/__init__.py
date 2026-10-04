"""Market data collectors."""

from .fred_collector import fetch_fred_series
from .wics_collector import WICS_INDUSTRY_CODES, fetch_wics_json, parse_wics_companies
from .yfinance_collector import fetch_market_index, fetch_stock, fetch_yfinance_close

__all__ = [
    # yfinance
    "fetch_stock",
    "fetch_market_index",
    "fetch_yfinance_close",
    # FRED
    "fetch_fred_series",
    # WICS
    "fetch_wics_json",
    "parse_wics_companies",
    "WICS_INDUSTRY_CODES",
]
