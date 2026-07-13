from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path

import numpy as np
import pandas as pd

from apps.backtester.config import build_db_config, load_env
from apps.backtester.fa_weighting_research import (
    BUY_COST, EXPOSURE, METHODS, SELL_COST, _metrics, _weights,
)
from data.loaders.kospi_data import download_kospi_index
from storage.postgres.connection import PostgreDB


def _load_replay_data(db: PostgreDB):
    selections = pd.DataFrame(db.fetch_all("""
        WITH ranked AS (
          SELECT r.*, ROW_NUMBER() OVER (
            PARTITION BY r.analysis_month
            ORDER BY CASE r.status_code WHEN 'PUBLISHED' THEN 0 WHEN 'PASS' THEN 1 ELSE 2 END,
                     r.run_version DESC, r.id DESC
          ) AS rn
          FROM fa_analysis_runs r
          JOIN strategies s ON s.id=r.strategy_id
          WHERE s.name='aggressive'
            AND r.status_code IN ('PASS','WARNING','PUBLISHED')
        )
        SELECT r.id run_id,r.analysis_month,r.cutoff_date,r.effective_date,
               r.status_code,c.stock_code,c.fa_score
        FROM ranked r
        JOIN fa_company_results c ON c.run_id=r.id
        WHERE r.rn=1 AND c.is_selected=TRUE AND c.is_eligible=TRUE
        ORDER BY r.effective_date,c.stock_code
    """))
    prices = pd.DataFrame(db.fetch_all("""
        SELECT stock_code,price_date,close FROM wics_constituent_prices
        WHERE close>0 ORDER BY price_date,stock_code
    """))
    if selections.empty or prices.empty:
        raise RuntimeError("historical replay selections or prices are empty")
    for column in ("analysis_month", "cutoff_date", "effective_date"):
        selections[column] = pd.to_datetime(selections[column])
    selections["fa_score"] = pd.to_numeric(selections["fa_score"])
    prices["price_date"] = pd.to_datetime(prices["price_date"])
    prices["close"] = pd.to_numeric(prices["close"])
    matrix = prices.pivot_table(index="price_date", columns="stock_code", values="close", aggfunc="last").sort_index()
    return selections, matrix


