from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from core.trade.kis_broker import KisBroker, get_tick_size, round_to_tick
from core.trade.kis_constants import OrdDvsn
from core.utils.parsing import parse_int
from storage.postgres.connection import PostgreDB
from storage.postgres.repositories.execution_repo import (
    fetch_execution_qty_by_order,
    insert_execution,
)
from storage.postgres.repositories.order_repo import (
    attach_broker_order_id,
    create_order,
    fetch_open_orders_by_plan,
    update_order_status,
)
from storage.postgres.repositories.trade_plan_repo import (
    fetch_trade_plan_progress,
    mark_trade_plan_company_risk_blocked,
    mark_trade_plan_status,
)
from storage.postgres.repositories.company_risk_repo import is_company_buy_blocked


class ExecutionError(RuntimeError):
    """Raised when an order plan cannot be executed safely."""


@dataclass(frozen=True)
class ExecutionConfig:
    max_child_qty: int = 100
    max_attempts: int = 20
    child_timeout_sec: int = 8
    cancel_confirm_timeout_sec: int = 5
    poll_interval_sec: float = 1.0
    max_top_level_participation: float = 0.20
    aggressive_limit_ticks: int = 1


@dataclass(frozen=True)
class QuoteDecision:
    price: int
    visible_qty: int
    child_qty: int


@dataclass
class ChildOrderResult:
    order_id: str
    broker_order_id: str | None
    requested_qty: int
    filled_qty: int
    remaining_qty: int
    limit_price: int
    avg_fill_price: int = 0
    status_code: str = "PENDING"
    note: str | None = None
    unresolved: bool = False


@dataclass(frozen=True)
class CancelResult:
    requested: bool
    cancel_confirmed: bool = False
    status: dict[str, Any] | None = None
    note: str | None = None


@dataclass
class ExecutionResult:
    plan_id: int
    symbol: str
    side: str
    requested_qty: int
    filled_qty: int = 0
    avg_fill_price: float = 0.0
    child_orders: list[ChildOrderResult] = field(default_factory=list)
    executable_qty: int | None = None
    unresolved: bool = False

    @property
    def remaining_qty(self) -> int:
        return max(0, self.requested_qty - self.filled_qty)


