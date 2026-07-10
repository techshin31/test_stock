"""Portfolio attribution tables for investor-facing analysis."""
from __future__ import annotations

import pandas as pd

from core.analytics.drawdown import calc_mdd_duration
from core.analytics.metrics import calc_cagr, calc_calmar, calc_mdd
from core.backtest.result import BacktestResult
from core.constant.types import Tickers

TRADE_REASON_LABELS = {
    "REBALANCE_BUY": "리밸런싱 매수",
    "REBALANCE_SELL": "리밸런싱 매도",
    "DEFENSIVE_ALLOCATION": "방어자산 배분",
    "UPTREND_ENTRY1": "상승장 1차 매수",
    "UPTREND_ENTRY2": "상승장 2차 매수",
    "SIDEWAYS_BB_LOWER_ENTRY": "횡보장 하단 반등 매수",
    "TRANSITION_EXIT": "전환장 비중 축소",
    "DEADCROSS": "데드크로스 비중 축소",
    "ATR_STOP": "ATR 손절",
    "DOWNTREND": "하락장 청산",
    "BB_UPPER_BREAKDOWN": "볼린저 상단 이탈 청산",
    "FORCED_EXIT": "편출 강제 청산",
}
SIDE_LABELS = {
    "BUY": "매수",
    "SELL": "매도",
}


def _empty(columns: list[str]) -> pd.DataFrame:
    return pd.DataFrame(columns=columns)


def _selected_columns(result: BacktestResult, include_defensive: bool) -> list[str]:
    if include_defensive:
        return list(result.weights.columns)
    return [col for col in result.weights.columns if col not in Tickers._member_names_]


def _contributions(result: BacktestResult, field: str) -> pd.DataFrame:
    value = getattr(result, field, None)
    if value is None:
        return pd.DataFrame(0.0, index=result.equity_curve.index, columns=result.weights.columns)
    return value.reindex(index=result.equity_curve.index, columns=result.weights.columns).fillna(0.0)


def _value_before(result: BacktestResult) -> pd.Series:
    equity = result.equity_curve.reindex(result.equity_curve.index).astype(float)
    return equity.shift(1).fillna(float(result.config.initial_capital))


def _ledger(result: BacktestResult) -> pd.DataFrame:
    if result.trade_ledger is None:
        return pd.DataFrame()
    ledger = result.trade_ledger.copy()
    if not ledger.empty and "date" in ledger.columns:
        ledger["date"] = pd.to_datetime(ledger["date"])
    return ledger


def summarize_ticker_performance(
    result: BacktestResult,
    include_defensive: bool = False,
    min_weight: float = 1e-6,
) -> pd.DataFrame:
    """Aggregate total performance contribution by ticker.

    Contribution values are portfolio-level return contributions. Amount columns
    convert those daily return contributions to currency using prior-day equity.
    """
    columns = [
        "ticker",
        "gross_contribution",
        "cost_ratio",
        "net_contribution",
        "gross_amount",
        "cost_amount",
        "net_amount",
        "held_days",
        "avg_weight",
        "max_weight",
        "trade_count",
        "buy_count",
        "sell_count",
        "first_trade",
        "last_trade",
    ]
    tickers = _selected_columns(result, include_defensive)
    if not tickers:
        return _empty(columns)

    gross = _contributions(result, "gross_return_contributions")
    costs = _contributions(result, "cost_contributions")
    net = _contributions(result, "net_return_contributions")
    weights = result.weights.reindex(columns=tickers).fillna(0.0)
    value_before = _value_before(result)
    ledger = _ledger(result)

    rows: list[dict[str, object]] = []
    for ticker in tickers:
        ticker_trades = ledger[ledger["ticker"] == ticker] if not ledger.empty else pd.DataFrame()
        held = weights[ticker].abs() > min_weight
        first_trade = ticker_trades["date"].min() if not ticker_trades.empty else pd.NaT
        last_trade = ticker_trades["date"].max() if not ticker_trades.empty else pd.NaT

        rows.append({
            "ticker": ticker,
            "gross_contribution": float(gross[ticker].sum()) if ticker in gross else 0.0,
            "cost_ratio": float(costs[ticker].sum()) if ticker in costs else 0.0,
            "net_contribution": float(net[ticker].sum()) if ticker in net else 0.0,
            "gross_amount": float(gross[ticker].multiply(value_before, axis=0).sum()) if ticker in gross else 0.0,
            "cost_amount": float(costs[ticker].multiply(value_before, axis=0).sum()) if ticker in costs else 0.0,
            "net_amount": float(net[ticker].multiply(value_before, axis=0).sum()) if ticker in net else 0.0,
            "held_days": int(held.sum()),
            "avg_weight": float(weights.loc[held, ticker].mean()) if held.any() else 0.0,
            "max_weight": float(weights[ticker].max()) if ticker in weights else 0.0,
            "trade_count": int(len(ticker_trades)),
            "buy_count": int((ticker_trades["side"] == "BUY").sum()) if not ticker_trades.empty else 0,
            "sell_count": int((ticker_trades["side"] == "SELL").sum()) if not ticker_trades.empty else 0,
            "first_trade": first_trade,
            "last_trade": last_trade,
        })

    return pd.DataFrame(rows, columns=columns).sort_values(
        ["net_contribution", "ticker"],
        ascending=[False, True],
        ignore_index=True,
    )


