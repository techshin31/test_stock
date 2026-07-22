from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import itertools
import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path
from statistics import NormalDist

import numpy as np
import pandas as pd

from apps.backtester.config import build_db_config, load_env
from apps.backtester.fa_weighting_replay import _load_replay_data
from apps.backtester.fa_weighting_research import BUY_COST, SELL_COST
from data.loaders.kospi_data import download_kospi_index
from storage.postgres.connection import PostgreDB


EXPOSURE = 0.90
FA_MINIMUM = 50.0


@dataclass(frozen=True)
class Variant:
    code: str
    label: str
    weight_method: str
    max_weight: float | None
    rebalance_band: float
    stop_loss: float | None
    trailing_stop: float | None
    volatility_scaled: bool = False
    cooldown_sessions: int = 0
    reentry_rule: str = "none"
    reentry_confirm_sessions: int = 0
    description: str = ""


VARIANTS = (
    Variant(
        "A0_LEGACY",
        "기존 연구 리플레이",
        "fa_excess",
        None,
        0.10,
        None,
        None,
        description="기존 보고서 수치 재현용. 종목 상한과 가격 손절은 반영하지 않음.",
    ),
    Variant(
        "X_CAP15_ONLY",
        "진단: 15% 상한만",
        "fa_excess",
        0.15,
        0.10,
        None,
        None,
        description="종목 상한 효과와 손절·재진입 효과를 분리하기 위한 진단 실험.",
    ),
    Variant(
        "A_CURRENT",
        "현재 규칙 근사",
        "fa_excess",
        0.15,
        0.10,
        0.10,
        0.08,
        description="FA 초과점수, 종목당 15%, 10% 리밸런싱 밴드, 10%/8% 손절.",
    ),
    Variant(
        "X_COOLDOWN5",
        "진단: 현재+5일 재진입 금지",
        "fa_excess",
        0.15,
        0.10,
        0.10,
        0.08,
        cooldown_sessions=5,
        description="현재 근사 규칙에서 손절 종목의 5거래일 재진입만 금지.",
    ),
    Variant(
        "R_EXIT_RECOVERY",
        "청산가 회복 2일 확인",
        "fa_excess",
        0.15,
        0.10,
        0.10,
        0.08,
        reentry_rule="exit_price_recovery",
        reentry_confirm_sessions=2,
        description="손절·트레일링 청산 후 청산가와 20일선을 웃도는 상태가 2거래일 이어질 때만 재진입.",
    ),
    Variant(
        "R_TREND_REARM",
        "추세 재무장 3일 확인",
        "fa_excess",
        0.15,
        0.10,
        0.10,
        0.08,
        reentry_rule="trend_rearm",
        reentry_confirm_sessions=3,
        description="손절·트레일링 청산 후 청산가 회복, 20일선 상승, 20일 모멘텀이 3거래일 확인될 때만 재진입.",
    ),
    Variant(
        "B_EQUAL",
        "동일 비중",
        "equal",
        0.15,
        0.10,
        0.10,
        0.08,
        description="신호와 위험 규칙은 유지하고 FA 비중 효과만 제거.",
    ),
    Variant(
        "C_CAP10",
        "종목 상한 10%",
        "fa_excess",
        0.10,
        0.10,
        0.10,
        0.08,
        description="현재 근사 규칙에서 종목 집중도만 10%로 축소.",
    ),
    Variant(
        "C_CAP08",
        "종목 상한 8%",
        "fa_excess",
        0.08,
        0.10,
        0.10,
        0.08,
        description="종목 상한 8% 민감도 실험.",
    ),
    Variant(
        "D_BAND20",
        "리밸런싱 밴드 20%",
        "fa_excess",
        0.15,
        0.20,
        0.10,
        0.08,
        description="현재 근사 규칙에서 매매 빈도만 축소.",
    ),
    Variant(
        "E_VOL_RISK",
        "변동성 조절·강화 손절",
        "fa_excess",
        0.10,
        0.20,
        0.08,
        0.06,
        volatility_scaled=True,
        cooldown_sessions=5,
        description="20일 변동성 역비례, 종목당 10%, 8%/6% 손절, 20% 밴드, 5거래일 재진입 금지.",
    ),
)


