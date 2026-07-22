"""Calibrate read-only execution stress scenarios from observed PAPER orders."""
from __future__ import annotations

import math

import pandas as pd


MIN_SIDE_SAMPLE = 30


def _number(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce").fillna(0.0)


def _wilson_interval(successes: int, total: int, z: float = 1.96) -> tuple[float, float]:
    if total <= 0:
        return 0.0, 0.0
    probability = successes / total
    denominator = 1.0 + z * z / total
    center = (probability + z * z / (2.0 * total)) / denominator
    margin = z * math.sqrt(
        probability * (1.0 - probability) / total
        + z * z / (4.0 * total * total)
    ) / denominator
    return max(center - margin, 0.0), min(center + margin, 1.0)


def _side_summary(frame: pd.DataFrame, side: str) -> dict:
    rows = frame[frame["side"].astype(str).str.upper() == side].copy()
    statuses = rows["status"].astype(str).str.upper().value_counts().to_dict()
    total = int(len(rows))
    filled = int(
        (_number(rows.get("filled_qty", pd.Series(dtype=float))) > 0).sum()
    )
    lower, upper = _wilson_interval(filled, total)
    ordered_qty = float(
        _number(rows.get("ordered_qty", pd.Series(dtype=float))).sum()
    )
    filled_qty = float(_number(rows.get("filled_qty", pd.Series(dtype=float))).sum())
    order_fill_rate = filled / total if total else 0.0
    quantity_fill_rate = min(filled_qty / ordered_qty, 1.0) if ordered_qty > 0 else 0.0
    posterior_mean = (filled + 1.0) / (total + 2.0)
    return {
        "side": side,
        "orders": total,
        "filled_orders": filled,
        "rejected_orders": int(statuses.get("REJECTED", 0)),
        "cancelled_orders": int(statuses.get("CANCELLED", 0)),
        "status_counts": {str(key): int(value) for key, value in statuses.items()},
        "order_fill_rate": order_fill_rate,
        "quantity_fill_rate": quantity_fill_rate,
        "beta_1_1_posterior_mean_fill_rate": posterior_mean,
        "wilson_95_lower_fill_rate": lower,
        "wilson_95_upper_fill_rate": upper,
        "sample_sufficient": total >= MIN_SIDE_SAMPLE,
    }


def calibrate_execution_outcomes(
    orders: pd.DataFrame,
    *,
    stabilized_since: str = "2026-07-21",
) -> dict:
    """Return transparent full-history and post-hardening execution scenarios."""
    frame = orders.copy()
    if "date" not in frame.columns:
        frame["date"] = pd.to_datetime(
            frame["created_at"], errors="coerce"
        ).dt.date.astype(str)
    frame["date"] = frame["date"].astype(str)
    full = {side: _side_summary(frame, side) for side in ("BUY", "SELL")}
    stabilized_frame = frame[frame["date"] >= stabilized_since]
    stabilized = {
        side: _side_summary(stabilized_frame, side) for side in ("BUY", "SELL")
    }

    scenarios = {
        "STABILIZED_POSTERIOR_MEAN": {
            "label": "post-hardening expected fill",
            "application": "DETERMINISTIC_BERNOULLI",
            "buy_fill_fraction": stabilized["BUY"][
                "beta_1_1_posterior_mean_fill_rate"
            ],
            "sell_fill_fraction": stabilized["SELL"][
                "beta_1_1_posterior_mean_fill_rate"
            ],
            "interpretation": "Beta(1,1) posterior mean from orders since the safety hardening date.",
        },
        "STABILIZED_WILSON_LOWER": {
            "label": "post-hardening conservative fill",
            "application": "DETERMINISTIC_BERNOULLI",
            "buy_fill_fraction": stabilized["BUY"]["wilson_95_lower_fill_rate"],
            "sell_fill_fraction": stabilized["SELL"]["wilson_95_lower_fill_rate"],
            "interpretation": "95% Wilson lower bound; deliberately conservative for small samples.",
        },
        "FULL_HISTORY_EMPIRICAL": {
            "label": "legacy-contaminated empirical fill",
            "application": "DETERMINISTIC_BERNOULLI",
            "buy_fill_fraction": full["BUY"]["order_fill_rate"],
            "sell_fill_fraction": full["SELL"]["order_fill_rate"],
            "interpretation": "All reconstructed orders, including the unstable pre-hardening period.",
        },
    }
    enough_evidence = all(
        stabilized[side]["sample_sufficient"] for side in ("BUY", "SELL")
    )
    return {
        "schema_version": 1,
        "mode": "PAPER",
        "observe_only": True,
        "stabilized_since": stabilized_since,
        "minimum_side_sample": MIN_SIDE_SAMPLE,
        "full_history": full,
        "stabilized": stabilized,
        "scenarios": scenarios,
        "calibration_status": (
            "READY" if enough_evidence else "PROVISIONAL_SMALL_SAMPLE"
        ),
        "production_parameter_permission": "DENIED_BY_DESIGN",
        "limitations": [
            "Order outcomes are observational and not randomized.",
            "The pre-hardening period includes retry and broker-error behavior that is no longer representative.",
            "The stabilized sample must reach the minimum independently for BUY and SELL before promotion use.",
            "Scenario replay uses deterministic full-fill-or-reject sampling; it does not predict a specific broker response.",
        ],
    }
