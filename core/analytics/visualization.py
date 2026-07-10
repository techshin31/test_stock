"""Matplotlib visualizations for backtest results."""
from __future__ import annotations

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker

from core.analytics.attribution import (
    add_trade_reason_labels,
    format_ticker_label,
    summarize_regime_exposure_by_ticker,
    summarize_ticker_performance,
    summarize_ticker_yearly_performance,
    summarize_trade_costs_by_year,
    summarize_trade_reasons,
)
from core.analytics.drawdown import calc_drawdown_series
from core.analytics.regime import (
    REGIME_COLORS,
    calc_kospi_regime_from_close,
    regime_legend,
    shade_regime_background,
)
from core.backtest.result import BacktestResult


_REGIME_COLORS = REGIME_COLORS


def _rotation_lines(ax: plt.Axes, result: BacktestResult) -> None:
    for plan in result.config.rotation_plans:
        ax.axvline(pd.Timestamp(plan.review_date), color="#666666", linestyle=":", linewidth=1)


def plot_equity_curve(result: BacktestResult) -> plt.Figure:
    """Plot strategy equity against an optional benchmark."""
    fig, ax = plt.subplots(figsize=(10, 5))
    result.equity_curve.plot(ax=ax, color="#1f77b4", linewidth=2, label="Strategy")

    if result.config.benchmark_returns is not None:
        benchmark = (1.0 + result.config.benchmark_returns.reindex(result.equity_curve.index).fillna(0.0)).cumprod()
        benchmark = benchmark * float(result.config.initial_capital)
        benchmark.plot(ax=ax, color="#777777", linestyle="--", label=result.config.strategy.BENCHMARK)

    _rotation_lines(ax, result)
    ax.set_title("Equity Curve")
    ax.set_ylabel("Portfolio Value")
    ax.legend(loc="best")
    ax.grid(True, alpha=0.25)
    fig.tight_layout()
    return fig


def plot_drawdown(result: BacktestResult) -> plt.Figure:
    """Plot the underwater curve and mark the maximum drawdown."""
    dd = calc_drawdown_series(result.equity_curve)
    fig, ax = plt.subplots(figsize=(10, 4))
    ax.fill_between(dd.index, dd.values, 0.0, color="#d62728", alpha=0.35)
    ax.plot(dd.index, dd.values, color="#a50f15", linewidth=1)
    if not dd.empty:
        trough = dd.idxmin()
        ax.scatter([trough], [dd.loc[trough]], color="#7f0000", zorder=3, label=f"MDD {dd.min():.1%}")
    ax.set_title("Drawdown")
    ax.set_ylabel("Drawdown")
    ax.legend(loc="lower left")
    ax.grid(True, alpha=0.25)
    fig.tight_layout()
    return fig


def plot_monthly_returns(result: BacktestResult) -> plt.Figure:
    """Plot a monthly returns heatmap."""
    monthly = (1.0 + result.daily_returns).resample("M").prod() - 1.0
    data = monthly.to_frame("return")
    data["year"] = data.index.year
    data["month"] = data.index.month
    pivot = data.pivot(index="year", columns="month", values="return")

    fig, ax = plt.subplots(figsize=(10, max(3, 0.35 * max(len(pivot), 1) + 2)))
    if pivot.empty:
        ax.text(0.5, 0.5, "No monthly returns", ha="center", va="center")
        ax.axis("off")
    else:
        vmax = max(abs(float(np.nanmin(pivot.values))), abs(float(np.nanmax(pivot.values))), 0.01)
        im = ax.imshow(pivot.values, cmap="RdYlGn", vmin=-vmax, vmax=vmax, aspect="auto")
        ax.set_xticks(range(len(pivot.columns)), [str(col) for col in pivot.columns])
        ax.set_yticks(range(len(pivot.index)), [str(idx) for idx in pivot.index])
        for row in range(pivot.shape[0]):
            for col in range(pivot.shape[1]):
                value = pivot.iloc[row, col]
                if pd.notna(value):
                    ax.text(col, row, f"{value:.1%}", ha="center", va="center", fontsize=8)
        fig.colorbar(im, ax=ax, format=lambda x, _: f"{x:.0%}")
    ax.set_title("Monthly Returns")
    fig.tight_layout()
    return fig


