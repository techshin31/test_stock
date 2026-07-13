from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import os
from collections import Counter
from pathlib import Path


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _account_rows(path: Path, report_date: dt.date) -> list[dict]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8", newline="") as handle:
        return [
            row for row in csv.DictReader(handle)
            if row.get("timestamp", "")[:10] == report_date.isoformat()
        ]


def build_simulation_report(
    log_dir: Path,
    report_date: dt.date,
    *,
    initial_cash: float | None = None,
) -> dict:
    account_path = log_dir / "sim_account.json"
    decision_path = log_dir / "decision_state.json"
    account = _read_json(account_path)
    decision = _read_json(decision_path)
    initial_cash = float(initial_cash or os.getenv("SIM_INITIAL_CASH", "500000000"))

    positions = account.get("positions", {})
    cash = float(account.get("cash", 0.0))
    market_value = sum(
        int(row["qty"]) * float(row.get("current_price") or row["avg_price"])
        for row in positions.values()
    )
    total_asset = cash + market_value
    unrealized_pnl = sum(
        int(row["qty"])
        * (float(row.get("current_price") or row["avg_price"]) - float(row["avg_price"]))
        for row in positions.values()
    )
    total_pnl = total_asset - initial_cash
    realized_pnl_estimate = total_pnl - unrealized_pnl

    account_rows = _account_rows(log_dir / "account_history.csv", report_date)
    start_asset = float(account_rows[0]["total_asset"]) if account_rows else total_asset
    end_asset = float(account_rows[-1]["total_asset"]) if account_rows else total_asset
    daily_return = end_asset / start_asset - 1.0 if start_asset else 0.0
    cumulative_return = total_asset / initial_cash - 1.0 if initial_cash else 0.0

    orders = list(account.get("orders", {}).values())
    day_orders = [
        row for row in orders
        if row.get("created_at", "")[:10] == report_date.isoformat()
    ]
    side_counts = Counter(row.get("side", "UNKNOWN") for row in day_orders)
    status_counts = Counter(row.get("status", "UNKNOWN") for row in day_orders)
    commission = sum(float(row.get("commission", 0.0)) for row in day_orders)
    tax = sum(float(row.get("tax", 0.0)) for row in day_orders)
    slippage = sum(float(row.get("slippage_cost", 0.0)) for row in day_orders)
    duplicate_keys = Counter(
        (
            row.get("symbol"), row.get("side"), row.get("qty"),
            row.get("created_at", "")[:16],
        )
        for row in day_orders
    )
    duplicate_count = sum(count - 1 for count in duplicate_keys.values() if count > 1)

    decisions = decision.get("decisions", [])
    target_weight = sum(float(row.get("target_weight", 0.0)) for row in decisions)
    nonterminal = sum(count for status, count in status_counts.items() if status != "FILLED")
    checks = [
        {"name": "cash_non_negative", "passed": cash >= 0, "detail": f"cash={cash:.2f}"},
        {"name": "target_weight_limit", "passed": target_weight <= 0.9001, "detail": f"target_weight={target_weight:.4f}"},
        {"name": "duplicate_orders", "passed": duplicate_count == 0, "detail": f"duplicates={duplicate_count}"},
        {"name": "terminal_orders", "passed": nonterminal == 0, "detail": f"nonterminal={nonterminal}"},
        {
            "name": "decision_freshness",
            "passed": decision.get("updated_at", "")[:10] == report_date.isoformat(),
            "detail": f"updated_at={decision.get('updated_at')}",
        },
        {"name": "account_history", "passed": bool(account_rows), "detail": f"snapshots={len(account_rows)}"},
    ]
    health = "PASS" if all(check["passed"] for check in checks) else "FAIL"
    return {
        "report_date": report_date.isoformat(),
        "generated_at": dt.datetime.now().isoformat(timespec="seconds"),
        "mode": "SIMULATE",
        "health": health,
        "checks": checks,
        "account": {
            "initial_cash": initial_cash,
            "cash": cash,
            "market_value": market_value,
            "total_asset": total_asset,
            "position_count": len(positions),
            "invested_weight": market_value / total_asset if total_asset else 0.0,
        },
        "performance": {
            "start_asset": start_asset,
            "end_asset": end_asset,
            "daily_return": daily_return,
            "cumulative_return": cumulative_return,
            "total_pnl": total_pnl,
            "unrealized_pnl": unrealized_pnl,
            "realized_pnl_estimate": realized_pnl_estimate,
        },
        "trading": {
            "buy_count": side_counts.get("BUY", 0),
            "sell_count": side_counts.get("SELL", 0),
            "filled_count": status_counts.get("FILLED", 0),
            "nonterminal_count": nonterminal,
            "duplicate_count": duplicate_count,
            "commission": commission,
            "tax": tax,
            "slippage": slippage,
        },
        "positions": positions,
    }


def _markdown(report: dict) -> str:
    account = report["account"]
    performance = report["performance"]
    trading = report["trading"]
    lines = [
        f"# Simulation Report — {report['report_date']}",
        "",
        f"- Health: **{report['health']}**",
        f"- Total asset: {account['total_asset']:,.0f}",
        f"- Cash: {account['cash']:,.0f}",
        f"- Positions: {account['position_count']}",
        f"- Daily return: {performance['daily_return']:.2%}",
        f"- Cumulative return: {performance['cumulative_return']:.2%}",
        f"- Total P&L: {performance['total_pnl']:,.0f}",
        f"- Buy / Sell: {trading['buy_count']} / {trading['sell_count']}",
        f"- Commission / Tax / Slippage: {trading['commission']:,.0f} / {trading['tax']:,.0f} / {trading['slippage']:,.0f}",
        "",
        "## Health checks",
        "",
    ]
    lines.extend(
        f"- [{'x' if check['passed'] else ' '}] {check['name']}: {check['detail']}"
        for check in report["checks"]
    )
    lines.extend(["", "## Positions", ""])
    if report["positions"]:
        lines.extend(
            f"- {symbol}: {row['qty']} shares, avg {float(row['avg_price']):,.2f}, current {float(row.get('current_price') or row['avg_price']):,.2f}"
            for symbol, row in sorted(report["positions"].items())
        )
    else:
        lines.append("- None")
    return "\n".join(lines) + "\n"


def write_simulation_report(log_dir: Path, report_date: dt.date) -> dict:
    report = build_simulation_report(log_dir, report_date)
    report_dir = log_dir / "reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    base = report_dir / report_date.isoformat()
    (base.with_suffix(".json")).write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (base.with_suffix(".md")).write_text(_markdown(report), encoding="utf-8")
    (report_dir / "latest.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", default=dt.date.today().isoformat())
    parser.add_argument("--log-dir", default="logs/simulate")
    args = parser.parse_args()
    report = write_simulation_report(Path(args.log_dir), dt.date.fromisoformat(args.date))
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if report["health"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
