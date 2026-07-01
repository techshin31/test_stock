from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from core.trade.execution import _order_status_code
from core.trade.kis_broker import KisBroker
from core.utils.parsing import parse_int
from storage.postgres.connection import PostgreDB
from storage.postgres.repositories.execution_repo import (
    fetch_execution_qty_by_order,
    insert_execution,
)
from storage.postgres.repositories.order_repo import (
    fetch_order_by_broker_id,
    update_order_status,
)


@dataclass(frozen=True)
class ReconcileSummary:
    broker_rows: int = 0
    managed_orders: int = 0
    inserted_executions: int = 0
    inserted_qty: int = 0
    updated_orders: int = 0


def reconcile_orders_from_broker_history(
    db: PostgreDB,
    broker: KisBroker,
    target_date: date | datetime | str,
    *,
    start_date: date | datetime | str | None = None,
    end_date: date | datetime | str | None = None,
) -> ReconcileSummary:
    """Sync managed orders and execution deltas from KIS daily order history.

    Parameters
    ----------
    target_date : date | datetime | str
        기준일. start_date/end_date가 없으면 이 날 하루치를 조회한다.
    start_date : date | datetime | str | None
        범위 조회 시작일 (포함). 지정하면 end_date도 함께 지정해야 한다.
    end_date : date | datetime | str | None
        범위 조회 종료일 (포함). 지정하면 start_date도 함께 지정해야 한다.
    """
    kis_start = _to_kis_date(start_date if start_date is not None else target_date)
    kis_end = _to_kis_date(end_date if end_date is not None else target_date)
    history = broker.history.get(kis_start, kis_end)
    broker_rows = history.get("output1", []) or []

    managed_orders = 0
    inserted_executions = 0
    inserted_qty = 0
    updated_orders = 0

    for row in broker_rows:
        broker_order_id = row.get("odno")
        if not broker_order_id:
            continue

        order = fetch_order_by_broker_id(db, broker_order_id=broker_order_id)
        if order is None:
            continue

        managed_orders += 1
        filled_qty = parse_int(row.get("tot_ccld_qty"))
        remaining_qty = parse_int(row.get("rmn_qty"))
        filled_amount = parse_int(row.get("tot_ccld_amt"))
        avg_fill_price = parse_int(row.get("avg_prvs"))
        if avg_fill_price == 0 and filled_qty > 0:
            avg_fill_price = filled_amount // filled_qty

        status_code = _order_status_code(
            filled_qty=filled_qty,
            remaining_qty=remaining_qty,
            requested_qty=parse_int(order.get("qty")),
            unresolved=False,
        )
        if row.get("cncl_yn") == "Y" and filled_qty == 0:
            status_code = "CANCELLED"

        order_id = str(order["id"])
        saved_qty = fetch_execution_qty_by_order(db, order_id)
        delta_qty = filled_qty - saved_qty
        if delta_qty > 0 and avg_fill_price > 0:
            amount = delta_qty * avg_fill_price
            side = str(order["order_side_code"])
            net_amount = -amount if side == "BUY" else amount
            insert_execution(
                db,
                order_id=order_id,
                data={
                    "symbol": order["symbol"],
                    "market_type_code": order.get("market_type_code", "KOSPI"),
                    "instrument_type_code": order.get("instrument_type_code", "STOCK"),
                    "order_side_code": side,
                    "qty": delta_qty,
                    "price": avg_fill_price,
                    "amount": amount,
                    "commission": 0,
                    "tax": 0,
                    "slippage": 0,
                    "net_amount": net_amount,
                },
            )
            inserted_executions += 1
            inserted_qty += delta_qty

        update_order_status(
            db,
            order_id,
            status_code,
            filled_qty=filled_qty,
            remaining_qty=remaining_qty,
            avg_fill_price=avg_fill_price or None,
            broker_order_id=broker_order_id,
            event_type="EOD_RECONCILE",
            raw_payload=row,
        )
        updated_orders += 1

    return ReconcileSummary(
        broker_rows=len(broker_rows),
        managed_orders=managed_orders,
        inserted_executions=inserted_executions,
        inserted_qty=inserted_qty,
        updated_orders=updated_orders,
    )


def _status_code_from_history_row(
    *,
    filled_qty: int,
    remaining_qty: int,
    is_cancelled: bool,
    requested_qty: int,
) -> str:
    """KIS 주문 이력 행 하나에서 표준 상태 코드를 결정한다."""
    if is_cancelled and filled_qty == 0:
        return "CANCELLED"
    return _order_status_code(
        filled_qty=filled_qty,
        remaining_qty=remaining_qty,
        requested_qty=requested_qty,
        unresolved=False,
    )


def _to_kis_date(value: date | datetime | str) -> str:
    if isinstance(value, datetime):
        return value.strftime("%Y%m%d")
    if isinstance(value, date):
        return value.strftime("%Y%m%d")
    text = str(value).strip()
    return text.replace("-", "")


