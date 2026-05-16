"""성과 지표 계산 — 순수 계산 함수"""

import numpy as np
import pandas as pd
import vectorbt as vbt


def _calc_mdd_duration_months(equity: pd.Series) -> float:
    """드로다운 최장 지속 기간 (개월 수)"""
    in_dd    = (equity / equity.cummax() - 1) < 0
    max_days = in_dd.groupby((~in_dd).cumsum()).sum().max()
    return round(max_days / 21, 1)


def _calc_sortino(equity: pd.Series) -> float:
    dr       = equity.pct_change().dropna()
    downside = dr[dr < 0].std() * np.sqrt(252)
    return dr.mean() * 252 / downside if downside > 1e-12 else np.nan


def _calc_equity_metrics(equity: pd.Series) -> dict:
    """가격/자산 시리즈에서 절대 지표 계산 (단기채·KOSPI·B&H 비교용)"""
    n_years  = max((equity.index[-1] - equity.index[0]).days / 365.25, 1e-6)
    cagr     = (equity.iloc[-1] / equity.iloc[0]) ** (1 / n_years) - 1
    mdd      = (equity / equity.cummax() - 1).min()
    calmar   = cagr / abs(mdd) if mdd < 0 else np.nan
    sortino  = _calc_sortino(equity)
    mdd_dur  = _calc_mdd_duration_months(equity)
    monthly  = equity.resample("M").last().pct_change().dropna()
    win_rate = (monthly > 0).mean() if len(monthly) > 0 else np.nan
    return {
        "cagr":         cagr,
        "mdd":          mdd,
        "mdd_duration": mdd_dur,
        "calmar":       calmar,
        "sortino":      sortino,
        "win_rate":     win_rate,
    }


def calc_metrics(
    pf: vbt.Portfolio,
    close_df: pd.DataFrame,
    benchmark_series: pd.Series = None,
) -> dict:
    """전략 포트폴리오 성과 지표 계산

    Parameters
    ----------
    pf               : 전략 포트폴리오
    close_df         : 주식 종가 (참고용, 현재 미사용)
    benchmark_series : KOSPI 지수 (None이면 상대 지표 생략)

    Returns
    -------
    절대 지표: cagr, mdd, mdd_duration, calmar, sortino, win_rate
    상대 지표: alpha, beta, mdd_reduction, calmar_improvement, info_ratio
    """
    equity = pf.value()
    result = _calc_equity_metrics(equity)

    if benchmark_series is not None:
        bm      = benchmark_series.reindex(equity.index, method="ffill").dropna()
        eq, bm  = equity.align(bm, join="inner")
        eq      = eq / eq.iloc[0]
        bm      = bm / bm.iloc[0]

        n_y     = max(len(eq) / 252, 1e-6)
        eq_ret  = eq.pct_change().dropna()
        bm_ret  = bm.pct_change().dropna()
        eq_ret, bm_ret = eq_ret.align(bm_ret, join="inner")

        eq_cagr = eq.iloc[-1] ** (1 / n_y) - 1
        bm_cagr = bm.iloc[-1] ** (1 / n_y) - 1
        alpha   = eq_cagr - bm_cagr

        cov  = np.cov(eq_ret.values, bm_ret.values)
        beta = cov[0, 1] / cov[1, 1] if cov[1, 1] > 1e-12 else np.nan

        excess = eq_ret - bm_ret
        ir     = excess.mean() / excess.std() * np.sqrt(252) if excess.std() > 1e-12 else np.nan

        eq_mdd        = (eq / eq.cummax() - 1).min()
        bm_mdd        = (bm / bm.cummax() - 1).min()
        mdd_reduction = (eq_mdd - bm_mdd) / abs(bm_mdd) if abs(bm_mdd) > 1e-12 else np.nan

        eq_calmar = eq_cagr / abs(eq_mdd) if eq_mdd < 0 else np.nan
        bm_calmar = bm_cagr / abs(bm_mdd) if bm_mdd < 0 else np.nan
        calmar_improvement = (
            eq_calmar - bm_calmar
            if not (np.isnan(eq_calmar) or np.isnan(bm_calmar))
            else np.nan
        )

        result.update({
            "alpha":              alpha,
            "beta":               beta,
            "mdd_reduction":      mdd_reduction,
            "calmar_improvement": calmar_improvement,
            "info_ratio":         ir,
        })

    return result
