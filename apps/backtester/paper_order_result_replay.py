"""Replay observed PAPER order outcomes and quantify ledger parity gaps.

This module is deliberately read-only.  It consumes the reconstructed order
lifecycle, applies only observed filled quantities/prices, and separates raw
replay results from explicit opening-balance calibration entries.  Calibration
entries are evidence of missing history; they are never emitted as trades.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
from collections import defaultdict
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd


KST = ZoneInfo("Asia/Seoul")
APPLICABLE_STATUSES = {"FILLED", "PARTIAL", "ACCEPTED", "SUBMITTED"}


def _number(value: object, default: float = 0.0) -> float:
    try:
        if value is None or pd.isna(value):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _symbol(value: object) -> str:
    return str(value or "").strip().upper().removesuffix(".KS")


def _effective_cost(row: dict) -> tuple[float, str]:
    recorded = _number(row.get("recorded_commission")) + _number(
        row.get("recorded_tax")
    )
    if recorded > 0:
        return recorded, "RECORDED"
    modeled = _number(row.get("modeled_commission")) + _number(
        row.get("modeled_tax")
    )
    return modeled, "MODELED" if modeled > 0 else "ZERO"


def replay_order_events(
    orders: list[dict],
    *,
    opening_cash: float,
    opening_positions: dict[str, float] | None = None,
) -> dict:
    """Apply observed fills in timestamp order without inventing executions."""
    cash = float(opening_cash)
    positions: defaultdict[str, float] = defaultdict(float)
    for ticker, qty in (opening_positions or {}).items():
        positions[_symbol(ticker)] = float(qty)

    events: list[dict] = []
    issues: list[dict] = []
    ordered = sorted(
        orders,
        key=lambda row: (str(row.get("created_at") or ""), str(row.get("order_id") or "")),
    )
    for row in ordered:
        status = str(row.get("status") or "UNKNOWN").upper()
        qty = _number(row.get("filled_qty"))
        ordered_qty = _number(row.get("ordered_qty"))
        if qty <= 0:
            continue
        if status not in APPLICABLE_STATUSES:
            issues.append(
                {
                    "order_id": str(row.get("order_id") or ""),
                    "code": "FILLED_QTY_WITH_NON_FILL_STATUS",
                    "detail": status,
                }
            )
            continue
        if ordered_qty > 0 and qty - ordered_qty > 1e-9:
            issues.append(
                {
                    "order_id": str(row.get("order_id") or ""),
                    "code": "OVERFILLED_ORDER",
                    "detail": f"filled={qty}, ordered={ordered_qty}",
                }
            )
            continue
        price = _number(row.get("avg_fill_price"))
        if price <= 0:
            issues.append(
                {
                    "order_id": str(row.get("order_id") or ""),
                    "code": "MISSING_FILL_PRICE",
                    "detail": f"filled_qty={qty}",
                }
            )
            continue

        ticker = _symbol(row.get("symbol"))
        side = str(row.get("side") or "UNKNOWN").upper()
        amount = _number(row.get("fill_amount"), qty * price)
        if amount <= 0:
            amount = qty * price
        cost, cost_source = _effective_cost(row)
        if side == "BUY":
            position_delta = qty
            cash_delta = -(amount + cost)
        elif side == "SELL":
            position_delta = -qty
            cash_delta = amount - cost
        else:
            issues.append(
                {
                    "order_id": str(row.get("order_id") or ""),
                    "code": "UNKNOWN_ORDER_SIDE",
                    "detail": side,
                }
            )
            continue
        positions[ticker] += position_delta
        cash += cash_delta
        events.append(
            {
                "timestamp": str(row.get("created_at") or ""),
                "order_id": str(row.get("order_id") or ""),
                "symbol": ticker,
                "stock_name": str(row.get("stock_name") or ticker),
                "side": side,
                "status": status,
                "filled_qty": qty,
                "fill_price": price,
                "fill_amount": amount,
                "cost": cost,
                "cost_source": cost_source,
                "cash_delta": cash_delta,
                "position_delta": position_delta,
                "cash_after": cash,
                "position_after": positions[ticker],
            }
        )

    return {
        "opening_cash": float(opening_cash),
        "ending_cash": cash,
        "cash_delta": cash - float(opening_cash),
        "opening_positions": {
            key: float(value) for key, value in sorted((opening_positions or {}).items())
            if abs(float(value)) > 1e-9
        },
        "ending_positions": {
            key: float(value) for key, value in sorted(positions.items())
            if abs(value) > 1e-9
        },
        "event_count": len(events),
        "issues": issues,
        "events": events,
    }


def _position_differences(
    actual: dict[str, float], replayed: dict[str, float]
) -> list[dict]:
    rows = []
    for ticker in sorted(set(actual) | set(replayed)):
        expected = float(actual.get(ticker, 0.0))
        observed = float(replayed.get(ticker, 0.0))
        difference = observed - expected
        if abs(difference) > 1e-9:
            rows.append(
                {
                    "symbol": ticker,
                    "endpoint_qty": expected,
                    "replayed_qty": observed,
                    "difference": difference,
                }
            )
    return rows


def build_parity_report(
    orders: list[dict],
    *,
    endpoint_cash: float,
    endpoint_positions: dict[str, float],
    starting_capital: float,
    cash_tolerance_ratio: float = 0.001,
) -> dict:
    """Build raw and calibrated parity views from the same observed events."""
    zero_state = replay_order_events(orders, opening_cash=0.0, opening_positions={})
    raw = replay_order_events(
        orders,
        opening_cash=starting_capital,
        opening_positions={},
    )
    opening_cash = float(endpoint_cash) - float(zero_state["cash_delta"])
    symbols = set(endpoint_positions) | set(zero_state["ending_positions"])
    opening_positions = {
        ticker: float(endpoint_positions.get(ticker, 0.0))
        - float(zero_state["ending_positions"].get(ticker, 0.0))
        for ticker in symbols
    }
    opening_positions = {
        ticker: qty for ticker, qty in opening_positions.items() if abs(qty) > 1e-9
    }
    calibrated = replay_order_events(
        orders,
        opening_cash=opening_cash,
        opening_positions=opening_positions,
    )

    raw_position_gaps = _position_differences(
        endpoint_positions, raw["ending_positions"]
    )
    calibrated_position_gaps = _position_differences(
        endpoint_positions, calibrated["ending_positions"]
    )
    priced_fill_orders = raw["event_count"]
    filled_order_rows = sum(_number(row.get("filled_qty")) > 0 for row in orders)
    event_coverage = priced_fill_orders / filled_order_rows if filled_order_rows else 1.0
    exact_parity = (
        abs(calibrated["ending_cash"] - endpoint_cash) < 0.01
        and not calibrated_position_gaps
    )
    calibration_free = (
        abs(opening_cash - starting_capital) < 0.01 and not opening_positions
    )
    cash_tolerance = abs(float(starting_capital)) * cash_tolerance_ratio
    reconciled_from_starting_capital = (
        abs(opening_cash - starting_capital) <= cash_tolerance
        and not opening_positions
    )
    return {
        "schema_version": 1,
        "generated_at": dt.datetime.now(KST).isoformat(timespec="seconds"),
        "mode": "PAPER",
        "observe_only": True,
        "broker_write_permission": "DENIED_BY_DESIGN",
        "method": "observed order-result event replay with explicit opening-balance calibration",
        "starting_capital": float(starting_capital),
        "endpoint": {
            "cash": float(endpoint_cash),
            "positions": {
                key: float(value) for key, value in sorted(endpoint_positions.items())
                if abs(float(value)) > 1e-9
            },
        },
        "raw_replay": {
            "ending_cash": raw["ending_cash"],
            "cash_difference_vs_endpoint": raw["ending_cash"] - endpoint_cash,
            "ending_positions": raw["ending_positions"],
            "position_gaps": raw_position_gaps,
        },
        "calibration": {
            "opening_cash_required": opening_cash,
            "opening_cash_difference_vs_500m": opening_cash - starting_capital,
            "cash_tolerance": cash_tolerance,
            "cash_tolerance_ratio": cash_tolerance_ratio,
            "reconciled_from_starting_capital_within_tolerance": (
                reconciled_from_starting_capital
            ),
            "opening_position_balancing_entries": opening_positions,
            "opening_position_balancing_abs_qty": sum(
                abs(value) for value in opening_positions.values()
            ),
            "note": "These are reconciliation balances, not fabricated trades.",
        },
        "calibrated_replay": {
            "ending_cash": calibrated["ending_cash"],
            "cash_difference_vs_endpoint": calibrated["ending_cash"] - endpoint_cash,
            "ending_positions": calibrated["ending_positions"],
            "position_gaps": calibrated_position_gaps,
            "exact_endpoint_parity": exact_parity,
        },
        "data_quality": {
            "order_rows": len(orders),
            "filled_order_rows": filled_order_rows,
            "priced_fill_event_count": priced_fill_orders,
            "priced_fill_event_coverage": event_coverage,
            "issues": raw["issues"],
        },
        "promotion_gate": {
            "ready": bool(
                exact_parity
                and reconciled_from_starting_capital
                and event_coverage == 1.0
            ),
            "exact_endpoint_parity": exact_parity,
            "calibration_free_from_500m": calibration_free,
            "reconciled_from_500m_within_tolerance": (
                reconciled_from_starting_capital
            ),
            "opening_cash_difference_abs": abs(opening_cash - starting_capital),
            "opening_cash_tolerance": cash_tolerance,
            "full_priced_fill_coverage": event_coverage == 1.0,
            "blockers": [
                message
                for passed, message in (
                    (exact_parity, "calibrated replay does not match the broker endpoint"),
                    (
                        reconciled_from_starting_capital,
                        "opening state exceeds the 0.10% starting-capital reconciliation tolerance",
                    ),
                    (event_coverage == 1.0, "one or more filled orders lack replayable prices"),
                )
                if not passed
            ],
        },
        "events": raw["events"],
    }


def _load_inputs(ledger_dir: Path) -> tuple[list[dict], float, dict[str, float]]:
    orders = pd.read_csv(ledger_dir / "order_lifecycle.csv", dtype={"symbol": "string"})
    positions = pd.read_csv(
        ledger_dir / "position_reconciliation.csv", dtype={"symbol": "string"}
    )
    summary = json.loads((ledger_dir / "summary.json").read_text(encoding="utf-8"))
    endpoint_positions = {
        _symbol(row.symbol): _number(row.actual_endpoint_qty)
        for row in positions.itertuples(index=False)
        if _number(row.actual_endpoint_qty) > 0
    }
    return orders.to_dict(orient="records"), _number(summary["endpoint"]["cash"]), endpoint_positions


def write_report(report: dict, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "summary.json").write_text(
        json.dumps({key: value for key, value in report.items() if key != "events"}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    pd.DataFrame(report["events"]).to_csv(
        output_dir / "events.csv", index=False, encoding="utf-8-sig"
    )
    pd.DataFrame(report["raw_replay"]["position_gaps"]).to_csv(
        output_dir / "raw_position_gaps.csv", index=False, encoding="utf-8-sig"
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Replay observed PAPER order outcomes without broker writes."
    )
    parser.add_argument(
        "--ledger-dir", default="reports/analysis/paper_ledger_latest"
    )
    parser.add_argument(
        "--output-dir", default="reports/analysis/paper_order_result_replay/latest"
    )
    parser.add_argument("--starting-capital", type=float, default=500_000_000.0)
    args = parser.parse_args()

    orders, endpoint_cash, endpoint_positions = _load_inputs(Path(args.ledger_dir))
    report = build_parity_report(
        orders,
        endpoint_cash=endpoint_cash,
        endpoint_positions=endpoint_positions,
        starting_capital=args.starting_capital,
    )
    write_report(report, Path(args.output_dir))
    print(json.dumps({key: value for key, value in report.items() if key != "events"}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
