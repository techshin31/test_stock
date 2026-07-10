"""Monthly macro direction and macro-industry relationship job."""
from __future__ import annotations

import math
from dataclasses import asdict, replace
from datetime import date, timedelta

import pandas as pd

from apps.worker.analyzer.config import AnalyzerConfig
from apps.worker.analyzer.models import MacroDirection, MacroResult, RelationshipResult
from apps.worker.analyzer.relationships import (
    calculate_relationship,
    transform_macro_for_relationship,
)
from apps.worker.analyzer.sector_job import industry_returns_frame
from apps.worker.fa_contract import MACRO_SIGNALS, SUPPORTED_INDUSTRIES, MacroSignalContract
from storage.postgres.connection import PostgreDB
from storage.postgres.repositories.fa_analysis_repo import insert_macro_results
from storage.postgres.repositories.macro_signal_repo import fetch_macro_signals_as_of
from storage.postgres.repositories.wics_industry_repo import fetch_wics_industry_prices


def classify_direction(value: float, threshold: float) -> MacroDirection:
    if value >= threshold:
        return MacroDirection.UP
    if value <= -threshold:
        return MacroDirection.DOWN
    return MacroDirection.FLAT


def _weighted_normalized_changes(
    values: pd.Series,
    windows: tuple[int, ...],
    weights: tuple[float, ...],
    *,
    use_return: bool,
) -> tuple[float, dict[str, dict[str, float]]]:
    if len(values) <= max(windows):
        raise ValueError(f"requires at least {max(windows) + 1} observations")
    daily_change = values.pct_change(fill_method=None) if use_return else values.diff()
    volatility = float(daily_change.tail(60).std(ddof=1))
    if not math.isfinite(volatility) or volatility <= 0:
        volatility = 0.0
    detail: dict[str, dict[str, float]] = {}
    trend_raw = 0.0
    for window, weight in zip(windows, weights):
        raw = (
            float(values.iloc[-1] / values.iloc[-window - 1] - 1.0)
            if use_return else float(values.iloc[-1] - values.iloc[-window - 1])
        )
        normalized = raw / (volatility * math.sqrt(window)) if volatility else 0.0
        trend_raw += normalized * weight
        detail[str(window)] = {"raw": raw, "normalized": normalized, "weight": weight}
    return trend_raw, detail


def calculate_macro_direction(
    signal_name_code: str,
    rows: list[dict],
    config: AnalyzerConfig,
) -> MacroResult:
    contract = next(item for item in MACRO_SIGNALS if item.code == signal_name_code)
    frame = pd.DataFrame(rows).sort_values("observation_date")
    if frame.empty:
        raise ValueError(f"no macro rows: {signal_name_code}")
    frame["observation_date"] = pd.to_datetime(frame["observation_date"])
    values = pd.Series(
        pd.to_numeric(frame["value"], errors="coerce").astype(float).values,
        index=frame["observation_date"],
    ).dropna()

    if contract.transform == "CPI_YOY_PRESSURE":
        monthly = values.resample("M").last()
        yoy = monthly.pct_change(12, fill_method=None).mul(100.0).dropna()
        if yoy.shape[0] < 7:
            raise ValueError("CPI requires at least 19 monthly observations")
        yoy_change_vol = float(yoy.diff().dropna().std(ddof=1))
        changes = {window: float(yoy.iloc[-1] - yoy.iloc[-window - 1]) for window in (3, 6)}
        normalized = {
            window: (
                value / (yoy_change_vol * math.sqrt(window))
                if yoy_change_vol > 0 else 0.0
            )
            for window, value in changes.items()
        }
        trend_raw = normalized[3] * 0.4 + normalized[6] * 0.6
        detail = {
            "transform": contract.transform,
            "latest_yoy": float(yoy.iloc[-1]),
            "pressure_changes": {str(k): v for k, v in changes.items()},
            "normalized_changes": {str(k): v for k, v in normalized.items()},
        }
        required_points = 19
    elif contract.transform == "YOY_CHANGE":
        monthly = values.resample("M").last()
        yoy = monthly.pct_change(12, fill_method=None).mul(100.0).dropna()
        if yoy.shape[0] < 7:
            raise ValueError(f"{signal_name_code} requires at least 19 monthly observations")
        yoy_change_vol = float(yoy.diff().dropna().std(ddof=1))
        changes = {window: float(yoy.iloc[-1] - yoy.iloc[-window - 1]) for window in (3, 6)}
        normalized = {
            window: (
                value / (yoy_change_vol * math.sqrt(window))
                if yoy_change_vol > 0 else 0.0
            )
            for window, value in changes.items()
        }
        trend_raw = normalized[3] * 0.4 + normalized[6] * 0.6
        detail = {
            "transform": contract.transform,
            "latest_yoy": float(yoy.iloc[-1]),
            "yoy_changes": {str(k): v for k, v in changes.items()},
            "normalized_changes": {str(k): v for k, v in normalized.items()},
        }
        required_points = 19
    else:
        if contract.frequency == "MONTHLY":
            trend_windows = (3, 6, 12)
            trend_weights = (0.2, 0.3, 0.5)
        else:
            trend_windows = config.scoring.macro_trend_windows
            trend_weights = config.scoring.macro_trend_weights
        trend_raw, windows = _weighted_normalized_changes(
            values,
            trend_windows,
            trend_weights,
            use_return=contract.transform == "MARKET_RETURN",
        )
        detail = {"transform": contract.transform, "windows": windows}
        required_points = max(trend_windows) + 1

    direction = classify_direction(trend_raw, config.scoring.macro_direction_threshold)
    last_row = frame.iloc[-1]
    return MacroResult(
        signal_name_code=signal_name_code,
        last_observation_date=last_row["observation_date"].date(),
        last_available_date=pd.Timestamp(last_row["available_date"]).date(),
        direction_code=direction,
        trend_raw=float(trend_raw),
        trend_strength=min(abs(float(trend_raw)) / 2.0, 1.0),
        data_point_count=len(values),
        confidence=min(len(values) / required_points, 1.0),
        calculation_detail=detail,
    )


