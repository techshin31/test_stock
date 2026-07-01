"""Display-oriented table builders for analytics notebooks."""
from __future__ import annotations

import pandas as pd

from core.analytics.performance import PerformanceReport


REFERENCE_STATUS = "참고"
STATUS_EMOJI = {
    "PASS": "✅",
    "WARN": "⚠️",
    "FAIL": "❌",
    "N/A": "➖",
    REFERENCE_STATUS: "➖",
    "": "",
}


def _status_label(status: str) -> str:
    return f"{STATUS_EMOJI.get(status, '')} {status}".strip()


def build_performance_summary_table(report: PerformanceReport) -> pd.DataFrame:
    """Build the headline capital summary table."""
    return pd.DataFrame(
        {
            "값": [
                f"{report.initial_value:,.0f} 원",
                f"{report.final_value:,.0f} 원",
                f"{report.total_return:+.2%}",
            ],
        },
        index=["초기 자산", "최종 자산", "총 수익률"],
    )


def build_kpi_table(report: PerformanceReport, statuses: dict[str, str]) -> pd.DataFrame:
    """Build a KPI table with explicit status for every row."""
    alpha_str = f"{report.alpha:+.2%}" if report.alpha is not None else "N/A"
    beta_str = f"{report.beta:.3f}" if report.beta is not None else "N/A"
    rows = [
        ("CAGR", f"{report.cagr:+.2%}", statuses.get("CAGR", "N/A")),
        ("MDD", f"{report.mdd:+.2%}", statuses.get("MDD", "N/A")),
        ("MDD 기간", f"{report.mdd_duration_months:.1f}개월", statuses.get("MDD Duration", "N/A")),
        ("Calmar", f"{report.calmar:.3f}", statuses.get("Calmar", "N/A")),
        ("Sharpe", f"{report.sharpe:.3f}", REFERENCE_STATUS),
        ("Sortino", f"{report.sortino:.3f}", statuses.get("Sortino", "N/A")),
        ("승률", f"{report.win_rate:.2%}", REFERENCE_STATUS),
        ("Profit Factor", f"{report.profit_factor:.3f}", REFERENCE_STATUS),
        ("연간 변동성", f"{report.volatility:.2%}", REFERENCE_STATUS),
        ("Alpha", alpha_str, statuses.get("Alpha", "N/A")),
        ("Beta", beta_str, statuses.get("Beta", "N/A")),
    ]
    table = pd.DataFrame(rows, columns=["지표", "값", "KPI 판정"])
    table["KPI 판정"] = table["KPI 판정"].map(_status_label)
    return table.set_index("지표")


def format_analysis_table(
    df: pd.DataFrame,
    pct_cols: tuple[str, ...] | list[str] = (),
    amount_cols: tuple[str, ...] | list[str] = (),
    weight_cols: tuple[str, ...] | list[str] = (),
    date_cols: tuple[str, ...] | list[str] = (),
    turnover_cols: tuple[str, ...] | list[str] = (),
) -> pd.DataFrame:
    """Format numeric analysis tables for notebook display."""
    view = df.copy()
    for col in pct_cols:
        if col in view.columns:
            view[col] = view[col].map(lambda v: "" if pd.isna(v) else f"{float(v):+.2%}")
    for col in amount_cols:
        if col in view.columns:
            view[col] = view[col].map(lambda v: "" if pd.isna(v) else f"{float(v):,.0f}원")
    for col in weight_cols:
        if col in view.columns:
            view[col] = view[col].map(lambda v: "" if pd.isna(v) else f"{float(v):.1%}")
    for col in date_cols:
        if col in view.columns:
            view[col] = pd.to_datetime(view[col], errors="coerce").dt.strftime("%Y-%m-%d").fillna("")
    for col in turnover_cols:
        if col in view.columns:
            view[col] = view[col].map(lambda v: "" if pd.isna(v) else f"{float(v):.2f}x")
    return view


def build_compare_assets_table(summary: pd.DataFrame) -> pd.DataFrame:
    """Format comparison-asset summary rows into a metric-by-asset table."""
    metric_order = [
        ("final_value", "최종 자산(만원)", lambda v: f"{float(v) / 1e4:,.1f}"),
        ("total_return", "총 수익률", lambda v: f"{float(v):+.2%}"),
        ("cagr", "CAGR", lambda v: f"{float(v):+.2%}"),
        ("mdd", "MDD", lambda v: f"{float(v):+.2%}"),
        ("mdd_months", "MDD 기간(개월)", lambda v: f"{float(v):.1f}"),
        ("calmar", "Calmar", lambda v: f"{float(v):.3f}"),
        ("sharpe", "Sharpe", lambda v: f"{float(v):.3f}"),
        ("sortino", "Sortino", lambda v: f"{float(v):.3f}"),
        ("volatility", "연간 변동성", lambda v: f"{float(v):.2%}"),
    ]
    if summary.empty:
        return pd.DataFrame()

    rows: dict[str, dict[str, str]] = {}
    for metric, label, formatter in metric_order:
        rows[label] = {
            str(row["asset"]): formatter(row[metric]) if pd.notna(row[metric]) else ""
            for _, row in summary.iterrows()
        }
    return pd.DataFrame.from_dict(rows, orient="index")
