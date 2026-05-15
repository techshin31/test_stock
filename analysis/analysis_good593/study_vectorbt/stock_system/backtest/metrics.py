"""성과지표 계산

calc_metrics(pf, pf_bh, close_df, benchmark_series)
  → 절대 지표 + 상대 지표 dict

build_metrics_table(pf, pf_bh, close_df, profile, benchmark_series)
  → profile의 목표/경보 기준으로 상태(✓ ⚠ ✗) 포함 DataFrame
"""

import numpy as np
import pandas as pd
import vectorbt as vbt


def _calc_mdd_duration_months(equity: pd.Series) -> float:
    """드로다운 최장 지속 기간 (개월 수)"""
    in_dd = (equity / equity.cummax() - 1) < 0
    max_days = current = 0
    for d in in_dd:
        current  = current + 1 if d else 0
        max_days = max(max_days, current)
    return round(max_days / 21, 1)


def _calc_sortino(equity: pd.Series) -> float:
    dr = equity.pct_change().dropna()
    downside = dr[dr < 0].std() * np.sqrt(252)
    return dr.mean() * 252 / downside if downside > 1e-12 else np.nan


def calc_metrics(
    pf: vbt.Portfolio,
    pf_bh: vbt.Portfolio,
    close_df: pd.DataFrame,
    benchmark_series: pd.Series = None,
) -> dict:
    """성과 지표 계산

    Parameters
    ----------
    pf               : 전략 포트폴리오
    pf_bh            : Buy & Hold 포트폴리오
    close_df         : 주식 종가 (ETF 제외)
    benchmark_series : KOSPI 지수 (None이면 상대 지표 생략)

    Returns
    -------
    절대 지표: cagr, mdd, mdd_duration, calmar, sortino
    상대 지표: alpha, beta, mdd_reduction, calmar_improvement, info_ratio, win_rate
    """
    equity = pf.value()
    n_years = max((equity.index[-1] - equity.index[0]).days / 365.25, 1e-6)

    cagr   = (equity.iloc[-1] / equity.iloc[0]) ** (1 / n_years) - 1
    mdd    = (equity / equity.cummax() - 1).min()
    calmar = cagr / abs(mdd) if mdd < 0 else np.nan
    sortino = _calc_sortino(equity)
    mdd_duration = _calc_mdd_duration_months(equity)

    result = {
        "cagr":         cagr,
        "mdd":          mdd,
        "mdd_duration": mdd_duration,
        "calmar":       calmar,
        "sortino":      sortino,
    }

    if benchmark_series is not None:
        bm = benchmark_series.reindex(equity.index, method="ffill").dropna()
        eq, bm = equity.align(bm, join="inner")
        eq = eq / eq.iloc[0]
        bm = bm / bm.iloc[0]

        n_y    = max(len(eq) / 252, 1e-6)
        eq_ret = eq.pct_change().dropna()
        bm_ret = bm.pct_change().dropna()
        eq_ret, bm_ret = eq_ret.align(bm_ret, join="inner")

        eq_cagr = eq.iloc[-1] ** (1 / n_y) - 1
        bm_cagr = bm.iloc[-1] ** (1 / n_y) - 1
        alpha   = eq_cagr - bm_cagr

        cov  = np.cov(eq_ret.values, bm_ret.values)
        beta = cov[0, 1] / cov[1, 1] if cov[1, 1] > 1e-12 else np.nan

        excess  = eq_ret - bm_ret
        ir      = excess.mean() / excess.std() * np.sqrt(252) if excess.std() > 1e-12 else np.nan

        eq_mdd = (eq / eq.cummax() - 1).min()
        bm_mdd = (bm / bm.cummax() - 1).min()
        mdd_reduction = (bm_mdd - eq_mdd) / abs(bm_mdd) if abs(bm_mdd) > 1e-12 else np.nan

        eq_calmar = eq_cagr / abs(eq_mdd) if eq_mdd < 0 else np.nan
        bm_calmar = bm_cagr / abs(bm_mdd) if bm_mdd < 0 else np.nan
        calmar_improvement = (
            eq_calmar - bm_calmar
            if not (np.isnan(eq_calmar) or np.isnan(bm_calmar))
            else np.nan
        )

        # 승률: 월별 수익률 기준
        monthly = equity.resample("M").last().pct_change().dropna()
        win_rate = (monthly > 0).mean() if len(monthly) > 0 else np.nan

        result.update({
            "alpha":              alpha,
            "beta":               beta,
            "mdd_reduction":      mdd_reduction,
            "calmar_improvement": calmar_improvement,
            "info_ratio":         ir,
            "win_rate":           win_rate,
        })

    return result


def build_metrics_table(
    pf: vbt.Portfolio,
    pf_bh: vbt.Portfolio,
    close_df: pd.DataFrame,
    profile,
    benchmark_series: pd.Series = None,
) -> pd.DataFrame:
    """profile 목표/경보 기준으로 상태 포함 성과 테이블

    Parameters
    ----------
    profile : profiles.neutral 또는 profiles.aggressive 모듈

    Returns
    -------
    DataFrame  컬럼: 지표명 | 전략값 | B&H값 | 목표 | 경보선 | 상태
    """
    metrics    = calc_metrics(pf, pf_bh, close_df, benchmark_series)
    metrics_bh = calc_metrics(pf_bh, pf_bh, close_df, benchmark_series)

    target = profile.METRICS_TARGET
    alert  = profile.METRICS_ALERT
    profile_name = getattr(profile, "__name__", "").split(".")[-1]

    # 지표별 표시 포맷 + 높을수록 좋은지 여부
    META = {
        "cagr":              ("CAGR",       True,  "{:.2%}"),
        "mdd":               ("MDD",        False, "{:.2%}"),
        "mdd_duration":      ("MDD기간(월)", False, "{:.1f}"),
        "calmar":            ("Calmar",     True,  "{:.2f}"),
        "sortino":           ("Sortino",    True,  "{:.2f}"),
        "alpha":             ("Alpha",      True,  "{:+.2%}"),
        "beta":              ("Beta",       False, "{:.2f}"),
        "mdd_reduction":     ("MDD감소율",  True,  "{:.2%}"),
        "calmar_improvement":("Calmar개선", True,  "{:+.2f}"),
        "info_ratio":        ("IR",         True,  "{:.2f}"),
        "win_rate":          ("승률",       True,  "{:.2%}"),
    }

    def _status(key: str, val: float) -> str:
        if np.isnan(val):
            return "—"
        t = target.get(key)
        a = alert.get(key)
        higher_is_better = META[key][1]
        if t is None or a is None:
            return "—"
        if higher_is_better:
            if val >= t:
                return "✓"
            if val >= a:
                return "⚠"
            return "✗"
        else:
            if val <= t:
                return "✓"
            if val <= a:
                return "⚠"
            return "✗"

    rows = []
    for key, (label, _, fmt) in META.items():
        val    = metrics.get(key, np.nan)
        val_bh = metrics_bh.get(key, np.nan)
        t_val  = target.get(key, np.nan)
        a_val  = alert.get(key, np.nan)

        def _f(v, fmt=fmt):
            try:
                return fmt.format(v) if not np.isnan(v) else "N/A"
            except Exception:
                return "N/A"

        rows.append({
            "지표":    label,
            f"{profile_name} 전략": _f(val),
            "B&H":    _f(val_bh),
            "목표":   _f(t_val) if not np.isnan(t_val) else "—",
            "경보선": _f(a_val) if not np.isnan(a_val) else "—",
            "상태":   _status(key, val),
        })

    return pd.DataFrame(rows).set_index("지표")
