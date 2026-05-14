"""성과지표 계산 — CAGR, MDD, Sharpe, Sortino, Calmar, Profit Factor, 승률"""

import numpy as np
import pandas as pd
import vectorbt as vbt


def calc_metrics(equity: pd.Series, label: str, n_years: float) -> dict:
    """단일 자산곡선의 핵심 성과지표 계산"""
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


def build_metrics_table(
    pf_09: vbt.Portfolio,
    pf_bh: vbt.Portfolio,
    pf_bh_ss: vbt.Portfolio,
    close_df: pd.DataFrame,
    bh_ss_name: str = "삼성전자",
) -> pd.DataFrame:
    """전략 vs Buy&Hold 성과 비교 테이블

    Parameters
    ----------
    pf_09      : 09번 포트폴리오
    pf_bh      : 균등 B&H 포트폴리오
    pf_bh_ss   : 단일 종목 B&H (기준 종목)
    close_df   : 전체 종가 DataFrame
    bh_ss_name : pf_bh_ss에 해당하는 종목명
    """
    n_years = (close_df.index[-1] - close_df.index[0]).days / 365.25
    names = list(close_df.columns)

    val_09 = pf_09.value()
    val_bh = pf_bh.value()
    init   = val_09.iloc[0]

    bh_norm    = val_bh / val_bh.iloc[0] * init
    bh_ss_val  = pf_bh_ss.value()
    bh_ss_norm = bh_ss_val / bh_ss_val.iloc[0] * init

    rows = [
        calc_metrics(bh_ss_norm, f"{bh_ss_name} 단독 B&H", n_years),
        calc_metrics(bh_norm,    f"{len(names)}종목 균등 B&H", n_years),
        calc_metrics(val_09,     "★ 09번 포트폴리오", n_years),
    ]
    for name in names:
        s = close_df[name]
        rows.append(calc_metrics(s / s.iloc[0] * init, f"  {name} 단독 B&H", n_years))

    return pd.DataFrame(rows).set_index("전략")
