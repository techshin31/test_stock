"""성과 지표 계산 — CAGR, MDD, Sharpe, Sortino, Calmar + 월별 히트맵"""
from __future__ import annotations

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import seaborn as sns

_TRADING_DAYS = 252
_RISK_FREE_RATE = 0.03  # 연 3% (무위험이자율 근사)


def calc_metrics(
    time_returns: pd.Series,
    initial_cash: float,
    final_value: float,
) -> dict[str, float]:
    """일별 수익률 시리즈로 주요 성과 지표 계산.

    Args:
        time_returns: Backtrader TimeReturn 분석기 결과 (일별 수익률)
        initial_cash: 초기 자본금
        final_value:  최종 자산

    Returns:
        dict with cagr, mdd, sharpe, sortino, calmar, total_return
    """
    if time_returns.empty:
        return {"cagr": 0, "mdd": 0, "sharpe": 0, "sortino": 0, "calmar": 0, "total_return": 0}

    r = time_returns.dropna().astype(float)
    n_days = len(r)
    years  = n_days / _TRADING_DAYS

    total_return = (final_value - initial_cash) / initial_cash
    cagr = (1 + total_return) ** (1 / years) - 1 if years > 0 else 0.0

    # MDD
    cum = (1 + r).cumprod()
    roll_max = cum.cummax()
    drawdown = (cum - roll_max) / roll_max
    mdd = float(drawdown.min())

    # Sharpe
    excess = r - _RISK_FREE_RATE / _TRADING_DAYS
    sharpe = float(excess.mean() / r.std() * np.sqrt(_TRADING_DAYS)) if r.std() > 0 else 0.0

    # Sortino (하방 변동성 기준)
    downside = r[r < 0]
    sortino = (
        float(excess.mean() / downside.std() * np.sqrt(_TRADING_DAYS))
        if len(downside) > 0 and downside.std() > 0 else 0.0
    )

    # Calmar
    calmar = abs(cagr / mdd) if mdd != 0 else 0.0

    return {
        "total_return": total_return,
        "cagr":         cagr,
        "mdd":          mdd,
        "sharpe":       sharpe,
        "sortino":      sortino,
        "calmar":       calmar,
    }


def plot_equity_curve(
    time_returns: pd.Series,
    benchmark_returns: pd.Series | None = None,
    initial_cash: float = 100_000_000,
    ax: plt.Axes | None = None,
) -> plt.Axes:
    """전략 vs 벤치마크 자산 곡선 비교."""
    if ax is None:
        _, ax = plt.subplots(figsize=(12, 5))

    cum_strat = (1 + time_returns).cumprod() * initial_cash
    cum_strat.plot(ax=ax, label="탑다운 전략", linewidth=2, color="steelblue")

    if benchmark_returns is not None:
        bm = benchmark_returns.reindex(time_returns.index, method="ffill").fillna(0)
        cum_bm = (1 + bm).cumprod() * initial_cash
        cum_bm.plot(ax=ax, label="KOSPI 벤치마크", linewidth=1.5,
                    linestyle="--", color="gray", alpha=0.8)

    ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"{x:,.0f}"))
    ax.set_title("자산 곡선 (Equity Curve)", fontsize=14)
    ax.set_xlabel("")
    ax.set_ylabel("자산 (원)")
    ax.legend()
    ax.grid(True, alpha=0.3)
    return ax


def plot_monthly_heatmap(
    time_returns: pd.Series,
    ax: plt.Axes | None = None,
) -> plt.Axes:
    """월별 수익률 히트맵."""
    if ax is None:
        _, ax = plt.subplots(figsize=(14, 5))

    r = time_returns.copy()
    r.index = pd.to_datetime(r.index)

    monthly = r.resample("ME").apply(lambda x: (1 + x).prod() - 1)
    pivot = monthly.groupby([monthly.index.year, monthly.index.month]).first().unstack()
    pivot.columns = ["Jan","Feb","Mar","Apr","May","Jun",
                     "Jul","Aug","Sep","Oct","Nov","Dec"][:len(pivot.columns)]

    sns.heatmap(
        pivot * 100,
        annot=True,
        fmt=".1f",
        center=0,
        cmap="RdYlGn",
        linewidths=0.5,
        ax=ax,
        cbar_kws={"label": "월 수익률 (%)"},
    )
    ax.set_title("월별 수익률 히트맵 (%)", fontsize=14)
    ax.set_xlabel("")
    ax.set_ylabel("연도")
    return ax


def plot_drawdown(
    time_returns: pd.Series,
    ax: plt.Axes | None = None,
) -> plt.Axes:
    """낙폭(Drawdown) 곡선."""
    if ax is None:
        _, ax = plt.subplots(figsize=(12, 3))

    cum = (1 + time_returns).cumprod()
    roll_max = cum.cummax()
    dd = (cum - roll_max) / roll_max

    dd.plot(ax=ax, color="crimson", linewidth=1.5, alpha=0.8)
    ax.fill_between(dd.index, dd.values, 0, color="crimson", alpha=0.2)
    ax.yaxis.set_major_formatter(mticker.PercentFormatter(xmax=1.0))
    ax.set_title("낙폭 (Drawdown)", fontsize=14)
    ax.set_xlabel("")
    ax.grid(True, alpha=0.3)
    return ax
