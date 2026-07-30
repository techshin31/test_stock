from apps.backtester import fa_model_evaluation
from apps.worker.fa_contract import (
    PAPER_TRADING_MODEL_VERSION,
    REAL_TRADING_MODEL_VERSION,
)


def _research_result(*, sharpe: float, drawdown: float) -> dict:
    metrics = {
        "months": 12,
        "total_return": 0.10,
        "cagr": 0.10,
        "annual_volatility": 0.15,
        "sharpe_zero_rf": sharpe,
        "max_drawdown": drawdown,
        "average_monthly_turnover": 0.10,
        "total_cost_ratio": 0.01,
    }
    return {
        "metadata": {"model_version": "unused"},
        "summary": {"equal": metrics, "fa_direct": metrics, "fa_excess": metrics},
    }


def test_evaluation_blocks_manual_review_when_drawdown_is_worse(monkeypatch):
    baseline = _research_result(sharpe=0.50, drawdown=-0.10)
    candidate = _research_result(sharpe=0.60, drawdown=-0.11)

    def fake_run_research(_db, *, model_version):
        return (
            baseline if model_version == "baseline" else candidate,
            None,
        )

    monkeypatch.setattr(fa_model_evaluation, "run_research", fake_run_research)

    result = fa_model_evaluation.run_model_evaluation(
        object(), baseline_model_version="baseline", candidate_model_version="candidate"
    )

    assert result["promotion_gate"]["ready_for_manual_review"] is False
    assert result["promotion_gate"]["order_permission"] == "DENIED_BY_DESIGN"
    assert result["promotion_gate"]["blockers"] == ["drawdown_not_worse"]


def test_evaluation_defaults_compare_established_and_paper_models(monkeypatch):
    observed_versions = []

    def fake_run_research(_db, *, model_version):
        observed_versions.append(model_version)
        return _research_result(sharpe=0.5, drawdown=-0.1), None

    monkeypatch.setattr(fa_model_evaluation, "run_research", fake_run_research)

    fa_model_evaluation.run_model_evaluation(object())

    assert observed_versions == [
        REAL_TRADING_MODEL_VERSION,
        PAPER_TRADING_MODEL_VERSION,
    ]
