import datetime
import json
import os
import uuid
from pathlib import Path

from core.broker.kis_api import normalize_symbol


class LocalSimulationBroker:
    """Persistent local broker used to test the complete execution loop."""

    is_mock = True
    is_simulated = True
    masked_account = "LOCAL-SIM"

    def __init__(self, state_path: str | os.PathLike | None = None):
        self.state_path = Path(state_path or os.getenv("SIM_ACCOUNT_PATH", "logs/simulate/sim_account.json"))
        self.initial_cash = float(os.getenv("SIM_INITIAL_CASH", "500000000"))
        self.commission_rate = float(os.getenv("SIM_COMMISSION_RATE", "0.00015"))
        self.sell_tax_rate = float(os.getenv("SIM_SELL_TAX_RATE", "0.0018"))
        self.slippage_rate = float(os.getenv("SIM_SLIPPAGE_RATE", "0.001"))
        self._market_prices: dict[str, float] = {}
        self._state = self._load()

    def _load(self) -> dict:
        legacy = Path("logs/sim_account.json")
        if not self.state_path.exists() and legacy.exists() and self.state_path != legacy:
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
            self.state_path.write_text(legacy.read_text(encoding="utf-8"), encoding="utf-8")
        if self.state_path.exists():
            return json.loads(self.state_path.read_text(encoding="utf-8"))
        state = {
            "cash": self.initial_cash,
            "positions": {},
            "orders": {},
            "updated_at": datetime.datetime.now().isoformat(timespec="seconds"),
        }
        self._save(state)
        return state

    def _save(self, state: dict | None = None) -> None:
        if state is not None:
            self._state = state
        self._state["updated_at"] = datetime.datetime.now().isoformat(timespec="seconds")
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.state_path.with_suffix(self.state_path.suffix + ".tmp")
        temp.write_text(json.dumps(self._state, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temp, self.state_path)

    def set_market_price(self, ticker: str, price: float) -> None:
        symbol = normalize_symbol(ticker)
        self._market_prices[symbol] = float(price)
        position = self._state["positions"].get(symbol)
        if position:
            position["current_price"] = float(price)
            self._save()

    def get_current_price(self, ticker: str) -> float:
        symbol = normalize_symbol(ticker)
        price = self._market_prices.get(symbol)
        if price is None:
            position = self._state["positions"].get(symbol, {})
            price = position.get("current_price") or position.get("avg_price")
        if not price or float(price) <= 0:
            raise ValueError(f"simulation price is unavailable: {ticker}")
        return float(price)

    def get_balance(self) -> dict:
        positions = {}
        stock_value = 0.0
        for symbol, row in self._state["positions"].items():
            qty = int(row["qty"])
            if qty <= 0:
                continue
            price = float(row.get("current_price") or row["avg_price"])
            avg_price = float(row["avg_price"])
            stock_value += qty * price
            positions[f"{symbol}.KS"] = {
                "qty": qty,
                "avg_price": avg_price,
                "current_price": price,
                "profit_rate": (price / avg_price - 1.0) * 100 if avg_price else 0.0,
            }
        cash = float(self._state["cash"])
        return {
            "cash": cash,
            "today_cash": cash,
            "total_asset": cash + stock_value,
            "positions": positions,
        }

    def place_market_buy(self, ticker: str, qty: int) -> dict:
        return self._fill("BUY", ticker, qty)

    def place_market_sell(self, ticker: str, qty: int) -> dict:
        return self._fill("SELL", ticker, qty)

    def _fill(self, side: str, ticker: str, qty: int) -> dict:
        if int(qty) <= 0:
            raise ValueError("simulation order quantity must be positive")
        symbol = normalize_symbol(ticker)
        reference = self.get_current_price(ticker)
        fill_price = reference * (
            1.0 + self.slippage_rate if side == "BUY" else 1.0 - self.slippage_rate
        )
        gross = fill_price * int(qty)
        commission = gross * self.commission_rate
        tax = gross * self.sell_tax_rate if side == "SELL" else 0.0
        position = self._state["positions"].get(symbol)

        if side == "BUY":
            cost = gross + commission
            if float(self._state["cash"]) < cost:
                raise ValueError("simulation cash shortage")
            old_qty = int(position["qty"]) if position else 0
            old_cost = old_qty * float(position["avg_price"]) if position else 0.0
            new_qty = old_qty + int(qty)
            self._state["cash"] = float(self._state["cash"]) - cost
            self._state["positions"][symbol] = {
                "qty": new_qty,
                "avg_price": (old_cost + gross + commission) / new_qty,
                "current_price": reference,
            }
        else:
            held = int(position["qty"]) if position else 0
            if held < int(qty):
                raise ValueError("simulation sellable quantity shortage")
            remaining = held - int(qty)
            self._state["cash"] = float(self._state["cash"]) + gross - commission - tax
            if remaining:
                position["qty"] = remaining
                position["current_price"] = reference
            else:
                self._state["positions"].pop(symbol, None)

        order_id = uuid.uuid4().hex[:12]
        self._state["orders"][order_id] = {
            "odno": order_id,
            "symbol": symbol,
            "side": side,
            "qty": int(qty),
            "reference_price": reference,
            "fill_price": fill_price,
            "slippage_cost": abs(fill_price - reference) * int(qty),
            "gross": gross,
            "commission": commission,
            "tax": tax,
            "status": "FILLED",
            "created_at": datetime.datetime.now().isoformat(timespec="seconds"),
        }
        self._save()
        return {"rt_cd": "0", "output": {"ODNO": order_id}, "msg1": "LOCAL_SIM_FILLED"}

    def get_order_status(self, broker_order_id: str, target_date=None) -> dict:
        row = self._state["orders"].get(str(broker_order_id))
        if not row:
            raise ValueError(f"simulation order not found: {broker_order_id}")
        return {
            "status": row["status"],
            "ordered_qty": row["qty"],
            "filled_qty": row["qty"],
            "remaining_qty": 0,
            "avg_fill_price": row["fill_price"],
            "total_fill_amount": row["gross"],
            "raw": row,
        }

    def fetch_daily_orders(self, target_date=None) -> list[dict]:
        return [
            {
                "odno": order_id,
                "pdno": row["symbol"],
                "sll_buy_dvsn_cd": "02" if row["side"] == "BUY" else "01",
                "ord_qty": str(row["qty"]),
                "tot_ccld_qty": str(row["qty"]),
                "rmn_qty": "0",
                "ord_tmd": row["created_at"][11:19].replace(":", ""),
            }
            for order_id, row in self._state["orders"].items()
            if row["created_at"][:10] == datetime.date.today().isoformat()
        ]