def plot_regime_timeline(result: BacktestResult) -> plt.Figure:
    """Plot equity with regime background bands from the first available ticker."""
    fig, ax = plt.subplots(figsize=(10, 5))
    result.equity_curve.plot(ax=ax, color="#1f77b4", linewidth=2)
    if result.regime_dict:
        regime_df = next(iter(result.regime_dict.values())).reindex(result.equity_curve.index).ffill()
        shade_regime_background(ax, regime_df, alpha=0.38)
        ax.legend(handles=regime_legend(regime_df), loc="upper left", fontsize=8)
    _rotation_lines(ax, result)
    ax.set_title("Regime Timeline")
    ax.set_ylabel("Portfolio Value")
    ax.grid(True, alpha=0.25)
    fig.tight_layout()
    return fig


def plot_ticker_contribution_bar(
    result: BacktestResult,
    get_ticker_name=None,
    include_defensive: bool = False,
) -> plt.Figure:
    """Plot total net performance contribution by ticker after costs."""
    summary = summarize_ticker_performance(result, include_defensive=include_defensive)
    fig, ax = plt.subplots(figsize=(13, max(4, 0.48 * max(len(summary), 1) + 2)))
    if summary.empty:
        ax.text(0.5, 0.5, "표시할 종목별 성과 기여도가 없습니다.", ha="center", va="center")
        ax.axis("off")
        fig.tight_layout()
        return fig

    plot_data = summary.sort_values("net_contribution", ascending=True).copy()
    colors = np.where(plot_data["net_contribution"] >= 0, "#2ca02c", "#d62728")
    labels = [format_ticker_label(ticker, get_ticker_name) for ticker in plot_data["ticker"]]
    ax.barh(labels, plot_data["net_contribution"], color=colors, alpha=0.85)
    ax.axvline(0, color="#333333", linewidth=0.8)
    ax.xaxis.set_major_formatter(mticker.PercentFormatter(xmax=1))
    ax.set_title("종목별 총 순성과 기여도 (비용 차감 후)", fontsize=13)
    ax.set_xlabel("포트폴리오 누적 수익률 기여도")
    ax.grid(True, axis="x", alpha=0.25)

    for y, value in enumerate(plot_data["net_contribution"]):
        ha = "left" if value >= 0 else "right"
        offset = 0.0015 if value >= 0 else -0.0015
        ax.text(value + offset, y, f"{value:+.2%}", va="center", ha=ha, fontsize=8)

    fig.tight_layout()
    return fig


def plot_ticker_yearly_contribution_heatmap(
    result: BacktestResult,
    get_ticker_name=None,
    include_defensive: bool = False,
) -> plt.Figure:
    """Plot ticker-by-year net contribution as a heatmap."""
    summary = summarize_ticker_yearly_performance(result, include_defensive=include_defensive)
    fig, ax = plt.subplots(figsize=(13, 6))
    if summary.empty:
        ax.text(0.5, 0.5, "표시할 종목별 연도별 성과 기여도가 없습니다.", ha="center", va="center")
        ax.axis("off")
        fig.tight_layout()
        return fig

    pivot = (
        summary
        .pivot_table(index="ticker", columns="year", values="net_contribution", aggfunc="sum")
        .fillna(0.0)
    )
    pivot = pivot.loc[pivot.abs().sum(axis=1).sort_values(ascending=False).index]
    values = pivot.values
    vmax = max(abs(float(np.nanmin(values))), abs(float(np.nanmax(values))), 0.01)
    im = ax.imshow(values, cmap="RdYlGn", vmin=-vmax, vmax=vmax, aspect="auto")
    ax.set_xticks(range(len(pivot.columns)), [str(col) for col in pivot.columns])
    ax.set_yticks(
        range(len(pivot.index)),
        [format_ticker_label(ticker, get_ticker_name, multiline=False) for ticker in pivot.index],
    )
    ax.set_title("종목별 연도별 순성과 기여도 (비용 차감 후)", fontsize=13)
    for row in range(pivot.shape[0]):
        for col in range(pivot.shape[1]):
            value = pivot.iloc[row, col]
            if abs(float(value)) >= 0.0001:
                ax.text(col, row, f"{value:+.1%}", ha="center", va="center", fontsize=8)
    fig.colorbar(im, ax=ax, format=lambda x, _: f"{x:.0%}", label="수익률 기여도")
    fig.tight_layout()
    return fig


