"""Exercise production trading components with synthetic data in a temporary account."""
from __future__ import annotations

import math
from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np
import pandas as pd

from core.broker.simulation import LocalSimulationBroker
from core.execution.trader import LiveTrader
from core.strategy.fa_ta_momentum import FaTaMomentumStrategy


def run_local_check() -> dict:
    # This is a component integration check, not a historical FA backtest.
    # Deliberately avoid LiveTrader.__init__: no DB/KIS/notification clients.
    with TemporaryDirectory(prefix="quantpilot-local-check-") as directory:
        state_path = Path(directory) / "account.json"
        settings = dict(initial_cash=1_000_000, commission_rate=0.00015,
                        sell_tax_rate=0.0018, slippage_rate=0.001)
        broker = LocalSimulationBroker(state_path, **settings)
        trader = object.__new__(LiveTrader)
        trader.broker = broker
        trader.execution_venue = "SIMULATE"
        trader.strategy_name = "aggressive"
        trader.max_position_weight = 0.15
        trader.max_order_attempts = 2
        trader.rebalance_band = 0.10
        trader.price_guard_path = Path(directory) / "price_guard.json"
        strategy = FaTaMomentumStrategy({})
        ticker = "005930.KS"
        close = np.linspace(100, 200, 70)
        frame = pd.DataFrame({
            "open": close, "high": close + 1, "low": close - 1,
            "close": close, "volume": 1000, "fa_score": 75.0,
            "is_eligible": True, "debt_ratio": 0.5, "score_confidence": 0.9,
        }, index=pd.bdate_range("2026-01-01", periods=len(close)))
        target, metadata = strategy.evaluate_latest(frame, "UPTREND")
        targets = trader._apply_portfolio_limits({ticker: target}, {ticker: metadata}, {})
        buy_orders = trader._calculate_orders(
            1_000_000, {}, targets, {ticker: frame}, {ticker: metadata},
        )
        checks = {
            "strategy_entry": target > 0 and metadata["signal_reason"] == "FA_TA_ENTRY",
            "position_cap": 0 < targets[ticker] <= 0.15,
            "buy_plan": len(buy_orders) == 1 and buy_orders[0]["type"] == "BUY",
        }
        if not checks["buy_plan"]:
            return _report(checks, [])

        before = state_path.read_bytes()
        trader.execution_venue = "DRY_RUN"
        preview = trader._execute_orders(buy_orders)
        checks["dry_run_no_fill"] = (
            state_path.read_bytes() == before
            and all(row["status"] == "DRY_RUN" for row in preview)
        )
        trader.execution_venue = "SIMULATE"
        bought = trader._execute_orders(buy_orders)
        checks["buy_filled"] = all(row["status"] == "FILLED" for row in bought)
        if not checks["buy_filled"]:
            return _report(checks, bought)
        after_buy_balance = trader.broker.get_balance()
        trader.broker = LocalSimulationBroker(state_path, **settings)
        repeated = trader._execute_orders(buy_orders)
        checks["restart_preserves_position"] = (
            trader.broker.get_balance()["positions"][ticker]["qty"] == buy_orders[0]["qty"]
        )
        checks["restart_deduplicates_order"] = (
            repeated[0].get("broker_order_id") == bought[0]["broker_order_id"]
            and trader.broker.get_balance() == after_buy_balance
            and len(trader.broker._state["orders"]) == 1
        )

        position = trader.broker.get_balance()["positions"][ticker]
        stop_price = position["avg_price"] * 0.88
        trader.broker.set_market_price(ticker, stop_price)
        balance = trader.broker.get_balance()
        current_weight = position["qty"] * stop_price / balance["total_asset"]
        exit_target, risk = strategy.evaluate_position_risk(
            current_position=current_weight, average_price=position["avg_price"],
            current_price=stop_price, peak_price=position["avg_price"],
        )
        checks["hard_stop"] = exit_target == 0 and risk["signal_reason"] == "HARD_STOP_LOSS"
        guarded = trader._apply_entry_circuit_breaker(
            {ticker: exit_target, "000660.KS": 0.15}, {ticker: risk},
            balance["positions"], balance["total_asset"], "MANUAL_KILL_SWITCH",
        )
        checks["kill_switch_keeps_exit"] = guarded[ticker] == 0 and guarded["000660.KS"] == 0
        sells = trader._calculate_orders(
            balance["total_asset"], balance["positions"], guarded,
            {ticker: frame}, {ticker: risk},
        )
        sold = trader._execute_orders(sells)
        checks["sell_filled"] = (
            len(sold) == 1 and sold[0]["type"] == "SELL" and sold[0]["status"] == "FILLED"
        )
        account = trader.broker.get_balance()
        checks["position_closed"] = not account["positions"]
        ledger = list(trader.broker._state["orders"].values())
        expected_cash = settings["initial_cash"] + sum(
            (-row["gross"] if row["side"] == "BUY" else row["gross"])
            - row["commission"] - row["tax"] for row in ledger
        )
        checks["cash_ledger_reconciles"] = (
            len(ledger) == 2
            and math.isclose(account["cash"], expected_cash, rel_tol=0, abs_tol=1e-6)
        )
        before_rejection = state_path.read_bytes()
        try:
            trader.broker.place_market_sell(ticker, 1)
        except ValueError:
            checks["oversell_rejected"] = state_path.read_bytes() == before_rejection
        else:
            checks["oversell_rejected"] = False
        return _report(checks, bought + sold)


def _report(checks, orders):
    return {
        "status": "PASS" if all(checks.values()) else "FAIL",
        "scope": "ISOLATED_COMPONENT_INTEGRATION", "input_source": "SYNTHETIC_FIXTURE",
        "external_broker_initialized": False, "production_database_modified": False,
        "fa_backtest_validated": False, "operational_readiness": "NOT_ASSESSED",
        "checks": checks, "simulation_fills": orders,
    }