def execute_plan_with_orderbook_slicing(
    db: PostgreDB,
    broker: KisBroker,
    plan: dict,
    config: ExecutionConfig | None = None,
) -> ExecutionResult:
    """Execute one stored trade plan with quote checks, slicing, cancel, and retry."""
    config = config or ExecutionConfig()
    symbol = str(plan["symbol"])
    side = str(plan["order_side_code"])
    requested_qty = int(plan["planned_qty"])
    progress = fetch_trade_plan_progress(db, int(plan["id"])) or {}
    confirmed_plan_filled_qty = parse_int(progress.get("filled_qty"))
    remaining_qty = max(0, requested_qty - confirmed_plan_filled_qty)
    filled_amount = 0

    result = ExecutionResult(
        plan_id=int(plan["id"]),
        symbol=symbol,
        side=side,
        requested_qty=requested_qty,
        filled_qty=confirmed_plan_filled_qty,
    )

    if requested_qty <= 0:
        mark_trade_plan_status(db, plan["id"], "SKIPPED")
        return result
    if remaining_qty <= 0:
        mark_trade_plan_status(db, plan["id"], "DONE")
        return result

    if sync_open_orders_for_plan(db, broker, int(plan["id"]), config):
        result.unresolved = True
        mark_trade_plan_status(db, plan["id"], "ORDERED")
        print(f"  [{symbol}] open broker order exists; skip new child order")
        return result

    progress = fetch_trade_plan_progress(db, int(plan["id"])) or {}
    confirmed_plan_filled_qty = parse_int(progress.get("filled_qty"))
    remaining_qty = max(0, requested_qty - confirmed_plan_filled_qty)
    result.filled_qty = confirmed_plan_filled_qty
    if remaining_qty <= 0:
        mark_trade_plan_status(db, plan["id"], "DONE")
        return result

    # Existing child orders are synchronized/cancelled first; only then may a
    # newly blocked BUY plan be closed without leaving a broker order behind.
    if side == "BUY" and is_company_buy_blocked(
        db, symbol, plan.get("plan_date")
    ):
        result.executable_qty = 0
        mark_trade_plan_company_risk_blocked(db, int(plan["id"]))
        print(f"  [{symbol}] BUY skipped: active company risk state")
        return result

    if side == "BUY":
        buyable_qty = _get_buyable_qty(broker, symbol)
        if buyable_qty <= 0:
            result.executable_qty = 0
            print(f"  [{symbol}] buyable quantity is 0; keep plan for later retry")
            return result
        if remaining_qty > buyable_qty:
            print(f"  [{symbol}] planned {remaining_qty} -> buyable {buyable_qty}")
            remaining_qty = buyable_qty

    deviation_limit = plan.get("price_deviation_limit")
    planned_price = parse_int(plan.get("planned_price"))
    if deviation_limit and float(deviation_limit) > 0 and planned_price > 0:
        book = broker.market.orderbook(symbol)
        lim = float(deviation_limit)
        if side == "BUY":
            current_ask, _ = best_quote_from_orderbook(book, "BUY")
            if current_ask > planned_price * (1 + lim):
                result.executable_qty = 0
                print(
                    f"  [{symbol}] BUY skipped: ask {current_ask:,}원 vs "
                    f"plan {planned_price:,}원 ({(current_ask/planned_price-1)*100:+.1f}% > "
                    f"+{lim*100:.1f}% limit)"
                )
                return result
        elif side == "SELL":
            current_bid, _ = best_quote_from_orderbook(book, "SELL")
            if current_bid < planned_price * (1 - lim):
                result.executable_qty = 0
                print(
                    f"  [{symbol}] SELL skipped: bid {current_bid:,}원 vs "
                    f"plan {planned_price:,}원 ({(current_bid/planned_price-1)*100:+.1f}% < "
                    f"-{lim*100:.1f}% limit)"
                )
                return result

    result.executable_qty = remaining_qty

    if side == "SELL":
        sellable_qty = _get_sellable_qty(broker, symbol)
        if sellable_qty <= 0:
            result.executable_qty = 0
            print(f"  [{symbol}] SELL skipped: KIS 매도가능수량 0 (미체결 매도 주문 또는 결제 제한 확인 필요)")
            return result
        if remaining_qty > sellable_qty:
            print(f"  [{symbol}] SELL planned {remaining_qty} -> KIS 매도가능 {sellable_qty}")
            remaining_qty = sellable_qty
            result.executable_qty = sellable_qty

    for attempt in range(1, config.max_attempts + 1):
        if remaining_qty <= 0:
            break

        decision = choose_child_order(broker, symbol, side, remaining_qty, config)
        child_qty = decision.child_qty
        if side == "BUY":
            buyable_qty = _get_buyable_qty(broker, symbol, decision.price)
            child_qty = min(child_qty, buyable_qty)
            if child_qty <= 0:
                print(f"  [{symbol}] attempt {attempt}: buyable quantity is 0")
                break

        order_plan = dict(plan)
        order_plan["planned_qty"] = child_qty
        order_plan["order_type_code"] = "LIMIT"
        order_plan["planned_price"] = decision.price
        order_id = create_order(db, order_plan)
        broker_order_id: str | None = None

        try:
            if side == "BUY":
                submit = broker.orders.buy_limit(symbol, child_qty, decision.price)
            elif side == "SELL":
                submit = broker.orders.sell_limit(symbol, child_qty, decision.price)
            else:
                raise ExecutionError(f"Unsupported order side: {side}")

            broker_order_id = submit["output"]["ODNO"]
            krx_org = submit["output"]["KRX_FWDG_ORD_ORGNO"]
            attach_broker_order_id(db, order_id, broker_order_id, raw_payload=submit.get("output"))
            mark_trade_plan_status(db, plan["id"], "ORDERED")
            print(
                f"  [{side}] {symbol} slice {attempt}: "
                f"{child_qty} @ {decision.price:,}원 "
                f"(visible {decision.visible_qty}주, odno={broker_order_id})"
            )

            status, status_error = poll_order_status(
                broker,
                broker_order_id,
                timeout_sec=config.child_timeout_sec,
                poll_interval_sec=config.poll_interval_sec,
            )
            filled_qty = int(status["filled_qty"]) if status else 0
            order_remaining_qty = int(status["remaining_qty"]) if status else child_qty
            avg_fill_price = int(status["avg_fill_price"]) if status else 0

            cancel_result = None
            if order_remaining_qty > 0:
                cancel_result = cancel_remaining_order(
                    broker=broker,
                    orgn_odno=broker_order_id,
                    krx_fwdg_ord_orgno=krx_org,
                    confirm_timeout_sec=config.cancel_confirm_timeout_sec,
                )
                if cancel_result.status is not None:
                    status = cancel_result.status
                    filled_qty = int(status["filled_qty"])
                    order_remaining_qty = int(status["remaining_qty"])
                    avg_fill_price = int(status["avg_fill_price"])

            unresolved = status is None or (
                order_remaining_qty > 0
                and (cancel_result is None or not cancel_result.cancel_confirmed)
            )
            status_code = _order_status_code(
                filled_qty=filled_qty,
                remaining_qty=order_remaining_qty,
                requested_qty=child_qty,
                unresolved=unresolved,
            )
            note = _status_note(status_error, cancel_result, unresolved)
            update_order_status(
                db,
                order_id,
                status_code,
                filled_qty=filled_qty,
                remaining_qty=order_remaining_qty,
                avg_fill_price=avg_fill_price or None,
                note=note,
                broker_order_id=broker_order_id,
                event_type="STATUS_POLL",
                raw_payload=status.get("order") if status else None,
            )
            _record_execution_delta(
                db=db,
                order_id=order_id,
                order_data=order_plan,
                total_filled_qty=filled_qty,
                avg_fill_price=avg_fill_price or decision.price,
            )

            result.child_orders.append(
                ChildOrderResult(
                    order_id=order_id,
                    broker_order_id=broker_order_id,
                    requested_qty=child_qty,
                    filled_qty=filled_qty,
                    remaining_qty=order_remaining_qty,
                    limit_price=decision.price,
                    avg_fill_price=avg_fill_price,
                    status_code=status_code,
                    note=note,
                    unresolved=unresolved,
                )
            )

            if filled_qty > 0:
                remaining_qty -= filled_qty
                result.filled_qty += filled_qty
                filled_amount += filled_qty * (avg_fill_price or decision.price)
                print(f"    filled {filled_qty}주, plan remaining {remaining_qty}주")
            else:
                print("    no confirmed fill")

            if unresolved:
                result.unresolved = True
                mark_trade_plan_status(db, plan["id"], "ORDERED")
                print("    status unresolved; stop slicing and reconcile later")
                break

        except KeyboardInterrupt:
            if broker_order_id:
                _cancel_safely(broker, broker_order_id, locals().get("krx_org"))
            update_order_status(db, order_id, "CANCELLED", note="interrupted by user")
            mark_trade_plan_status(db, plan["id"], "CANCELLED")
            raise
        except Exception as exc:
            if broker_order_id:
                cancel_result = cancel_remaining_order(
                    broker=broker,
                    orgn_odno=broker_order_id,
                    krx_fwdg_ord_orgno=locals().get("krx_org"),
                    confirm_timeout_sec=config.cancel_confirm_timeout_sec,
                )
                if cancel_result.cancel_confirmed:
                    status = cancel_result.status or {}
                    filled_qty = int(status.get("filled_qty", 0) or 0)
                    avg_fill_price = int(status.get("avg_fill_price", 0) or 0)
                    update_order_status(
                        db,
                        order_id,
                        "CANCELLED" if filled_qty == 0 else "PARTIAL",
                        filled_qty=filled_qty,
                        remaining_qty=int(status.get("remaining_qty", 0) or 0),
                        avg_fill_price=avg_fill_price or None,
                        note=f"cancelled after error: {exc}",
                        broker_order_id=broker_order_id,
                        event_type="ERROR_CANCELLED",
                        raw_payload=status.get("order"),
                    )
                    _record_execution_delta(
                        db=db,
                        order_id=order_id,
                        order_data=order_plan,
                        total_filled_qty=filled_qty,
                        avg_fill_price=avg_fill_price or decision.price,
                    )
                    if filled_qty > 0:
                        remaining_qty -= filled_qty
                        result.filled_qty += filled_qty
                        filled_amount += filled_qty * (avg_fill_price or decision.price)
                    print(f"  [{symbol}] slice {attempt} error-cancelled (filled={filled_qty}): {exc}")
                    if remaining_qty > 0:
                        # 취소 확인됐고 잔량이 남아 있으면 재호가 시도
                        continue
                    mark_trade_plan_status(db, plan["id"], "ORDERED")
                else:
                    update_order_status(
                        db,
                        order_id,
                        "ACCEPTED",
                        note=f"broker state unresolved after error: {exc}; cancel={cancel_result.note}",
                        broker_order_id=broker_order_id,
                        event_type="ERROR_UNRESOLVED",
                    )
                    result.unresolved = True
                    mark_trade_plan_status(db, plan["id"], "ORDERED")
                    print(f"  [{symbol}] slice {attempt} unresolved after error: {exc}")
            else:
                update_order_status(db, order_id, "REJECTED", note=str(exc), event_type="SUBMIT_ERROR")
                print(f"  [{symbol}] slice {attempt} failed before broker order id: {exc}")
            if result.filled_qty == 0:
                mark_trade_plan_status(db, plan["id"], "ORDERED")
            break

    newly_filled_qty = result.filled_qty - confirmed_plan_filled_qty
    if newly_filled_qty > 0:
        result.avg_fill_price = filled_amount / newly_filled_qty
        final_status = "ORDERED" if result.unresolved else ("DONE" if result.remaining_qty == 0 else "ORDERED")
        mark_trade_plan_status(db, plan["id"], final_status)
    elif result.unresolved:
        mark_trade_plan_status(db, plan["id"], "ORDERED")
    elif result.child_orders:
        mark_trade_plan_status(db, plan["id"], "ORDERED")
    else:
        mark_trade_plan_status(db, plan["id"], "ORDERED")

    return result


