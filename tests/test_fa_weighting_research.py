import pandas as pd
import pytest

from apps.backtester.fa_weighting_research import EXPOSURE, _weights


def test_fa_direct_weights_follow_scores_and_sum_to_exposure():
    frame = pd.DataFrame({"fa_score": [60.0, 90.0]}, index=["A", "B"])

    weights = _weights(frame, "fa_direct")

    assert weights.sum() == pytest.approx(EXPOSURE)
    assert weights["B"] / weights["A"] == pytest.approx(1.5)


def test_fa_excess_uses_score_above_minimum():
    frame = pd.DataFrame({"fa_score": [60.0, 70.0]}, index=["A", "B"])

    weights = _weights(frame, "fa_excess")

    assert weights.sum() == pytest.approx(EXPOSURE)
    assert weights["B"] / weights["A"] == pytest.approx(2.0)


def test_equal_weights_ignore_fa_score():
    frame = pd.DataFrame({"fa_score": [51.0, 99.0]}, index=["A", "B"])

    weights = _weights(frame, "equal")

    assert weights["A"] == pytest.approx(weights["B"])
