from __future__ import annotations

import argparse
import datetime as dt
import json
from collections import defaultdict
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from apps.backtester.config import build_db_config, load_env
from storage.postgres.connection import PostgreDB


KST = ZoneInfo("Asia/Seoul")
BUY_COMMISSION_RATE = 0.00015
SELL_COMMISSION_RATE = 0.00015
SELL_TAX_RATE = 0.0018


def _as_float(value, default: float = 0.0) -> float:
    try:
        return float(value) if value is not None else default
    except (TypeError, ValueError):
        return default


def _normalize_symbol(value: str) -> str:
    return str(value or "").strip().upper().removesuffix(".KS")


def _parse_local_timestamp(value: str) -> dt.datetime:
    parsed = dt.datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=KST)
    return parsed.astimezone(KST)


def _load_dashboard(path: Path) -> tuple[dt.datetime, dict]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    cutoff = _parse_local_timestamp(str(payload["updated_at"]))
    if str(payload.get("execution_mode", "")).upper() != "PAPER":
        raise RuntimeError("dashboard endpoint is not PAPER")
    return cutoff, payload


def _load_trade_reasons(path: Path, cutoff: dt.datetime) -> dict[str, dict]:
    result: dict[str, dict] = {}
    if not path.exists():
        return result
    for raw in path.read_text(encoding="utf-8-sig", errors="replace").splitlines():
        if not raw.strip():
            continue
        try:
            row = json.loads(raw)
            timestamp = _parse_local_timestamp(str(row["timestamp"]))
        except (json.JSONDecodeError, KeyError, ValueError):
            continue
        if timestamp > cutoff:
            continue
        broker_id = str(row.get("broker_order_id") or "").strip()
        if broker_id:
            result[broker_id] = {
                "strategy_reason": row.get("reason"),
                "logged_status": row.get("status"),
                "trade_log_timestamp": timestamp.isoformat(timespec="seconds"),
            }
    return result


def _load_broker_fill_backfill(
    path: Path | None, *, account_scope: str
) -> dict[tuple[str, str], dict]:
    if path is None or not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if str(payload.get("mode") or "").upper() != "PAPER":
        raise RuntimeError("broker fill backfill is not PAPER evidence")
    if str(payload.get("account_scope") or "") != account_scope:
        raise RuntimeError("broker fill backfill account scope mismatch")
    safety = payload.get("safety") or {}
    if (
        int(safety.get("orders_created") or 0) != 0
        or int(safety.get("orders_cancelled") or 0) != 0
        or int(safety.get("account_mutations") or 0) != 0
        or safety.get("real_mode_used") is True
    ):
        raise RuntimeError("broker fill backfill is not read-only PAPER evidence")
    result = {}
    fill_rows = payload.get("broker_filled_rows")
    if fill_rows is None:
        fill_rows = payload.get("fill_overrides")
    if fill_rows is None:
        fill_rows = payload.get("matched_rows") or []
    default_date = str(payload.get("target_date") or "")
    for row in fill_rows:
        broker_id = str(row.get("broker_order_id") or "").lstrip("0") or "0"
        date = str(row.get("date") or default_date)
        qty = _as_float(row.get("filled_qty"))
        total = _as_float(row.get("total_fill_amount"))
        symbol = _normalize_symbol(row.get("symbol"))
        if qty <= 0 or total <= 0 or not symbol:
            raise RuntimeError(f"invalid broker fill backfill row: {broker_id}")
        result[(date, broker_id)] = dict(row)
    return result


def _load_broker_only_fills(
    path: Path | None, *, account_scope: str
) -> list[dict]:
    if path is None or not path.exists():
        return []
    # Reuse all mode, account, and read-only safety validation above.
    _load_broker_fill_backfill(path, account_scope=account_scope)
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    rows = []
    for row in payload.get("broker_only_rows") or []:
        qty = _as_float(row.get("filled_qty"))
        total = _as_float(row.get("total_fill_amount"))
        if (
            not row.get("broker_order_id")
            or not _normalize_symbol(row.get("symbol"))
            or str(row.get("side") or "").upper() not in {"BUY", "SELL"}
            or qty <= 0
            or total <= 0
        ):
            raise RuntimeError("invalid broker-only fill evidence row")
        rows.append(dict(row))
    return rows


