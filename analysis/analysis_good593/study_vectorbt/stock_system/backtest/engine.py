"""백테스팅 실행 엔진 (vectorbt 전용)

공개 API:
  run_walk_forward(profile, close_df, ...)  투자성향 파라미터로 WF 백테스팅
  run_bh_portfolio(close_df, ...)           균등 비중 Buy & Hold
"""

import itertools

import numpy as np
import pandas as pd
import vectorbt as vbt

from ..portfolio import add_cash_etf
from ..rotation import RotationManager, build_rotated_size_df


# ── 백테스트 실행 (내부용) ────────────────────────────────────────────────────

def _run_portfolio_backtest(
    close_df: pd.DataFrame,
    size_df: pd.DataFrame,
    fees: float = 0.0015,
    slippage: float = 0.001,
    init_cash: float = 1_000_000,
) -> vbt.Portfolio:
    return vbt.Portfolio.from_orders(
        close_df,
        size=size_df,
        size_type="targetpercent",
        group_by=True,
        cash_sharing=True,
        fees=fees,
        slippage=slippage,
        init_cash=init_cash,
        freq="D",
    )


# ── Buy & Hold ────────────────────────────────────────────────────────────────

def run_bh_portfolio(
    close_df: pd.DataFrame,
    fees: float = 0.0015,
    slippage: float = 0.001,
    init_cash: float = 1_000_000,
    start_date=None,
) -> vbt.Portfolio:
    """균등 비중 Buy & Hold (start_date 또는 첫날 1/N씩 매수)"""
    if start_date is not None:
        close_df = close_df[close_df.index >= start_date]
    n = close_df.shape[1]
    bh_size = pd.DataFrame(np.nan, index=close_df.index, columns=close_df.columns)
    bh_size.iloc[0] = 1.0 / n
    return _run_portfolio_backtest(close_df, bh_size, fees=fees, slippage=slippage,
                                   init_cash=init_cash)


# ── Walk-Forward (내부용) ─────────────────────────────────────────────────────

def _score_equity(equity: pd.Series, metric: str) -> float:
    if len(equity) < 10:
        return np.nan
    n_years = max((equity.index[-1] - equity.index[0]).days / 365.25, 1e-6)
    cagr    = (equity.iloc[-1] / equity.iloc[0]) ** (1 / n_years) - 1
    mdd     = (equity / equity.cummax() - 1).min()
    dr      = equity.pct_change().dropna()
    if metric == "calmar_ratio":
        return cagr / abs(mdd) if mdd < 0 else np.nan
    if metric == "sharpe_ratio":
        return dr.mean() / dr.std() * np.sqrt(252) if dr.std() > 1e-12 else np.nan
    if metric == "total_return":
        return equity.iloc[-1] / equity.iloc[0] - 1
    return np.nan