def sync_open_orders_for_plan(
    db: PostgreDB,
    broker: KisBroker,
    plan_id: int,
    config: ExecutionConfig,
) -> bool:
    """Poll and, when possible, cancel open broker orders for one plan.

    Returns True when any order remains unresolved/open after synchronization.
    """
    still_open = False
    for order in fetch_open_orders_by_plan(db, plan_id):
        broker_order_id = order.get("broker_order_id")
        if not broker_order_id:
            still_open = True
            continue

        status, status_error = poll_order_status(
            broker,
            broker_order_id,
            timeout_sec=config.child_timeout_sec,
            poll_interval_sec=config.poll_interval_sec,
        )
        if status is None:
            update_order_status(
                db,
                str(order["id"]),
                order["order_status_code"],
                note=f"open order status unresolved: {status_error}",
                broker_order_id=broker_order_id,
                event_type="OPEN_STATUS_TIMEOUT",
            )
            still_open = True
            continue

        filled_qty = int(status["filled_qty"])
        remaining_qty = int(status["remaining_qty"])
        avg_fill_price = int(status["avg_fill_price"])
        cancel_result = None

        if remaining_qty > 0:
            cancel_result = cancel_remaining_order(
                broker=broker,
                orgn_odno=broker_order_id,
                krx_fwdg_ord_orgno=_extract_krx_org(status.get("order")),
                confirm_timeout_sec=config.cancel_confirm_timeout_sec,
            )
            if cancel_result.status is not None:
                status = cancel_result.status
                filled_qty = int(status["filled_qty"])
                remaining_qty = int(status["remaining_qty"])
                avg_fill_price = int(status["avg_fill_price"])

        unresolved = remaining_qty > 0 and (
            cancel_result is None or not cancel_result.cancel_confirmed
        )
        status_code = _order_status_code(
            filled_qty=filled_qty,
            remaining_qty=remaining_qty,
            requested_qty=int(order["qty"]),
            unresolved=unresolved,
        )
        note = _status_note(status_error, cancel_result, unresolved)
        update_order_status(
            db,
            str(order["id"]),
            status_code,
            filled_qty=filled_qty,
            remaining_qty=remaining_qty,
            avg_fill_price=avg_fill_price or None,
            note=note,
            broker_order_id=broker_order_id,
            event_type="OPEN_STATUS_SYNC",
            raw_payload=status.get("order"),
        )
        _record_execution_delta(
            db=db,
            order_id=str(order["id"]),
            order_data=order,
            total_filled_qty=filled_qty,
            avg_fill_price=avg_fill_price or int(order.get("price") or 0),
        )
        if unresolved:
            still_open = True

    return still_open