def summarize_ticker_yearly_performance(
    result: BacktestResult,
    include_defensive: bool = False,
    include_zero: bool = False,
    min_weight: float = 1e-6,
) -> pd.DataFrame:
    """Aggregate yearly performance contribution by ticker."""
    columns = [
        "year",
        "ticker",
        "gross_contribution",
        "cost_ratio",
        "net_contribution",
        "gross_amount",
        "cost_amount",
        "net_amount",
        "held_days",
        "avg_weight",
        "max_weight",
        "trade_count",
        "buy_count",
        "sell_count",
    ]
    tickers = _selected_columns(result, include_defensive)
    if not tickers:
        return _empty(columns)

    gross = _contributions(result, "gross_return_contributions")
    costs = _contributions(result, "cost_contributions")
    net = _contributions(result, "net_return_contributions")
    weights = result.weights.reindex(columns=tickers).fillna(0.0)
    value_before = _value_before(result)
    ledger = _ledger(result)
    years = sorted(result.equity_curve.index.year.unique())

    rows: list[dict[str, object]] = []
    for year in years:
        mask = result.equity_curve.index.year == year
        year_index = result.equity_curve.index[mask]
        year_ledger = ledger[ledger["date"].dt.year == year] if not ledger.empty else pd.DataFrame()

        for ticker in tickers:
            ticker_trades = year_ledger[year_ledger["ticker"] == ticker] if not year_ledger.empty else pd.DataFrame()
            held = weights.loc[year_index, ticker].abs() > min_weight
            gross_value = float(gross.loc[year_index, ticker].sum()) if ticker in gross else 0.0
            cost_value = float(costs.loc[year_index, ticker].sum()) if ticker in costs else 0.0
            net_value = float(net.loc[year_index, ticker].sum()) if ticker in net else 0.0
            held_days = int(held.sum())
            trade_count = int(len(ticker_trades))

            if not include_zero and held_days == 0 and trade_count == 0 and abs(net_value) < 1e-15 and cost_value == 0.0:
                continue

            rows.append({
                "year": int(year),
                "ticker": ticker,
                "gross_contribution": gross_value,
                "cost_ratio": cost_value,
                "net_contribution": net_value,
                "gross_amount": float(gross.loc[year_index, ticker].multiply(value_before.loc[year_index], axis=0).sum()) if ticker in gross else 0.0,
                "cost_amount": float(costs.loc[year_index, ticker].multiply(value_before.loc[year_index], axis=0).sum()) if ticker in costs else 0.0,
                "net_amount": float(net.loc[year_index, ticker].multiply(value_before.loc[year_index], axis=0).sum()) if ticker in net else 0.0,
                "held_days": held_days,
                "avg_weight": float(weights.loc[year_index, ticker].loc[held].mean()) if held.any() else 0.0,
                "max_weight": float(weights.loc[year_index, ticker].max()),
                "trade_count": trade_count,
                "buy_count": int((ticker_trades["side"] == "BUY").sum()) if not ticker_trades.empty else 0,
                "sell_count": int((ticker_trades["side"] == "SELL").sum()) if not ticker_trades.empty else 0,
            })

    return pd.DataFrame(rows, columns=columns).sort_values(
        ["year", "net_contribution", "ticker"],
        ascending=[True, False, True],
        ignore_index=True,
    )


