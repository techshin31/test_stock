from __future__ import annotations

import json
import os
import socket
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


_LOG_PATH = Path(os.getenv("AUDIT_LOG_PATH", "logs/trader_audit.jsonl"))


def _write(record: dict[str, Any]) -> None:
    _LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(record, ensure_ascii=False, default=str)
    with _LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def _base(event: str) -> dict[str, Any]:
    return {
        "ts": datetime.now(timezone.utc).isoformat(),
        "host": socket.gethostname(),
        "event": event,
    }


def log_startup(config_summary: dict[str, Any]) -> None:
    _write({**_base("STARTUP"), **config_summary})


def log_gate(allowed: bool, reason: str) -> None:
    _write({**_base("GATE"), "allowed": allowed, "reason": reason})


def log_cycle_start(plan_date: str, plan_count: int) -> None:
    _write({**_base("CYCLE_START"), "plan_date": plan_date, "plan_count": plan_count})


def log_order(
    symbol: str,
    side: str,
    qty: int,
    price: int | None,
    status: str,
    plan_id: int | None = None,
    note: str | None = None,
) -> None:
    _write({
        **_base("ORDER"),
        "symbol": symbol,
        "side": side,
        "qty": qty,
        "price": price,
        "status": status,
        "plan_id": plan_id,
        "note": note,
    })


def log_cycle_end(filled_count: int, error_count: int, elapsed_sec: float) -> None:
    _write({
        **_base("CYCLE_END"),
        "filled_count": filled_count,
        "error_count": error_count,
        "elapsed_sec": round(elapsed_sec, 2),
    })


def log_eod(reconcile_summary: dict[str, Any]) -> None:
    _write({**_base("EOD_RECONCILE"), **reconcile_summary})


def log_error(context: str, error: str) -> None:
    _write({**_base("ERROR"), "context": context, "error": error})


def log_loss_limit(reason: str) -> None:
    _write({**_base("LOSS_LIMIT_BREACH"), "reason": reason})


def log_position_sync(synced: int, zeroed: int, zeroed_symbols: list[str]) -> None:
    _write({
        **_base("POSITION_SYNC"),
        "synced": synced,
        "zeroed": zeroed,
        "zeroed_symbols": zeroed_symbols,
    })