def choose_child_order(
    broker: KisBroker,
    symbol: str,
    side: str,
    remaining_qty: int,
    config: ExecutionConfig,
) -> QuoteDecision:
    book = broker.market.orderbook(symbol)
    price, visible_qty = best_quote_from_orderbook(book, side)
    price = _aggressive_limit_price(price, side, config.aggressive_limit_ticks)
    visible_cap = max(1, int(visible_qty * config.max_top_level_participation))
    child_qty = min(remaining_qty, config.max_child_qty, visible_cap)
    if child_qty <= 0:
        raise ExecutionError(f"No executable quantity for {symbol}")
    return QuoteDecision(price=price, visible_qty=visible_qty, child_qty=child_qty)


def best_quote_from_orderbook(orderbook: dict[str, Any], side: str) -> tuple[int, int]:
    output = orderbook.get("output1") or orderbook.get("output") or orderbook
    if isinstance(output, list):
        output = output[0] if output else {}
    if not isinstance(output, dict):
        raise ExecutionError(f"Unexpected orderbook payload: {orderbook}")

    if side == "BUY":
        price = parse_int(output.get("askp1"))
        qty = parse_int(output.get("askp_rsqn1") or output.get("askp_rsqn_1"))
    elif side == "SELL":
        price = parse_int(output.get("bidp1"))
        qty = parse_int(output.get("bidp_rsqn1") or output.get("bidp_rsqn_1"))
    else:
        raise ExecutionError(f"Unsupported order side: {side}")

    if price <= 0:
        raise ExecutionError(f"Orderbook has no executable {side} price: {output}")
    if qty <= 0:
        raise ExecutionError(f"Orderbook has no visible {side} quantity: {output}")
    return price, qty


