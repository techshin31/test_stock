"""성과 시각화 — 자산곡선, MDD, 기여도, 분산효과, 연도별 수익률"""

import numpy as np
import pandas as pd
import vectorbt as vbt
import matplotlib.pyplot as plt
import koreanize_matplotlib
import seaborn as sns


def _calc_mdd(equity: pd.Series) -> float:
    return (equity / equity.cummax() - 1).min()


def _calc_mdd_duration(equity: pd.Series) -> int:
    in_dd = (equity / equity.cummax() - 1) < 0
    return int(in_dd.groupby((~in_dd).cumsum()).sum().max())


def plot_equity_curves(
    pf: vbt.Portfolio,
    pf_bh: vbt.Portfolio,
    names: list,
    n: int,
    benchmark_series: pd.Series = None,
    profile_name: str = "위험중립형",
) -> None:
    """자산 곡선 · 드로다운 · 보유 종목 수 3단 플롯"""
    val    = pf.value()
    val_bh = pf_bh.value()
    init   = val.iloc[0]
    bh_norm = val_bh / val_bh.iloc[0] * init

    if benchmark_series is not None:
        bm = benchmark_series.reindex(val.index, method="ffill").dropna()
        bm_norm  = bm / bm.iloc[0] * init
        bm_label = benchmark_series.name or "벤치마크"
    else:
        bm_norm  = bh_norm
        bm_label = f"{n}종목 균등 B&H"

    asset_vals = pf.asset_value(group_by=False)
    asset_vals.columns = names

    fig, axes = plt.subplots(3, 1, figsize=(14, 11),
                              gridspec_kw={"height_ratios": [3, 1, 1]}, sharex=True)

    axes[0].plot(bm_norm,  color="gray",    lw=1.5, ls=":",  label=bm_label)
    axes[0].plot(bh_norm,  color="orange",  lw=2.0, ls="--", label=f"{n}종목 균등 B&H")
    axes[0].plot(val,      color="crimson", lw=2.5, ls="-",  label=f"★ {profile_name} 포트")
    axes[0].set_title("자산 곡선 비교", fontsize=13)
    axes[0].set_ylabel("포트폴리오 가치 (정규화)")
    axes[0].legend(fontsize=10)
    axes[0].grid(True, alpha=0.3)

    dd    = (val      / val.cummax()      - 1) * 100
    dd_bh = (bh_norm  / bh_norm.cummax() - 1) * 100
    dd_bm = (bm_norm  / bm_norm.cummax() - 1) * 100
    axes[1].fill_between(dd.index,    0, dd,    color="crimson", alpha=0.4, label=f"{profile_name} MDD")
    axes[1].fill_between(dd_bh.index, 0, dd_bh, color="orange",  alpha=0.3, label=f"{n}종목 B&H MDD")
    axes[1].fill_between(dd_bm.index, 0, dd_bm, color="gray",    alpha=0.2, label=f"{bm_label} MDD")
    axes[1].set_ylabel("드로다운 (%)")
    axes[1].set_ylim(min(dd.min(), dd_bh.min(), dd_bm.min()) * 1.15, 5)
    axes[1].legend(fontsize=9)
    axes[1].grid(True, alpha=0.3)

    n_held = (asset_vals > 0.5).sum(axis=1)
    axes[2].fill_between(n_held.index, 0, n_held, color="steelblue", alpha=0.5)
    axes[2].set_ylabel("보유 종목 수")
    axes[2].set_ylim(0, n + 0.5)
    axes[2].set_yticks(range(n + 1))
    axes[2].axhline(n, color="gray", lw=1, ls="--", alpha=0.5)
    axes[2].grid(True, alpha=0.3)

    plt.suptitle(f"{profile_name} 포트폴리오 vs {bm_label} 비교", fontsize=14, fontweight="bold")
    plt.tight_layout()
    plt.show()