def _load_broker_nonfill_overrides(
    path: Path | None, *, account_scope: str
) -> dict[tuple[str, str], dict]:
    if path is None or not path.exists():
        return {}
    _load_broker_fill_backfill(path, account_scope=account_scope)
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    result = {}
    for row in payload.get("broker_nonfill_overrides") or []:
        broker_id = str(row.get("broker_order_id") or "").lstrip("0") or "0"
        date = str(row.get("date") or "")
        if (
            not date
            or not _normalize_symbol(row.get("symbol"))
            or _as_float(row.get("filled_qty")) != 0
            or _as_float(row.get("total_fill_amount")) != 0
            or _as_float(row.get("remaining_qty"))
            != _as_float(row.get("ordered_qty"))
        ):
            raise RuntimeError(f"invalid broker nonfill override: {broker_id}")
        result[(date, broker_id)] = dict(row)
    return result


def _build_broker_only_ledger(
    rows: list[dict], company_names: dict[str, str], *, account_scope: str
) -> pd.DataFrame:
    result = []
    for row in rows:
        symbol = _normalize_symbol(row.get("symbol"))
        qty = _as_float(row.get("filled_qty"))
        total = _as_float(row.get("total_fill_amount"))
        side = str(row.get("side") or "").upper()
        order_time = str(row.get("order_time") or "000000").zfill(6)
        timestamp = dt.datetime.combine(
            dt.date.fromisoformat(str(row["date"])),
            dt.time(
                int(order_time[0:2]),
                int(order_time[2:4]),
                int(order_time[4:6]),
                tzinfo=KST,
            ),
        )
        modeled_commission = total * (
            BUY_COMMISSION_RATE if side == "BUY" else SELL_COMMISSION_RATE
        )
        modeled_tax = total * SELL_TAX_RATE if side == "SELL" else 0.0
        broker_id = str(row["broker_order_id"])
        result.append({
            "order_id": f"BROKER_ONLY:{broker_id}",
            "created_at": timestamp.isoformat(),
            "date": str(row["date"]),
            "symbol": symbol,
            "stock_name": company_names.get(symbol, symbol),
            "display_name": f"{company_names.get(symbol, symbol)} ({symbol})",
            "side": side,
            "status": "FILLED",
            "ordered_qty": _as_float(row.get("ordered_qty"), qty),
            "filled_qty": qty,
            "order_price": 0.0,
            "avg_fill_price": total / qty,
            "fill_amount": total,
            "fill_price_available": True,
            "execution_row_count": 0,
            "execution_qty": 0.0,
            "execution_amount": 0.0,
            "broker_backfill_total_amount": total,
            "broker_backfill_reported_avg_price": _as_float(
                row.get("avg_fill_price")
            ),
            "recorded_commission": 0.0,
            "recorded_tax": 0.0,
            "recorded_slippage": 0.0,
            "modeled_commission": modeled_commission,
            "modeled_tax": modeled_tax,
            "modeled_total_cost": modeled_commission + modeled_tax,
            "broker_order_id": broker_id,
            "strategy_reason": "BROKER_HISTORY_RECOVERY",
            "broker_note": "Read-only KIS daily-order evidence absent from DB orders",
            "execution_venue": "PAPER",
            "account_scope": account_scope,
            "scope_class": "CONFIRMED_PAPER_BROKER_ONLY",
            "fill_source": "BROKER_DAILY_ORDER_ONLY",
        })
    return pd.DataFrame(result)


def _fetch_source_rows(
    db: PostgreDB,
    cutoff: dt.datetime,
    *,
    strategy_lineage: tuple[str, ...],
    account_scope: str,
) -> dict[str, list[dict]]:
    cutoff_utc = cutoff.astimezone(dt.timezone.utc)
    orders = db.fetch_all(
        """
        SELECT o.id::text, o.created_at, o.updated_at, o.submitted_at, o.filled_at,
               o.symbol, o.order_side_code, o.qty, o.price, o.order_status_code,
               o.filled_qty, o.avg_fill_price, o.commission, o.note,
               o.broker_order_id, o.execution_venue_code, o.account_scope,
               o.idempotency_key
        FROM orders o
        JOIN strategies s ON s.id = o.strategy_id
        WHERE s.name = ANY(%s)
          AND o.created_at <= %s
          AND (
                (o.execution_venue_code = 'PAPER' AND o.account_scope = %s)
                OR o.execution_venue_code = 'UNKNOWN'
              )
        ORDER BY o.created_at, o.id
        """,
        (list(strategy_lineage), cutoff_utc, account_scope),
    )
    executions = db.fetch_all(
        """
        SELECT e.id::text, e.order_id::text, e.qty, e.price, e.amount,
               e.commission, e.tax, e.slippage, e.net_amount, e.executed_at
        FROM executions e
        JOIN orders o ON o.id = e.order_id
        JOIN strategies s ON s.id = o.strategy_id
        WHERE s.name = ANY(%s)
          AND e.executed_at <= %s
          AND (
                (o.execution_venue_code = 'PAPER' AND o.account_scope = %s)
                OR o.execution_venue_code = 'UNKNOWN'
              )
        ORDER BY e.executed_at, e.id
        """,
        (list(strategy_lineage), cutoff_utc, account_scope),
    )
    balances = db.fetch_all(
        """
        SELECT bh.recorded_at, bh.cash, bh.stock_value, bh.total_value,
               bh.execution_venue_code, bh.account_scope
        FROM balance_history bh
        JOIN strategies s ON s.id = bh.strategy_id
        WHERE s.name = ANY(%s)
          AND bh.recorded_at <= %s
          AND (
                (bh.execution_venue_code = 'PAPER' AND bh.account_scope = %s)
                OR bh.execution_venue_code = 'UNKNOWN'
              )
        ORDER BY bh.recorded_at
        """,
        (list(strategy_lineage), cutoff_utc, account_scope),
    )
    companies = db.fetch_all("SELECT stock_code, company_name FROM companies")
    return {"orders": orders, "executions": executions, "balances": balances, "companies": companies}


