"""Backward-compatibility shim. Use individual category modules instead.

from data.loaders.commodities import download_copper, download_gold, download_wti
from data.loaders.rates import download_tnx, download_cpi
from data.loaders.risk_indicators import download_sox, download_bdry
from data.loaders.fx import download_dollar_index
"""
from .commodities import download_all_commodities, download_copper, download_gold, download_wti
from .fx import download_all_fx, download_dollar_index
from .rates import download_all_rates, download_cpi, download_tnx
from .risk_indicators import download_all_risk_indicators, download_bdry, download_sox

__all__ = [
    "download_copper",
    "download_gold",
    "download_wti",
    "download_tnx",
    "download_cpi",
    "download_sox",
    "download_bdry",
    "download_dollar_index",
    "download_all_commodities",
    "download_all_rates",
    "download_all_risk_indicators",
    "download_all_fx",
]
