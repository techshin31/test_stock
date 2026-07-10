"""Portfolio performance aggregation."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from core.analytics.drawdown import calc_mdd_duration
from core.analytics.metrics import calc_cagr, calc_calmar, calc_mdd
from core.backtest.result import BacktestResult
from core.strategy.base import AbstractStrategy


@dataclass
class PerformanceReport:
    start_date: pd.Timestamp
    end_date: pd.Timestamp
    initial_value: float
    final_value: float
    total_return: float
    cagr: float
    volatility: float
    sharpe: float
    sortino: float
    mdd: float
    mdd_duration: int
    mdd_duration_months: float
    calmar: float
    win_rate: float
    profit_factor: float
    alpha: float | None
    beta: float | None


def _safe_ratio(numerator: float, denominator: float) -> float:
    if denominator == 0 or np.isnan(denominator):
        return 0.0
    return float(numerator / denominator)


def _alpha_beta(
    returns: pd.Series,
    benchmark_returns: pd.Series | None,
    trading_days: int,
) -> tuple[float | None, float | None]:
    if benchmark_returns is None:
        return None, None

    aligned = pd.concat([returns.rename("strategy"), benchmark_returns.rename("benchmark")], axis=1).dropna()
    if len(aligned) < 2:
        return None, None

    benchmark_var = float(aligned["benchmark"].var())
    if benchmark_var == 0.0 or np.isnan(benchmark_var):
        return None, None

    beta = float(aligned["strategy"].cov(aligned["benchmark"]) / benchmark_var)
    alpha = float((aligned["strategy"] - beta * aligned["benchmark"]).mean() * trading_days)
    return alpha, beta


def calc_performance(
    result: BacktestResult,
    risk_free_rate: float = 0.03,
    trading_days: int = 252,
) -> PerformanceReport:
    """Calculate aggregate KPI values from a backtest result."""
    equity = result.equity_curve.dropna().astype(float)
    if equity.empty:
        raise ValueError("equity_curve is empty")

    returns = result.daily_returns.reindex(equity.index).fillna(0.0).astype(float)
    mean_return = float(returns.mean())
    std_return = float(returns.std())
    annual_return = mean_return * trading_days
    annual_vol = std_return * np.sqrt(trading_days)

    downside = returns[returns < 0.0]
    downside_vol = float(downside.std() * np.sqrt(trading_days)) if len(downside) > 1 else 0.0
    positive_sum = float(returns[returns > 0.0].sum())
    negative_sum = float(returns[returns < 0.0].sum())

    alpha, beta = _alpha_beta(returns, result.config.benchmark_returns, trading_days)
    mdd_duration = calc_mdd_duration(equity)

    return PerformanceReport(
        start_date=pd.Timestamp(equity.index[0]),
        end_date=pd.Timestamp(equity.index[-1]),
        initial_value=float(equity.iloc[0]),
        final_value=float(equity.iloc[-1]),
        total_return=float(equity.iloc[-1] / equity.iloc[0] - 1.0) if equity.iloc[0] else 0.0,
        cagr=calc_cagr(equity, trading_days),
        volatility=annual_vol,
        sharpe=_safe_ratio(annual_return - risk_free_rate, annual_vol),
        sortino=_safe_ratio(annual_return - risk_free_rate, downside_vol),
        mdd=calc_mdd(equity),
        mdd_duration=mdd_duration,
        mdd_duration_months=float(mdd_duration / 21.0),
        calmar=calc_calmar(equity, trading_days),
        win_rate=float((returns > 0.0).sum() / len(returns)) if len(returns) else 0.0,
        profit_factor=_safe_ratio(positive_sum, abs(negative_sum)),
        alpha=alpha,
        beta=beta,
    )


def _status_higher(value: float | None, target: float, warning: float) -> str:
    if value is None:
        return "N/A"
    if value >= target:
        return "PASS"
    if value >= warning:
        return "WARN"
    return "FAIL"


def _status_lower(value: float | None, target: float, warning: float) -> str:
    if value is None:
        return "N/A"
    if value <= target:
        return "PASS"
    if value <= warning:
        return "WARN"
    return "FAIL"


def _status_mdd(value: float, target: float, warning: float) -> str:
    if value >= target:
        return "PASS"
    if value >= warning:
        return "WARN"
    return "FAIL"


def check_kpi_targets(
    report: PerformanceReport,
    strategy: AbstractStrategy,
) -> dict[str, str]:
    """Compare KPI values with strategy target and warning thresholds."""
    is_risk_neutral = strategy.INVESTMENT_TYPE.name == "RISK_NEUTRAL"
    target_sortino = 0.8 if is_risk_neutral else 1.0
    warning_sortino = 0.5 if is_risk_neutral else 0.6
    target_alpha = 0.02 if is_risk_neutral else 0.05
    warning_alpha = 0.0 if is_risk_neutral else 0.02
    target_beta = 0.8 if is_risk_neutral else 1.3
    warning_beta = 1.0 if is_risk_neutral else 1.5
    target_calmar = 0.35 if is_risk_neutral else 0.45
    warning_calmar = 0.20 if is_risk_neutral else 0.25

    return {
        "CAGR": _status_higher(report.cagr, strategy.TARGET_CAGR, strategy.WARNING_CAGR),
        "MDD": _status_mdd(report.mdd, strategy.TARGET_MDD, strategy.WARNING_MDD),
        "MDD Duration": _status_lower(
            report.mdd_duration_months,
            strategy.TARGET_MDD_DURATION,
            strategy.WARNING_MDD_DURATION,
        ),
        "Calmar": _status_higher(report.calmar, target_calmar, warning_calmar),
        "Sortino": _status_higher(report.sortino, target_sortino, warning_sortino),
        "Alpha": _status_higher(report.alpha, target_alpha, warning_alpha),
        "Beta": _status_lower(report.beta, target_beta, warning_beta),
    }