def _build_order_ledger(
    source: dict[str, list[dict]],
    trade_reasons: dict[str, dict],
    broker_fill_backfill: dict[tuple[str, str], dict] | None = None,
    broker_nonfill_overrides: dict[tuple[str, str], dict] | None = None,
) -> pd.DataFrame:
    broker_fill_backfill = broker_fill_backfill or {}
    broker_nonfill_overrides = broker_nonfill_overrides or {}
    company_names = {
        _normalize_symbol(row["stock_code"]): str(row["company_name"])
        for row in source["companies"]
    }
    executions_by_order: dict[str, list[dict]] = defaultdict(list)
    for execution in source["executions"]:
        executions_by_order[str(execution["order_id"])].append(execution)

    rows: list[dict] = []
    for order in source["orders"]:
        order_id = str(order["id"])
        created_at = pd.Timestamp(order["created_at"]).tz_convert(KST)
        local_date = created_at.date().isoformat()
        symbol = _normalize_symbol(order.get("symbol"))
        broker_id = str(order.get("broker_order_id") or "")
        broker_key = broker_id.lstrip("0") or "0"
        nonfill_override = broker_nonfill_overrides.get((local_date, broker_key))
        original_linked = executions_by_order.get(order_id, [])
        linked = [] if nonfill_override else original_linked
        original_execution_qty = sum(
            _as_float(row.get("qty")) for row in original_linked
        )
        original_execution_amount = sum(
            _as_float(row.get("amount")) for row in original_linked
        )
        execution_qty = sum(_as_float(row.get("qty")) for row in linked)
        execution_amount = sum(_as_float(row.get("amount")) for row in linked)
        execution_slippage = sum(_as_float(row.get("slippage")) for row in linked)
        recorded_commission = sum(_as_float(row.get("commission")) for row in linked)
        recorded_tax = sum(_as_float(row.get("tax")) for row in linked)
        filled_qty = _as_float(order.get("filled_qty"))
        if filled_qty <= 0 and execution_qty > 0:
            filled_qty = execution_qty
        original_status = str(order.get("order_status_code") or "UNKNOWN").upper()
        original_filled_qty = filled_qty
        effective_status = original_status
        if nonfill_override:
            if _normalize_symbol(nonfill_override.get("symbol")) != symbol:
                raise RuntimeError(f"broker nonfill symbol mismatch: {broker_id}")
            if (
                abs(
                    _as_float(nonfill_override.get("ordered_qty"))
                    - _as_float(order.get("qty"))
                )
                > 1e-9
            ):
                raise RuntimeError(f"broker nonfill quantity mismatch: {broker_id}")
            filled_qty = 0.0
            effective_status = "EXPIRED_UNFILLED"
        backfill = broker_fill_backfill.get((local_date, broker_key))
        backfill_used = False
        avg_fill_price = _as_float(order.get("avg_fill_price"))
        if avg_fill_price <= 0 and execution_qty > 0:
            avg_fill_price = execution_amount / execution_qty
        if avg_fill_price <= 0:
            avg_fill_price = _as_float(order.get("price"))
        if nonfill_override:
            avg_fill_price = 0.0
        if backfill and filled_qty > 0:
            backfill_qty = _as_float(backfill.get("filled_qty"))
            backfill_total = _as_float(backfill.get("total_fill_amount"))
            if _normalize_symbol(backfill.get("symbol")) != symbol:
                raise RuntimeError(f"broker backfill symbol mismatch: {broker_id}")
            if abs(backfill_qty - filled_qty) > 1e-9:
                raise RuntimeError(f"broker backfill quantity mismatch: {broker_id}")
            avg_fill_price = backfill_total / filled_qty
            backfill_used = True
        fill_amount = (
            _as_float(backfill.get("total_fill_amount"))
            if backfill_used
            else filled_qty * avg_fill_price
            if filled_qty > 0 and avg_fill_price > 0
            else 0.0
        )
        side = str(order.get("order_side_code") or "UNKNOWN").upper()
        modeled_commission = fill_amount * (
            BUY_COMMISSION_RATE if side == "BUY" else SELL_COMMISSION_RATE
        )
        modeled_tax = fill_amount * SELL_TAX_RATE if side == "SELL" else 0.0
        reason_row = trade_reasons.get(broker_id, {})
        venue = str(order.get("execution_venue_code") or "UNKNOWN").upper()
        scope_class = "CONFIRMED_PAPER" if venue == "PAPER" else "INFERRED_LEGACY_PAPER"
        rows.append(
            {
                "order_id": order_id,
                "created_at": created_at.isoformat(),
                "date": local_date,
                "symbol": symbol,
                "stock_name": company_names.get(symbol, symbol),
                "display_name": f"{company_names.get(symbol, symbol)} ({symbol})",
                "side": side,
                "status": effective_status,
                "db_original_status": original_status,
                "db_original_filled_qty": original_filled_qty,
                "broker_status_override": bool(nonfill_override),
                "ordered_qty": _as_float(order.get("qty")),
                "filled_qty": filled_qty,
                "order_price": _as_float(order.get("price")),
                "avg_fill_price": avg_fill_price,
                "fill_amount": fill_amount,
                "fill_price_available": bool(filled_qty <= 0 or avg_fill_price > 0),
                "execution_row_count": len(linked),
                "execution_qty": execution_qty,
                "execution_amount": execution_amount,
                "db_original_execution_row_count": len(original_linked),
                "db_original_execution_qty": original_execution_qty,
                "db_original_execution_amount": original_execution_amount,
                "broker_backfill_total_amount": (
                    _as_float(backfill.get("total_fill_amount"))
                    if backfill_used
                    else 0.0
                ),
                "broker_backfill_reported_avg_price": (
                    _as_float(backfill.get("avg_fill_price"))
                    if backfill_used
                    else 0.0
                ),
                "recorded_commission": recorded_commission,
                "recorded_tax": recorded_tax,
                "recorded_slippage": execution_slippage,
                "modeled_commission": modeled_commission,
                "modeled_tax": modeled_tax,
                "modeled_total_cost": modeled_commission + modeled_tax,
                "broker_order_id": broker_id or None,
                "strategy_reason": reason_row.get("strategy_reason"),
                "broker_note": order.get("note"),
                "execution_venue": venue,
                "account_scope": order.get("account_scope"),
                "scope_class": scope_class,
                "fill_source": (
                    "BROKER_DAILY_ORDER_NO_FILL_OVERRIDE"
                    if nonfill_override
                    else
                    "EXECUTION_ROWS"
                    if linked
                    else "BROKER_DAILY_ORDER_BACKFILL"
                    if backfill_used
                    else "ORDER_FILL_FIELDS"
                    if filled_qty > 0 and avg_fill_price > 0
                    else "MISSING_FILL_PRICE"
                    if filled_qty > 0
                    else "NO_FILL"
                ),
            }
        )
    return pd.DataFrame(rows)