def plot_weight_heatmap(pf: vbt.Portfolio, names: list) -> None:
    """월별 종목 보유 비중 히트맵"""
    val        = pf.value()
    asset_vals = pf.asset_value(group_by=False)
    asset_vals.columns = names

    weights   = asset_vals.div(val, axis=0).clip(0, 1) * 100
    weights_m = weights.resample("M").mean()
    vmax      = max(round(weights_m.values.max() / 10) * 10, 20)

    fig, ax = plt.subplots(figsize=(16, 4))
    sns.heatmap(
        weights_m.T, ax=ax, cmap="RdYlGn", vmin=0, vmax=vmax,
        linewidths=0.3,
        cbar_kws={"label": "보유 비중 (%)", "shrink": 0.8},
        xticklabels=[d.strftime("%y.%m") for d in weights_m.index],
    )
    ax.set_title(f"월별 종목 보유 비중 히트맵 (빨강=0%, 초록={vmax:.0f}%)", fontsize=12)
    ax.set_xlabel("날짜")
    plt.xticks(rotation=45, ha="right", fontsize=8)
    plt.tight_layout()
    plt.show()

    print("\n=== 종목별 평균 포지션 비중 ===")
    avg_w = weights.mean()
    for name in names:
        print(f"  {name:12s}: {avg_w[name]:.1f}%  (최대 {weights[name].max():.1f}%)")


def plot_contribution(pf: vbt.Portfolio, close_df: pd.DataFrame, names: list) -> None:
    """종목별 포트폴리오 수익 기여도 분석"""
    val        = pf.value()
    asset_vals = pf.asset_value(group_by=False)
    asset_vals.columns = names

    stock_rets    = close_df.pct_change().fillna(0)
    pos_w         = asset_vals.div(val, axis=0).fillna(0).clip(0, 1)
    daily_contrib = pos_w.shift(1).fillna(0) * stock_rets
    total_contrib = daily_contrib.sum() * 100
    cum_contrib   = daily_contrib.cumsum() * 100

    colors_line = ["#e41a1c", "#377eb8", "#4daf4a", "#984ea3", "#ff7f00",
                   "#a65628", "#f781bf", "#999999"][:len(names)]

    fig, axes = plt.subplots(1, 2, figsize=(14, 5))

    colors_c = ["#2166ac" if v >= 0 else "#b2182b" for v in total_contrib]
    bars = axes[0].barh(names, total_contrib, color=colors_c, edgecolor="black", lw=0.6, alpha=0.88)
    axes[0].axvline(0, color="black", lw=0.9)
    axes[0].set_xlabel("포트폴리오 수익률 기여도 (%p)")
    axes[0].set_title("종목별 포트폴리오 수익 기여도", fontsize=12)
    axes[0].grid(True, alpha=0.3, axis="x")
    for bar, val_c in zip(bars, total_contrib):
        xpos = val_c + 0.15 if val_c >= 0 else val_c - 0.15
        ha   = "left" if val_c >= 0 else "right"
        axes[0].text(xpos, bar.get_y() + bar.get_height() / 2,
                     f"{val_c:+.1f}%p", va="center", ha=ha, fontsize=9, fontweight="bold")

    for name, color in zip(names, colors_line):
        axes[1].plot(cum_contrib[name], lw=1.8, color=color, label=name)
    axes[1].axhline(0, color="black", lw=0.8, ls="--", alpha=0.5)
    axes[1].set_title("종목별 누적 기여도 추이", fontsize=12)
    axes[1].set_ylabel("누적 기여도 (%p)")
    axes[1].legend(fontsize=9)
    axes[1].grid(True, alpha=0.3)

    plt.suptitle("종목별 기여도 분석", fontsize=13, fontweight="bold")
    plt.tight_layout()
    plt.show()


