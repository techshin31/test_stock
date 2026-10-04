from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from core.analytics.attribution import calc_equity_stats
from core.analytics.metrics import calc_cagr, calc_calmar
from core.analytics.performance import calc_performance


def test_cagr_uses_252_intervals_for_253_observations():
    curve = pd.Series(np.linspace(100.0, 110.0, 253))
    assert calc_cagr(curve) == pytest.approx(0.10)


def test_cagr_counts_internal_missing_sessions_but_trims_missing_endpoints():
    curve = pd.Series([None, 100.0, None, 110.0, None])
    assert calc_cagr(curve, trading_days_per_year=2) == pytest.approx(0.10)


@pytest.mark.parametrize('curve', [[], [None], [100.0], [0.0, 110.0]])
def test_cagr_handles_insufficient_or_zero_initial_equity(curve):
    assert calc_cagr(pd.Series(curve, dtype=float)) == 0.0


def test_cagr_rejects_invalid_annualization_period():
    with pytest.raises(ValueError, match='must be positive'):
        calc_cagr(pd.Series([100.0, 110.0]), 0)


def test_calmar_and_report_aggregations_preserve_elapsed_missing_sessions():
    curve = pd.Series([100.0, 90.0, None, 110.0], index=pd.bdate_range('2026-01-01', periods=4))
    # Three elapsed return intervals; one missing observation is not a shorter year.
    expected_cagr = 0.10
    expected_calmar = 1.0
    assert calc_cagr(curve, 3) == pytest.approx(expected_cagr)
    assert calc_calmar(curve, 3) == pytest.approx(expected_calmar)
    stats = calc_equity_stats(curve, trading_days=3)
    assert stats['cagr'] == pytest.approx(expected_cagr)
    assert stats['calmar'] == pytest.approx(expected_calmar)
    result = SimpleNamespace(
        equity_curve=curve,
        daily_returns=curve.pct_change(fill_method=None),
        config=SimpleNamespace(benchmark_returns=None),
    )
    report = calc_performance(result, trading_days=3)
    assert report.cagr == pytest.approx(expected_cagr)
    assert report.calmar == pytest.approx(expected_calmar)
    assert report.total_return == pytest.approx(0.10)
