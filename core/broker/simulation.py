import datetime
import copy
import json
import math
import os
import uuid
from pathlib import Path
from zoneinfo import ZoneInfo

from core.broker.kis_api import normalize_symbol

KST = ZoneInfo("Asia/Seoul")


class LocalSimulationBroker:
    """Persistent local broker used to test the complete execution loop."""

    is_mock = True
    is_simulated = True
    masked_account = "LOCAL-SIM"

    def __init__(
        self, state_path: str | os.PathLike | None = None, *,
        initial_cash: float | None = None,
        commission_rate: float | None = None,
        sell_tax_rate: float | None = None,
        slippage_rate: float | None = None,
    ):
        default_path = Path("logs/simulate/sim_account.json")
        self.state_path = Path(state_path or os.getenv("SIM_ACCOUNT_PATH") or default_path)
        self._migrate_legacy = self.state_path == default_path
        self.initial_cash = self._positive(initial_cash if initial_cash is not None else os.getenv("SIM_INITIAL_CASH", "500000000"))
        self.commission_rate = self._rate(commission_rate if commission_rate is not None else os.getenv("SIM_COMMISSION_RATE", "0.00015"))
        self.sell_tax_rate = self._rate(sell_tax_rate if sell_tax_rate is not None else os.getenv("SIM_SELL_TAX_RATE", "0.0018"))
        self.slippage_rate = self._rate(slippage_rate if slippage_rate is not None else os.getenv("SIM_SLIPPAGE_RATE", "0.001"))
        self._market_prices: dict[str, float] = {}
        self._state = self._load()

    @staticmethod
    def _finite(value) -> float:
        try:
            number = float(value)
        except (TypeError, ValueError, OverflowError):
            raise ValueError("simulation values must be finite numbers") from None
        if isinstance(value, bool) or not math.isfinite(number):
            raise ValueError("simulation values must be finite numbers")
        return number

    @classmethod
    def _positive(cls, value) -> float:
        number = cls._finite(value)
        if number <= 0:
            raise ValueError("simulation amounts and prices must be positive finite numbers")
        return number

    @classmethod
    def _rate(cls, value) -> float:
        number = cls._finite(value)
        if not 0 <= number < 1:
            raise ValueError("simulation cost rates must be finite and in [0, 1)")
        return number

    @classmethod
    def validate_quantity(cls, value) -> int:
        number = cls._finite(value)
        if number <= 0 or not number.is_integer():
            raise ValueError("simulation quantity must be a positive whole number")
        return int(number)

    @classmethod
    def _validate_state(cls, state):
        if not isinstance(state, dict) or not isinstance(state.get("positions"), dict) or not isinstance(state.get("orders"), dict):
            raise ValueError("simulation account state is incomplete")
        cash = cls._finite(state["cash"])
        if cash < 0:
            raise ValueError("simulation account cash must be nonnegative and finite")
        for row in state["positions"].values():
            cls.validate_quantity(row["qty"])
            cls._positive(row["avg_price"])
            cls._positive(row.get("current_price", row["avg_price"]))
        keys = set()
        for row in state["orders"].values():
            cls.validate_quantity(row["qty"])
            cls._positive(row["fill_price"])
            cls._positive(row["reference_price"])
            if not isinstance(row["symbol"], str) or not row["symbol"]:
                raise ValueError("simulation order symbol is invalid")
            datetime.datetime.fromisoformat(row["created_at"])
            key = row.get("idempotency_key")
            if key is not None:
                if not isinstance(key, str) or not key.strip() or key in keys:
                    raise ValueError("simulation account has an invalid idempotency key")
                keys.add(key)
            for name in ("gross", "commission", "tax", "slippage_cost"):
                value = cls._finite(row[name])
                if value < 0:
                    raise ValueError("simulation order amounts must be nonnegative and finite")
            if row["side"] not in {"BUY", "SELL"} or row["status"] != "FILLED":
                raise ValueError("simulation account has an invalid fill")

    def _load(self) -> dict:
        legacy = Path("logs/sim_account.json")
        if not self.state_path.exists() and legacy.exists() and self._migrate_legacy:
            state = json.loads(legacy.read_text(encoding="utf-8"))
            self._save(state)
        if self.state_path.exists():
            try:
                state = json.loads(self.state_path.read_text(encoding="utf-8"))
                self._validate_state(state)
            except (ValueError, TypeError, KeyError, AttributeError):
                raise ValueError("simulation account state is invalid; preserve the file and repair it") from None
            return state
        state = {
            "cash": self.initial_cash,
            "positions": {},
            "orders": {},
            "updated_at": datetime.datetime.now(KST).isoformat(timespec="seconds"),
        }
        self._save(state)
        return state

    def _save(self, state: dict | None = None) -> None:
        candidate = copy.deepcopy(state if state is not None else self._state)
        self._validate_state(candidate)
        candidate["updated_at"] = datetime.datetime.now(KST).isoformat(timespec="seconds")
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.state_path.with_suffix(self.state_path.suffix + ".tmp")
        temp.write_text(json.dumps(candidate, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
        os.replace(temp, self.state_path)
        self._state = candidate

    def set_market_price(self, ticker: str, price: float) -> None:
        symbol = normalize_symbol(ticker)
        price = self._positive(price)
        candidate = copy.deepcopy(self._state)
        position = candidate["positions"].get(symbol)
        if position:
            position["current_price"] = price
            self._save(candidate)
        self._market_prices[symbol] = price

    def get_current_price(self, ticker: str) -> float:
        symbol = normalize_symbol(ticker)
        price = self._market_prices.get(symbol)
        if price is None:
            position = self._state["positions"].get(symbol, {})
            price = position.get("current_price") or position.get("avg_price")
        if price is None:
            raise ValueError(f"simulation price is unavailable: {ticker}")
        return self._positive(price)

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

    def place_market_buy(self, ticker: str, qty: int, *, idempotency_key: str | None = None) -> dict:
        return self._fill("BUY", ticker, qty, idempotency_key=idempotency_key)

    def place_market_sell(self, ticker: str, qty: int, *, idempotency_key: str | None = None) -> dict:
        return self._fill("SELL", ticker, qty, idempotency_key=idempotency_key)

    def _fill(self, side: str, ticker: str, qty: int, *, idempotency_key: str | None = None) -> dict:
        qty = self.validate_quantity(qty)
        symbol = normalize_symbol(ticker)
        if idempotency_key is not None:
            if not isinstance(idempotency_key, str) or not idempotency_key.strip():
                raise ValueError("simulation idempotency key must be a nonempty string")
            for order_id, row in self._state["orders"].items():
                if row.get("idempotency_key") == idempotency_key:
                    if (row["side"], row["symbol"], row["qty"]) != (side, symbol, qty):
                        raise ValueError("simulation idempotency key conflicts with a previous order")
                    return {"rt_cd": "0", "output": {"ODNO": order_id}, "msg1": "LOCAL_SIM_EXISTING_FILL"}
        reference = self.get_current_price(ticker)
        fill_price = reference * (
            1.0 + self.slippage_rate if side == "BUY" else 1.0 - self.slippage_rate
        )
        gross = fill_price * int(qty)
        commission = gross * self.commission_rate
        tax = gross * self.sell_tax_rate if side == "SELL" else 0.0
        candidate = copy.deepcopy(self._state)
        position = candidate["positions"].get(symbol)

        if side == "BUY":
            cost = gross + commission
            if float(candidate["cash"]) < cost:
                raise ValueError("simulation cash shortage")
            old_qty = int(position["qty"]) if position else 0
            old_cost = old_qty * float(position["avg_price"]) if position else 0.0
            new_qty = old_qty + int(qty)
            candidate["cash"] = float(candidate["cash"]) - cost
            candidate["positions"][symbol] = {
                "qty": new_qty,
                "avg_price": (old_cost + gross + commission) / new_qty,
                "current_price": reference,
            }
        else:
            held = int(position["qty"]) if position else 0
            if held < int(qty):
                raise ValueError("simulation sellable quantity shortage")
            remaining = held - int(qty)
            candidate["cash"] = float(candidate["cash"]) + gross - commission - tax
            if remaining:
                position["qty"] = remaining
                position["current_price"] = reference
            else:
                candidate["positions"].pop(symbol, None)

        order_id = uuid.uuid4().hex[:12]
        candidate["orders"][order_id] = {
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
            "idempotency_key": idempotency_key,
            "created_at": datetime.datetime.now(KST).isoformat(timespec="seconds"),
        }
        self._save(candidate)
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
        target_day = target_date or datetime.datetime.now(KST).date()
        target_day = target_day.isoformat() if hasattr(target_day, "isoformat") else str(target_day)
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
            if row["created_at"][:10] == target_day
        ]
