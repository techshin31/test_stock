"""Small Korean interpretation helpers for investor-facing reports."""
from __future__ import annotations

import pandas as pd


def interpret_kpi(statuses: dict[str, str]) -> list[str]:
    """Return short interpretation bullets from KPI statuses."""
    failed = [name for name, status in statuses.items() if status == "FAIL"]
    warned = [name for name, status in statuses.items() if status == "WARN"]
    passed = [name for name, status in statuses.items() if status == "PASS"]

    bullets: list[str] = []
    if passed:
        bullets.append(f"목표를 충족한 핵심 지표는 {', '.join(passed)}입니다.")
    if warned:
        bullets.append(f"주의 구간에 있는 지표는 {', '.join(warned)}입니다. 재진입 기준이나 손절 조건을 함께 확인하세요.")
    if failed:
        bullets.append(f"목표 미달 지표는 {', '.join(failed)}입니다. 이 구간은 투자자 관점에서 별도 점검이 필요합니다.")
    if not bullets:
        bullets.append("KPI 판정 데이터가 없습니다.")
    return bullets


def interpret_ticker_performance(summary: pd.DataFrame, top_n: int = 3) -> list[str]:
    """Summarize which tickers drove or hurt performance."""
    if summary.empty:
        return ["종목별 성과 기여도가 없습니다."]

    top = summary.nlargest(top_n, "net_contribution")
    bottom = summary.nsmallest(top_n, "net_contribution")
    cost = summary.loc[summary["cost_amount"].abs().idxmax()] if "cost_amount" in summary else None
    bullets = [
        "성과 기여 상위 종목: "
        + ", ".join(f"{row.ticker}({row.net_contribution:+.2%})" for row in top.itertuples()),
        "성과 기여 하위 종목: "
        + ", ".join(f"{row.ticker}({row.net_contribution:+.2%})" for row in bottom.itertuples()),
    ]
    if cost is not None:
        bullets.append(f"거래 비용 부담이 가장 큰 종목은 {cost['ticker']}이며 비용은 약 {float(cost['cost_amount']):,.0f}원입니다.")
    return bullets


def interpret_trade_costs(yearly_summary: pd.DataFrame, reason_summary: pd.DataFrame) -> list[str]:
    """Summarize transaction-cost concentration by year and reason."""
    bullets: list[str] = []
    if yearly_summary.empty:
        return ["거래 비용 요약이 없습니다."]

    total = yearly_summary[yearly_summary["year"] == "TOTAL"]
    if not total.empty:
        row = total.iloc[0]
        bullets.append(
            f"전체 거래는 {int(row['trade_count'])}건, 총 거래 비용은 약 {float(row['total_cost_amount']):,.0f}원입니다."
        )

    yearly = yearly_summary[yearly_summary["year"] != "TOTAL"]
    if not yearly.empty:
        max_year = yearly.loc[yearly["total_cost_amount"].astype(float).idxmax()]
        bullets.append(f"거래 비용이 가장 컸던 해는 {max_year['year']}년입니다.")

    if not reason_summary.empty:
        top_reason = reason_summary.sort_values("trade_count", ascending=False).iloc[0]
        bullets.append(
            f"가장 자주 발생한 매매 사유는 {top_reason['trade_reason']} / {top_reason['side']}입니다."
        )
    return bullets


def interpret_compare_assets(summary: pd.DataFrame) -> list[str]:
    """Summarize the strategy versus comparison assets."""
    if summary.empty:
        return ["비교 자산 성과 요약이 없습니다."]

    best_return = summary.loc[summary["total_return"].astype(float).idxmax()]
    lowest_mdd = summary.loc[summary["mdd"].astype(float).idxmax()]
    return [
        f"총 수익률이 가장 높은 자산은 {best_return['asset']}({float(best_return['total_return']):+.2%})입니다.",
        f"MDD가 가장 낮은 자산은 {lowest_mdd['asset']}({float(lowest_mdd['mdd']):+.2%})입니다.",
    ]


def interpret_regime_exposure(summary: pd.DataFrame) -> list[str]:
    """Summarize dominant held-period regimes by ticker."""
    if summary.empty:
        return ["국면 노출 요약이 없습니다."]

    dominant = summary.sort_values(["ticker", "ratio"], ascending=[True, False]).groupby("ticker").head(1)
    return [
        "보유 기간 중 지배적인 국면: "
        + ", ".join(f"{row.ticker}={row.regime}({row.ratio:.1%})" for row in dominant.itertuples())
    ]