def plot_diversification(
    pf: vbt.Portfolio,
    close_df: pd.DataFrame,
    names: list,
) -> None:
    """분산투자 효과: 상관관계 히트맵 + 변동성 비교"""
    val = pf.value()

    returns_df = close_df.pct_change().dropna()
    corr_mat   = returns_df.corr()
    vols       = returns_df.std() * np.sqrt(252) * 100

    pf_vol   = returns_df.mean(axis=1).std() * np.sqrt(252) * 100
    pf09_vol = val.pct_change().dropna().std() * np.sqrt(252) * 100

    fig, axes = plt.subplots(1, 2, figsize=(14, 5))

    sns.heatmap(corr_mat, ax=axes[0], annot=True, fmt=".2f", cmap="coolwarm",
                vmin=-1, vmax=1, linewidths=0.5, cbar_kws={"shrink": 0.8})
    axes[0].set_title(f"{len(names)}종목 수익률 상관관계", fontsize=12)

    n = len(names)
    vol_data   = list(vols[names]) + [pf_vol, pf09_vol]
    vol_labels = names + ["균등B&H\n포트폴리오", "전략\n포트폴리오"]
    colors_vol = ["#aec7e8"] * n + ["orange", "crimson"]

    bars = axes[1].bar(range(len(vol_data)), vol_data, color=colors_vol,
                       edgecolor="black", lw=0.6, alpha=0.9)
    axes[1].set_xticks(range(len(vol_data)))
    axes[1].set_xticklabels(vol_labels, fontsize=9)
    axes[1].set_ylabel("연간 변동성 (%)")
    axes[1].set_title("변동성 비교: 개별 종목 vs 포트폴리오", fontsize=12)
    axes[1].grid(True, alpha=0.3, axis="y")
    for bar, v in zip(bars, vol_data):
        axes[1].text(bar.get_x() + bar.get_width() / 2, v + 0.3,
                     f"{v:.1f}%", ha="center", va="bottom", fontsize=8.5, fontweight="bold")

    plt.suptitle("분산투자 효과 분석", fontsize=13, fontweight="bold")
    plt.tight_layout()
    plt.show()


def plot_yearly_returns(
    pf: vbt.Portfolio,
    pf_bh: vbt.Portfolio,
    n: int = 5,
    benchmark_series: pd.Series = None,
    profile_name: str = "위험중립형",
) -> None:
    """연도별 성과 비교 바차트"""
    val    = pf.value()
    val_bh = pf_bh.value()
    init   = val.iloc[0]
    bh_norm = val_bh.reindex(val.index, method="ffill")
    bh_norm = bh_norm / bh_norm.iloc[0] * init

    if benchmark_series is not None:
        bm = benchmark_series.reindex(val.index, method="ffill").dropna()
        bm_norm  = bm / bm.iloc[0] * init
        bm_label = benchmark_series.name or "벤치마크"
    else:
        bm_norm  = bh_norm
        bm_label = "균등 B&H"

    def _yearly(equity: pd.Series) -> pd.Series:
        return equity.resample("A").last().pct_change().dropna()

    yr     = _yearly(val)
    yr_bh  = _yearly(bh_norm)
    yr_bm  = _yearly(bm_norm)

    years = [str(y.year) for y in yr.index]
    x = np.arange(len(years))
    w = 0.28

    fig, ax = plt.subplots(figsize=(13, 5))
    C_BM = ["#4292c6" if v >= 0 else "#9ecae1" for v in yr_bm]
    C_BH = ["#fd8d3c" if v >= 0 else "#fdbe85" for v in yr_bh]
    C_ST = ["#b2182b" if v >= 0 else "#fca69a" for v in yr]

    b1 = ax.bar(x - w, yr_bm * 100, w, color=C_BM, edgecolor="#333", lw=0.6, label=bm_label)
    b2 = ax.bar(x,     yr_bh * 100, w, color=C_BH, edgecolor="#333", lw=0.6, label=f"{n}종목 균등 B&H")
    b3 = ax.bar(x + w, yr     * 100, w, color=C_ST, edgecolor="#333", lw=0.6, label=f"★ {profile_name} 포트")

    ax.axhline(0, color="black", lw=0.9)
    ax.set_xticks(x)
    ax.set_xticklabels(years, fontsize=10)
    ax.set_ylabel("연간 수익률 (%)")
    ax.set_title("연도별 성과 비교", fontsize=13)
    ax.legend(fontsize=9)
    ax.grid(True, alpha=0.3, axis="y")

    for bars, vals in [(b1, yr_bm), (b2, yr_bh), (b3, yr)]:
        for bar, v in zip(bars, vals):
            vp = v * 100
            yp = vp + 0.5 if vp >= 0 else vp - 1.2
            ax.text(bar.get_x() + bar.get_width() / 2, yp,
                    f"{vp:.0f}%", ha="center",
                    va="bottom" if vp >= 0 else "top",
                    fontsize=7, fontweight="bold")

    plt.tight_layout()
    plt.show()