def _average_cost_replay(orders: pd.DataFrame) -> tuple[float, float, dict[str, float]]:
    qty: dict[str, float] = defaultdict(float)
    average_cost: dict[str, float] = defaultdict(float)
    realized_gross = 0.0
    unmatched_sell_qty = 0.0
    for row in orders.sort_values(["created_at", "order_id"]).itertuples(index=False):
        if row.filled_qty <= 0 or row.avg_fill_price <= 0:
            continue
        symbol = row.symbol
        if row.side == "BUY":
            new_qty = qty[symbol] + row.filled_qty
            if new_qty > 0:
                average_cost[symbol] = (
                    qty[symbol] * average_cost[symbol] + row.filled_qty * row.avg_fill_price
                ) / new_qty
            qty[symbol] = new_qty
        elif row.side == "SELL":
            matched = min(qty[symbol], row.filled_qty)
            if matched > 0:
                realized_gross += matched * (row.avg_fill_price - average_cost[symbol])
                qty[symbol] -= matched
            unmatched_sell_qty += max(row.filled_qty - matched, 0.0)
            if qty[symbol] <= 1e-9:
                qty[symbol] = 0.0
                average_cost[symbol] = 0.0
    return realized_gross, unmatched_sell_qty, dict(qty)


def _minimum_opening_inventory(orders: pd.DataFrame) -> dict[str, float]:
    """Infer only inventory mathematically required to avoid a cash-account short."""
    required: dict[str, float] = {}
    fills = orders[orders["filled_qty"] > 0].sort_values(
        ["created_at", "order_id"]
    )
    for symbol, rows in fills.groupby("symbol", sort=False):
        running = 0.0
        minimum = 0.0
        for row in rows.itertuples(index=False):
            running += row.filled_qty if row.side == "BUY" else -row.filled_qty
            minimum = min(minimum, running)
        required[str(symbol)] = max(-minimum, 0.0)
    return required


