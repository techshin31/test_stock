"""Market data collectors."""

from .dart_collector import (
    classify_dart_event,
    fetch_dart_events,
    fetch_financial_statements,
    split_by_statement_type,
)
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
    # DART
    "fetch_financial_statements",
    "split_by_statement_type",
    "fetch_dart_events",
    "classify_dart_event",
    # WICS
    "fetch_wics_json",
    "parse_wics_companies",
    "WICS_INDUSTRY_CODES",
]
