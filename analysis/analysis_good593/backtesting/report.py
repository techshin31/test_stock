"""성과 비교 리포트 — 전략 vs 벤치마크, 리밸런싱 이력, 국면 시각화"""
from __future__ import annotations

import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches

from .runner import BacktestResult
from .metrics import (
    calc_metrics,
    plot_equity_curve,
    plot_monthly_heatmap,
    plot_drawdown,
)
from .strategy.macro_signal import Regime

_REGIME_COLORS = {
    Regime.A: "#4CAF50",   # 초록 — Risk-On 저금리
    Regime.B: "#FF9800",   # 주황 — Risk-On 고금리
    Regime.C: "#2196F3",   # 파랑 — Risk-Off 저금리
    Regime.D: "#F44336",   # 빨강 — Risk-Off 고금리
}

_REGIME_LABELS = {
    Regime.A: "A: Risk-On + 저금리",
    Regime.B: "B: Risk-On + 고금리",
    Regime.C: "C: Risk-Off + 저금리",
    Regime.D: "D: Risk-Off + 고금리",
}


def print_summary_table(result: BacktestResult) -> None:
    """전략 vs 벤치마크 성과 요약 테이블 출력."""
    strat_m = calc_metrics(result.time_returns, result.initial_cash, result.final_value)

    # 벤치마크 metrics (KOSPI 근사)
    bm = result.benchmark_returns.reindex(result.time_returns.index, method="ffill").fillna(0)
    bm_final = result.initial_cash * (1 + bm).cumprod().iloc[-1]
    bm_m = calc_metrics(bm, result.initial_cash, bm_final)

    rows = [
        ("총 수익률",  f"{strat_m['total_return']:.2%}", f"{bm_m['total_return']:.2%}"),
        ("CAGR",       f"{strat_m['cagr']:.2%}",         f"{bm_m['cagr']:.2%}"),
        ("MDD",        f"{strat_m['mdd']:.2%}",           f"{bm_m['mdd']:.2%}"),
        ("Sharpe",     f"{strat_m['sharpe']:.2f}",        f"{bm_m['sharpe']:.2f}"),
        ("Sortino",    f"{strat_m['sortino']:.2f}",       f"{bm_m['sortino']:.2f}"),
        ("Calmar",     f"{strat_m['calmar']:.2f}",        f"{bm_m['calmar']:.2f}"),
    ]

    col_w = [14, 16, 16]
    header = f"{'지표':<{col_w[0]}} {'탑다운 전략':>{col_w[1]}} {'KOSPI 벤치마크':>{col_w[2]}}"
    sep = "-" * sum(col_w)
    print(sep)
    print(header)
    print(sep)
    for label, strat_val, bm_val in rows:
        print(f"{label:<{col_w[0]}} {strat_val:>{col_w[1]}} {bm_val:>{col_w[2]}}")
    print(sep)


def plot_full_report(
    result: BacktestResult,
    macro_signal=None,
    figsize: tuple = (14, 16),
) -> plt.Figure:
    """전체 성과 대시보드 (4개 서브플롯)."""
    fig, axes = plt.subplots(4, 1, figsize=figsize)
    fig.suptitle("탑다운 백테스팅 성과 리포트", fontsize=16, fontweight="bold", y=0.98)

    # 1. 자산 곡선
    plot_equity_curve(
        result.time_returns,
        result.benchmark_returns,
        result.initial_cash,
        ax=axes[0],
    )

    # 2. 낙폭
    plot_drawdown(result.time_returns, ax=axes[1])

    # 3. 월별 히트맵
    plot_monthly_heatmap(result.time_returns, ax=axes[2])

    # 4. 국면 분류 (macro_signal이 있을 때)
    if macro_signal is not None:
        _plot_regime_timeline(macro_signal.to_series(), axes[3])
    else:
        axes[3].set_visible(False)

    plt.tight_layout(rect=[0, 0, 1, 0.97])
    return fig


def plot_rebalance_history(result: BacktestResult) -> plt.Figure:
    """리밸런싱 이력 — 날짜별 편입 종목 수 및 섹터 구성."""
    schedule = result.rebalance_schedule
    if not schedule:
        print("리밸런싱 이력 없음")
        return None

    dates = sorted(schedule.keys())
    n_stocks = [len(schedule[d]) for d in dates]

    fig, ax = plt.subplots(figsize=(12, 4))
    ax.bar(range(len(dates)), n_stocks, color="steelblue", alpha=0.8)
    ax.set_xticks(range(len(dates)))
    ax.set_xticklabels([str(d) for d in dates], rotation=45, ha="right", fontsize=9)
    ax.set_title("리밸런싱 이력 — 편입 종목 수", fontsize=14)
    ax.set_ylabel("종목 수")
    ax.grid(True, axis="y", alpha=0.3)
    plt.tight_layout()
    return fig


def _plot_regime_timeline(regime_series: pd.Series, ax: plt.Axes) -> None:
    """국면 타임라인 막대 차트."""
    for regime, color in _REGIME_COLORS.items():
        mask = regime_series == regime
        if not mask.any():
            continue
        dates = regime_series.index[mask]
        ax.bar(dates, [1] * len(dates), color=color, width=1.5, alpha=0.8)

    patches = [
        mpatches.Patch(color=c, label=_REGIME_LABELS[r])
        for r, c in _REGIME_COLORS.items()
    ]
    ax.legend(handles=patches, loc="upper right", fontsize=8)
    ax.set_title("매크로 국면 타임라인", fontsize=14)
    ax.set_yticks([])
    ax.grid(False)