def run_daily_replay(db: PostgreDB, *, pass_only: bool = False) -> tuple[dict, pd.DataFrame]:
    selections, prices = _load_replay_data(db)
    if pass_only:
        selections = selections[selections["status_code"].isin(["PASS", "PUBLISHED"])]
        if selections.empty:
            raise RuntimeError("no PASS/PUBLISHED replay selections")
    start = selections["effective_date"].min()
    end = min(selections["effective_date"].max() + pd.offsets.MonthEnd(1), prices.index.max())
    prices = prices.loc[:end].ffill(limit=3)
    ma20 = prices.rolling(20, min_periods=20).mean()
    ma60 = prices.rolling(60, min_periods=60).mean()
    mom60 = prices.pct_change(60)
    kospi = download_kospi_index(
        (start - pd.Timedelta(days=400)).date().isoformat(),
        (end + pd.Timedelta(days=1)).date().isoformat(),
    ).reindex(prices.index).ffill()
    kospi_up = kospi > kospi.rolling(200, min_periods=200).mean()
    asset_returns = prices.pct_change().fillna(0.0)

    replay_by_date = {
        date: frame.set_index("stock_code")
        for date, frame in selections.groupby("effective_date")
    }
    replay_dates = sorted(replay_by_date)
    calendar = prices.loc[start:end].index
    current_universe = pd.DataFrame()
    states = {
        method: {"weights": pd.Series(dtype=float), "returns": [], "costs": [], "turnovers": []}
        for method in METHODS
    }
    detail_rows = []

    for today in calendar:
        if today in replay_by_date:
            current_universe = replay_by_date[today]
        if current_universe.empty:
            continue
        for method in METHODS:
            state = states[method]
            weights = state["weights"]
            day_asset_returns = asset_returns.loc[today].reindex(weights.index).fillna(0.0)
            gross_return = float((weights * day_asset_returns).sum()) if not weights.empty else 0.0
            if not weights.empty and 1.0 + gross_return > 0:
                weights = weights * (1.0 + day_asset_returns) / (1.0 + gross_return)

            eligible = []
            if bool(kospi_up.get(today, False)):
                for ticker in current_universe.index:
                    if ticker not in prices.columns or pd.isna(ma60.at[today, ticker]):
                        continue
                    held = float(weights.get(ticker, 0.0)) > 0.0
                    trend_ok = ma20.at[today, ticker] >= ma60.at[today, ticker]
                    entry_ok = (
                        prices.at[today, ticker] > ma60.at[today, ticker]
                        and trend_ok
                        and mom60.at[today, ticker] > 0
                    )
                    if (held and trend_ok) or (not held and entry_ok):
                        eligible.append(ticker)

            if eligible:
                target = _weights(current_universe.loc[eligible], method)
            else:
                target = pd.Series(dtype=float)
            union = weights.index.union(target.index)
            current = weights.reindex(union).fillna(0.0)
            desired = target.reindex(union).fillna(0.0)
            rebalance = (
                (desired == 0)
                | (current == 0)
                | (current < desired * 0.90)
                | (current > desired * 1.10)
            )
            final = current.where(~rebalance, desired)
            delta = final - current
            buy_turnover = float(delta.clip(lower=0.0).sum())
            sell_turnover = float(-delta.clip(upper=0.0).sum())
            cost = buy_turnover * BUY_COST + sell_turnover * SELL_COST
            state["returns"].append((today, gross_return - cost))
            state["costs"].append((today, cost))
            state["turnovers"].append((today, buy_turnover + sell_turnover))
            state["weights"] = final[final > 1e-10]
            if buy_turnover + sell_turnover > 0:
                for ticker in union[delta.abs() > 1e-10]:
                    detail_rows.append({
                        "date": today.date().isoformat(), "method": method,
                        "ticker": ticker, "prev_weight": float(current[ticker]),
                        "target_weight": float(final[ticker]), "delta_weight": float(delta[ticker]),
                        "fa_score": float(current_universe.at[ticker, "fa_score"]) if ticker in current_universe.index else None,
                    })

    summary = {}
    for method, state in states.items():
        returns = pd.Series(dict(state["returns"])).sort_index()
        costs = pd.Series(dict(state["costs"])).reindex(returns.index)
        turnovers = pd.Series(dict(state["turnovers"])).reindex(returns.index)
        equity = (1 + returns).cumprod()
        years = max(len(returns) / 252, 1 / 252)
        drawdown = equity / equity.cummax() - 1
        summary[method] = {
            "trading_days": len(returns),
            "total_return": float(equity.iloc[-1] - 1),
            "cagr": float(equity.iloc[-1] ** (1 / years) - 1),
            "annual_volatility": float(returns.std() * np.sqrt(252)),
            "sharpe_zero_rf": float(returns.mean() / returns.std() * np.sqrt(252)) if returns.std() > 0 else 0.0,
            "max_drawdown": float(drawdown.min()),
            "average_daily_turnover": float(turnovers.mean()),
            "total_cost_ratio": float(costs.sum()),
        }
    status_counts = selections.drop_duplicates("run_id")["status_code"].value_counts().to_dict()
    return {
        "metadata": {
            "generated_at": dt.datetime.now().isoformat(timespec="seconds"),
            "period_start": calendar.min().date().isoformat(),
            "period_end": calendar.max().date().isoformat(),
            "replay_runs": int(selections["run_id"].nunique()),
            "replay_statuses": status_counts,
            "pass_only": pass_only,
            "methodology": "monthly historical FA macro-sector-company replay + daily KOSPI/TA entry-exit + 10% rebalance band",
            "limitations": [
                "Historical replay runs are research PASS/WARNING records, not retroactively PUBLISHED production records.",
                "Execution uses daily closes and proportional weights rather than share-level fills.",
            ],
        },
        "summary": summary,
    }, pd.DataFrame(detail_rows)


def write_report(result: dict, trades: pd.DataFrame, output_dir: Path):
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "metrics.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    trades.to_csv(output_dir / "rebalances.csv", index=False, encoding="utf-8-sig")
    labels = {"equal": "동일 비중", "fa_direct": "FA 직접 비례", "fa_excess": "FA 초과점수 비례"}
    best = max(result["summary"], key=lambda key: result["summary"][key]["sharpe_zero_rf"])
    lines = [
        "# FA 배분 통합 역사 리플레이 리포트", "",
        f"- 기간: {result['metadata']['period_start']} ~ {result['metadata']['period_end']}",
        f"- 월별 FA 리플레이: {result['metadata']['replay_runs']}개", "",
        f"- 리플레이 상태: {result['metadata']['replay_statuses']}", "",
        "| 방식 | 누적수익률 | CAGR | 변동성 | Sharpe | MDD | 일평균 회전율 | 누적 비용률 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for method, row in result["summary"].items():
        lines.append(
            f"| {labels[method]} | {row['total_return']:.2%} | {row['cagr']:.2%} | "
            f"{row['annual_volatility']:.2%} | {row['sharpe_zero_rf']:.3f} | "
            f"{row['max_drawdown']:.2%} | {row['average_daily_turnover']:.3%} | {row['total_cost_ratio']:.2%} |"
        )
    lines += [
        "", "## 결론", "",
        f"통합 리플레이 기준 Sharpe 최상 방식은 **{labels[best]}**입니다.",
        "초기 데이터 구간의 WARNING 비중이 높으므로 운영 배분 공식 변경 전 PASS 구간 단독 결과도 함께 확인해야 합니다.",
        "", "## 한계",
    ]
    lines.extend(f"- {item}" for item in result["metadata"]["limitations"])
    (output_dir / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", default="reports/fa_weighting_replay")
    parser.add_argument("--pass-only", action="store_true")
    args = parser.parse_args()
    load_env(); db = PostgreDB(build_db_config())
    try: result, trades = run_daily_replay(db, pass_only=args.pass_only)
    finally: db.close()
    write_report(result, trades, Path(args.output_dir))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__": main()
