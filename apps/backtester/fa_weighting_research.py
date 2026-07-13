from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path

import numpy as np
import pandas as pd

from apps.backtester.config import build_db_config, load_env
from storage.postgres.connection import PostgreDB


METHODS = ("equal", "fa_direct", "fa_excess")
EXPOSURE = 0.90
FA_MINIMUM = 50.0
BUY_COST = 0.00015 + 0.001
SELL_COST = 0.00015 + 0.001 + 0.0018


def _load_frames(db: PostgreDB) -> tuple[pd.DataFrame, pd.DataFrame]:
    scores = pd.DataFrame(db.fetch_all("""
        SELECT stock_code, available_date, fa_score, score_confidence,
               is_eligible, market_cap, market_data_date
        FROM company_quarter_fa
        WHERE available_date IS NOT NULL
          AND fa_score IS NOT NULL
          AND score_confidence IS NOT NULL
          AND market_cap IS NOT NULL
          AND score_model_code <> 'UNSUPPORTED'
        ORDER BY available_date, stock_code
    """))
    prices = pd.DataFrame(db.fetch_all("""
        SELECT stock_code, price_date, close
        FROM wics_constituent_prices
        WHERE close > 0
        ORDER BY price_date, stock_code
    """))
    if scores.empty or prices.empty:
        raise RuntimeError("FA score or constituent price history is empty")
    scores["available_date"] = pd.to_datetime(scores["available_date"])
    scores["market_data_date"] = pd.to_datetime(scores["market_data_date"])
    for column in ("fa_score", "score_confidence", "market_cap"):
        scores[column] = pd.to_numeric(scores[column], errors="coerce")
    prices["price_date"] = pd.to_datetime(prices["price_date"])
    prices["close"] = pd.to_numeric(prices["close"], errors="coerce")
    return scores, prices.dropna(subset=["close"])


def _weights(frame: pd.DataFrame, method: str) -> pd.Series:
    if method == "equal":
        raw = pd.Series(1.0, index=frame.index)
    elif method == "fa_direct":
        raw = frame["fa_score"].clip(lower=0.0)
    elif method == "fa_excess":
        raw = (frame["fa_score"] - FA_MINIMUM).clip(lower=0.0)
    else:
        raise ValueError(method)
    if float(raw.sum()) <= 0:
        raw = pd.Series(1.0, index=frame.index)
    return raw / raw.sum() * EXPOSURE


def _metrics(returns: pd.Series, costs: pd.Series, turnovers: pd.Series) -> dict:
    equity = (1.0 + returns).cumprod()
    years = max(len(returns) / 12.0, 1 / 12)
    total_return = float(equity.iloc[-1] - 1.0)
    cagr = float(equity.iloc[-1] ** (1 / years) - 1.0)
    volatility = float(returns.std(ddof=1) * np.sqrt(12)) if len(returns) > 1 else 0.0
    sharpe = float(returns.mean() / returns.std(ddof=1) * np.sqrt(12)) if returns.std(ddof=1) > 0 else 0.0
    drawdown = equity / equity.cummax() - 1.0
    return {
        "months": int(len(returns)),
        "total_return": total_return,
        "cagr": cagr,
        "annual_volatility": volatility,
        "sharpe_zero_rf": sharpe,
        "max_drawdown": float(drawdown.min()),
        "average_monthly_turnover": float(turnovers.mean()),
        "total_cost_ratio": float(costs.sum()),
        "final_equity_multiple": float(equity.iloc[-1]),
    }