def plot_mdd_comparison(
    pf: vbt.Portfolio,
    pf_bh: vbt.Portfolio,
    kospi: pd.Series,
    n: int = 5,
    profile_name: str = "위험중립형",
) -> None:
    """MDD Depth + Duration 비교 (기준: KOSPI)"""
    port_val = pf.value()
    kospi_eq = kospi.reindex(port_val.index, method="ffill").dropna()
    kospi_eq = kospi_eq / kospi_eq.iloc[0] * port_val.iloc[0]

    targets = {
        "KOSPI\n(벤치마크)":   kospi_eq,
        f"{n}종목\n균등 B&H": pf_bh.value(),
        profile_name:          port_val,
    }

    mdd_vals = {k: abs(_calc_mdd(v)) * 100  for k, v in targets.items()}
    dur_vals = {k: _calc_mdd_duration(v)    for k, v in targets.items()}
    labels   = list(targets.keys())
    colors   = ["#4472C4", "#ffa500", "#dc143c"]

    print("=== MDD 비교 ===")
    for label in labels:
        print(f"  {label.replace(chr(10), ' '):20s}: MDD {mdd_vals[label]:.1f}%  Duration {dur_vals[label]}일")

    kospi_mdd = _calc_mdd(kospi_eq)
    port_mdd  = _calc_mdd(port_val)
    depth_ok  = port_mdd > kospi_mdd
    print()
    print(f"MDD depth: KOSPI {kospi_mdd:.1%} → {profile_name} {port_mdd:.1%}",
          "(✅ 개선)" if depth_ok else "(❌ 미개선)")

    fig, axes = plt.subplots(1, 2, figsize=(12, 4))

    bars = axes[0].bar(labels, list(mdd_vals.values()), color=colors, edgecolor="black", lw=0.6, alpha=0.85)
    axes[0].axhline(15, color="red", lw=1.5, ls="--", label="기준 15%")
    axes[0].set_ylabel("MDD (%)")
    axes[0].set_title("MDD Depth 비교", fontsize=12)
    axes[0].legend(fontsize=9)
    axes[0].grid(True, alpha=0.3, axis="y")
    for bar, v in zip(bars, mdd_vals.values()):
        axes[0].text(bar.get_x() + bar.get_width() / 2, v + 0.3,
                     f"{v:.1f}%", ha="center", fontsize=10, fontweight="bold")

    bars2 = axes[1].bar(labels, list(dur_vals.values()), color=colors, edgecolor="black", lw=0.6, alpha=0.85)
    axes[1].axhline(126, color="orange", lw=1.5, ls="--", label="기준 126일")
    axes[1].set_ylabel("거래일")
    axes[1].set_title("MDD Duration 비교", fontsize=12)
    axes[1].legend(fontsize=9)
    axes[1].grid(True, alpha=0.3, axis="y")
    for bar, v in zip(bars2, dur_vals.values()):
        axes[1].text(bar.get_x() + bar.get_width() / 2, v + 3,
                     f"{v}일", ha="center", fontsize=10, fontweight="bold")

    plt.suptitle(f"MDD Depth + Duration 비교  [기준: KOSPI]", fontsize=13, fontweight="bold")
    plt.tight_layout()
    plt.show()