def _macro_rows_to_series(rows: list[dict]) -> pd.Series:
    frame = pd.DataFrame(rows)
    frame["observation_date"] = pd.to_datetime(frame["observation_date"])
    return pd.Series(
        pd.to_numeric(frame["value"], errors="coerce").astype(float).values,
        index=frame["observation_date"],
    ).sort_index()


def _minimum_abs_correlation(
    contract: MacroSignalContract,
    config: AnalyzerConfig,
) -> float:
    if contract.minimum_abs_correlation_override is not None:
        return contract.minimum_abs_correlation_override
    return config.scoring.minimum_abs_correlation


def _apply_contract_industry_limit(
    contract: MacroSignalContract,
    industry_code: str,
    relationship: RelationshipResult,
) -> RelationshipResult:
    if contract.eligible_industry_codes is None:
        return relationship
    if industry_code in contract.eligible_industry_codes:
        return relationship
    return replace(relationship, is_eligible=False, contribution=0.0)


def run(
    db: PostgreDB,
    run_id: int,
    cutoff_date: date,
    config: AnalyzerConfig,
) -> list[MacroResult]:
    start_date = cutoff_date - timedelta(days=365 * config.scoring.cpi_relationship_years + 400)
    source_rows = fetch_macro_signals_as_of(
        db,
        cutoff_date=cutoff_date,
        signal_names=[item.code for item in MACRO_SIGNALS],
        start_observation_date=start_date,
        end_observation_date=cutoff_date,
    )
    grouped = {
        code: [row for row in source_rows if row["signal_name_code"] == code]
        for code in (item.code for item in MACRO_SIGNALS)
    }
    industry_rows = fetch_wics_industry_prices(
        db,
        cutoff_date=cutoff_date,
        industry_codes=list(SUPPORTED_INDUSTRIES),
        start_date=cutoff_date - timedelta(days=365 * config.scoring.daily_relationship_years + 90),
    )
    weekly_returns = industry_returns_frame(industry_rows, "WEEKLY")
    monthly_returns = industry_returns_frame(industry_rows, "MONTHLY")
    prepared: list[tuple[MacroSignalContract, MacroResult, pd.Series, str]] = []
    for contract in MACRO_SIGNALS:
        rows = grouped[contract.code]
        if not rows:
            continue
        try:
            result = calculate_macro_direction(contract.code, rows, config)
            macro_changes, frequency = transform_macro_for_relationship(
                _macro_rows_to_series(rows), contract.transform
            )
        except ValueError:
            continue
        prepared.append((contract, result, macro_changes, frequency))

    results: list[MacroResult] = []
    signal_weight = 1.0 / len(prepared) if prepared else 0.0
    for contract, result, macro_changes, frequency in prepared:
        industry_frame = monthly_returns if frequency == "MONTHLY" else weekly_returns
        minimum_samples = (
            config.scoring.minimum_monthly_samples
            if frequency == "MONTHLY" else config.scoring.minimum_weekly_samples
        )
        relationships = []
        for industry_code in SUPPORTED_INDUSTRIES:
            relationship = calculate_relationship(
                signal_name_code=contract.code,
                industry_code=industry_code,
                macro_changes=macro_changes,
                industry_returns=industry_frame.get(industry_code, pd.Series(dtype=float)),
                frequency_code=frequency,
                direction_code=result.direction_code,
                trend_strength=result.trend_strength,
                minimum_sample_count=minimum_samples,
                minimum_abs_correlation=_minimum_abs_correlation(contract, config),
                minimum_relationship_confidence=config.scoring.minimum_relationship_confidence,
                signal_weight=signal_weight,
            )
            relationship = _apply_contract_industry_limit(
                contract,
                industry_code,
                relationship,
            )
            relationships.append(asdict(relationship))
        results.append(replace(
            result,
            calculation_detail={**result.calculation_detail, "relationships": relationships},
        ))

    insert_macro_results(
        db,
        run_id,
        [
            {
                **asdict(result),
                "direction_code": result.direction_code.value,
            }
            for result in results
        ],
    )
    return results