def _annualized_metrics(returns: pd.Series, turnovers: pd.Series, costs: pd.Series) -> dict:
    returns = returns.dropna().astype(float)
    turnovers = turnovers.reindex(returns.index).fillna(0.0)
    costs = costs.reindex(returns.index).fillna(0.0)
    equity = (1.0 + returns).cumprod()
    years = max(len(returns) / 252.0, 1.0 / 252.0)
    total_return = float(equity.iloc[-1] - 1.0)
    cagr = float(equity.iloc[-1] ** (1.0 / years) - 1.0)
    volatility = float(returns.std(ddof=1) * math.sqrt(252)) if len(returns) > 1 else 0.0
    sharpe = (
        float(returns.mean() / returns.std(ddof=1) * math.sqrt(252))
        if len(returns) > 1 and returns.std(ddof=1) > 0
        else 0.0
    )
    downside = returns[returns < 0]
    downside_vol = float(downside.std(ddof=1) * math.sqrt(252)) if len(downside) > 1 else 0.0
    sortino = float(returns.mean() * 252 / downside_vol) if downside_vol > 0 else 0.0
    drawdown = equity / equity.cummax() - 1.0
    max_drawdown = float(drawdown.min())
    calmar = float(cagr / abs(max_drawdown)) if max_drawdown < 0 else 0.0
    gains = float(returns[returns > 0].sum())
    losses = float(-returns[returns < 0].sum())
    return {
        "trading_days": int(len(returns)),
        "total_return": total_return,
        "cagr": cagr,
        "annual_volatility": volatility,
        "sharpe_zero_rf": sharpe,
        "sortino_zero_rf": sortino,
        "calmar": calmar,
        "max_drawdown": max_drawdown,
        "positive_day_rate": float((returns > 0).mean()),
        "profit_factor_daily": float(gains / losses) if losses > 0 else None,
        "best_day": float(returns.max()),
        "worst_day": float(returns.min()),
        "average_daily_turnover": float(turnovers.mean()),
        "annualized_turnover": float(turnovers.mean() * 252),
        "total_cost_ratio": float(costs.sum()),
        "final_equity_multiple": float(equity.iloc[-1]),
    }


def _cap_weights(raw: pd.Series, cap: float | None) -> pd.Series:
    raw = raw[raw > 0].astype(float)
    if raw.empty:
        return raw
    if cap is None:
        return raw / raw.sum() * EXPOSURE
    result = pd.Series(0.0, index=raw.index)
    remaining = set(raw.index)
    remaining_budget = min(EXPOSURE, cap * len(remaining))
    while remaining and remaining_budget > 1e-12:
        total = float(raw.loc[list(remaining)].sum())
        proposed = raw.loc[list(remaining)] / total * remaining_budget
        capped = proposed[proposed >= cap - 1e-12].index.tolist()
        if not capped:
            result.loc[proposed.index] = proposed
            break
        for ticker in capped:
            result.at[ticker] = cap
            remaining.remove(ticker)
            remaining_budget -= cap
    return result[result > 1e-12]


def _target_weights(
    universe: pd.DataFrame,
    eligible: list[str],
    variant: Variant,
    volatility: pd.Series,
) -> pd.Series:
    if not eligible:
        return pd.Series(dtype=float)
    frame = universe.loc[eligible]
    if variant.weight_method == "equal":
        raw = pd.Series(1.0, index=frame.index)
    else:
        raw = (frame["fa_score"].astype(float) - FA_MINIMUM).clip(lower=0.0)
        if float(raw.sum()) <= 0:
            raw = pd.Series(1.0, index=frame.index)
    if variant.volatility_scaled:
        stable_vol = volatility.reindex(raw.index).clip(lower=0.10, upper=0.80)
        raw = raw / stable_vol
        raw = raw.replace([np.inf, -np.inf], np.nan).dropna()
    return _cap_weights(raw, variant.max_weight)


