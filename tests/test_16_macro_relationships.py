from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from apps.worker.analyzer.config import load_config
from apps.worker.analyzer.macro_job import (
    _apply_contract_industry_limit,
    _minimum_abs_correlation,
    calculate_macro_direction,
    classify_direction,
    run as run_macro_analysis,
)
from apps.worker.analyzer.models import MacroDirection, RelationshipResult
from apps.worker.analyzer.relationships import calculate_relationship, transform_macro_for_relationship
from apps.worker.fa_contract import MACRO_SIGNALS


def _rows(values):
    start = date(2025, 1, 1)
    return [
        {
            "observation_date": start + timedelta(days=index),
            "available_date": start + timedelta(days=index + 1),
            "value": value,
        }
        for index, value in enumerate(values)
    ]


def test_direction_threshold_boundaries():
    assert classify_direction(0.5, 0.5) == MacroDirection.UP
    assert classify_direction(-0.5, 0.5) == MacroDirection.DOWN
    assert classify_direction(0.499, 0.5) == MacroDirection.FLAT


def test_tnx_uses_yield_changes_not_returns():
    result = calculate_macro_direction("TNX", _rows(np.linspace(1.0, 5.0, 150)), load_config())
    assert result.calculation_detail["transform"] == "YIELD_CHANGE"
    assert result.calculation_detail["windows"]["20"]["raw"] == pytest.approx(
        5.0 - np.linspace(1.0, 5.0, 150)[-21]
    )


def test_cpi_uses_yoy_pressure_instead_of_rising_level():
    start = date(2021, 1, 1)
    rows = [
        {
            "observation_date": (pd.Timestamp(start) + pd.DateOffset(months=index)).date(),
            "available_date": (pd.Timestamp(start) + pd.DateOffset(months=index, days=15)).date(),
            "value": 100.0 * (1.002 ** index),
        }
        for index in range(48)
    ]
    result = calculate_macro_direction("CPI", rows, load_config())
    assert result.direction_code == MacroDirection.FLAT
    assert result.calculation_detail["transform"] == "CPI_YOY_PRESSURE"


def test_yoy_change_transform_outputs_monthly_changes():
    index = pd.date_range("2024-01-01", periods=24, freq="MS")
    values = pd.Series(np.linspace(100.0, 130.0, 24), index=index)
    transformed, frequency = transform_macro_for_relationship(values, "YOY_CHANGE")
    assert frequency == "MONTHLY"
    assert not transformed.dropna().empty


def test_monthly_market_return_transform_keeps_monthly_frequency():
    index = pd.date_range("2024-01-01", periods=18, freq="MS")
    values = pd.Series(np.linspace(100.0, 120.0, 18), index=index)
    transformed, frequency = transform_macro_for_relationship(values, "MARKET_RETURN")
    assert frequency == "MONTHLY"
    assert transformed.index.freqstr == "ME"


def test_down_macro_and_negative_correlation_has_positive_contribution():
    index = pd.date_range("2023-01-06", periods=120, freq="W-FRI")
    macro = pd.Series(np.linspace(-1, 1, 120), index=index)
    industry = -macro
    result = calculate_relationship(
        signal_name_code="DXY", industry_code="G4530",
        macro_changes=macro, industry_returns=industry, frequency_code="WEEKLY",
        direction_code=MacroDirection.DOWN, trend_strength=1.0,
        minimum_sample_count=104, minimum_abs_correlation=0.15,
        minimum_relationship_confidence=0.5, signal_weight=0.125,
    )
    assert result.is_eligible
    assert result.contribution > 0


def test_insufficient_sample_relationship_is_excluded():
    index = pd.date_range("2025-01-03", periods=20, freq="W-FRI")
    result = calculate_relationship(
        signal_name_code="SOX", industry_code="G4530",
        macro_changes=pd.Series(range(20), index=index, dtype=float),
        industry_returns=pd.Series(range(20), index=index, dtype=float),
        frequency_code="WEEKLY", direction_code=MacroDirection.UP,
        trend_strength=1.0, minimum_sample_count=104,
        minimum_abs_correlation=0.15, minimum_relationship_confidence=0.5,
        signal_weight=0.125,
    )
    assert not result.is_eligible
    assert result.contribution == 0.0


def test_constant_industry_returns_do_not_emit_nan_relationship():
    index = pd.date_range("2023-01-06", periods=120, freq="W-FRI")
    result = calculate_relationship(
        signal_name_code="SOX", industry_code="G4530",
        macro_changes=pd.Series(range(120), index=index, dtype=float),
        industry_returns=pd.Series(0.0, index=index), frequency_code="WEEKLY",
        direction_code=MacroDirection.UP, trend_strength=1.0,
        minimum_sample_count=104, minimum_abs_correlation=0.15,
        minimum_relationship_confidence=0.5, signal_weight=0.125,
    )
    assert result.correlation is None
    assert result.beta is None
    assert not result.is_eligible


def test_hallyu_contract_limits_relationship_to_eligible_industries():
    contract = next(signal for signal in MACRO_SIGNALS if signal.code == "GTREND_KPOP")
    relationship = RelationshipResult(
        signal_name_code="GTREND_KPOP",
        industry_code="G1010",
        frequency_code="MONTHLY",
        correlation=0.9,
        beta=1.0,
        sample_count=60,
        sign_stability=1.0,
        relationship_confidence=1.0,
        contribution=0.2,
        is_eligible=True,
    )
    blocked = _apply_contract_industry_limit(contract, "G1010", relationship)
    allowed = _apply_contract_industry_limit(contract, "G2550", relationship)

    assert _minimum_abs_correlation(contract, load_config()) == pytest.approx(0.25)
    assert not blocked.is_eligible
    assert blocked.contribution == 0.0
    assert allowed is relationship


def test_macro_run_uses_available_signals_and_skips_missing(monkeypatch):
    from apps.worker.analyzer import macro_job

    rows = [
        {
            **row,
            "signal_name_code": "SOX",
        }
        for row in _rows(np.linspace(100.0, 130.0, 180))
    ]
    inserted = []
    monkeypatch.setattr(
        macro_job,
        "fetch_macro_signals_as_of",
        lambda *args, **kwargs: rows,
    )
    monkeypatch.setattr(
        macro_job,
        "fetch_wics_industry_prices",
        lambda *args, **kwargs: [],
    )
    monkeypatch.setattr(
        macro_job,
        "insert_macro_results",
        lambda db, run_id, payload: inserted.extend(payload) or len(payload),
    )

    results = run_macro_analysis(object(), 1, date(2026, 5, 31), load_config())

    assert [result.signal_name_code for result in results] == ["SOX"]
    assert [row["signal_name_code"] for row in inserted] == ["SOX"]
