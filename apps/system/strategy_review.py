"""Chronological diagnostics of an existing backtest, without parameter tuning."""
from pathlib import Path
import math
import numpy as np
import pandas as pd

from core.execution.strategy_policy import resolve_strategy_policy


def dated_csv(path):
    frame = pd.read_csv(path, index_col=0, parse_dates=True)
    if frame.empty or not isinstance(frame.index, pd.DatetimeIndex) or frame.index.hasnans or not frame.index.is_monotonic_increasing or not frame.index.is_unique:
        raise ValueError("INVALID_OR_UNORDERED_BACKTEST_DATES")
    return frame


def performance(returns):
    curve = pd.concat([pd.Series([1.0]), (1 + returns.reset_index(drop=True)).cumprod()], ignore_index=True)
    volatility = returns.std(ddof=1)
    return {"sessions": len(returns), "return_pct": float((curve.iloc[-1] - 1) * 100),
            "max_drawdown_pct": float((curve / curve.cummax() - 1).min() * 100),
            "sharpe": float(returns.mean() / volatility * math.sqrt(252)) if volatility > 0 else None}


def review(directory, benchmark):
    directory = Path(directory)
    equity_frame = dated_csv(directory / "equity-curve.csv")
    if equity_frame.shape[1] != 1:
        raise ValueError("EXPECTED_ONE_EQUITY_SERIES")
    equity = equity_frame.iloc[:, 0]
    weights = dated_csv(directory / "weights.csv")
    index_frame = dated_csv(benchmark)
    if index_frame.shape[1] != 1:
        raise ValueError("EXPECTED_ONE_BENCHMARK_SERIES")
    index = index_frame.iloc[:, 0].reindex(equity.index)
    if (len(equity) < 30 or not weights.index.equals(equity.index)
            or not np.isfinite(equity.to_numpy(dtype=float)).all() or (equity <= 0).any()
            or not np.isfinite(index.to_numpy(dtype=float)).all() or (index <= 0).any()
            or not np.isfinite(weights.to_numpy(dtype=float)).all() or (weights < -1e-8).any().any()
            or (weights.sum(axis=1) > 1.0001).any()):
        raise ValueError("INVALID_EQUITY_WEIGHTS_OR_BENCHMARK_COVERAGE")
    trades = pd.read_csv(directory / "trade-ledger.csv")
    trades["date"] = pd.to_datetime(trades["date"], errors="raise")
    turnover = pd.to_numeric(trades["trade_turnover"], errors="raise")
    if not np.isfinite(turnover).all() or (turnover < 0).any() or not trades["date"].isin(equity.index).all():
        raise ValueError("INVALID_TURNOVER_OR_TRADE_DATE")
    returns = equity.pct_change().fillna(0)
    benchmark_returns = index.pct_change().fillna(0)
    split = max(1, len(equity) * 2 // 3)
    periods = []
    for label, start, end in [("EARLIER_TWO_THIRDS", 0, split), ("LATER_ONE_THIRD", split, len(equity))]:
        periods.append({"period": label, "start": equity.index[start].date().isoformat(),
                        "end": equity.index[end - 1].date().isoformat(),
                        "strategy": performance(returns.iloc[start:end]),
                        "benchmark": performance(benchmark_returns.iloc[start:end])})
    daily_turnover = trades.assign(turnover=turnover).groupby("date")["turnover"].sum().reindex(equity.index, fill_value=0)
    stress = []
    for bps in (0, 10, 30, 50):
        stressed = returns - daily_turnover * bps / 10000
        if (stressed <= -1).any():
            raise ValueError("COST_STRESS_EXCEEDS_ACCOUNT_VALUE")
        stress.append({"additional_cost_bps": bps, **performance(stressed)})
    stock_weights = weights.drop(columns=[c for c in weights if c in {"BOND_ETF", "INVERSE_ETF", "CASH"}])
    concentration = stock_weights.max(axis=1) if not stock_weights.empty else pd.Series(0, index=weights.index)
    drawdown = equity / equity.cummax() - 1
    trough = drawdown.idxmin()
    peak = equity.loc[:trough].idxmax()
    policies = {venue: resolve_strategy_policy(venue, {}).as_dict() for venue in ("PAPER", "REAL")}
    total, market = performance(returns), performance(benchmark_returns)
    holdout_underperformance = periods[-1]["strategy"]["return_pct"] < periods[-1]["benchmark"]["return_pct"]
    reasons = [reason for failed, reason in [
        (total["max_drawdown_pct"] < -20, "DRAWDOWN_EXCEEDS_20_PERCENT"),
        (total["return_pct"] < market["return_pct"], "BENCHMARK_UNDERPERFORMANCE"),
        (holdout_underperformance, "LATER_PERIOD_UNDERPERFORMANCE"),
        ((concentration > policies["PAPER"]["max_position_weight"] + 1e-8).any(), "BACKTEST_EXCEEDS_RUNTIME_POSITION_CAP"),
    ] if failed]
    return {"status": "PASS", "purpose": "RESEARCH_DIAGNOSTICS_ONLY", "strategy": total,
            "benchmark": market, "chronological_periods": periods, "cost_stress": stress,
            "sharpe_risk_free_rate": 0.0,
            "cost_stress_method": "fixed observed trade path; extra proportional turnover cost; no liquidity/fill simulation",
            "drawdown_window": {"peak": peak.date(), "trough": trough.date(), "drawdown_pct": float(drawdown.min() * 100)},
            "concentration": {"maximum_stock_weight": float(concentration.max()),
                              "sessions_above_paper_cap": int((concentration > policies["PAPER"]["max_position_weight"] + 1e-8).sum()),
                              "mean_cash_weight": float((1 - weights.sum(axis=1)).mean())},
            "trade_reason_counts": trades["trade_reason"].fillna("UNKNOWN").value_counts().to_dict(),
            "runtime_policies": policies, "promotion_status": "BLOCKED", "promotion_reasons": reasons + ["EXTERNAL_PAPER_AND_LONG_TERM_OBSERVATION_REQUIRED"],
            "limitations": ["chronological split is retrospective, not an independent tuned holdout",
                            "no parameter optimization or production policy changes", "no asset return attribution without validated trade prices"]}