def _apply_execution_model(
    current: pd.Series,
    requested_final: pd.Series,
    execution_model: dict | None,
    *,
    event_key: str = "",
) -> tuple[pd.Series, pd.Series, pd.Series]:
    requested_delta = requested_final - current
    if not execution_model:
        return (
            requested_final,
            requested_delta,
            pd.Series(1.0, index=requested_delta.index, dtype=float),
        )
    buy_fraction = float(execution_model["buy_fill_fraction"])
    sell_fraction = float(execution_model["sell_fill_fraction"])
    for key, value in (
        ("buy_fill_fraction", buy_fraction),
        ("sell_fill_fraction", sell_fraction),
    ):
        if not 0.0 <= value <= 1.0:
            raise ValueError(f"{key} must be between 0 and 1")
    if execution_model.get("application") == "DETERMINISTIC_BERNOULLI":
        code = str(execution_model.get("code") or "CUSTOM")
        values = []
        for ticker, requested in requested_delta.items():
            side = "BUY" if requested >= 0 else "SELL"
            probability = buy_fraction if side == "BUY" else sell_fraction
            raw = f"{code}:{event_key}:{ticker}:{side}".encode("utf-8")
            sample = int.from_bytes(hashlib.sha256(raw).digest()[:8], "big") / 2**64
            values.append(1.0 if sample < probability else 0.0)
        fill_fraction = pd.Series(values, index=requested_delta.index, dtype=float)
    else:
        fill_fraction = pd.Series(
            np.where(requested_delta >= 0, buy_fraction, sell_fraction),
            index=requested_delta.index,
            dtype=float,
        )
    delta = requested_delta * fill_fraction
    return current + delta, delta, fill_fraction


def _bootstrap_alpha_ci(alpha: pd.Series, *, block: int = 20, samples: int = 1000) -> tuple[float, float]:
    values = alpha.dropna().to_numpy(dtype=float)
    if len(values) < block:
        return float("nan"), float("nan")
    rng = np.random.default_rng(20260722)
    starts = np.arange(0, len(values) - block + 1)
    means = np.empty(samples)
    needed = math.ceil(len(values) / block)
    for idx in range(samples):
        picked = rng.choice(starts, size=needed, replace=True)
        sample = np.concatenate([values[start : start + block] for start in picked])[: len(values)]
        means[idx] = sample.mean() * 252
    return float(np.quantile(means, 0.025)), float(np.quantile(means, 0.975))


def _deflated_sharpe_probabilities(returns: pd.DataFrame) -> dict[str, float]:
    daily_sharpes = returns.mean() / returns.std(ddof=1)
    trials = max(len(daily_sharpes), 2)
    sharpe_std = float(daily_sharpes.std(ddof=1))
    normal = NormalDist()
    gamma = 0.5772156649015329
    expected_max = sharpe_std * (
        (1 - gamma) * normal.inv_cdf(1 - 1 / trials)
        + gamma * normal.inv_cdf(1 - 1 / (trials * math.e))
    )
    result = {}
    for code in returns:
        series = returns[code].dropna()
        sr = float(series.mean() / series.std(ddof=1)) if series.std(ddof=1) > 0 else 0.0
        skew = float(series.skew())
        kurtosis = float(series.kurt() + 3.0)
        denominator = math.sqrt(max(1 - skew * sr + ((kurtosis - 1) / 4) * sr * sr, 1e-12))
        z = (sr - expected_max) * math.sqrt(max(len(series) - 1, 1)) / denominator
        result[code] = float(normal.cdf(z))
    return result


