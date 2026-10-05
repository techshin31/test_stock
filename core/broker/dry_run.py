"""An in-memory hypothetical account for credential-free order planning."""
from __future__ import annotations

import os

from core.broker.kis_api import normalize_symbol
from core.broker.simulation import LocalSimulationBroker


class DryRunBroker:
    is_mock = True
    is_simulated = True
    masked_account = "DRY-RUN-VIRTUAL"

    def __init__(self, initial_cash=None):
        self.cash = LocalSimulationBroker._positive(
            initial_cash if initial_cash is not None else os.getenv("DRY_RUN_INITIAL_CASH", "10000000")
        )
        self._prices = {}

    def get_balance(self):
        return {"cash": self.cash, "today_cash": self.cash, "total_asset": self.cash,
                "positions": {}, "account_source": "HYPOTHETICAL"}

    def set_market_price(self, ticker, price):
        self._prices[normalize_symbol(ticker)] = LocalSimulationBroker._positive(price)

    def get_current_price(self, ticker):
        return self._prices[normalize_symbol(ticker)]

    def fetch_daily_orders(self, target_date=None):
        return []

    def place_market_buy(self, *args, **kwargs):
        raise PermissionError("DRY_RUN cannot submit orders")

    def place_market_sell(self, *args, **kwargs):
        raise PermissionError("DRY_RUN cannot submit orders")
