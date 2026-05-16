"""성과 보고서 생성 — 지표 테이블"""

import numpy as np
import pandas as pd
import vectorbt as vbt

from .calc import calc_metrics, _calc_equity_metrics


# 지표별 표시 라벨·방향·포맷
# higher_is_better:
#   True  → 값이 클수록 좋음 (CAGR, Calmar, MDD 등)
#   False → 값이 작을수록 좋음 (MDD기간, Beta)
META = {
    "cagr":              ("CAGR",               True,  "{:.2%}"),
    "mdd":               ("MDD",                True,  "{:.2%}"),   # 덜 음수 = 더 좋음
    "mdd_duration":      ("MDD기간(월)",          False, "{:.1f}"),
    "calmar":            ("Calmar",              True,  "{:.2f}"),
    "sortino":           ("Sortino",             True,  "{:.2f}"),
    "alpha":             ("Alpha(vs KOSPI)",     True,  "{:+.2%}"),
    "beta":              ("Beta",                False, "{:.2f}"),
    "mdd_reduction":     ("MDD감소율(vs KOSPI)",  True,  "{:.2%}"),
    "calmar_improvement":("Calmar개선",           True,  "{:+.2f}"),
    "info_ratio":        ("IR(vs KOSPI)",        True,  "{:.2f}"),
    "win_rate":          ("승률",                True,  "{:.2%}"),
}

# 비교 대상(단기채·B&H·KOSPI)에 표시할 절대 지표만
ABS_KEYS = {"cagr", "mdd", "mdd_duration", "calmar", "sortino", "win_rate"}


def build_metrics_table(
    pf: vbt.Portfolio,
    close_df: pd.DataFrame,
    profile,
    benchmark_series: pd.Series = None,
    etf_series: pd.Series = None,
    pf_bh: vbt.Portfolio = None,
) -> pd.DataFrame:
    """profile 목표/경보 기준으로 상태 포함 성과 테이블

    비교 대상 컬럼:
      etf_series 있음 → 단기채 100% 컬럼  (위험중립형)
      pf_bh      있음 → B&H 컬럼          (적극투자형)
    KOSPI 컬럼은 benchmark_series가 있으면 항상 표시.
    """
    equity       = pf.value()
    metrics      = calc_metrics(pf, close_df, benchmark_series)
    target       = profile.METRICS_TARGET
    alert        = profile.METRICS_ALERT
    profile_name = getattr(profile, "__name__", "").split(".")[-1]

    # ── 비교 대상 지표 ─────────────────────────────────────────────────────
    def _align_metrics(series: pd.Series) -> dict:
        eq = series.reindex(equity.index, method="ffill").dropna()
        eq = eq / eq.iloc[0] * equity.iloc[0]
        return _calc_equity_metrics(eq)

    cmp_m, cmp_label = {}, None
    if etf_series is not None:
        cmp_m, cmp_label = _align_metrics(etf_series), "단기채 100%"
    elif pf_bh is not None:
        cmp_m, cmp_label = _calc_equity_metrics(pf_bh.value()), "B&H"

    bm_m = _align_metrics(benchmark_series) if benchmark_series is not None else {}

    # ── 상태 판별 ──────────────────────────────────────────────────────────
    def _status(key: str, val: float) -> str:
        if np.isnan(val):
            return "—"
        t = target.get(key)
        a = alert.get(key)
        if t is None or a is None:
            return "—"
        if META[key][1]:  # higher_is_better
            return "✓" if val >= t else ("⚠" if val >= a else "✗")
        else:
            return "✓" if val <= t else ("⚠" if val <= a else "✗")

    def _fmt(v: float, fmt: str) -> str:
        try:
            return fmt.format(v) if not np.isnan(v) else "N/A"
        except Exception:
            return "N/A"

    # ── 테이블 행 구성 ─────────────────────────────────────────────────────
    rows = []
    for key, (label, _, fmt) in META.items():
        val    = metrics.get(key, np.nan)
        cmp_v  = cmp_m.get(key, np.nan) if key in ABS_KEYS else np.nan
        bm_v   = bm_m.get(key,  np.nan) if key in ABS_KEYS else np.nan
        t_val  = target.get(key, np.nan)
        a_val  = alert.get(key,  np.nan)

        row = {
            "지표":                  label,
            f"{profile_name} 전략":  _fmt(val, fmt),
            "목표":                  _fmt(t_val, fmt) if not np.isnan(t_val) else "—",
            "경보선":                _fmt(a_val, fmt) if not np.isnan(a_val) else "—",
            "상태":                  _status(key, val),
        }
        if cmp_label:
            row[cmp_label] = _fmt(cmp_v, fmt) if not np.isnan(cmp_v) else "—"
        if bm_m:
            row["KOSPI"] = _fmt(bm_v, fmt) if not np.isnan(bm_v) else "—"

        rows.append(row)

    # ── 컬럼 순서 정렬 ─────────────────────────────────────────────────────
    col_order = ["지표", f"{profile_name} 전략"]
    if cmp_label:
        col_order.append(cmp_label)
    if bm_m:
        col_order.append("KOSPI")
    col_order += ["목표", "경보선", "상태"]

    return pd.DataFrame(rows).set_index("지표")[
        [c for c in col_order if c != "지표"]
    ]


def build_period_stats_table(
    pf: vbt.Portfolio,
    pf_bh: vbt.Portfolio,
    benchmark_series: pd.Series = None,
    freq: str = "Y",
    profile_name: str = "전략",
) -> pd.DataFrame:
    """기간별(연/분기/월) 수익률 비교 테이블

    Parameters
    ----------
    freq : 'Y' 연도별 | 'Q' 분기별 | 'M' 월별
    """
    _resample = {"Y": "A", "Q": "Q", "M": "M"}[freq]

    val    = pf.value()
    val_bh = pf_bh.value().reindex(val.index, method="ffill")
    val_bh = val_bh / val_bh.iloc[0] * val.iloc[0]

    def _ret(equity: pd.Series) -> pd.Series:
        return equity.resample(_resample).last().pct_change().dropna() * 100

    cols: dict = {f"{profile_name}(%)": _ret(val), "B&H(%)": _ret(val_bh)}

    if benchmark_series is not None:
        bm = benchmark_series.reindex(val.index, method="ffill").dropna()
        bm = bm / bm.iloc[0] * val.iloc[0]
        cols["KOSPI(%)"] = _ret(bm)

    df = pd.DataFrame(cols)

    if benchmark_series is not None:
        df[f"{profile_name}-KOSPI(%p)"] = df[f"{profile_name}(%)"] - df["KOSPI(%)"]
    df[f"{profile_name}-B&H(%p)"] = df[f"{profile_name}(%)"] - df["B&H(%)"]

    if freq == "Q":
        df.index = [f"{i.year}Q{i.quarter}" for i in df.index]
    elif freq == "Y":
        df.index = [str(i.year) for i in df.index]
    elif freq == "M":
        df.index = [i.strftime("%Y-%m") for i in df.index]

    return df.round(2)