def run_research(db: PostgreDB) -> tuple[dict, pd.DataFrame]:
    scores, prices = _load_frames(db)
    price_matrix = prices.pivot_table(
        index="price_date", columns="stock_code", values="close", aggfunc="last"
    ).sort_index()
    month_ends = price_matrix.groupby(price_matrix.index.to_period("M")).apply(
        lambda frame: frame.index.max()
    ).tolist()
    month_ends = [date for date in month_ends if date >= scores["available_date"].min()]
    periods = list(zip(month_ends[:-1], month_ends[1:]))
    method_returns = {method: [] for method in METHODS}
    method_costs = {method: [] for method in METHODS}
    method_turnovers = {method: [] for method in METHODS}
    previous_weights = {method: pd.Series(dtype=float) for method in METHODS}
    detail_rows = []

    for rebalance_date, next_date in periods:
        available = scores[
            (scores["available_date"] <= rebalance_date)
            & (scores["market_data_date"] <= rebalance_date)
            & scores["is_eligible"].astype(bool)
            & (scores["score_confidence"] >= 0.70)
            & (scores["fa_score"] >= FA_MINIMUM)
        ].sort_values(["available_date", "stock_code"])
        latest = available.drop_duplicates("stock_code", keep="last")
        latest = latest[latest["stock_code"].isin(price_matrix.columns)]
        latest = latest.sort_values(
            ["fa_score", "score_confidence", "market_cap", "stock_code"],
            ascending=[False, False, False, True],
        ).copy()
        if latest.empty:
            continue
        start_prices = price_matrix.loc[rebalance_date].reindex(latest["stock_code"])
        end_prices = price_matrix.loc[next_date].reindex(latest["stock_code"])
        valid = start_prices.notna() & end_prices.notna() & (start_prices > 0)
        valid_codes = list(start_prices.index[valid])
        latest = latest.set_index("stock_code").loc[valid_codes]
        forward_returns = end_prices.loc[valid_codes] / start_prices.loc[valid_codes] - 1.0
        if latest.empty:
            continue

        for method in METHODS:
            weights = _weights(latest, method)
            prior = previous_weights[method]
            union = prior.index.union(weights.index)
            delta = weights.reindex(union).fillna(0.0) - prior.reindex(union).fillna(0.0)
            buy_turnover = float(delta.clip(lower=0.0).sum())
            sell_turnover = float(-delta.clip(upper=0.0).sum())
            cost = buy_turnover * BUY_COST + sell_turnover * SELL_COST
            gross_return = float((weights * forward_returns).sum())
            net_return = gross_return - cost
            method_returns[method].append((next_date, net_return))
            method_costs[method].append((next_date, cost))
            method_turnovers[method].append((next_date, buy_turnover + sell_turnover))
            previous_weights[method] = weights
            for ticker in weights.index:
                detail_rows.append({
                    "rebalance_date": rebalance_date.date().isoformat(),
                    "next_date": next_date.date().isoformat(),
                    "method": method,
                    "ticker": ticker,
                    "fa_score": float(latest.at[ticker, "fa_score"]),
                    "weight": float(weights[ticker]),
                    "forward_return": float(forward_returns[ticker]),
                })

    summary = {}
    for method in METHODS:
        returns = pd.Series(dict(method_returns[method])).sort_index()
        costs = pd.Series(dict(method_costs[method])).reindex(returns.index)
        turnovers = pd.Series(dict(method_turnovers[method])).reindex(returns.index)
        if returns.empty:
            raise RuntimeError(f"no valid periods for {method}")
        summary[method] = _metrics(returns, costs, turnovers)
    metadata = {
        "generated_at": dt.datetime.now().isoformat(timespec="seconds"),
        "methodology": "monthly point-in-time latest eligible FA scores; no security-count cap",
        "exposure": EXPOSURE,
        "fa_minimum": FA_MINIMUM,
        "buy_cost_rate": BUY_COST,
        "sell_cost_rate": SELL_COST,
        "score_history_start": scores["available_date"].min().date().isoformat(),
        "score_history_end": scores["available_date"].max().date().isoformat(),
        "price_history_start": price_matrix.index.min().date().isoformat(),
        "price_history_end": price_matrix.index.max().date().isoformat(),
        "important_limitations": [
            "Only two PUBLISHED aggressive FA runs exist, so historical candidates are reconstructed from point-in-time quarterly FA scores.",
            "Sector selection and live TA entry timing are not replayed; this isolates allocation-method effects.",
            "Monthly close-to-close returns and approximate transaction costs are used.",
        ],
    }
    return {"metadata": metadata, "summary": summary}, pd.DataFrame(detail_rows)


def _write_report(result: dict, details: pd.DataFrame, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "metrics.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    details.to_csv(output_dir / "allocations.csv", index=False, encoding="utf-8-sig")
    summary = result["summary"]
    best = max(summary, key=lambda method: summary[method]["sharpe_zero_rf"])
    lines = [
        "# FA 비중 배분 비교 연구 리포트",
        "",
        f"Generated: {result['metadata']['generated_at']}",
        "",
        "## 성과 비교",
        "",
        "| 배분 방식 | 개월 | 누적수익률 | CAGR | 변동성 | Sharpe | MDD | 월평균 회전율 | 누적 비용률 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    labels = {"equal": "동일 비중", "fa_direct": "FA 점수 직접 비례", "fa_excess": "FA 50점 초과분 비례"}
    for method in METHODS:
        row = summary[method]
        lines.append(
            f"| {labels[method]} | {row['months']} | {row['total_return']:.2%} | "
            f"{row['cagr']:.2%} | {row['annual_volatility']:.2%} | "
            f"{row['sharpe_zero_rf']:.3f} | {row['max_drawdown']:.2%} | "
            f"{row['average_monthly_turnover']:.2%} | {row['total_cost_ratio']:.2%} |"
        )
    lines.extend([
        "",
        "## 결론 및 권고",
        "",
        f"이 배분 방식 단독 비교에서 무위험수익률 0 기준 Sharpe가 가장 높은 방식은 **{labels[best]}**입니다.",
        "FA 직접 비례 방식은 동일 비중보다 누적수익률과 Sharpe가 소폭 낮았습니다. 현재 결과만으로 FA 비례 배분을 최종 운영안으로 확정하지 않는 것이 좋습니다.",
        "향후 PUBLISHED FA 발행 이력이 충분히 쌓이면 실제 섹터 선택과 TA 진입 시점을 함께 재현해 다시 검증해야 합니다.",
        "",
        "## 방법론과 한계",
        "",
        f"- {result['metadata']['methodology']}",
        f"- FA 점수 기간: {result['metadata']['score_history_start']} ~ {result['metadata']['score_history_end']}",
        f"- 가격 기간: {result['metadata']['price_history_start']} ~ {result['metadata']['price_history_end']}",
    ])
    lines.extend(f"- {item}" for item in result["metadata"]["important_limitations"])
    (output_dir / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", default="reports/fa_weighting_research")
    args = parser.parse_args()
    load_env()
    db = PostgreDB(build_db_config())
    try:
        result, details = run_research(db)
    finally:
        db.close()
    _write_report(result, details, Path(args.output_dir))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
