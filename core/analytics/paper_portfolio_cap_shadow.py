"""Observe tighter portfolio concentration limits without changing PAPER orders.

The production allocator remains authoritative.  These challengers calculate
counterfactual target weights only, then persist an auditable PAPER observation
for later comparison.  No returned field is consumed by order generation.
"""
from __future__ import annotations

import datetime as dt
import json
import os
from pathlib import Path
from typing import Mapping


PORTFOLIO_CAP_VARIANTS: tuple[tuple[str, float], ...] = (
    ("C_CAP10", 0.10),
    ("C_CAP08", 0.08),
)


def _atomic_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _clean_target_weights(target_positions: Mapping[str, object]) -> dict[str, float]:
    return {
        str(ticker): max(0.0, float(weight or 0.0))
        for ticker, weight in target_positions.items()
    }


def _candidate_summary(
    target_positions: Mapping[str, float],
    cap: float,
) -> dict:
    candidate = {
        ticker: min(weight, cap) if weight > 0.0 else 0.0
        for ticker, weight in target_positions.items()
    }
    capped = {
        ticker: {
            "production_target_weight": round(weight, 6),
            "shadow_target_weight": round(candidate[ticker], 6),
            "reduction": round(weight - candidate[ticker], 6),
        }
        for ticker, weight in target_positions.items()
        if weight > cap
    }
    gross = sum(candidate.values())
    return {
        "max_single_position_weight": cap,
        "gross_target_weight": round(gross, 6),
        "cash_weight": round(max(0.0, 1.0 - gross), 6),
        "active_position_count": sum(weight > 0.0 for weight in candidate.values()),
        "capped_position_count": len(capped),
        "capped_positions": capped,
        "shadow_target_positions": {
            ticker: round(weight, 6) for ticker, weight in sorted(candidate.items())
        },
    }


def evaluate_paper_portfolio_cap_shadow(
    *,
    mode: str,
    strategy: str,
    account_scope: str,
    signal_date: dt.date,
    target_positions: Mapping[str, object],
    log_dir: Path,
) -> dict:
    """Persist C_CAP10/C_CAP08 counterfactual targets for a PAPER session.

    This function deliberately copies all inputs before applying caps.  It is
    not allowed to mutate ``target_positions`` or grant an order permission.
    """
    normalized_mode = str(mode).upper()
    if normalized_mode != "PAPER":
        raise ValueError("portfolio-cap shadow evaluation is PAPER-only")
    if not strategy or account_scope in {"", "UNKNOWN", None}:
        raise ValueError("strategy and a certified PAPER account scope are required")

    state_path = log_dir / "portfolio_cap_shadow_state.json"
    history_path = log_dir / "portfolio_cap_shadow_history.jsonl"
    previous_state: dict = {}
    if state_path.exists():
        try:
            previous_state = json.loads(state_path.read_text(encoding="utf-8"))
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            previous_state = {}
    if previous_state and (
        previous_state.get("mode") != normalized_mode
        or previous_state.get("strategy") != strategy
        or previous_state.get("account_scope") != account_scope
    ):
        raise RuntimeError("existing portfolio-cap state belongs to a different PAPER scope")

    production_targets = _clean_target_weights(target_positions)
    signal_day = signal_date.isoformat()
    observed_sessions = sorted(
        set([*(previous_state.get("observed_sessions") or []), signal_day])
    )
    is_new_session = signal_day not in (previous_state.get("observed_sessions") or [])
    generated_at = dt.datetime.now(dt.timezone(dt.timedelta(hours=9))).isoformat(
        timespec="seconds"
    )
    payload = {
        "schema_version": 1,
        "generated_at": generated_at,
        "mode": normalized_mode,
        "strategy": strategy,
        "account_scope": account_scope,
        "observe_only": True,
        "order_permission": "DENIED_BY_DESIGN",
        "observed_sessions": observed_sessions,
        "production": {
            "gross_target_weight": round(sum(production_targets.values()), 6),
            "max_single_position_weight": round(
                max(production_targets.values(), default=0.0), 6
            ),
            "target_positions": {
                ticker: round(weight, 6)
                for ticker, weight in sorted(production_targets.items())
            },
        },
        "challengers": [
            {
                "variant": variant,
                "observe_only": True,
                "order_permission": "DENIED_BY_DESIGN",
                **_candidate_summary(production_targets, cap),
            }
            for variant, cap in PORTFOLIO_CAP_VARIANTS
        ],
    }
    _atomic_json(state_path, payload)
    if is_new_session:
        history_path.parent.mkdir(parents=True, exist_ok=True)
        with history_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")
    return payload


def load_portfolio_cap_shadow_state(path: Path) -> dict:
    """Load the current counterfactual state without modifying runtime evidence."""
    if not path.exists():
        return {
            "observe_only": True,
            "order_permission": "DENIED_BY_DESIGN",
            "observed_sessions": [],
            "challengers": [],
        }
    return json.loads(path.read_text(encoding="utf-8"))