def summarize_trade_costs_by_year(result: BacktestResult, include_total: bool = True) -> pd.DataFrame:
    """Summarize yearly and total turnover, trade count, and transaction costs."""
    columns = [
        "year",
        "trade_count",
        "buy_count",
        "sell_count",
        "traded_assets",
        "rebalance_days",
        "total_turnover",
        "total_cost_ratio",
        "total_cost_amount",
    ]
    ledger = _ledger(result)
    value_before = _value_before(result)
    cost_amount = result.cost_series.reindex(result.equity_curve.index).fillna(0.0).multiply(value_before, axis=0)
    years = sorted(result.equity_curve.index.year.unique())

    rows: list[dict[str, object]] = []
    for year in years:
        date_mask = result.equity_curve.index.year == year
        year_cost = result.cost_series.loc[date_mask]
        year_amount = cost_amount.loc[date_mask]
        year_ledger = ledger[ledger["date"].dt.year == year] if not ledger.empty else pd.DataFrame()
        rows.append({
            "year": int(year),
            "trade_count": int(len(year_ledger)),
            "buy_count": int((year_ledger["side"] == "BUY").sum()) if not year_ledger.empty else 0,
            "sell_count": int((year_ledger["side"] == "SELL").sum()) if not year_ledger.empty else 0,
            "traded_assets": int(year_ledger["ticker"].nunique()) if not year_ledger.empty else 0,
            "rebalance_days": int((year_cost > 0.0).sum()),
            "total_turnover": float(year_ledger["trade_turnover"].sum()) if not year_ledger.empty else 0.0,
            "total_cost_ratio": float(year_cost.sum()),
            "total_cost_amount": float(year_amount.sum()),
        })

    if include_total:
        rows.append({
            "year": "TOTAL",
            "trade_count": int(len(ledger)),
            "buy_count": int((ledger["side"] == "BUY").sum()) if not ledger.empty else 0,
            "sell_count": int((ledger["side"] == "SELL").sum()) if not ledger.empty else 0,
            "traded_assets": int(ledger["ticker"].nunique()) if not ledger.empty else 0,
            "rebalance_days": int((result.cost_series > 0.0).sum()),
            "total_turnover": float(ledger["trade_turnover"].sum()) if not ledger.empty else 0.0,
            "total_cost_ratio": float(result.cost_series.sum()),
            "total_cost_amount": float(cost_amount.sum()),
        })

    return pd.DataFrame(rows, columns=columns)


def summarize_trade_reasons(result: BacktestResult) -> pd.DataFrame:
    """Summarize trade count and costs by signal or rebalance reason."""
    columns = [
        "trade_reason",
        "side",
        "trade_count",
        "total_turnover",
        "total_cost_ratio",
        "total_cost_amount",
    ]
    ledger = _ledger(result)
    if ledger.empty:
        return _empty(columns)

    grouped = (
        ledger
        .groupby(["trade_reason", "side"], dropna=False)
        .agg(
            trade_count=("ticker", "size"),
            total_turnover=("trade_turnover", "sum"),
            total_cost_ratio=("cost_ratio", "sum"),
            total_cost_amount=("cost_amount", "sum"),
        )
        .reset_index()
    )
    return grouped.sort_values(
        ["trade_count", "total_cost_amount"],
        ascending=[False, False],
        ignore_index=True,
    )[columns]


