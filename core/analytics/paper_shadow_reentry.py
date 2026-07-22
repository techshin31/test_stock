"""Observe the trend-rearm re-entry rule without creating broker orders.

The shadow evaluator is intentionally isolated from target weights and execution.
It reads completed PAPER risk exits, evaluates one signal observation per KRX
session, and persists evidence that can later support (or block) promotion.
"""
from __future__ import annotations

import datetime as dt
import json
import math
import os
from pathlib import Path
from typing import Mapping

import pandas as pd


RISK_EXIT_REASONS = {"HARD_STOP_LOSS", "TRAILING_STOP"}
DEFAULT_CONFIRM_SESSIONS = 3
DEFAULT_OBSERVATION_SESSIONS = 10


def _atomic_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _normalize_symbol(value: object) -> str:
    symbol = str(value or "").strip().upper()
    return symbol if symbol.endswith(".KS") else f"{symbol}.KS"


def _reason_code(value: object) -> str:
    text = str(value or "").strip().upper()
    for code in RISK_EXIT_REASONS:
        if text.startswith(code):
            return code
    return text


def _load_completed_risk_exits(
    path: Path,
    *,
    mode: str,
    strategy: str,
) -> dict[str, dict]:
    exits: dict[str, dict] = {}
    if not path.exists():
        return exits
    for raw in path.read_text(encoding="utf-8-sig", errors="replace").splitlines():
        if not raw.strip():
            continue
        try:
            row = json.loads(raw)
            timestamp = dt.datetime.fromisoformat(str(row["timestamp"]))
        except (json.JSONDecodeError, KeyError, TypeError, ValueError):
            continue
        reason = _reason_code(row.get("reason"))
        if (
            str(row.get("mode", "")).upper() != mode
            or str(row.get("strategy", "")) != strategy
            or str(row.get("type", "")).upper() != "SELL"
            or str(row.get("status", "")).upper() != "FILLED"
            or reason not in RISK_EXIT_REASONS
        ):
            continue
        symbol = _normalize_symbol(row.get("ticker"))
        exit_price = float(row.get("avg_fill_price") or row.get("expected_price") or 0.0)
        if not math.isfinite(exit_price) or exit_price <= 0:
            continue
        candidate = {
            "ticker": symbol,
            "exit_timestamp": timestamp.isoformat(timespec="seconds"),
            "exit_date": timestamp.date().isoformat(),
            "exit_price": exit_price,
            "exit_price_source": (
                "BROKER_AVG_FILL" if row.get("avg_fill_price") else "ORDER_EXPECTED_PRICE"
            ),
            "exit_reason": reason,
            "broker_order_id": row.get("broker_order_id"),
        }
        previous = exits.get(symbol)
        if previous is None or candidate["exit_timestamp"] > previous["exit_timestamp"]:
            exits[symbol] = candidate
    return exits


def _technical_observation(frame: pd.DataFrame, exit_price: float) -> dict:
    if frame is None or frame.empty or "close" not in frame.columns:
        return {"data_ready": False, "reason": "PRICE_DATA_UNAVAILABLE"}
    close = pd.to_numeric(frame["close"], errors="coerce").dropna()
    if len(close) < 21:
        return {"data_ready": False, "reason": "INSUFFICIENT_20_SESSION_HISTORY"}
    ma20 = close.rolling(20, min_periods=20).mean()
    current_close = float(close.iloc[-1])
    current_ma20 = float(ma20.iloc[-1])
    previous_ma20 = float(ma20.iloc[-2])
    momentum20 = float(close.iloc[-1] / close.iloc[-21] - 1.0)
    conditions = {
        "above_exit_price": current_close > exit_price,
        "above_ma20": current_close > current_ma20,
        "ma20_rising": current_ma20 > previous_ma20,
        "momentum20_positive": momentum20 > 0.0,
    }
    return {
        "data_ready": True,
        "close": current_close,
        "ma20": current_ma20,
        "previous_ma20": previous_ma20,
        "momentum20": momentum20,
        "conditions": conditions,
        "all_conditions_met": all(conditions.values()),
    }


