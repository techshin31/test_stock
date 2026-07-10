"""Deterministic macro-to-industry relationship statistics."""
from __future__ import annotations

import math

import pandas as pd

from apps.worker.analyzer.models import MacroDirection, RelationshipResult


def _looks_monthly(series: pd.Series) -> bool:
    if len(series) < 3:
        return False
    gaps = series.index.to_series().sort_values().diff().dropna()
    if gaps.empty:
        return False
    return gaps.median() >= pd.Timedelta(days=20)


def transform_macro_for_relationship(
    values: pd.Series,
    transform: str,
) -> tuple[pd.Series, str]:
    """Convert macro levels to changes aligned with industry returns."""
    series = pd.to_numeric(values, errors="coerce").astype(float).sort_index()
    if transform == "CPI_YOY_PRESSURE":
        monthly = series.resample("M").last()
        return (
            monthly.pct_change(12, fill_method=None).mul(100.0).dropna().diff(),
            "MONTHLY",
        )
    if transform == "YOY_CHANGE":
        monthly = series.resample("M").last()
        return (
            monthly.pct_change(12, fill_method=None).mul(100.0).dropna().diff(),
            "MONTHLY",
        )
    if transform == "LEVEL":
        monthly = series.resample("M").last()
        return monthly.diff(), "MONTHLY"

    if _looks_monthly(series):
        monthly = series.resample("M").last()
        if transform == "YIELD_CHANGE":
            return monthly.diff(), "MONTHLY"
        if transform == "MARKET_RETURN":
            return monthly.pct_change(fill_method=None), "MONTHLY"

    weekly = series.resample("W-FRI").last()
    if transform == "YIELD_CHANGE":
        return weekly.diff(), "WEEKLY"
    if transform == "MARKET_RETURN":
        return weekly.pct_change(fill_method=None), "WEEKLY"
    raise ValueError(f"unsupported macro transform: {transform}")


def _sign_stability(
    aligned: pd.DataFrame,
    full_correlation: float,
    frequency_code: str,
) -> float:
    periods = (12, 24, 36) if frequency_code == "MONTHLY" else (52, 104, 156)
    signs: list[bool] = []
    target_sign = 1 if full_correlation >= 0 else -1
    for period in periods:
        window = aligned.tail(period)
        if len(window) < max(6, period // 2):
            continue
        correlation = window["macro"].corr(window["industry"])
        if pd.notna(correlation) and correlation != 0:
            signs.append((1 if correlation > 0 else -1) == target_sign)
    return sum(signs) / len(signs) if signs else 0.0


def calculate_relationship(
    *,
    signal_name_code: str,
    industry_code: str,
    macro_changes: pd.Series,
    industry_returns: pd.Series,
    frequency_code: str,
    direction_code: MacroDirection,
    trend_strength: float,
    minimum_sample_count: int,
    minimum_abs_correlation: float,
    minimum_relationship_confidence: float,
    signal_weight: float,
) -> RelationshipResult:
    aligned = pd.concat(
        [macro_changes.rename("macro"), industry_returns.rename("industry")],
        axis=1,
        join="inner",
    ).dropna()
    sample_count = len(aligned)
    if sample_count < 2 or float(aligned["macro"].var(ddof=1)) == 0.0:
        return RelationshipResult(
            signal_name_code, industry_code, frequency_code, None, None,
            sample_count, 0.0, 0.0, 0.0, False,
        )

    correlation = float(aligned["macro"].corr(aligned["industry"]))
    beta = float(
        aligned["macro"].cov(aligned["industry"])
        / aligned["macro"].var(ddof=1)
    )
    if not math.isfinite(correlation) or not math.isfinite(beta):
        return RelationshipResult(
            signal_name_code, industry_code, frequency_code, None, None,
            sample_count, 0.0, 0.0, 0.0, False,
        )
    stability = _sign_stability(aligned, correlation, frequency_code)
    sample_confidence = min(sample_count / minimum_sample_count, 1.0)
    correlation_confidence = min(abs(correlation) / 0.40, 1.0)
    confidence = sample_confidence * correlation_confidence * stability
    eligible = (
        sample_count >= minimum_sample_count
        and abs(correlation) >= minimum_abs_correlation
        and confidence >= minimum_relationship_confidence
    )
    direction_sign = {
        MacroDirection.UP: 1.0,
        MacroDirection.DOWN: -1.0,
        MacroDirection.FLAT: 0.0,
    }[direction_code]
    contribution = (
        direction_sign
        * correlation
        * trend_strength
        * confidence
        * signal_weight
        if eligible else 0.0
    )
    if not math.isfinite(contribution):
        contribution = 0.0
        eligible = False
    return RelationshipResult(
        signal_name_code=signal_name_code,
        industry_code=industry_code,
        frequency_code=frequency_code,
        correlation=correlation,
        beta=beta,
        sample_count=sample_count,
        sign_stability=stability,
        relationship_confidence=confidence,
        contribution=contribution,
        is_eligible=eligible,
    )
