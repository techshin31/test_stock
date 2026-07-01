"""Persistence for current company-level trading risk states."""
from __future__ import annotations

import json
from datetime import date

from ..connection import PostgreDB


BUY_BLOCK_ACTIONS = ("BLOCK_BUY", "SELL_ONLY")


def upsert_company_risk_states(db: PostgreDB, rows: list[dict]) -> int:
    if not rows:
        return 0
    params = [
        (
            row["stock_code"], row["risk_action_code"], row.get("reason_code"),
            row.get("source_dart_event_id"), row["effective_date"],
            row.get("expires_at"), row["policy_version"],
            row.get("is_manual_override", False),
            json.dumps(row.get("detail", {}), ensure_ascii=False, default=str),
        )
        for row in rows
    ]
    db.execute_many(
        """
        INSERT INTO company_risk_states (
            stock_code, risk_action_code, reason_code, source_dart_event_id,
            effective_date, expires_at, policy_version, is_manual_override, detail
        ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb)
        ON CONFLICT (stock_code, source_dart_event_id, policy_version) DO UPDATE SET
            risk_action_code = EXCLUDED.risk_action_code,
            reason_code = EXCLUDED.reason_code,
            source_dart_event_id = EXCLUDED.source_dart_event_id,
            effective_date = EXCLUDED.effective_date,
            expires_at = EXCLUDED.expires_at,
            is_manual_override = EXCLUDED.is_manual_override,
            detail = EXCLUDED.detail,
            updated_at = NOW()
        """,
        params,
    )
    return len(params)


def fetch_active_company_risk_states(
    db: PostgreDB,
    as_of_date: date,
    stock_codes: list[str] | None = None,
) -> list[dict]:
    conditions = [
        "effective_date <= %s",
        "(expires_at IS NULL OR expires_at >= %s)",
    ]
    params: list[object] = [as_of_date, as_of_date]
    if stock_codes:
        conditions.append("stock_code = ANY(%s)")
        params.append(stock_codes)
    return db.fetch_all(
        f"""
        SELECT * FROM (
            SELECT DISTINCT ON (stock_code) *
            FROM company_risk_states
            WHERE {' AND '.join(conditions)}
            ORDER BY stock_code, is_manual_override DESC,
                     effective_date DESC, id DESC
        ) latest
        WHERE risk_action_code = ANY(%s)
        ORDER BY stock_code
        """,
        tuple(params + [list(BUY_BLOCK_ACTIONS)]),
    )


def fetch_buy_blocked_stock_codes(
    db: PostgreDB,
    as_of_date: date,
    stock_codes: list[str] | None = None,
) -> set[str]:
    return {
        row["stock_code"]
        for row in fetch_active_company_risk_states(db, as_of_date, stock_codes)
    }


def is_company_buy_blocked(
    db: PostgreDB,
    stock_code: str,
    as_of_date: date,
) -> bool:
    return bool(fetch_active_company_risk_states(db, as_of_date, [stock_code]))