def plot_yearly_stock_etf(
    pf: vbt.Portfolio,
    names_all: list,
    etf_name: str = "단기채",
) -> None:
    """연도별 주식 vs 단기채 수익 기여도"""
    val        = pf.value()
    asset_vals = pf.asset_value(group_by=False)
    asset_vals.columns = names_all

    stock_names = [n for n in names_all if n != etf_name]
    stock_val   = asset_vals[stock_names].sum(axis=1)
    etf_val     = asset_vals[etf_name]

    port_val_prev = val.shift(1)
    daily_stock   = stock_val.diff() / port_val_prev
    daily_etf     = etf_val.diff()   / port_val_prev

    stock_contrib = daily_stock.resample("A").sum().dropna()
    etf_contrib   = daily_etf.resample("A").sum().dropna()
    total_ret     = (val.resample("A").last() / val.resample("A").last().shift(1) - 1).dropna()

    idx           = stock_contrib.index.intersection(etf_contrib.index).intersection(total_ret.index)
    stock_contrib = stock_contrib.reindex(idx)
    etf_contrib   = etf_contrib.reindex(idx)
    total_ret     = total_ret.reindex(idx)
    years         = [str(y.year) for y in idx]
    x             = np.arange(len(years))

    print(f"{'연도':>6} {'주식 기여도':>10} {'단기채 기여도':>12} {'포트 총수익':>10}")
    print("-" * 44)
    for yr, sc, ec, tr in zip(years, stock_contrib, etf_contrib, total_ret):
        print(f"{yr:>6}  {sc:>+9.2%}   {ec:>+11.2%}   {tr:>+9.2%}")

    fig, ax = plt.subplots(figsize=(13, 5))

    s_pos = np.where(stock_contrib >= 0, stock_contrib * 100, 0)
    s_neg = np.where(stock_contrib <  0, stock_contrib * 100, 0)
    e_pos = np.where(etf_contrib   >= 0, etf_contrib   * 100, 0)
    e_neg = np.where(etf_contrib   <  0, etf_contrib   * 100, 0)

    ax.bar(x, s_pos, color="#dc143c", alpha=0.85, label="주식 기여도(+)")
    ax.bar(x, s_neg, color="#fca69a", alpha=0.85, label="주식 기여도(-)")
    ax.bar(x, e_pos, bottom=s_pos, color="#4472C4", alpha=0.85, label="단기채 기여도(+)")
    ax.bar(x, e_neg, bottom=s_neg, color="#9ecae1", alpha=0.85, label="단기채 기여도(-)")

    ax.plot(x, total_ret * 100, "ko-", lw=2, markersize=7, label="포트 총수익률", zorder=5)
    for i, v in enumerate(total_ret * 100):
        yp = v + 0.8 if v >= 0 else v - 1.5
        ax.text(x[i], yp, f"{v:.1f}%", ha="center", fontsize=8, fontweight="bold")

    ax.axhline(0, color="black", lw=0.9)
    ax.set_xticks(x)
    ax.set_xticklabels(years, fontsize=10)
    ax.set_ylabel("수익률 기여도 (%)")
    ax.set_title("연도별 주식 vs 단기채 수익 기여도", fontsize=13, fontweight="bold")
    ax.legend(fontsize=9, ncol=2)
    ax.grid(True, alpha=0.3, axis="y")
    plt.tight_layout()
    plt.show()


def plot_quarterly_returns(
    pf: vbt.Portfolio,
    pf_bh: vbt.Portfolio,
    n: int = 5,
    benchmark_series: pd.Series = None,
    profile_name: str = "전략",
) -> None:
    """분기별 수익률 비교 바차트"""
    val     = pf.value()
    val_bh  = pf_bh.value()
    init    = val.iloc[0]
    bh_norm = val_bh.reindex(val.index, method="ffill")
    bh_norm = bh_norm / bh_norm.iloc[0] * init

    if benchmark_series is not None:
        bm       = benchmark_series.reindex(val.index, method="ffill").dropna()
        bm_norm  = bm / bm.iloc[0] * init
        bm_label = benchmark_series.name or "벤치마크"
    else:
        bm_norm  = bh_norm
        bm_label = "균등 B&H"

    def _quarterly(equity: pd.Series) -> pd.Series:
        return equity.resample("Q").last().pct_change().dropna()

    qr    = _quarterly(val)
    qr_bh = _quarterly(bh_norm)
    qr_bm = _quarterly(bm_norm)

    quarters = [f"{q.year}Q{q.quarter}" for q in qr.index]
    x = np.arange(len(quarters))
    w = 0.28

    fig, ax = plt.subplots(figsize=(max(14, len(quarters) * 0.9), 6))

    C_BM = ["#4292c6" if v >= 0 else "#9ecae1" for v in qr_bm]
    C_BH = ["#fd8d3c" if v >= 0 else "#fdbe85" for v in qr_bh]
    C_ST = ["#b2182b" if v >= 0 else "#fca69a" for v in qr]

    b1 = ax.bar(x - w, qr_bm * 100, w, color=C_BM, edgecolor="#333", lw=0.6, label=bm_label)
    b2 = ax.bar(x,     qr_bh * 100, w, color=C_BH, edgecolor="#333", lw=0.6, label=f"{n}종목 균등 B&H")
    b3 = ax.bar(x + w, qr     * 100, w, color=C_ST, edgecolor="#333", lw=0.6, label=f"★ {profile_name} 포트")

    ax.axhline(0, color="black", lw=0.9)
    ax.set_xticks(x)
    ax.set_xticklabels(quarters, rotation=45, ha="right", fontsize=8)
    ax.set_ylabel("분기 수익률 (%)")
    ax.set_title("분기별 성과 비교", fontsize=13)
    ax.legend(fontsize=9)
    ax.grid(True, alpha=0.3, axis="y")

    for bars, vals in [(b1, qr_bm), (b2, qr_bh), (b3, qr)]:
        for bar, v in zip(bars, vals):
            vp = v * 100
            yp = vp + 0.3 if vp >= 0 else vp - 0.9
            ax.text(bar.get_x() + bar.get_width() / 2, yp,
                    f"{vp:.0f}%", ha="center",
                    va="bottom" if vp >= 0 else "top",
                    fontsize=6, fontweight="bold")

    plt.tight_layout()
    plt.show()