def plot_trade_costs_by_year(result: BacktestResult) -> plt.Figure:
    """Plot yearly transaction costs with trade frequency."""
    summary = summarize_trade_costs_by_year(result)
    yearly = summary[summary["year"] != "TOTAL"].copy() if not summary.empty else pd.DataFrame()
    fig, ax_cost = plt.subplots(figsize=(13, 5))
    if yearly.empty:
        ax_cost.text(0.5, 0.5, "표시할 거래 비용 요약이 없습니다.", ha="center", va="center")
        ax_cost.axis("off")
        fig.tight_layout()
        return fig

    x = np.arange(len(yearly))
    cost_manwon = yearly["total_cost_amount"].astype(float) / 10_000
    bars = ax_cost.bar(x, cost_manwon, color="#8c564b", alpha=0.75, label="거래 비용")
    ax_cost.set_ylabel("거래 비용 (만원)")
    ax_cost.set_xticks(x, yearly["year"].astype(str).tolist())
    ax_cost.grid(True, axis="y", alpha=0.25)

    for bar, value in zip(bars, cost_manwon):
        ax_cost.text(
            bar.get_x() + bar.get_width() / 2,
            bar.get_height(),
            f"{value:,.1f}",
            ha="center",
            va="bottom",
            fontsize=8,
        )

    ax_count = ax_cost.twinx()
    ax_count.plot(x, yearly["trade_count"], color="#1f77b4", marker="o", linewidth=2, label="총 거래 건수")
    ax_count.plot(x, yearly["rebalance_days"], color="#ff7f0e", marker="s", linewidth=1.6, label="리밸런싱 발생일")
    ax_count.set_ylabel("거래 건수 / 리밸런싱 일수")

    handles1, labels1 = ax_cost.get_legend_handles_labels()
    handles2, labels2 = ax_count.get_legend_handles_labels()
    ax_count.legend(handles1 + handles2, labels1 + labels2, loc="upper left", fontsize=9)
    ax_cost.set_title("연도별 거래 비용과 거래 빈도", fontsize=13)
    fig.tight_layout()
    return fig


def plot_trade_reason_burden(result: BacktestResult) -> plt.Figure:
    """Plot trade count and cost by Korean/code trade reason labels."""
    summary = add_trade_reason_labels(summarize_trade_reasons(result))
    fig, axes = plt.subplots(1, 2, figsize=(13, max(4, 0.38 * max(len(summary), 1) + 2)), sharey=True)
    if summary.empty:
        axes[0].text(0.5, 0.5, "표시할 매매 사유 요약이 없습니다.", ha="center", va="center")
        for ax in axes:
            ax.axis("off")
        fig.tight_layout()
        return fig

    plot_data = summary.sort_values(["trade_count", "total_cost_amount"], ascending=True)
    y_labels = plot_data["reason_side_label"].tolist()
    axes[0].barh(y_labels, plot_data["trade_count"], color="#1f77b4", alpha=0.82)
    axes[0].set_title("매매 사유별 거래 건수", fontsize=11)
    axes[0].set_xlabel("거래 건수")
    axes[0].grid(True, axis="x", alpha=0.25)

    axes[1].barh(y_labels, plot_data["total_cost_amount"] / 10_000, color="#8c564b", alpha=0.78)
    axes[1].set_title("매매 사유별 거래 비용", fontsize=11)
    axes[1].set_xlabel("거래 비용 (만원)")
    axes[1].grid(True, axis="x", alpha=0.25)

    fig.suptitle("매수/매도 사유별 거래 부담", fontsize=13)
    fig.tight_layout()
    return fig


def plot_kospi_regime_portfolio(
    result: BacktestResult,
    kospi_index: pd.Series,
    initial_capital: float | None = None,
    show_rotation_lines: bool = True,
) -> plt.Figure:
    """Plot KOSPI close-only regime background with strategy and KOSPI equity curves."""
    bt_index = result.equity_curve.index
    capital = float(initial_capital or result.config.initial_capital)
    kospi_close = kospi_index.reindex(bt_index, method="ffill").dropna()
    kospi_regime = calc_kospi_regime_from_close(kospi_index).reindex(bt_index).ffill()
    kospi_equity = kospi_close.div(kospi_close.iloc[0]).mul(capital).reindex(bt_index).ffill()

    fig, axes = plt.subplots(2, 1, figsize=(13, 7), sharex=True, gridspec_kw={"height_ratios": [2, 1]})
    ax_strategy, ax_kospi = axes
    shade_regime_background(ax_strategy, kospi_regime, alpha=0.42)
    result.equity_curve.plot(ax=ax_strategy, color="#1f77b4", linewidth=2.0, label="위험중립형 포트폴리오")
    if show_rotation_lines:
        _rotation_lines(ax_strategy, result)
    ax_strategy.set_title("KOSPI 기준 국면 배경 + 위험중립형 포트폴리오 자산 곡선", fontsize=13)
    ax_strategy.set_ylabel("포트폴리오 가치")
    ax_strategy.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"{x / 1e4:,.0f}만"))
    ax_strategy.grid(True, alpha=0.22)
    ax_strategy.legend(handles=[*regime_legend(kospi_regime), *ax_strategy.get_legend_handles_labels()[0]], loc="upper left", fontsize=8)

    shade_regime_background(ax_kospi, kospi_regime, alpha=0.42)
    kospi_equity.plot(ax=ax_kospi, color="#555555", linewidth=1.6, label="KOSPI B&H")
    ax_kospi.set_title("KOSPI B&H 비교 곡선 (초기 투자금 환산)", fontsize=11)
    ax_kospi.set_ylabel("KOSPI 환산 자산")
    ax_kospi.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"{x / 1e4:,.0f}만"))
    ax_kospi.grid(True, alpha=0.22)
    ax_kospi.legend(loc="upper left", fontsize=8)

    fig.tight_layout()
    return fig