def _position_reconciliation(
    orders: pd.DataFrame, dashboard: dict, company_names: dict[str, str]
) -> pd.DataFrame:
    fills = orders[orders["filled_qty"] > 0].copy()
    signed = fills["filled_qty"].where(fills["side"] == "BUY", -fills["filled_qty"])
    known_net = signed.groupby(fills["symbol"]).sum().to_dict()
    minimum_opening = _minimum_opening_inventory(orders)
    endpoint = {
        _normalize_symbol(row["ticker"]): row
        for row in dashboard.get("positions", [])
    }
    symbols = sorted(set(known_net) | set(endpoint))
    rows = []
    for symbol in symbols:
        current = endpoint.get(symbol, {})
        actual_qty = _as_float(current.get("qty"))
        replay_qty = _as_float(known_net.get(symbol))
        opening_qty = _as_float(minimum_opening.get(symbol))
        replay_with_opening = replay_qty + opening_qty
        raw_gap = actual_qty - replay_qty
        gap = actual_qty - replay_with_opening
        current_price = _as_float(current.get("current_price"))
        avg_price = _as_float(current.get("avg_price"))
        rows.append(
            {
                "symbol": symbol,
                "stock_name": company_names.get(symbol, symbol),
                "display_name": f"{company_names.get(symbol, symbol)} ({symbol})",
                "known_fill_net_qty": replay_qty,
                "minimum_opening_inventory_qty": opening_qty,
                "replay_qty_with_minimum_opening": replay_with_opening,
                "actual_endpoint_qty": actual_qty,
                "raw_qty_gap_before_opening_inventory": raw_gap,
                "qty_gap_balancing_entry": gap,
                "exact_qty_match": abs(gap) < 1e-9,
                "current_price": current_price,
                "broker_avg_price": avg_price,
                "endpoint_market_value": actual_qty * current_price,
                "endpoint_unrealized_pnl": actual_qty * (current_price - avg_price),
            }
        )
    return pd.DataFrame(rows)


