"""PAPER-only, 1x inverse ETF hedge policy.

The module is deliberately pure: it turns observed daily market regime data and
the current account state into a target weight plus auditable state. Order
placement remains the responsibility of :mod:`core.execution.trader`.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import math
from typing import Any

import pandas as pd


@dataclass(frozen=True)
class InverseHedgeConfig:
    """Risk bounds for the KOSPI200 1x inverse ETF hedge."""

    min_confirmations: int = 2
    min_confidence: float = 2 / 3
    stop_loss_pct: float = 0.05
    max_holding_sessions: int = 5
    cooldown_sessions: int = 3
    stage_weights: tuple[float, float, float] = (0.10, 0.20, 0.30)

    def __post_init__(self) -> None:
        if self.min_confirmations < 2:
            raise ValueError("Inverse hedge requires at least two confirmations")
        if not math.isfinite(self.min_confidence) or not 0 < self.min_confidence <= 1:
            raise ValueError("Inverse hedge confidence must be in (0, 1]")
        if not math.isfinite(self.stop_loss_pct) or not 0 < self.stop_loss_pct <= 0.10:
            raise ValueError("Inverse hedge stop loss must be in (0, 0.10]")
        if self.max_holding_sessions < 1 or self.cooldown_sessions < 1:
            raise ValueError("Inverse hedge session limits must be positive")
        if len(self.stage_weights) != 3 or any(
            not math.isfinite(weight) or weight <= 0 or weight > 0.30
            for weight in self.stage_weights
        ):
            raise ValueError("Inverse hedge stage weights must be within (0, 0.30]")
        if tuple(sorted(self.stage_weights)) != self.stage_weights:
            raise ValueError("Inverse hedge stage weights must be non-decreasing")


def _as_date_text(value: date | str) -> str:
    return value.isoformat() if isinstance(value, date) else str(value)[:10]


def _consecutive_downtrends(regime_frame: pd.DataFrame) -> int:
    if not isinstance(regime_frame, pd.DataFrame) or "REGIME" not in regime_frame:
        return 0
    count = 0
    for regime in reversed(regime_frame["REGIME"].dropna().astype(str).tolist()):
        if regime != "DOWNTREND":
            break
        count += 1
    return count


def _downtrend_confidence(regime_frame: pd.DataFrame, close: pd.Series) -> float:
    """Return a transparent 0..1 confirmation score from daily trend alignment."""
    if (
        not isinstance(regime_frame, pd.DataFrame)
        or regime_frame.empty
        or not isinstance(close, pd.Series)
        or close.empty
    ):
        return 0.0
    try:
        latest = regime_frame.iloc[-1]
        latest_close = float(close.dropna().iloc[-1])
        ma20 = float(latest["ma20"])
        ma60 = float(latest["ma60"])
        ma120 = float(latest["ma120"])
    except (KeyError, IndexError, TypeError, ValueError):
        return 0.0
    values = (latest_close, ma20, ma60, ma120)
    if not all(pd.notna(value) for value in values):
        return 0.0
    confirmations = (
        latest_close < ma20,
        ma20 < ma60,
        ma60 < ma120,
    )
    return round(sum(confirmations) / len(confirmations), 4)


def _current_weight(position: dict[str, Any] | None, total_eval: float) -> float:
    if not position or total_eval <= 0:
        return 0.0
    try:
        value = float(position.get("qty") or 0) * float(
            position.get("current_price") or position.get("avg_price") or 0
        )
    except (AttributeError, TypeError, ValueError):
        return 0.0
    return round(max(value, 0.0) / total_eval, 6)


def _new_state(state: dict[str, Any] | None) -> dict[str, Any]:
    source = state if isinstance(state, dict) else {}
    return {
        "schema_version": 1,
        "active": bool(source.get("active")),
        "entry_date": source.get("entry_date"),
        "held_sessions": max(int(source.get("held_sessions") or 0), 0),
        "last_held_signal_date": source.get("last_held_signal_date"),
        "cooldown_sessions_remaining": max(
            int(source.get("cooldown_sessions_remaining") or 0), 0
        ),
        "last_evaluated_date": source.get("last_evaluated_date"),
        "last_exit_reason": source.get("last_exit_reason"),
    }


def _stage_weight(confirmations: int, config: InverseHedgeConfig) -> float:
    if confirmations <= config.min_confirmations:
        return config.stage_weights[0]
    if confirmations == config.min_confirmations + 1:
        return config.stage_weights[1]
    return config.stage_weights[2]


def evaluate_inverse_hedge(
    *,
    signal_date: date | str,
    regime_frame: pd.DataFrame,
    close: pd.Series,
    market_regime: str | None,
    position: dict[str, Any] | None,
    total_eval: float,
    state: dict[str, Any] | None,
    config: InverseHedgeConfig,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Evaluate one daily 1x inverse-ETF hedge decision.

    An entry needs two completed DOWNTREND observations. The target then steps
    from 10% to 20% and finally 30% only when daily moving averages confirm the
    regime. A held hedge exits immediately outside DOWNTREND, on a dedicated
    loss limit, or after the bounded holding window.
    """
    today = _as_date_text(signal_date)
    next_state = _new_state(state)
    cooldown_before = next_state["cooldown_sessions_remaining"]
    cooldown_active = cooldown_before > 0
    if cooldown_active and next_state["last_evaluated_date"] != today:
        next_state["cooldown_sessions_remaining"] = cooldown_before - 1

    has_position = bool(position and float(position.get("qty") or 0) > 0)
    if has_position:
        next_state["active"] = True
        if not next_state["entry_date"]:
            # A restart can discover a broker-held hedge without a local entry
            # record. Start the bounded window conservatively from discovery.
            next_state["entry_date"] = today
            next_state["held_sessions"] = 1
        elif next_state["last_held_signal_date"] != today:
            next_state["held_sessions"] += 1
        next_state["last_held_signal_date"] = today
    elif next_state["active"]:
        next_state["active"] = False
        next_state["entry_date"] = None
        next_state["held_sessions"] = 0
        next_state["last_held_signal_date"] = None

    confirmations = _consecutive_downtrends(regime_frame)
    confidence = _downtrend_confidence(regime_frame, close)
    current_weight = _current_weight(position, total_eval)
    reason = "INVERSE_HEDGE_INACTIVE"
    status = "INACTIVE"
    target_weight = 0.0

    def exit_with(reason_code: str, status_code: str) -> None:
        nonlocal reason, status, target_weight
        reason = reason_code
        status = status_code
        target_weight = 0.0
        next_state["cooldown_sessions_remaining"] = config.cooldown_sessions
        next_state["last_exit_reason"] = reason_code

    if has_position:
        average_price = float(position.get("avg_price") or 0.0)
        current_price = float(position.get("current_price") or 0.0)
        if average_price > 0 and current_price > 0:
            hedge_return = current_price / average_price - 1.0
            if hedge_return <= -config.stop_loss_pct:
                exit_with("INVERSE_HEDGE_STOP_LOSS", "EXIT_STOP_LOSS")
        if status != "EXIT_STOP_LOSS" and next_state["held_sessions"] >= config.max_holding_sessions:
            exit_with("INVERSE_HEDGE_MAX_HOLD", "EXIT_MAX_HOLD")

    if status not in {"EXIT_STOP_LOSS", "EXIT_MAX_HOLD"}:
        if market_regime != "DOWNTREND":
            reason = "DOWNTREND_EXIT" if has_position else "INVERSE_HEDGE_INACTIVE"
            status = "EXIT_REGIME" if has_position else "INACTIVE"
        elif cooldown_active:
            reason = "INVERSE_HEDGE_COOLDOWN"
            status = "COOLDOWN"
        elif confirmations < config.min_confirmations:
            reason = "INVERSE_HEDGE_WAIT_CONFIRMATION"
            status = "WAIT_CONFIRMATION"
        elif confidence < config.min_confidence:
            reason = "INVERSE_HEDGE_LOW_CONFIDENCE"
            status = "WAIT_CONFIDENCE"
        else:
            target_weight = _stage_weight(confirmations, config)
            if has_position:
                reason = (
                    "INVERSE_HEDGE_SCALE_UP"
                    if target_weight > current_weight + 0.001
                    else "INVERSE_HEDGE_HOLD"
                )
                status = "ACTIVE"
            else:
                reason = "INVERSE_HEDGE_ENTRY"
                status = "ENTRY_READY"

    next_state["last_evaluated_date"] = today
    decision = {
        "schema_version": 1,
        "instrument": "KODEX_INVERSE_1X",
        "market_regime": market_regime or "UNAVAILABLE",
        "status": status,
        "reason": reason,
        "target_weight": round(target_weight, 4),
        "current_weight": current_weight,
        "confirmed_downtrend_sessions": confirmations,
        "required_confirmations": config.min_confirmations,
        "confidence": confidence,
        "minimum_confidence": config.min_confidence,
        "stop_loss_pct": config.stop_loss_pct,
        "max_holding_sessions": config.max_holding_sessions,
        "held_sessions": next_state["held_sessions"],
        "cooldown_sessions_remaining": next_state["cooldown_sessions_remaining"],
        "cooldown_active": cooldown_active or next_state["cooldown_sessions_remaining"] > 0,
        "last_exit_reason": next_state["last_exit_reason"],
    }
    return decision, next_state