def _cscv_pbo(returns: pd.DataFrame, blocks: int = 8) -> dict:
    if len(returns) < blocks * 20:
        return {"pbo": None, "combinations": 0, "reason": "insufficient observations"}
    slices = [chunk.index for chunk in np.array_split(returns, blocks)]
    bad = 0
    logits = []
    count = 0
    for chosen in itertools.combinations(range(blocks), blocks // 2):
        train_idx = np.concatenate([slices[i] for i in chosen])
        test_idx = np.concatenate([slices[i] for i in range(blocks) if i not in chosen])
        train = returns.loc[train_idx]
        test = returns.loc[test_idx]
        train_sr = train.mean() / train.std(ddof=1)
        test_sr = test.mean() / test.std(ddof=1)
        winner = train_sr.idxmax()
        relative_rank = float(test_sr.rank(method="average", pct=True).loc[winner])
        relative_rank = min(max(relative_rank, 1e-6), 1 - 1e-6)
        logits.append(math.log(relative_rank / (1 - relative_rank)))
        bad += relative_rank <= 0.5
        count += 1
    return {
        "pbo": float(bad / count),
        "combinations": count,
        "median_rank_logit": float(np.median(logits)),
        "blocks": blocks,
    }


def run_experiments(
    db: PostgreDB,
    *,
    pass_only: bool = False,
    execution_model: dict | None = None,
) -> tuple[dict, dict[str, pd.DataFrame]]:
    if execution_model:
        _apply_execution_model(
            pd.Series([0.0]), pd.Series([0.0]), execution_model
        )
    selections, prices = _load_replay_data(db)
    if pass_only:
        selections = selections[selections["status_code"].isin(["PASS", "PUBLISHED"])]
        if selections.empty:
            raise RuntimeError("no PASS/PUBLISHED replay selections")
    start = selections["effective_date"].min()
    end = min(selections["effective_date"].max() + pd.offsets.MonthEnd(1), prices.index.max())
    prices = prices.loc[:end].ffill(limit=3)
    asset_returns = prices.pct_change().fillna(0.0)
    ma20 = prices.rolling(20, min_periods=20).mean()
    ma60 = prices.rolling(60, min_periods=60).mean()
    mom20 = prices.pct_change(20)
    mom60 = prices.pct_change(60)
    vol20 = asset_returns.rolling(20, min_periods=20).std() * math.sqrt(252)
    kospi = download_kospi_index(
        (start - pd.Timedelta(days=400)).date().isoformat(),
        (end + pd.Timedelta(days=1)).date().isoformat(),
    ).reindex(prices.index).ffill()
    kospi_up = kospi > kospi.rolling(200, min_periods=200).mean()
    replay_by_date = {date: frame.set_index("stock_code") for date, frame in selections.groupby("effective_date")}
    calendar = prices.loc[start:end].index
    current_universe = pd.DataFrame()
    states = {
        variant.code: {
            "weights": pd.Series(dtype=float),
            "entry_prices": {},
            "peak_prices": {},
            "returns": [],
            "turnovers": [],
            "costs": [],
            "exposures": [],
            "stop_counts": {"hard": 0, "trailing": 0},
            "cooldown_until": {},
            "reentry_blocks": {},
            "reentry_blocked_sessions": 0,
            "confirmed_reentries": 0,
        }
        for variant in VARIANTS
    }
    event_rows: list[dict] = []

    for today in calendar:
        if today in replay_by_date:
            current_universe = replay_by_date[today]
        if current_universe.empty:
            continue
        for variant in VARIANTS:
            state = states[variant.code]
            weights = state["weights"]
            day_returns = asset_returns.loc[today].reindex(weights.index).fillna(0.0)
            gross_return = float((weights * day_returns).sum()) if not weights.empty else 0.0
            if not weights.empty and 1 + gross_return > 0:
                weights = weights * (1 + day_returns) / (1 + gross_return)

            stopped: dict[str, str] = {}
            for ticker in list(weights.index):
                price = float(prices.at[today, ticker]) if ticker in prices.columns and pd.notna(prices.at[today, ticker]) else 0.0
                if price <= 0:
                    continue
                entry = float(state["entry_prices"].get(ticker, price))
                peak = max(float(state["peak_prices"].get(ticker, price)), price)
                state["entry_prices"][ticker] = entry
                state["peak_prices"][ticker] = peak
                if variant.stop_loss is not None and price <= entry * (1 - variant.stop_loss):
                    stopped[ticker] = "HARD_STOP"
                    state["stop_counts"]["hard"] += 1
                    state["cooldown_until"][ticker] = calendar.get_loc(today) + variant.cooldown_sessions
                elif variant.trailing_stop is not None and peak > entry and price <= peak * (1 - variant.trailing_stop):
                    stopped[ticker] = "TRAILING_STOP"
                    state["stop_counts"]["trailing"] += 1
                    state["cooldown_until"][ticker] = calendar.get_loc(today) + variant.cooldown_sessions
                if ticker in stopped and variant.reentry_rule != "none":
                    state["reentry_blocks"][ticker] = {
                        "exit_price": price,
                        "exit_reason": stopped[ticker],
                        "confirm_streak": 0,
                    }

            eligible: list[str] = []
            if bool(kospi_up.get(today, False)):
                for ticker in current_universe.index:
                    if ticker in stopped or ticker not in prices.columns or pd.isna(ma60.at[today, ticker]):
                        continue
                    if calendar.get_loc(today) <= state["cooldown_until"].get(ticker, -1):
                        continue
                    held = float(weights.get(ticker, 0.0)) > 0.0
                    trend_ok = ma20.at[today, ticker] >= ma60.at[today, ticker]
                    entry_ok = prices.at[today, ticker] > ma60.at[today, ticker] and trend_ok and mom60.at[today, ticker] > 0
                    reentry = state["reentry_blocks"].get(ticker)
                    if not held and reentry is not None and variant.reentry_rule != "none":
                        rule_ok = bool(
                            prices.at[today, ticker] > float(reentry["exit_price"])
                            and prices.at[today, ticker] > ma20.at[today, ticker]
                        )
                        if variant.reentry_rule == "trend_rearm":
                            prior_ma20 = ma20[ticker].shift(1).get(today)
                            rule_ok = bool(
                                rule_ok
                                and pd.notna(prior_ma20)
                                and ma20.at[today, ticker] > prior_ma20
                                and mom20.at[today, ticker] > 0
                            )
                        reentry["confirm_streak"] = int(reentry["confirm_streak"] + 1) if rule_ok else 0
                        if reentry["confirm_streak"] < variant.reentry_confirm_sessions:
                            state["reentry_blocked_sessions"] += 1
                            continue
                    if (held and trend_ok) or (not held and entry_ok):
                        eligible.append(ticker)

            target = _target_weights(current_universe, eligible, variant, vol20.loc[today])
            union = weights.index.union(target.index)
            current = weights.reindex(union).fillna(0.0)
            desired = target.reindex(union).fillna(0.0)
            band = variant.rebalance_band
            rebalance = (desired == 0) | (current == 0) | (current < desired * (1 - band)) | (current > desired * (1 + band))
            requested_final = current.where(~rebalance, desired)
            requested_delta = requested_final - current
            final, delta, fill_fraction = _apply_execution_model(
                current,
                requested_final,
                execution_model,
                event_key=f"{today.date().isoformat()}:{variant.code}",
            )
            buy_turnover = float(delta.clip(lower=0.0).sum())
            sell_turnover = float(-delta.clip(upper=0.0).sum())
            cost = buy_turnover * BUY_COST + sell_turnover * SELL_COST
            state["returns"].append((today, gross_return - cost))
            state["turnovers"].append((today, buy_turnover + sell_turnover))
            state["costs"].append((today, cost))
            state["exposures"].append((today, float(final.sum())))

            for ticker in union[delta.abs() > 1e-10]:
                price = float(prices.at[today, ticker]) if ticker in prices.columns and pd.notna(prices.at[today, ticker]) else None
                event_reason = stopped.get(ticker, "REBALANCE" if current[ticker] > 0 else "ENTRY")
                if current[ticker] <= 1e-10 and final[ticker] > 1e-10 and ticker in state["reentry_blocks"]:
                    event_reason = "CONFIRMED_REENTRY"
                event_rows.append({
                    "date": today.date().isoformat(),
                    "variant": variant.code,
                    "ticker": ticker,
                    "previous_weight": float(current[ticker]),
                    "target_weight": float(final[ticker]),
                    "delta_weight": float(delta[ticker]),
                    "requested_delta_weight": float(requested_delta[ticker]),
                    "execution_fill_fraction": float(fill_fraction[ticker]),
                    "execution_model": (
                        str(execution_model.get("code") or "CUSTOM")
                        if execution_model
                        else "IDEAL_FULL_FILL"
                    ),
                    "price": price,
                    "reason": event_reason,
                })
                if final[ticker] <= 1e-10:
                    state["entry_prices"].pop(ticker, None)
                    state["peak_prices"].pop(ticker, None)
                elif current[ticker] <= 1e-10 and price:
                    state["entry_prices"][ticker] = price
                    state["peak_prices"][ticker] = price
                    if ticker in state["reentry_blocks"]:
                        state["reentry_blocks"].pop(ticker, None)
                        state["confirmed_reentries"] += 1
            state["weights"] = final[final > 1e-10]

    daily_returns = pd.DataFrame({code: pd.Series(dict(state["returns"])) for code, state in states.items()}).sort_index()
    daily_turnovers = pd.DataFrame({code: pd.Series(dict(state["turnovers"])) for code, state in states.items()}).reindex(daily_returns.index)
    daily_costs = pd.DataFrame({code: pd.Series(dict(state["costs"])) for code, state in states.items()}).reindex(daily_returns.index)
    daily_exposures = pd.DataFrame({code: pd.Series(dict(state["exposures"])) for code, state in states.items()}).reindex(daily_returns.index)

    summary = {}
    for variant in VARIANTS:
        metrics = _annualized_metrics(daily_returns[variant.code], daily_turnovers[variant.code], daily_costs[variant.code])
        metrics.update({
            "average_exposure": float(daily_exposures[variant.code].mean()),
            "hard_stop_count": states[variant.code]["stop_counts"]["hard"],
            "trailing_stop_count": states[variant.code]["stop_counts"]["trailing"],
            "reentry_blocked_sessions": states[variant.code]["reentry_blocked_sessions"],
            "confirmed_reentries": states[variant.code]["confirmed_reentries"],
        })
        summary[variant.code] = metrics

    period_rows = []
    for year, index in daily_returns.groupby(daily_returns.index.year).groups.items():
        for variant in VARIANTS:
            metrics = _annualized_metrics(
                daily_returns.loc[index, variant.code],
                daily_turnovers.loc[index, variant.code],
                daily_costs.loc[index, variant.code],
            )
            period_rows.append({"period": str(year), "variant": variant.code, **metrics})
    period_summary = pd.DataFrame(period_rows)

    comparison_rows = []
    baseline = daily_returns["A_CURRENT"]
    for variant in VARIANTS:
        alpha = daily_returns[variant.code] - baseline
        ci_low, ci_high = _bootstrap_alpha_ci(alpha)
        tracking_error = float(alpha.std(ddof=1) * math.sqrt(252))
        annual_alpha = float(alpha.mean() * 252)
        comparison_rows.append({
            "variant": variant.code,
            "annualized_alpha_vs_current": annual_alpha,
            "tracking_error_vs_current": tracking_error,
            "information_ratio_vs_current": annual_alpha / tracking_error if tracking_error > 0 else 0.0,
            "bootstrap_alpha_ci_low": ci_low,
            "bootstrap_alpha_ci_high": ci_high,
        })
    comparison = pd.DataFrame(comparison_rows)

    status_counts = selections.drop_duplicates("run_id")["status_code"].value_counts().to_dict()
    warning_share = float(status_counts.get("WARNING", 0) / max(sum(status_counts.values()), 1))
    data_quality = {
        "price_history_end": prices.index.max().date().isoformat(),
        "experiment_end": calendar.max().date().isoformat(),
        "selection_runs": int(selections["run_id"].nunique()),
        "selection_statuses": status_counts,
        "warning_run_share": warning_share,
        "price_tickers": int(prices.shape[1]),
        "calendar_days": int(len(calendar)),
        "price_missing_rate_after_fill": float(prices.loc[start:end].isna().mean().mean()),
        "kospi_missing_rate": float(kospi.loc[start:end].isna().mean()),
        "quality_grade": "LOW" if warning_share > 0.5 and not pass_only else "MEDIUM",
        "limitations": [
            (
                "Only PASS/PUBLISHED historical selection runs are included."
                if pass_only
                else "WARNING historical selection runs are included in the full-scope replay."
            ),
            "The latest available constituent price, not the current PAPER snapshot date, determines the experiment end.",
            "Daily closes and proportional weights approximate share-level fills and intraday stop execution.",
            (
                "Observed execution fill fractions are applied as expected partial fills; "
                "individual broker responses remain stochastic."
                if execution_model
                else "Broker rejections, ambiguous results, and partial fills are not represented in the ideal-fill scenario."
            ),
        ],
    }
    robustness = {
        "deflated_sharpe_probability": _deflated_sharpe_probabilities(daily_returns),
        "cscv": _cscv_pbo(daily_returns),
        "trial_count": len(VARIANTS),
        "notes": [
            "Deflated Sharpe uses the observed cross-variant Sharpe dispersion as the multiple-testing benchmark.",
            "CSCV uses eight contiguous blocks and ranks the in-sample winner in the complementary out-of-sample blocks.",
        ],
    }
    result = {
        "metadata": {
            "generated_at": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
            "period_start": calendar.min().date().isoformat(),
            "period_end": calendar.max().date().isoformat(),
            "pass_only": pass_only,
            "buy_cost_rate": BUY_COST,
            "sell_cost_rate": SELL_COST,
            "variant_definitions": [asdict(variant) for variant in VARIANTS],
            "execution_model": execution_model or {
                "code": "IDEAL_FULL_FILL",
                "buy_fill_fraction": 1.0,
                "sell_fill_fraction": 1.0,
            },
        },
        "summary": summary,
        "data_quality": data_quality,
        "robustness": robustness,
    }
    frames = {
        "daily_returns": daily_returns,
        "daily_turnovers": daily_turnovers,
        "daily_costs": daily_costs,
        "daily_exposures": daily_exposures,
        "events": pd.DataFrame(event_rows),
        "period_summary": period_summary,
        "comparison_vs_current": comparison,
    }
    return result, frames


def write_outputs(result: dict, frames: dict[str, pd.DataFrame], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "metrics.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    summary_rows = []
    labels = {variant.code: variant.label for variant in VARIANTS}
    for code, metrics in result["summary"].items():
        summary_rows.append({"variant": code, "label": labels[code], **metrics})
    pd.DataFrame(summary_rows).to_csv(output_dir / "summary.csv", index=False, encoding="utf-8-sig")
    for name, frame in frames.items():
        export = frame.copy()
        if isinstance(export.index, pd.DatetimeIndex):
            export.index.name = "date"
        export.to_csv(output_dir / f"{name}.csv", index=True, encoding="utf-8-sig")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", default="reports/analysis/paper_strategy_experiments/full")
    parser.add_argument("--pass-only", action="store_true")
    parser.add_argument("--execution-model-code")
    parser.add_argument("--buy-fill-fraction", type=float)
    parser.add_argument("--sell-fill-fraction", type=float)
    args = parser.parse_args()
    load_env()
    db = PostgreDB(build_db_config())
    try:
        provided_fractions = (
            args.buy_fill_fraction is not None
            and args.sell_fill_fraction is not None
        )
        if bool(args.execution_model_code) != provided_fractions:
            raise ValueError(
                "execution model code and both fill fractions must be provided together"
            )
        execution_model = None
        if args.execution_model_code:
            execution_model = {
                "code": args.execution_model_code,
                "buy_fill_fraction": args.buy_fill_fraction,
                "sell_fill_fraction": args.sell_fill_fraction,
            }
        result, frames = run_experiments(
            db, pass_only=args.pass_only, execution_model=execution_model
        )
    finally:
        db.close()
    write_outputs(result, frames, Path(args.output_dir))
    print(json.dumps({"metadata": result["metadata"], "summary": result["summary"], "data_quality": result["data_quality"], "robustness": result["robustness"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
