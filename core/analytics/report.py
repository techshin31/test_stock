"""Text and figure reporting helpers."""
from __future__ import annotations

from dataclasses import asdict

import matplotlib.pyplot as plt
import pandas as pd

from core.analytics.attribution import (
    summarize_regime_exposure_by_ticker,
    summarize_ticker_performance,
    summarize_trade_costs_by_year,
    summarize_trade_reasons,
)
from core.analytics.drawdown import calc_drawdown_periods
from core.analytics.interpretation import (
    interpret_compare_assets,
    interpret_kpi,
    interpret_regime_exposure,
    interpret_ticker_performance,
    interpret_trade_costs,
)
from core.analytics.performance import PerformanceReport, check_kpi_targets
from core.analytics.visualization import (
    plot_drawdown,
    plot_equity_curve,
    plot_kospi_regime_portfolio,
    plot_monthly_returns,
    plot_regime_exposure_by_ticker,
    plot_regime_timeline,
    plot_ticker_contribution_bar,
    plot_ticker_regime_invested_values,
    plot_ticker_yearly_contribution_heatmap,
    plot_trade_costs_by_year,
    plot_trade_reason_burden,
    plot_universe_timeline,
    plot_walk_forward_windows,
)
from core.backtest.result import BacktestResult


def generate_report(
    result: BacktestResult,
    report: PerformanceReport,
) -> list[plt.Figure]:
    """Generate the standard chart set for a backtest result."""
    return [
        plot_equity_curve(result),
        plot_drawdown(result),
        plot_monthly_returns(result),
        plot_regime_timeline(result),
        plot_walk_forward_windows(result),
        plot_universe_timeline(result),
    ]


def generate_investor_report(
    result: BacktestResult,
    kospi_index: pd.Series | None = None,
    get_ticker_name=None,
) -> list[plt.Figure]:
    """Generate investor-facing attribution, cost, and regime charts."""
    figures = [
        plot_ticker_contribution_bar(result, get_ticker_name=get_ticker_name),
        plot_ticker_yearly_contribution_heatmap(result, get_ticker_name=get_ticker_name),
        plot_trade_costs_by_year(result),
        plot_trade_reason_burden(result),
        plot_regime_exposure_by_ticker(result, get_ticker_name=get_ticker_name, held_only=True),
        plot_ticker_regime_invested_values(result, get_ticker_name=get_ticker_name),
    ]
    if kospi_index is not None:
        figures.insert(4, plot_kospi_regime_portfolio(result, kospi_index))
    return figures


def build_investor_commentary(
    result: BacktestResult,
    report: PerformanceReport,
    compare_summary: pd.DataFrame | None = None,
) -> list[str]:
    """Build short Korean interpretation bullets for a backtest result."""
    statuses = check_kpi_targets(report, result.config.strategy)
    bullets = []
    bullets.extend(interpret_kpi(statuses))
    bullets.extend(interpret_ticker_performance(summarize_ticker_performance(result)))
    bullets.extend(interpret_trade_costs(summarize_trade_costs_by_year(result), summarize_trade_reasons(result)))
    if compare_summary is not None:
        bullets.extend(interpret_compare_assets(compare_summary))
    bullets.extend(interpret_regime_exposure(summarize_regime_exposure_by_ticker(result, held_only=True)))
    return bullets


def _fmt_pct(value: float | None) -> str:
    return "N/A" if value is None else f"{value:.2%}"


def _fmt_num(value: float | None) -> str:
    return "N/A" if value is None else f"{value:.2f}"