def summarize_regime_exposure_by_ticker(
    result: BacktestResult,
    held_only: bool = True,
    include_defensive: bool = False,
    min_weight: float = 1e-6,
) -> pd.DataFrame:
    """Summarize regime exposure by ticker.

    When held_only is True, only days with positive portfolio weight are counted.
    Defensive assets are excluded by default because they do not have per-asset
    regime classifications.
    """
    columns = ["ticker", "regime", "days", "ratio", "held_only"]
    tickers = _selected_columns(result, include_defensive)
    rows: list[dict[str, object]] = []

    for ticker in tickers:
        if ticker not in result.regime_dict:
            continue
        regime = result.regime_dict[ticker]["REGIME"].reindex(result.equity_curve.index).ffill()
        if held_only and ticker in result.weights:
            mask = result.weights[ticker].fillna(0.0).abs() > min_weight
            regime = regime.loc[mask]
        regime = regime.dropna()
        total = int(len(regime))
        if total == 0:
            continue

        for regime_name, days in regime.value_counts().items():
            rows.append({
                "ticker": ticker,
                "regime": regime_name,
                "days": int(days),
                "ratio": float(days / total),
                "held_only": bool(held_only),
            })

    return pd.DataFrame(rows, columns=columns).sort_values(
        ["ticker", "days"],
        ascending=[True, False],
        ignore_index=True,
    )


def format_ticker_label(
    ticker: str,
    get_ticker_name=None,
    multiline: bool = True,
) -> str:
    """Return a ticker label that can include a Korean display name."""
    name = get_ticker_name(ticker) if get_ticker_name is not None else None
    if not name or name == ticker:
        return str(ticker)
    separator = "\n" if multiline else " "
    return f"{ticker}{separator}{name}"


def add_trade_reason_labels(summary: pd.DataFrame) -> pd.DataFrame:
    """Add Korean/code labels for trade reason visualizations."""
    if summary.empty:
        return summary.copy()

    view = summary.copy()
    view["reason_name"] = view["trade_reason"].map(TRADE_REASON_LABELS).fillna(view["trade_reason"].astype(str))
    view["side_name"] = view["side"].map(SIDE_LABELS).fillna(view["side"].astype(str))
    view["reason_side_label"] = view.apply(
        lambda row: f"{row['reason_name']} ({row['trade_reason']})\n{row['side_name']} ({row['side']})",
        axis=1,
    )
    return view


def calc_equity_stats(
    equity: pd.Series,
    risk_free_rate: float = 0.03,
    trading_days: int = 252,
) -> dict[str, float]:
    """Calculate compact performance stats for a single equity curve."""
    curve = equity.dropna().astype(float)
    if curve.empty:
        return {
            "final_value": 0.0,
            "total_return": 0.0,
            "cagr": 0.0,
            "mdd": 0.0,
            "mdd_months": 0.0,
            "calmar": 0.0,
            "sharpe": 0.0,
            "sortino": 0.0,
            "volatility": 0.0,
        }

    returns = curve.pct_change().fillna(0.0)
    annual_return = float(returns.mean() * trading_days)
    annual_vol = float(returns.std() * trading_days ** 0.5)
    downside = returns[returns < 0.0]
    downside_vol = float(downside.std() * trading_days ** 0.5) if len(downside) > 1 else 0.0
    mdd_duration = calc_mdd_duration(curve)

    return {
        "final_value": float(curve.iloc[-1]),
        "total_return": float(curve.iloc[-1] / curve.iloc[0] - 1.0) if curve.iloc[0] else 0.0,
        "cagr": calc_cagr(curve, trading_days),
        "mdd": calc_mdd(curve),
        "mdd_months": float(mdd_duration / 21.0),
        "calmar": calc_calmar(curve, trading_days),
        "sharpe": float((annual_return - risk_free_rate) / annual_vol) if annual_vol else 0.0,
        "sortino": float((annual_return - risk_free_rate) / downside_vol) if downside_vol else 0.0,
        "volatility": annual_vol,
    }


def summarize_compare_assets(
    equity_curves: dict[str, pd.Series],
    risk_free_rate: float = 0.03,
    trading_days: int = 252,
) -> pd.DataFrame:
    """Summarize strategy and comparison-asset equity curves."""
    columns = [
        "asset",
        "final_value",
        "total_return",
        "cagr",
        "mdd",
        "mdd_months",
        "calmar",
        "sharpe",
        "sortino",
        "volatility",
    ]
    rows = []
    for asset, equity in equity_curves.items():
        stats = calc_equity_stats(equity, risk_free_rate=risk_free_rate, trading_days=trading_days)
        rows.append({"asset": asset, **stats})
    return pd.DataFrame(rows, columns=columns)
