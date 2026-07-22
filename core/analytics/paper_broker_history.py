"""Read-only KIS PAPER history audit against the local order ledger."""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
from pathlib import Path
from zoneinfo import ZoneInfo

from apps.backtester.config import build_db_config, load_env
from core.broker.kis_api import KisBroker
from storage.postgres.connection import PostgreDB


KST = ZoneInfo("Asia/Seoul")
DEFAULT_START_DATE = dt.date(2026, 7, 3)
DEFAULT_STRATEGIES = ("risk_neutral", "aggressive")


def _broker_id(value: object) -> str:
    return str(value or "").strip().lstrip("0") or "0"


def _symbol(value: object) -> str:
    return str(value or "").strip().upper().split(".", 1)[0]


def _number(value: object) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _broker_row(row: dict, date: dt.date) -> dict:
    side_code = str(row.get("sll_buy_dvsn_cd") or "")
    return {
        "date": date.isoformat(),
        "broker_order_id": str(row.get("odno") or ""),
        "symbol": _symbol(row.get("pdno")),
        "stock_name": str(row.get("prdt_name") or ""),
        "side": "SELL" if side_code == "01" else "BUY" if side_code == "02" else side_code,
        "ordered_qty": _number(row.get("ord_qty")),
        "filled_qty": _number(row.get("tot_ccld_qty")),
        "remaining_qty": _number(row.get("rmn_qty")),
        "total_fill_amount": _number(row.get("tot_ccld_amt")),
        "avg_fill_price": _number(row.get("avg_prvs")),
        "cancelled": str(row.get("cncl_yn") or "N").upper() == "Y",
        "order_time": str(row.get("ord_tmd") or "").zfill(6),
    }


def _fetch_db_orders(
    db,
    *,
    start_date: dt.date,
    end_date: dt.date,
    strategy_names: tuple[str, ...],
    account_scope: str,
) -> list[dict]:
    return db.fetch_all(
        """
        SELECT o.id::text AS order_id,
               (o.created_at AT TIME ZONE 'Asia/Seoul')::date::text AS local_date,
               s.name AS strategy_name, o.broker_order_id, o.symbol,
               o.order_side_code, o.order_status_code, o.qty, o.filled_qty,
               o.avg_fill_price
        FROM orders o
        JOIN strategies s ON s.id = o.strategy_id
        WHERE s.name = ANY(%s)
          AND (o.created_at AT TIME ZONE 'Asia/Seoul')::date BETWEEN %s AND %s
          AND o.broker_order_id IS NOT NULL
          AND (
                (o.execution_venue_code = 'PAPER' AND o.account_scope = %s)
                OR o.execution_venue_code = 'UNKNOWN'
              )
        ORDER BY o.created_at, o.id
        """,
        (list(strategy_names), start_date, end_date, account_scope),
    )