def print_summary(
    result: BacktestResult,
    report: PerformanceReport,
) -> None:
    """Print a compact console summary."""
    statuses = check_kpi_targets(report, result.config.strategy)
    lines = [
        f"{result.config.strategy.INVESTMENT_TYPE.name} backtest",
        f"Period: {report.start_date.date()} ~ {report.end_date.date()}",
        f"Initial: {report.initial_value:,.0f} / Final: {report.final_value:,.0f}",
        "",
        "Metric | Value | Status",
        "--- | ---: | ---",
        f"CAGR | {_fmt_pct(report.cagr)} | {statuses['CAGR']}",
        f"MDD | {_fmt_pct(report.mdd)} | {statuses['MDD']}",
        f"MDD Duration | {report.mdd_duration_months:.1f} months | {statuses['MDD Duration']}",
        f"Calmar | {_fmt_num(report.calmar)} | {statuses['Calmar']}",
        f"Sortino | {_fmt_num(report.sortino)} | {statuses['Sortino']}",
        f"Alpha | {_fmt_pct(report.alpha)} | {statuses['Alpha']}",
        f"Beta | {_fmt_num(report.beta)} | {statuses['Beta']}",
    ]
    print("\n".join(lines))


def to_markdown(
    result: BacktestResult,
    report: PerformanceReport,
) -> str:
    """Return a Markdown report string."""
    statuses = check_kpi_targets(report, result.config.strategy)
    lines = [
        f"# {result.config.strategy.INVESTMENT_TYPE.name} Backtest Report",
        "",
        "## Summary",
        "",
        f"- Period: {report.start_date.date()} ~ {report.end_date.date()}",
        f"- Initial capital: {report.initial_value:,.0f}",
        f"- Final value: {report.final_value:,.0f}",
        f"- Total return: {_fmt_pct(report.total_return)}",
        f"- Benchmark: {result.config.strategy.BENCHMARK}",
        "",
        "## KPI",
        "",
        "| Metric | Value | Status |",
        "|---|---:|---|",
        f"| CAGR | {_fmt_pct(report.cagr)} | {statuses['CAGR']} |",
        f"| MDD | {_fmt_pct(report.mdd)} | {statuses['MDD']} |",
        f"| MDD Duration | {report.mdd_duration_months:.1f} months | {statuses['MDD Duration']} |",
        f"| Calmar | {_fmt_num(report.calmar)} | {statuses['Calmar']} |",
        f"| Sharpe | {_fmt_num(report.sharpe)} |  |",
        f"| Sortino | {_fmt_num(report.sortino)} | {statuses['Sortino']} |",
        f"| Win Rate | {_fmt_pct(report.win_rate)} |  |",
        f"| Profit Factor | {_fmt_num(report.profit_factor)} |  |",
        f"| Alpha | {_fmt_pct(report.alpha)} | {statuses['Alpha']} |",
        f"| Beta | {_fmt_num(report.beta)} | {statuses['Beta']} |",
        "",
        "## Universe Snapshots",
        "",
    ]

    for dt, tickers in result.universe_snapshots:
        lines.append(f"- {dt}: {', '.join(tickers)}")

    if result.excluded_tickers:
        lines.extend(["", "## Excluded Tickers", ""])
        for ticker, reason in result.excluded_tickers.items():
            lines.append(f"- {ticker}: {reason}")

    periods = sorted(calc_drawdown_periods(result.equity_curve), key=lambda item: item.drawdown)[:5]
    lines.extend(["", "## Top Drawdowns", "", "| Start | Trough | End | Drawdown | Duration |", "|---|---|---|---:|---:|"])
    for period in periods:
        end = period.end.date() if period.end is not None else "Unrecovered"
        lines.append(
            f"| {period.start.date()} | {period.trough.date()} | {end} | "
            f"{period.drawdown:.2%} | {period.duration_days} |"
        )

    lines.extend(["", "## Walk-Forward Windows", ""])
    for ticker, windows in result.wf_windows.items():
        if not windows:
            continue
        lines.append(f"### {ticker}")
        lines.append("")
        lines.append("| IS | OOS | Score | Params |")
        lines.append("|---|---|---:|---|")
        for window in windows:
            params = window.get("best_params") or {}
            lines.append(
                f"| {window['is_start'].date()} ~ {window['is_end'].date()} | "
                f"{window['oos_start'].date()} ~ {window['oos_end'].date()} | "
                f"{float(window['is_score']):.2f} | {params} |"
            )
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def to_dict(report: PerformanceReport) -> dict:
    """Return a JSON-serializable report dictionary."""
    data = asdict(report)
    data["start_date"] = str(report.start_date.date())
    data["end_date"] = str(report.end_date.date())
    return data