def poll_order_status(
    broker: KisBroker,
    broker_order_id: str,
    timeout_sec: int,
    poll_interval_sec: float = 1.0,
) -> tuple[dict[str, Any] | None, str | None]:
    deadline = time.monotonic() + timeout_sec
    last_status: dict[str, Any] | None = None
    last_error: str | None = None
    while time.monotonic() < deadline:
        remaining_sec = max(1, min(5, deadline - time.monotonic()))
        try:
            status = broker.orders.get_order_status(
                broker_order_id,
                request_timeout=remaining_sec,
            )
        except Exception as exc:
            last_error = str(exc)
            print(f"    poll failed: {exc}")
            time.sleep(min(poll_interval_sec, max(0, deadline - time.monotonic())))
            continue
        if status is not None:
            last_status = status
            print(
                f"    poll: filled {status['filled_qty']}주 / "
                f"remain {status['remaining_qty']}주"
            )
            if status["remaining_qty"] == 0 or status.get("is_cancelled"):
                return status, last_error
        time.sleep(min(poll_interval_sec, max(0, deadline - time.monotonic())))
    return last_status, last_error


def cancel_remaining_order(
    broker: KisBroker,
    orgn_odno: str,
    krx_fwdg_ord_orgno: str | None,
    confirm_timeout_sec: int,
) -> CancelResult:
    if not krx_fwdg_ord_orgno:
        return CancelResult(requested=False, note="missing krx_fwdg_ord_orgno")

    try:
        broker.orders.cancel(
            orgn_odno=orgn_odno,
            krx_fwdg_ord_orgno=krx_fwdg_ord_orgno,
            qty_all_yn="Y",
        )
    except Exception as exc:
        return CancelResult(requested=True, note=f"cancel request failed: {exc}")

    status, status_error = poll_order_status(
        broker,
        orgn_odno,
        timeout_sec=confirm_timeout_sec,
        poll_interval_sec=1.0,
    )
    if status is None:
        return CancelResult(
            requested=True,
            cancel_confirmed=False,
            note=f"cancel requested; status confirm failed: {status_error}",
        )
    return CancelResult(
        requested=True,
        cancel_confirmed=status["remaining_qty"] == 0 or status["is_cancelled"],
        status=status,
        note="cancel confirmed" if status["remaining_qty"] == 0 or status["is_cancelled"] else "cancel requested but remaining quantity still open",
    )