def plot_monthly_heatmap(
    pf: vbt.Portfolio,
    pf_bh: vbt.Portfolio,
    n: int = 5,
    benchmark_series: pd.Series = None,
    profile_name: str = "전략",
) -> None:
    """월별 수익률 히트맵 (캘린더 뷰) — 전략 / B&H / KOSPI 비교"""
    val    = pf.value()
    val_bh = pf_bh.value().reindex(val.index, method="ffill")
    val_bh = val_bh / val_bh.iloc[0] * val.iloc[0]

    MONTH_LABELS = ["1월","2월","3월","4월","5월","6월","7월","8월","9월","10월","11월","12월","연간"]

    def _pivot(equity: pd.Series) -> pd.DataFrame:
        mr    = equity.resample("M").last().pct_change().dropna()
        pivot = pd.DataFrame({
            "ret":   (mr * 100).values,
            "year":  mr.index.year,
            "month": mr.index.month,
        }).pivot_table(index="year", columns="month", values="ret", aggfunc="first")
        pivot  = pivot.reindex(columns=range(1, 13))
        annual = ((mr + 1).resample("A").prod() - 1) * 100
        annual.index = annual.index.year
        pivot["연간"]  = annual.reindex(pivot.index).values
        pivot.columns  = MONTH_LABELS
        return pivot

    targets = [(_pivot(val), f"★ {profile_name}"), (_pivot(val_bh), f"{n}종목 균등 B&H")]
    if benchmark_series is not None:
        bm       = benchmark_series.reindex(val.index, method="ffill").dropna()
        bm_norm  = bm / bm.iloc[0] * val.iloc[0]
        bm_label = benchmark_series.name or "KOSPI"
        targets.append((_pivot(bm_norm), bm_label))

    n_plots = len(targets)
    n_rows  = len(targets[0][0])

    all_vals = np.concatenate([p.values[~np.isnan(p.values)] for p, _ in targets])
    vmax     = max(abs(all_vals).max() if len(all_vals) > 0 else 10, 5)

    fig, axes = plt.subplots(n_plots, 1, figsize=(18, n_rows * 0.7 * n_plots + 2))
    if n_plots == 1:
        axes = [axes]

    for ax, (pivot, title) in zip(axes, targets):
        sns.heatmap(pivot, ax=ax, cmap="RdYlGn", center=0, vmin=-vmax, vmax=vmax,
                    annot=True, fmt=".1f", linewidths=0.4, linecolor="white",
                    cbar_kws={"label": "수익률 (%)", "shrink": 0.7})
        ax.set_title(f"{title} 월별 수익률 (%)", fontsize=12)
        ax.set_xlabel("")
        ax.set_ylabel("연도")
        ax.tick_params(axis="x", labelsize=9)

    plt.suptitle("월별 수익률 히트맵 비교", fontsize=14, fontweight="bold")
    plt.tight_layout()
    plt.show()
