"""성과지표 계산 — 절대 지표 + 벤치마크 상대 지표 (Alpha, Beta, IR, MDD감소율)"""

import numpy as np
import pandas as pd
import vectorbt as vbt


def calc_metrics(equity: pd.Series, label: str, n_years: float) -> dict:
    """단일 자산곡선의 핵심 성과지표 계산 (절대값)"""
    total  = equity.iloc[-1] / equity.iloc[0] - 1
    cagr   = (equity.iloc[-1] / equity.iloc[0]) ** (1 / n_years) - 1
    dr     = equity.pct_change().dropna()
    vol    = dr.std() * np.sqrt(252)
    sharpe = dr.mean() / dr.std() * np.sqrt(252) if dr.std() > 0 else np.nan
    mdd    = (equity / equity.cummax() - 1).min()
    calmar = cagr / abs(mdd) if mdd < 0 else np.nan
    return {
        "전략":        label,
        "총 수익률":   f"{total:.2%}",
        "CAGR":       f"{cagr:.2%}",
        "연간 변동성": f"{vol:.2%}",
        "샤프비율":    f"{sharpe:.2f}",
        "MDD":        f"{mdd:.2%}",
        "Calmar":      f"{calmar:.2f}" if not np.isnan(calmar) else "N/A",
    }


def _calc_sortino(equity: pd.Series) -> float:
    dr = equity.pct_change().dropna()
    downside_std = dr[dr < 0].std() * np.sqrt(252)
    return dr.mean() * 252 / downside_std if downside_std > 1e-12 else np.nan


def calc_relative_metrics(
    equity: pd.Series,
    benchmark: pd.Series,
    label: str,
) -> dict:
    """벤치마크 대비 상대 성과지표

    Parameters
    ----------
    equity    : 전략 자산곡선
    benchmark : 벤치마크 자산곡선
    label     : 행 이름

    Returns
    -------
    dict: Alpha, Beta, IR, MDD감소율, Calmar개선, Sortino개선
    """
    eq, bm = equity.align(benchmark, join="inner")
    eq = eq / eq.iloc[0]
    bm = bm / bm.iloc[0]

    n_years = max(len(eq) / 252, 1e-6)

    eq_ret = eq.pct_change().dropna()
    bm_ret = bm.pct_change().dropna()
    eq_ret, bm_ret = eq_ret.align(bm_ret, join="inner")

    eq_cagr = eq.iloc[-1] ** (1 / n_years) - 1
    bm_cagr = bm.iloc[-1] ** (1 / n_years) - 1
    alpha   = eq_cagr - bm_cagr

    cov  = np.cov(eq_ret.values, bm_ret.values)
    beta = cov[0, 1] / cov[1, 1] if cov[1, 1] > 1e-12 else np.nan

    excess = eq_ret - bm_ret
    ir = excess.mean() / excess.std() * np.sqrt(252) if excess.std() > 1e-12 else np.nan

    eq_mdd = (eq / eq.cummax() - 1).min()
    bm_mdd = (bm / bm.cummax() - 1).min()
    mdd_reduction = (bm_mdd - eq_mdd) / abs(bm_mdd) if abs(bm_mdd) > 1e-12 else np.nan

    eq_calmar = eq_cagr / abs(eq_mdd) if eq_mdd < 0 else np.nan
    bm_calmar = bm_cagr / abs(bm_mdd) if bm_mdd < 0 else np.nan
    calmar_diff = (
        eq_calmar - bm_calmar
        if not (np.isnan(eq_calmar) or np.isnan(bm_calmar))
        else np.nan
    )

    eq_sortino  = _calc_sortino(equity)
    bm_sortino  = _calc_sortino(benchmark)
    sortino_diff = (
        eq_sortino - bm_sortino
        if not (np.isnan(eq_sortino) or np.isnan(bm_sortino))
        else np.nan
    )

    def _f(v, pct=False):
        if isinstance(v, float) and np.isnan(v):
            return "N/A"
        return f"{v:+.2%}" if pct else f"{v:+.2f}"

    return {
        "전략":          label,
        "Alpha(연환산)": _f(alpha, pct=True),
        "Beta":          f"{beta:.2f}" if not np.isnan(beta) else "N/A",
        "IR":            _f(ir),
        "MDD감소율":     _f(mdd_reduction, pct=True),
        "Calmar개선":    _f(calmar_diff),
        "Sortino개선":   _f(sortino_diff),
    }


def build_metrics_table(
    pf_09: vbt.Portfolio,
    pf_bh: vbt.Portfolio,
    close_df: pd.DataFrame,
    benchmark_series: pd.Series | None = None,
) -> pd.DataFrame:
    """전략 vs Buy&Hold 성과 비교 테이블 (절대 + 상대 지표)

    Parameters
    ----------
    benchmark_series : 벤치마크 지수 시리즈 (예: KOSPI).
                       None이면 균등 B&H를 벤치마크로 사용.
    """
    names  = list(close_df.columns)
    val_09 = pf_09.value()
    val_bh = pf_bh.value()
    init   = val_09.iloc[0]

    # pf_09 기간 기준으로 bh 정규화 (WF는 훈련 기간 이후부터 시작)
    bh_norm = val_bh.reindex(val_09.index, method="ffill")
    bh_norm = bh_norm / bh_norm.iloc[0] * init

    if benchmark_series is not None:
        bm_aligned = benchmark_series.reindex(val_09.index, method="ffill").dropna()
        bm_for_rel = bm_aligned / bm_aligned.iloc[0] * init
        bm_label   = benchmark_series.name or "벤치마크"
    else:
        bm_for_rel = bh_norm
        bm_label   = None

    targets = [
        (bh_norm, f"{len(names)}종목 균등 B&H"),
        (val_09,  "★ 위험중립형 포트"),
    ]
    if bm_label:
        targets.insert(0, (bm_for_rel, f"◆ {bm_label} (벤치마크)"))
    for name in names:
        s = close_df[name].reindex(val_09.index, method="ffill")
        targets.append((s / s.iloc[0] * init, f"  {name} 단독 B&H"))

    # 각 equity 시리즈의 실제 기간으로 n_years를 개별 계산
    abs_rows = [
        calc_metrics(eq, lbl, (eq.index[-1] - eq.index[0]).days / 365.25)
        for eq, lbl in targets
    ]
    rel_rows = [calc_relative_metrics(eq, bm_for_rel, lbl) for eq, lbl in targets]

    df_abs = pd.DataFrame(abs_rows).set_index("전략")
    df_rel = pd.DataFrame(rel_rows).set_index("전략")

    return pd.concat([df_abs, df_rel], axis=1)