def _get_sellable_qty(broker: KisBroker, symbol: str) -> int:
    """KIS 잔고에서 특정 종목의 주문가능수량(매도가능수량)을 조회한다."""
    balance = broker.account.balance()
    holdings = balance.get("output1") or []
    for item in holdings:
        if str(item.get("pdno", "")).strip() == symbol:
            return parse_int(item.get("ord_psbl_qty"))
    return 0


def _get_buyable_qty(broker: KisBroker, symbol: str, limit_price: int | None = None) -> int:
    if limit_price is None:
        buyable = broker.account.buyable_amount(stock_code=symbol)
    else:
        buyable = broker.account.buyable_amount(
            stock_code=symbol,
            ord_unpr=str(limit_price),
            ord_dvsn=OrdDvsn.LIMIT,
        )
    return parse_int(buyable.get("output", {}).get("nrcvb_buy_qty"))


def _aggressive_limit_price(price: int, side: str, ticks: int) -> int:
    tick = get_tick_size(price)
    if side == "BUY":
        return round_to_tick(price + tick * max(0, ticks))
    if side == "SELL":
        return max(tick, round_to_tick(price - tick * max(0, ticks)))
    raise ExecutionError(f"Unsupported order side: {side}")


def _order_status_code(
    filled_qty: int,
    remaining_qty: int,
    requested_qty: int,
    unresolved: bool = False,
) -> str:
    if unresolved:
        return "PARTIAL" if filled_qty > 0 else "ACCEPTED"
    if filled_qty >= requested_qty and remaining_qty == 0:
        return "FILLED"
    if filled_qty > 0:
        return "PARTIAL"
    return "CANCELLED"


def _cancel_safely(broker: KisBroker, broker_order_id: str, krx_org: str | None) -> None:
    if not krx_org:
        return
    try:
        broker.orders.cancel(
            orgn_odno=broker_order_id,
            krx_fwdg_ord_orgno=krx_org,
            qty_all_yn="Y",
        )
    except Exception as cancel_error:
        print(f"    cancel failed for {broker_order_id}: {cancel_error}")


def _status_note(
    status_error: str | None,
    cancel_result: CancelResult | None,
    unresolved: bool,
) -> str | None:
    parts: list[str] = []
    if status_error:
        parts.append(f"status poll error: {status_error}")
    if cancel_result and cancel_result.note:
        parts.append(cancel_result.note)
    if unresolved:
        parts.append("broker state unresolved; requires reconciliation")
    return "; ".join(parts) if parts else None


def _record_execution_delta(
    db: PostgreDB,
    order_id: str,
    order_data: dict,
    total_filled_qty: int,
    avg_fill_price: int,
) -> None:
    """Persist only the newly confirmed fill quantity for one order."""
    if total_filled_qty <= 0:
        return

    saved_qty = fetch_execution_qty_by_order(db, order_id)
    delta_qty = total_filled_qty - saved_qty
    if delta_qty <= 0:
        return

    price = avg_fill_price or parse_int(order_data.get("price") or order_data.get("planned_price"))
    if price <= 0:
        return

    amount = delta_qty * price
    side = str(order_data["order_side_code"])
    net_amount = -amount if side == "BUY" else amount
    insert_execution(
        db,
        order_id=order_id,
        data={
            "symbol": order_data["symbol"],
            "market_type_code": order_data.get("market_type_code", "KOSPI"),
            "instrument_type_code": order_data.get("instrument_type_code", "STOCK"),
            "order_side_code": side,
            "qty": delta_qty,
            "price": price,
            "amount": amount,
            "commission": 0,
            "tax": 0,
            "slippage": 0,
            "net_amount": net_amount,
        },
    )


def _extract_krx_org(order_payload: dict[str, Any] | None) -> str | None:
    if not order_payload:
        return None
    for key in (
        "krx_fwdg_ord_orgno",
        "KRX_FWDG_ORD_ORGNO",
        "ord_gno_brno",
        "ORD_GNO_BRNO",
    ):
        value = order_payload.get(key)
        if value:
            return str(value)
    return None
