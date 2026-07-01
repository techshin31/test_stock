"""Versioned projection from DART events to current company risk states."""
from __future__ import annotations

from datetime import date, timedelta

from storage.postgres.connection import PostgreDB
from storage.postgres.repositories.company_risk_repo import (
    upsert_company_risk_states,
)
from storage.postgres.repositories.dart_event_repo import fetch_dart_events


POLICY_VERSION = "dart-dilution-v1.0.0"
BUY_BLOCK_DAYS_BY_SUBTYPE = {
    "PAID_IN_CAPITAL_INCREASE": 90,
    "CONVERTIBLE_BOND": 90,
    "BOND_WITH_WARRANT": 90,
    "EXCHANGE_BOND": 90,
}


def derive_company_risk_states(
    event_rows: list[dict],
    as_of_date: date,
) -> list[dict]:
    """Return one versioned automatic risk-state row per blocking event."""
    states: list[dict] = []
    for event in event_rows:
        subtype = event.get("event_subtype_code")
        block_days = BUY_BLOCK_DAYS_BY_SUBTYPE.get(subtype)
        if block_days is None:
            continue
        effective_date = event["rcept_dt"]
        if isinstance(effective_date, str):
            effective_date = date.fromisoformat(effective_date)
        expires_at = effective_date + timedelta(days=block_days)
        if effective_date > as_of_date:
            continue
        candidate = {
            "stock_code": event["stock_code"],
            "risk_action_code": "BLOCK_BUY",
            "reason_code": subtype,
            "source_dart_event_id": event.get("id"),
            "effective_date": effective_date,
            "expires_at": expires_at,
            "policy_version": POLICY_VERSION,
            "is_manual_override": False,
            "detail": {
                "rcept_no": event.get("rcept_no"),
                "report_nm": event.get("report_nm"),
                "block_days": block_days,
            },
        }
        states.append(candidate)
    return sorted(
        states,
        key=lambda row: (
            row["stock_code"], row["effective_date"],
            str(row["source_dart_event_id"]),
        ),
    )


def refresh_company_risk_states(db: PostgreDB, as_of_date: date) -> int:
    events = fetch_dart_events(
        db,
        event_categories=["CAPITAL_CHANGE"],
        end_date=as_of_date,
    )
    states = derive_company_risk_states(events, as_of_date)
    return upsert_company_risk_states(db, states)