def plot_regime_exposure_by_ticker(
    result: BacktestResult,
    get_ticker_name=None,
    held_only: bool = True,
    include_defensive: bool = False,
) -> plt.Figure:
    """Plot stacked regime exposure ratio by ticker."""
    summary = summarize_regime_exposure_by_ticker(
        result,
        held_only=held_only,
        include_defensive=include_defensive,
    )
    fig, ax = plt.subplots(figsize=(13, 5))
    if summary.empty:
        ax.text(0.5, 0.5, "표시할 국면 노출이 없습니다.", ha="center", va="center")
        ax.axis("off")
        fig.tight_layout()
        return fig

    pivot = summary.pivot(index="ticker", columns="regime", values="ratio").fillna(0.0)
    pivot = pivot[[col for col in _REGIME_COLORS if col in pivot.columns]]
    labels = [format_ticker_label(ticker, get_ticker_name, multiline=False) for ticker in pivot.index]
    pivot.index = labels
    pivot.plot(kind="bar", stacked=True, color=[_REGIME_COLORS[col] for col in pivot.columns], ax=ax)
    ax.yaxis.set_major_formatter(mticker.PercentFormatter(xmax=1))
    basis = "보유 기간 기준" if held_only else "전체 기간 기준"
    ax.set_title(f"종목별 {basis} 국면 노출 비율", fontsize=12)
    ax.set_xlabel("종목")
    ax.set_ylabel("노출 비율")
    ax.legend(handles=regime_legend(pd.Series(pivot.columns)), title="국면", loc="upper right", fontsize=8)
    ax.grid(True, axis="y", alpha=0.25)
    fig.tight_layout()
    return fig


def plot_ticker_regime_invested_values(
    result: BacktestResult,
    get_ticker_name=None,
    tickers: list[str] | None = None,
) -> plt.Figure:
    """Plot each ticker's own regime background with invested capital."""
    stock_cols = tickers or [ticker for ticker in result.signals.columns if ticker in result.values.columns]
    stock_cols = [ticker for ticker in stock_cols if ticker in result.regime_dict and ticker in result.values]
    fig, axes = plt.subplots(len(stock_cols) or 1, 1, figsize=(13, max(3.2 * max(len(stock_cols), 1), 4)), sharex=True)
    axes_list = [axes] if len(stock_cols) <= 1 else list(axes)
    if not stock_cols:
        axes_list[0].text(0.5, 0.5, "표시할 종목별 투자금 곡선이 없습니다.", ha="center", va="center")
        axes_list[0].axis("off")
        fig.tight_layout()
        return fig

    trades = result.trade_ledger.copy() if result.trade_ledger is not None else pd.DataFrame()
    if not trades.empty and "date" in trades:
        trades["date"] = pd.to_datetime(trades["date"])

    for ax, ticker in zip(axes_list, stock_cols):
        ticker_regime = result.regime_dict[ticker]["REGIME"].reindex(result.equity_curve.index).ffill()
        ticker_value = result.values[ticker].reindex(result.equity_curve.index).fillna(0.0)
        ticker_weight = result.weights[ticker].reindex(result.equity_curve.index).fillna(0.0)

        shade_regime_background(ax, ticker_regime, alpha=0.38)
        ticker_value.plot(ax=ax, color="#1f77b4", linewidth=1.6, label="투자금")

        active_days = int((ticker_weight > 0.001).sum())
        max_weight = float(ticker_weight.max())
        max_value = float(ticker_value.max())
        label = format_ticker_label(ticker, get_ticker_name, multiline=False)
        ax.set_title(
            f"{label} | 보유일 {active_days}일 | 최대비중 {max_weight:.1%} | 최대투자금 {max_value / 1e4:,.0f}만원",
            fontsize=10,
            loc="left",
        )
        ax.set_ylabel("투자금")
        ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"{x / 1e4:.0f}만"))
        ax.grid(True, alpha=0.22)

        if not trades.empty:
            ticker_trades = trades[(trades["ticker"] == ticker) & (trades["date"].isin(ticker_value.index))]
            buys = ticker_trades[ticker_trades["side"] == "BUY"]
            sells = ticker_trades[ticker_trades["side"] == "SELL"]
            if not buys.empty:
                ax.plot(
                    pd.to_datetime(buys["date"]),
                    ticker_value.reindex(pd.to_datetime(buys["date"])),
                    linestyle="None",
                    marker="^",
                    color="#2ca02c",
                    markersize=5,
                    label="매수",
                )
            if not sells.empty:
                ax.plot(
                    pd.to_datetime(sells["date"]),
                    ticker_value.reindex(pd.to_datetime(sells["date"])),
                    linestyle="None",
                    marker="v",
                    color="#d62728",
                    markersize=5,
                    label="매도",
                )

        handles, labels = ax.get_legend_handles_labels()
        unique = dict(zip(labels, handles))
        ax.legend(unique.values(), unique.keys(), loc="upper left", fontsize=8)

    first_handles, first_labels = axes_list[0].get_legend_handles_labels()
    unique_first = dict(zip(first_labels, first_handles))
    axes_list[0].legend(
        handles=[*regime_legend(result.regime_dict[stock_cols[0]]["REGIME"]), *unique_first.values()],
        loc="upper right",
        fontsize=8,
    )
    fig.suptitle("투자 종목별 국면 배경과 실제 투자금 곡선", fontsize=14, y=0.995)
    fig.tight_layout()
    return fig