def _walk_forward_portfolio(
    profile,
    close_df: pd.DataFrame,
    high_df: pd.DataFrame,
    low_df: pd.DataFrame,
    param_grid: dict,
    train_months: int = 12,
    test_months: int = 3,
    fees: float = 0.0015,
    slippage: float = 0.001,
    init_cash: float = 1_000_000,
    metric: str = "calmar_ratio",
    warmup_days: int = 150,
    min_momentum: float = 0.0,
    kospi: pd.Series = None,
    cash_etf: pd.Series = None,
    rotation_plans: list = None,
) -> tuple:
    """IS 12개월 학습 → OOS test_months 적용 슬라이딩 WF (종목별 독립 그리드 서치)

    Returns
    -------
    pf      : vbt.Portfolio
    wf_info : dict (windows, n_windows, close_df_all, names_all)
    """
    idx    = close_df.index
    names  = list(close_df.columns)
    keys   = list(param_grid.keys())
    combos = list(itertools.product(*param_grid.values()))
    default_params = {k: vals[len(vals) // 2] for k, vals in param_grid.items()}
    manager        = RotationManager()

    windows      = []
    period_start = idx[0]
    full_size_df = pd.DataFrame(np.nan, index=idx, columns=close_df.columns)

    while True:
        train_end = period_start + pd.DateOffset(months=train_months)
        test_end  = train_end   + pd.DateOffset(months=test_months)

        if test_end > idx[-1] + pd.Timedelta(days=1):
            break

        train_mask = (idx >= period_start) & (idx < train_end)
        test_mask  = (idx >= train_end)    & (idx < test_end)

        if train_mask.sum() < 130 or test_mask.sum() < 5:
            period_start += pd.DateOffset(months=test_months)
            continue

        # ── 0. rotation 적용 ──────────────────────────────────────────────────
        if rotation_plans:
            for plan in rotation_plans:
                if period_start <= pd.Timestamp(plan.review_date) < train_end:
                    manager.apply_plan(plan, idx)

        sell_only    = set(manager.get_sell_only())
        active_names = [n for n in names if n not in sell_only]

        tr_close = close_df[train_mask]
        tr_high  = high_df[train_mask]
        tr_low   = low_df[train_mask]

        # ── 1. 학습: 종목별 독립 그리드 서치 ──────────────────────────────────
        per_stock_params = {}

        for name in active_names:
            best_score_s  = -np.inf
            best_params_s = None

            for combo in combos:
                params = dict(zip(keys, combo))
                try:
                    _, _, size_s, _ = profile.make_signals(
                        tr_close[name], tr_high[name], tr_low[name],
                        adx_threshold=params.get("adx_threshold", 25.0),
                        adx_sideways=params.get("adx_sideways", 20.0),
                        kospi=kospi,
                        use_adx_mode=True,
                    )
                    pf_s  = _run_portfolio_backtest(
                        tr_close[[name]], size_s.to_frame(name),
                        fees=fees, slippage=slippage, init_cash=init_cash,
                    )
                    score = _score_equity(pf_s.value(), metric)
                    if np.isfinite(score) and score > best_score_s:
                        best_score_s  = score
                        best_params_s = params
                except Exception:
                    continue

            if best_params_s is None:
                prev = windows[-1]["per_stock"].get(name, {}) if windows else {}
                best_params_s = prev.get("best_params") or default_params

            per_stock_params[name] = {
                "best_params":  best_params_s,
                "use_adx_mode": bool(np.isfinite(best_score_s) and best_score_s > 0),
                "best_score":   round(best_score_s, 4) if np.isfinite(best_score_s) else np.nan,
            }

        # ── 2. warmup 버퍼 포함 신호 계산 ────────────────────────────────────
        warmup_start = train_end - pd.Timedelta(days=int(warmup_days * 1.5))
        warmup_start = max(warmup_start, idx[0])
        wu_mask      = (idx >= warmup_start) & (idx < test_end)

        try:
            sz_wu, _ = build_rotated_size_df(
                manager,
                profile,
                close_df[wu_mask], high_df[wu_mask], low_df[wu_mask],
                per_stock_params=per_stock_params,
                min_momentum=min_momentum,
                kospi=kospi,
            )
            test_dates = close_df[test_mask].index
            full_size_df.loc[test_dates] = sz_wu.reindex(test_dates).values
        except Exception:
            period_start += pd.DateOffset(months=test_months)
            continue

        # ── 3. 테스트 구간 내 강제 청산 완료된 종목 정리 ──────────────────────
        test_end_dt = close_df[test_mask].index[-1]
        for name in list(manager.get_sell_only()):
            deadline = manager.get_force_close_date(name)
            if deadline is not None and deadline <= test_end_dt:
                manager.complete_exit(name)

        windows.append({
            "train_start": period_start,
            "train_end":   train_end,
            "test_start":  close_df[test_mask].index[0],
            "test_end":    close_df[test_mask].index[-1],
            "per_stock":   per_stock_params,
        })

        period_start += pd.DateOffset(months=test_months)

    # ── 검증 구간 시작부터 포트폴리오 운용 ──────────────────────────────────────
    first_test = windows[0]["test_start"] if windows else idx[0]
    active_idx = idx[idx >= first_test]

    close_used = close_df.loc[active_idx]
    high_used  = high_df.loc[active_idx]
    low_used   = low_df.loc[active_idx]
    size_used  = full_size_df.loc[active_idx]

    if cash_etf is not None:
        size_used, close_all, _, _ = add_cash_etf(
            size_used, close_used, high_used, low_used, cash_etf
        )
    else:
        close_all = close_used

    pf = _run_portfolio_backtest(close_all, size_used, fees=fees, slippage=slippage,
                                 init_cash=init_cash)

    wf_info = {
        "windows":      windows,
        "n_windows":    len(windows),
        "close_df_all": close_all,
        "names_all":    list(close_all.columns),
    }
    return pf, wf_info


# ── 공개 API ──────────────────────────────────────────────────────────────────

def run_walk_forward(
    profile,
    close_df: pd.DataFrame,
    high_df: pd.DataFrame,
    low_df: pd.DataFrame,
    **kwargs,
) -> tuple:
    """투자성향 파라미터로 포트폴리오 Walk-Forward 백테스팅 실행

    Parameters
    ----------
    profile : profiles 모듈 (get_profile("neutral") 반환값)
    """
    return _walk_forward_portfolio(
        profile,
        close_df, high_df, low_df,
        param_grid=profile.ADX_PARAM_GRID,
        train_months=profile.WF_TRAIN_MONTHS,
        test_months=profile.WF_TEST_MONTHS,
        fees=profile.FEES,
        slippage=profile.SLIPPAGE,
        min_momentum=profile.MIN_MOMENTUM,
        metric="calmar_ratio",
        **kwargs,
    )