def audit_broker_history(
    db,
    broker,
    *,
    start_date: dt.date,
    end_date: dt.date,
    strategy_names: tuple[str, ...] = DEFAULT_STRATEGIES,
) -> dict:
    if not getattr(broker, "is_mock", False):
        raise PermissionError("PAPER broker history audit requires mock=True")
    if end_date < start_date:
        raise ValueError("end_date must not precede start_date")
    account_scope = str(getattr(broker, "masked_account", "") or "")
    if not account_scope or account_scope == "UNKNOWN":
        raise RuntimeError("PAPER account scope is unavailable")

    db_rows = _fetch_db_orders(
        db,
        start_date=start_date,
        end_date=end_date,
        strategy_names=strategy_names,
        account_scope=account_scope,
    )
    db_by_key = {}
    for row in db_rows:
        key = (str(row["local_date"]), _broker_id(row.get("broker_order_id")))
        if key in db_by_key:
            raise RuntimeError(f"duplicate DB broker order key: {key}")
        db_by_key[key] = row

    broker_by_key = {}
    daily_counts = {}
    day = start_date
    while day <= end_date:
        if day.weekday() < 5:
            rows = broker.fetch_daily_orders(day)
            daily_counts[day.isoformat()] = len(rows)
            for raw in rows:
                normalized = _broker_row(raw, day)
                key = (day.isoformat(), _broker_id(normalized["broker_order_id"]))
                if key in broker_by_key:
                    raise RuntimeError(f"duplicate KIS broker order key: {key}")
                broker_by_key[key] = normalized
        day += dt.timedelta(days=1)

    fill_overrides = []
    broker_filled_rows = []
    nonfill_overrides = []
    broker_only_rows = []
    unresolved_db_filled_rows = []
    exact_matches = 0

    for key, broker_row in broker_by_key.items():
        db_row = db_by_key.get(key)
        broker_filled = _number(broker_row.get("filled_qty"))
        if db_row is None:
            if broker_filled > 0:
                broker_only_rows.append(broker_row)
            continue
        db_filled = _number(db_row.get("filled_qty"))
        db_status = str(db_row.get("order_status_code") or "").upper()
        db_avg = _number(db_row.get("avg_fill_price"))
        common = {
            **broker_row,
            "db_order_id": str(db_row["order_id"]),
            "db_strategy_name": str(db_row["strategy_name"]),
            "db_original_status": db_status,
            "db_original_filled_qty": db_filled,
            "db_original_avg_fill_price": db_avg,
        }
        if broker_filled > 0:
            broker_filled_rows.append(common)
        if broker_filled <= 0 and (db_filled > 0 or db_status == "FILLED"):
            nonfill_overrides.append(common)
        elif broker_filled > 0 and (
            db_filled != broker_filled
            or db_status != "FILLED"
            or db_avg <= 0
        ):
            fill_overrides.append(common)
        else:
            exact_matches += 1

    for key, db_row in db_by_key.items():
        if key in broker_by_key:
            continue
        if (
            str(db_row.get("order_status_code") or "").upper() == "FILLED"
            or _number(db_row.get("filled_qty")) > 0
        ):
            unresolved_db_filled_rows.append({
                "date": str(db_row["local_date"]),
                "db_order_id": str(db_row["order_id"]),
                "db_strategy_name": str(db_row["strategy_name"]),
                "broker_order_id": str(db_row.get("broker_order_id") or ""),
                "symbol": _symbol(db_row.get("symbol")),
                "side": str(db_row.get("order_side_code") or "").upper(),
                "db_original_status": str(db_row.get("order_status_code") or ""),
                "db_original_filled_qty": _number(db_row.get("filled_qty")),
                "db_original_avg_fill_price": _number(db_row.get("avg_fill_price")),
            })

    return {
        "schema_version": 1,
        "generated_at": dt.datetime.now(KST).isoformat(timespec="seconds"),
        "mode": "PAPER",
        "account_scope": account_scope,
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "strategy_lineage": list(strategy_names),
        "operation": "READ_ONLY_KIS_DAILY_ORDER_AUDIT",
        "daily_broker_row_counts": daily_counts,
        "db_order_rows": len(db_rows),
        "broker_order_rows": len(broker_by_key),
        "exact_matched_rows": exact_matches,
        "fill_overrides": fill_overrides,
        "broker_filled_rows": broker_filled_rows,
        "broker_only_rows": broker_only_rows,
        "broker_nonfill_overrides": nonfill_overrides,
        "unresolved_db_filled_rows": unresolved_db_filled_rows,
        "audit_complete": len(unresolved_db_filled_rows) == 0,
        "safety": {
            "orders_created": 0,
            "orders_cancelled": 0,
            "account_mutations": 0,
            "real_mode_used": False,
        },
    }


def write_audit(payload: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    os.replace(temporary, path)


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit PAPER KIS order history without writes.")
    parser.add_argument("--start", default=DEFAULT_START_DATE.isoformat())
    parser.add_argument("--end", default=dt.date.today().isoformat())
    parser.add_argument(
        "--output", default="reports/analysis/paper_broker_history/latest.json"
    )
    args = parser.parse_args()
    load_env()
    db = PostgreDB(build_db_config())
    try:
        payload = audit_broker_history(
            db,
            KisBroker(mock=True),
            start_date=dt.date.fromisoformat(args.start),
            end_date=dt.date.fromisoformat(args.end),
        )
    finally:
        db.close()
    write_audit(payload, Path(args.output))
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