def plot_walk_forward_windows(result: BacktestResult) -> plt.Figure:
    """Plot IS/OOS walk-forward windows by ticker."""
    rows = [(ticker, window) for ticker, windows in result.wf_windows.items() for window in windows]
    fig, ax = plt.subplots(figsize=(10, max(3, 0.35 * max(len(rows), 1) + 1)))
    if not rows:
        ax.text(0.5, 0.5, "No walk-forward windows", ha="center", va="center")
        ax.axis("off")
        fig.tight_layout()
        return fig

    y_labels = []
    for y, (ticker, window) in enumerate(rows):
        y_labels.append(ticker)
        ax.barh(y, window["is_end"] - window["is_start"], left=window["is_start"], color="#9ecae1", label="IS" if y == 0 else None)
        ax.barh(y, window["oos_end"] - window["oos_start"], left=window["oos_start"], color="#fdae6b", label="OOS" if y == 0 else None)
        params = window.get("best_params") or {}
        label = f"{window.get('is_score', 0.0):.2f}"
        if params:
            label += f" / {params.get('adx_threshold')}/{params.get('adx_sideways')}"
        ax.text(window["oos_start"], y, label, va="center", fontsize=8)

    ax.set_yticks(range(len(y_labels)), y_labels)
    ax.set_title("Walk-Forward Windows")
    ax.legend(loc="best")
    ax.grid(True, axis="x", alpha=0.25)
    fig.tight_layout()
    return fig


def plot_universe_timeline(result: BacktestResult, get_ticker_name=None) -> plt.Figure:
    """Plot universe snapshots as a simple timeline table."""
    snapshots = result.universe_snapshots
    fig, ax = plt.subplots(figsize=(13, max(3.5, 0.8 * max(len(snapshots), 1) + 1)))
    if not snapshots:
        ax.text(0.5, 0.5, "No universe snapshots", ha="center", va="center")
        ax.axis("off")
        fig.tight_layout()
        return fig

    def snapshot_label(tickers: list[str]) -> str:
        labels = [format_ticker_label(ticker, get_ticker_name, multiline=False) for ticker in tickers]
        rows = [", ".join(labels[pos:pos + 3]) for pos in range(0, len(labels), 3)]
        return "\n".join(rows)

    for y, (dt, tickers) in enumerate(snapshots):
        ax.scatter(pd.Timestamp(dt), y, color="#1f77b4")
        ax.text(pd.Timestamp(dt), y, "  " + snapshot_label(tickers), va="center", fontsize=8)
    ax.set_yticks(range(len(snapshots)), [str(dt) for dt, _ in snapshots])
    ax.set_title("Universe Timeline")
    ax.grid(True, axis="x", alpha=0.25)
    fig.tight_layout()
    return fig