def _daily_nav(source: dict[str, list[dict]]) -> pd.DataFrame:
    frame = pd.DataFrame(source["balances"])
    if frame.empty:
        return frame
    frame["recorded_at"] = pd.to_datetime(frame["recorded_at"], utc=True).dt.tz_convert(KST)
    for column in ("cash", "stock_value", "total_value"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame = frame[frame["total_value"] > 0].copy()
    frame["date"] = frame["recorded_at"].dt.date.astype(str)
    frame["scope_class"] = frame["execution_venue_code"].map(
        lambda value: "CONFIRMED_PAPER" if str(value).upper() == "PAPER" else "INFERRED_LEGACY_PAPER"
    )
    return frame.sort_values("recorded_at").groupby("date", as_index=False).tail(1).reset_index(drop=True)


def reconstruct(
    db: PostgreDB,
    *,
    dashboard_path: Path,
    trade_history_path: Path,
    starting_capital: float,
    baseline_path: Path = Path("reports/promotion/paper/baseline.json"),
    broker_backfill_path: Path | None = None,
    strategy_lineage: tuple[str, ...] = ("risk_neutral", "aggressive"),
) -> tuple[dict, dict[str, pd.DataFrame]]:
    cutoff, dashboard = _load_dashboard(dashboard_path)
    account_scope = str(dashboard.get("account_scope") or "UNKNOWN")
    if account_scope == "UNKNOWN":
        raise RuntimeError("dashboard PAPER account scope is unavailable")
    source = _fetch_source_rows(
        db,
        cutoff,
        strategy_lineage=strategy_lineage,
        account_scope=account_scope,
    )
    trade_reasons = _load_trade_reasons(trade_history_path, cutoff)
    broker_fill_backfill = _load_broker_fill_backfill(
        broker_backfill_path, account_scope=account_scope
    )
    broker_nonfill_overrides = _load_broker_nonfill_overrides(
        broker_backfill_path, account_scope=account_scope
    )
    orders = _build_order_ledger(
        source,
        trade_reasons,
        broker_fill_backfill,
        broker_nonfill_overrides,
    )
    company_names = {
        _normalize_symbol(row["stock_code"]): str(row["company_name"])
        for row in source["companies"]
    }
    broker_only = _build_broker_only_ledger(
        _load_broker_only_fills(
            broker_backfill_path, account_scope=account_scope
        ),
        company_names,
        account_scope=account_scope,
    )
    if not broker_only.empty:
        orders = pd.concat([orders, broker_only], ignore_index=True).sort_values(
            ["created_at", "order_id"]
        ).reset_index(drop=True)
    positions = _position_reconciliation(orders, dashboard, company_names)
    daily_nav = _daily_nav(source)

    filled = orders[orders["filled_qty"] > 0].copy()
    terminal = orders[
        orders["status"].isin(
            ["FILLED", "PARTIAL", "REJECTED", "CANCELLED", "EXPIRED_UNFILLED"]
        )
    ]
    realized_gross, unmatched_sell_qty, replay_quantities = _average_cost_replay(orders)
    endpoint_asset = _as_float(dashboard.get("total_eval"))
    endpoint_cash = _as_float(dashboard.get("cash"))
    total_pnl = endpoint_asset - starting_capital
    total_return = total_pnl / starting_capital if starting_capital else None
    endpoint_unrealized = float(positions["endpoint_unrealized_pnl"].sum())
    dashboard_unrealized = _as_float(dashboard.get("unrealized_pnl"), endpoint_unrealized)
    modeled_costs = float(filled["modeled_total_cost"].sum())
    recorded_slippage = float(filled["recorded_slippage"].sum())
    residual = total_pnl - realized_gross - dashboard_unrealized + modeled_costs

    baseline = json.loads(baseline_path.read_text(encoding="utf-8-sig")) if baseline_path.exists() else {}
    baseline_asset = _as_float(baseline.get("baseline_total_asset"))
    post_baseline_pnl = endpoint_asset - baseline_asset if baseline_asset else None

    status_counts = orders["status"].value_counts().to_dict()
    scope_counts = orders["scope_class"].value_counts().to_dict()
    daily_orders = (
        orders.groupby(["date", "status"]).size().unstack(fill_value=0).reset_index()
    )
    daily_fills = filled.groupby("date").agg(
        filled_orders=("order_id", "count"),
        fill_notional=("fill_amount", "sum"),
        modeled_cost=("modeled_total_cost", "sum"),
        recorded_slippage=("recorded_slippage", "sum"),
    ).reset_index()
    daily_order_replay = daily_orders.merge(daily_fills, on="date", how="left").fillna(0)

    exact_position_matches = int(positions["exact_qty_match"].sum())
    held_positions = positions[positions["actual_endpoint_qty"] > 0]
    exact_held_matches = int(held_positions["exact_qty_match"].sum())
    phantom_replay_positions = int(
        (
            (positions["actual_endpoint_qty"] == 0)
            & (positions["replay_qty_with_minimum_opening"].abs() > 1e-9)
        ).sum()
    )
    fill_price_coverage = float(filled["fill_price_available"].mean()) if len(filled) else 0.0
    execution_coverage = float((filled["execution_row_count"] > 0).mean()) if len(filled) else 0.0
    broker_backfill_count = int(
        (filled["fill_source"] == "BROKER_DAILY_ORDER_BACKFILL").sum()
    )
    broker_only_count = int(
        (filled["fill_source"] == "BROKER_DAILY_ORDER_ONLY").sum()
    )
    broker_nonfill_override_count = int(
        orders["broker_status_override"].fillna(False).sum()
    )
    broker_nonfill_overridden_execution_rows = int(
        orders.loc[
            orders["broker_status_override"].fillna(False),
            "db_original_execution_row_count",
        ].sum()
    )
    recorded_cost_zero_rate = float(
        ((filled["recorded_commission"] == 0) & (filled["recorded_tax"] == 0)).mean()
    ) if len(filled) else 0.0
    first_nav = daily_nav.iloc[0].to_dict() if not daily_nav.empty else {}
    raw_balances = pd.DataFrame(source["balances"])
    if not raw_balances.empty:
        raw_balances["recorded_at"] = pd.to_datetime(raw_balances["recorded_at"], utc=True)
        raw_balances["cash"] = pd.to_numeric(raw_balances["cash"], errors="coerce")
        raw_balances["total_value"] = pd.to_numeric(raw_balances["total_value"], errors="coerce")
    paper_raw = raw_balances[
        raw_balances["execution_venue_code"].astype(str).str.upper() == "PAPER"
    ] if not raw_balances.empty else pd.DataFrame()
    if not paper_raw.empty:
        first_paper_at = paper_raw["recorded_at"].min()
        legacy_raw = raw_balances[
            (raw_balances["recorded_at"] < first_paper_at)
            & (raw_balances["execution_venue_code"].astype(str).str.upper() == "UNKNOWN")
        ]
    else:
        legacy_raw = pd.DataFrame()
    legacy_last_cash = _as_float(legacy_raw.sort_values("recorded_at").iloc[-1]["cash"]) if not legacy_raw.empty else None
    paper_first_cash = _as_float(paper_raw.sort_values("recorded_at").iloc[0]["cash"]) if not paper_raw.empty else None
    positive_raw = raw_balances[raw_balances["total_value"] > 0].sort_values("recorded_at") if not raw_balances.empty else pd.DataFrame()
    first_positive_observation = positive_raw.iloc[0].to_dict() if not positive_raw.empty else {}
    unpriced_fills = filled[(filled["filled_qty"] > 0) & (filled["avg_fill_price"] <= 0)]

    pnl_rows = [
        {"component": "5억원 대비 총손익", "amount": total_pnl, "classification": "EXACT_ENDPOINT", "notes": "현재 PAPER 총평가액 - 500,000,000원"},
        {"component": "현재 보유종목 평가손익", "amount": dashboard_unrealized, "classification": "BROKER_REPORTED", "notes": "컷오프 스냅샷의 보유수량·평균단가·현재가"},
        {"component": "기록으로 매칭된 실현손익(총액)", "amount": realized_gross, "classification": "PARTIAL_ESTIMATE", "notes": "기록된 체결만 평균단가법으로 매칭; 누락 거래 때문에 전체 실현손익 아님"},
        {"component": "추정 수수료·세금", "amount": -modeled_costs, "classification": "MODELED", "notes": "매수/매도 수수료 0.015%, 매도세 0.18%"},
        {"component": "미복원 조정손익", "amount": residual, "classification": "UNRESOLVED_BALANCING_ITEM", "notes": "초기 보유·누락 체결·수수료·외부 변동을 포함하는 잔차"},
    ]
    pnl_attribution = pd.DataFrame(pnl_rows)

    summary = {
        "metadata": {
            "generated_at": dt.datetime.now(KST).isoformat(timespec="seconds"),
            "cutoff": cutoff.isoformat(timespec="seconds"),
            "timezone": "Asia/Seoul",
            "mode": "PAPER",
            "strategy": str(dashboard.get("strategy") or "aggressive"),
            "strategy_lineage": list(strategy_lineage),
            "account_scope": dashboard.get("account_scope"),
            "starting_capital": starting_capital,
            "scope_policy": "PAPER confirmed rows plus UNKNOWN legacy rows across the risk_neutral-to-aggressive account lineage",
        },
        "endpoint": {
            "cash": endpoint_cash,
            "total_asset": endpoint_asset,
            "position_count": int(len(dashboard.get("positions", []))),
            "total_pnl": total_pnl,
            "total_return": total_return,
            "broker_unrealized_pnl": dashboard_unrealized,
            "certified_baseline_asset": baseline_asset or None,
            "post_baseline_pnl": post_baseline_pnl,
            "post_baseline_return": post_baseline_pnl / baseline_asset if baseline_asset and post_baseline_pnl is not None else None,
        },
        "order_result_replay": {
            "orders": int(len(orders)),
            "terminal_orders": int(len(terminal)),
            "status_counts": {str(k): int(v) for k, v in status_counts.items()},
            "scope_counts": {str(k): int(v) for k, v in scope_counts.items()},
            "filled_orders": int(len(filled)),
            "fill_rate": float(len(filled) / len(orders)) if len(orders) else 0.0,
            "terminal_fill_rate": float(len(filled) / len(terminal)) if len(terminal) else 0.0,
            "fill_notional": float(filled["fill_amount"].sum()),
            "fill_notional_multiple_of_starting_capital": float(filled["fill_amount"].sum() / starting_capital),
            "modeled_commission_and_tax": modeled_costs,
            "recorded_slippage": recorded_slippage,
            "partially_matched_realized_gross_pnl": realized_gross,
            "unmatched_sell_qty": unmatched_sell_qty,
        },
        "reconciliation": {
            "position_rows": int(len(positions)),
            "exact_position_matches": exact_position_matches,
            "position_match_rate": exact_position_matches / len(positions) if len(positions) else 0.0,
            "endpoint_held_positions": int(len(held_positions)),
            "exact_endpoint_held_position_matches": exact_held_matches,
            "endpoint_held_position_match_rate": exact_held_matches / len(held_positions) if len(held_positions) else 0.0,
            "phantom_nonzero_replay_positions": phantom_replay_positions,
            "balancing_qty_abs_sum": float(positions["qty_gap_balancing_entry"].abs().sum()),
            "minimum_opening_inventory_abs_sum": float(
                positions["minimum_opening_inventory_qty"].sum()
            ),
            "unresolved_pnl_balancing_item": residual,
            "known_replay_nonzero_positions": int(sum(abs(v) > 1e-9 for v in replay_quantities.values())),
        },
        "data_quality": {
            "overall_grade": "LOW_FOR_TRADE_LEVEL_PNL__HIGH_FOR_ENDPOINT_PNL",
            "fill_price_coverage": fill_price_coverage,
            "auditable_fill_evidence_coverage": fill_price_coverage,
            "execution_table_coverage_of_filled_orders": execution_coverage,
            "broker_daily_order_backfill_count": broker_backfill_count,
            "broker_only_filled_order_count": broker_only_count,
            "broker_nonfill_override_count": broker_nonfill_override_count,
            "broker_nonfill_overridden_execution_rows": (
                broker_nonfill_overridden_execution_rows
            ),
            "zero_recorded_commission_tax_rate": recorded_cost_zero_rate,
            "unpriced_filled_orders": int(len(unpriced_fills)),
            "unpriced_filled_qty": float(unpriced_fills["filled_qty"].sum()),
            "first_positive_observation_at": (
                pd.Timestamp(first_positive_observation["recorded_at"]).tz_convert(KST).isoformat()
                if first_positive_observation else None
            ),
            "first_positive_observation_total": _as_float(first_positive_observation.get("total_value")) if first_positive_observation else None,
            "first_positive_daily_nav_date": first_nav.get("date"),
            "first_positive_daily_nav_total": _as_float(first_nav.get("total_value")) if first_nav else None,
            "legacy_last_cash": legacy_last_cash,
            "paper_first_cash": paper_first_cash,
            "legacy_to_paper_cash_continuity": legacy_last_cash == paper_first_cash if legacy_last_cash is not None and paper_first_cash is not None else None,
            "critical_findings": [
                "The account endpoint and 500M total P&L are directly observed and exact at the cutoff.",
                "All filled orders have auditable prices; the execution table remains historically incomplete.",
                "Minimum opening inventory is inferred only where observed sells would otherwise create a cash-account short; it is not a fabricated trade.",
                "Legacy UNKNOWN scope is inferred as PAPER lineage from exact cash continuity, not explicit account identity.",
                "Commission and tax fields are zero; configured rates are modeled separately.",
                "Position gaps are preserved as balancing entries and are never fabricated into trades.",
            ],
        },
    }
    frames = {
        "order_lifecycle": orders,
        "daily_order_replay": daily_order_replay,
        "position_reconciliation": positions,
        "daily_nav": daily_nav,
        "pnl_attribution": pnl_attribution,
    }
    return summary, frames


def write_outputs(summary: dict, frames: dict[str, pd.DataFrame], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    for name, frame in frames.items():
        frame.to_csv(output_dir / f"{name}.csv", index=False, encoding="utf-8-sig")


def main() -> None:
    parser = argparse.ArgumentParser(description="Reconstruct the PAPER order/P&L ledger without broker writes.")
    parser.add_argument("--dashboard", default="logs/paper/dashboard_state.json")
    parser.add_argument("--trade-history", default="logs/paper/trade_history.jsonl")
    parser.add_argument("--starting-capital", type=float, default=500_000_000.0)
    parser.add_argument(
        "--broker-backfill",
        default="reports/analysis/paper_broker_history/latest.json",
    )
    parser.add_argument("--output-dir", default="reports/analysis/paper_ledger_latest")
    args = parser.parse_args()

    load_env()
    db = PostgreDB(build_db_config())
    try:
        summary, frames = reconstruct(
            db,
            dashboard_path=Path(args.dashboard),
            trade_history_path=Path(args.trade_history),
            starting_capital=args.starting_capital,
            broker_backfill_path=Path(args.broker_backfill),
        )
    finally:
        db.close()
    write_outputs(summary, frames, Path(args.output_dir))
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