def evaluate_paper_shadow_reentry(
    *,
    mode: str,
    strategy: str,
    account_scope: str,
    signal_date: dt.date,
    ohlcv_store: Mapping[str, pd.DataFrame],
    positions: Mapping[str, dict],
    log_dir: Path,
    confirm_sessions: int = DEFAULT_CONFIRM_SESSIONS,
    observation_sessions_required: int = DEFAULT_OBSERVATION_SESSIONS,
) -> dict:
    """Persist one observe-only PAPER trend-rearm evaluation per session."""
    normalized_mode = str(mode).upper()
    if normalized_mode != "PAPER":
        raise ValueError("trend-rearm shadow evaluation is PAPER-only")
    if not strategy or account_scope in {"", "UNKNOWN", None}:
        raise ValueError("strategy and a certified PAPER account scope are required")
    if confirm_sessions < 1 or observation_sessions_required < 1:
        raise ValueError("shadow session thresholds must be positive")

    state_path = log_dir / "shadow_reentry_state.json"
    history_path = log_dir / "shadow_reentry_history.jsonl"
    state = {}
    if state_path.exists():
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            state = {}
    if state and (
        state.get("mode") != normalized_mode
        or state.get("strategy") != strategy
        or state.get("account_scope") != account_scope
    ):
        raise RuntimeError("existing shadow state belongs to a different PAPER scope")

    signal_day = signal_date.isoformat()
    observed_sessions = list(state.get("observed_sessions") or [])
    is_new_session = signal_day not in observed_sessions
    if is_new_session:
        observed_sessions.append(signal_day)
        observed_sessions = sorted(set(observed_sessions))

    exits = _load_completed_risk_exits(
        log_dir / "trade_history.jsonl",
        mode=normalized_mode,
        strategy=strategy,
    )
    prior_candidates = dict(state.get("candidates") or {})
    held_symbols = {_normalize_symbol(symbol) for symbol in positions}
    candidates: dict[str, dict] = {}
    ready_candidates = 0

    for ticker, exit_event in sorted(exits.items()):
        previous = prior_candidates.get(ticker, {})
        exit_changed = previous.get("exit_timestamp") != exit_event["exit_timestamp"]
        streak = 0 if exit_changed else int(previous.get("confirmation_streak") or 0)
        observation = _technical_observation(ohlcv_store.get(ticker), exit_event["exit_price"])
        after_exit_session = signal_date > dt.date.fromisoformat(exit_event["exit_date"])
        qualifies_today = bool(
            after_exit_session
            and ticker not in held_symbols
            and observation.get("data_ready")
            and observation.get("all_conditions_met")
        )
        if is_new_session and not exit_changed:
            streak = streak + 1 if qualifies_today else 0
        elif is_new_session and exit_changed:
            streak = 1 if qualifies_today else 0
        shadow_ready = streak >= confirm_sessions
        ready_candidates += int(shadow_ready)
        candidates[ticker] = {
            **exit_event,
            "signal_date": signal_day,
            "production_position_present": ticker in held_symbols,
            "observation": observation,
            "eligible_after_exit_session": after_exit_session,
            "qualifies_today": qualifies_today,
            "confirmation_streak": streak,
            "required_confirmation_sessions": confirm_sessions,
            "shadow_reentry_ready": shadow_ready,
            "action": "OBSERVE_ONLY_NO_ORDER",
        }

    generated_at = dt.datetime.now(dt.timezone(dt.timedelta(hours=9))).isoformat(
        timespec="seconds"
    )
    payload = {
        "schema_version": 1,
        "generated_at": generated_at,
        "mode": normalized_mode,
        "strategy": strategy,
        "account_scope": account_scope,
        "variant": "R_TREND_REARM",
        "observe_only": True,
        "order_permission": "DENIED_BY_DESIGN",
        "rule": {
            "eligible_exit_reasons": sorted(RISK_EXIT_REASONS),
            "conditions": [
                "close > recorded exit price",
                "close > MA20",
                "MA20 > previous-session MA20",
                "20-session momentum > 0",
            ],
            "required_consecutive_sessions": confirm_sessions,
        },
        "observed_sessions": observed_sessions,
        "completed_observation_sessions": len(observed_sessions),
        "required_observation_sessions": observation_sessions_required,
        "observation_window_complete": len(observed_sessions) >= observation_sessions_required,
        "risk_exit_count": len(exits),
        "shadow_ready_candidate_count": ready_candidates,
        "candidates": candidates,
    }
    _atomic_json(state_path, payload)
    if is_new_session:
        history_path.parent.mkdir(parents=True, exist_ok=True)
        with history_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")
    return payload


def load_shadow_state(path: Path) -> dict:
    if not path.exists():
        return {
            "variant": "R_TREND_REARM",
            "observe_only": True,
            "completed_observation_sessions": 0,
            "required_observation_sessions": DEFAULT_OBSERVATION_SESSIONS,
            "observation_window_complete": False,
            "candidates": {},
        }
    return json.loads(path.read_text(encoding="utf-8"))
