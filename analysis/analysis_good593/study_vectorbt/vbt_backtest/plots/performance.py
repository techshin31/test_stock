"""성과 시각화 — 자산곡선, MDD, 월별 히트맵, 기여도, 분산효과, 연도별 수익률"""

import numpy as np
import pandas as pd
import vectorbt as vbt
import matplotlib.pyplot as plt
import koreanize_matplotlib
import seaborn as sns


def plot_equity_curves(
    pf_09: vbt.Portfolio,
    pf_bh: vbt.Portfolio,
    pf_bh_ss: vbt.Portfolio,
    names: list[str],
    n: int,
) -> None:
    """자산 곡선 · 드로다운 · 보유 종목 수 3단 플롯"""
    val_09    = pf_09.value()
    val_bh    = pf_bh.value()
    bh_ss_val = pf_bh_ss.value()
    init      = val_09.iloc[0]

    bh_norm    = val_bh / val_bh.iloc[0] * init
    bh_ss_norm = bh_ss_val / bh_ss_val.iloc[0] * init

    asset_vals = pf_09.asset_value(group_by=False)
    asset_vals.columns = names

    fig, axes = plt.subplots(3, 1, figsize=(14, 11),
                              gridspec_kw={"height_ratios": [3, 1, 1]}, sharex=True)

    axes[0].plot(bh_ss_norm, color="gray",    lw=1.5, ls=":",  label=f"{names[0]} 단독 B&H")
    axes[0].plot(bh_norm,    color="orange",  lw=2.0, ls="--", label=f"{n}종목 균등 B&H")
    axes[0].plot(val_09,     color="crimson", lw=2.5, ls="-",  label="★ 09번 포트폴리오")
    axes[0].set_title("자산 곡선 비교", fontsize=13)
    axes[0].set_ylabel("포트폴리오 가치 (정규화)")
    axes[0].legend(fontsize=10)
    axes[0].grid(True, alpha=0.3)

    dd09  = (val_09  / val_09.cummax()  - 1) * 100
    dd_bh = (bh_norm / bh_norm.cummax() - 1) * 100
    axes[1].fill_between(dd09.index,  0, dd09,  color="crimson", alpha=0.4, label="09번 포트폴리오 MDD")
    axes[1].fill_between(dd_bh.index, 0, dd_bh, color="orange",  alpha=0.3, label=f"{n}종목 B&H MDD")
    axes[1].set_ylabel("드로다운 (%)")
    axes[1].set_ylim(min(dd09.min(), dd_bh.min()) * 1.15, 5)
    axes[1].legend(fontsize=9)
    axes[1].grid(True, alpha=0.3)

    n_held = (asset_vals > 0.5).sum(axis=1)
    axes[2].fill_between(n_held.index, 0, n_held, color="steelblue", alpha=0.5)
    axes[2].set_ylabel("보유 종목 수")
    axes[2].set_ylim(0, n + 0.5)
    axes[2].set_yticks(range(n + 1))
    axes[2].axhline(n, color="gray", lw=1, ls="--", alpha=0.5)
    axes[2].grid(True, alpha=0.3)

    plt.suptitle("09번 포트폴리오 vs Buy & Hold 비교", fontsize=14, fontweight="bold")
    plt.tight_layout()
    plt.show()


def plot_weight_heatmap(
    pf_09: vbt.Portfolio,
    names: list[str],
) -> None:
    """월별 종목 보유 비중 히트맵"""
    val_09     = pf_09.value()
    asset_vals = pf_09.asset_value(group_by=False)
    asset_vals.columns = names

    weights   = asset_vals.div(val_09, axis=0).clip(0, 1) * 100
    weights_m = weights.resample("M").mean()

    fig, ax = plt.subplots(figsize=(16, 4))
    sns.heatmap(
        weights_m.T,
        ax=ax,
        cmap="RdYlGn",
        vmin=0, vmax=20,
        linewidths=0.3,
        cbar_kws={"label": "보유 비중 (%)", "shrink": 0.8},
        xticklabels=[d.strftime("%y.%m") for d in weights_m.index],
    )
    ax.set_title("월별 종목 보유 비중 히트맵 (빨강=0%, 초록=20%)", fontsize=12)
    ax.set_xlabel("날짜")
    ax.set_ylabel("")
    plt.xticks(rotation=45, ha="right", fontsize=8)
    plt.tight_layout()
    plt.show()

    print("\n=== 종목별 평균 포지션 비중 ===")
    avg_w = weights.mean()
    for name in names:
        print(f"  {name:10s}: {avg_w[name]:.1f}%  (최대 {weights[name].max():.1f}%)")


def plot_contribution(
    pf_09: vbt.Portfolio,
    close_df: pd.DataFrame,
    names: list[str],
    colors_line: list[str] | None = None,
) -> None:
    """종목별 포트폴리오 수익 기여도 분석 (바차트 + 누적 시계열)"""
    if colors_line is None:
        colors_line = ["#e41a1c", "#377eb8", "#4daf4a", "#984ea3", "#ff7f00"]

    val_09     = pf_09.value()
    asset_vals = pf_09.asset_value(group_by=False)
    asset_vals.columns = names

    stock_rets    = close_df.pct_change().fillna(0)
    pos_w         = asset_vals.div(val_09, axis=0).fillna(0).clip(0, 1)
    daily_contrib = pos_w.shift(1).fillna(0) * stock_rets
    total_contrib = daily_contrib.sum() * 100
    cum_contrib   = daily_contrib.cumsum() * 100

    fig, axes = plt.subplots(1, 2, figsize=(14, 5))

    colors_c = ["#2166ac" if v >= 0 else "#b2182b" for v in total_contrib]
    bars = axes[0].barh(names, total_contrib, color=colors_c,
                        edgecolor="black", linewidth=0.6, alpha=0.88)
    axes[0].axvline(0, color="black", linewidth=0.9)
    axes[0].set_xlabel("포트폴리오 수익률 기여도 (%p)")
    axes[0].set_title("종목별 포트폴리오 수익 기여도", fontsize=12)
    axes[0].grid(True, alpha=0.3, axis="x")
    for bar, val in zip(bars, total_contrib):
        xpos = val + 0.15 if val >= 0 else val - 0.15
        ha   = "left" if val >= 0 else "right"
        axes[0].text(xpos, bar.get_y() + bar.get_height() / 2,
                     f"{val:+.1f}%p", va="center", ha=ha, fontsize=9, fontweight="bold")

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

    print("\n=== 종목별 기여도 순위 ===")
    for name in total_contrib.sort_values(ascending=False).index:
        print(f"  {name:10s}: {total_contrib[name]:+.2f}%p")


def plot_diversification(
    pf_09: vbt.Portfolio,
    pf_bh: vbt.Portfolio,
    close_df: pd.DataFrame,
    names: list[str],
) -> None:
    """분산투자 효과: 상관관계 히트맵 + 변동성 비교 바차트"""
    val_09  = pf_09.value()
    val_bh  = pf_bh.value()
    init    = val_09.iloc[0]
    bh_norm = val_bh / val_bh.iloc[0] * init

    returns_df = close_df.pct_change().dropna()
    corr_mat   = returns_df.corr()
    vols       = returns_df.std() * np.sqrt(252) * 100

    pf_vol   = returns_df.mean(axis=1).std() * np.sqrt(252) * 100
    pf09_vol = val_09.pct_change().dropna().std() * np.sqrt(252) * 100

    fig, axes = plt.subplots(1, 2, figsize=(14, 5))

    sns.heatmap(
        corr_mat,
        ax=axes[0],
        annot=True, fmt=".2f", cmap="coolwarm",
        vmin=-1, vmax=1, linewidths=0.5,
        cbar_kws={"shrink": 0.8},
    )
    axes[0].set_title(f"{len(names)}종목 수익률 상관관계", fontsize=12)

    n = len(names)
    vol_data   = list(vols[names]) + [pf_vol, pf09_vol]
    vol_labels = names + ["균등B&H\n포트폴리오", "09번\n포트폴리오"]
    colors_vol = ["#aec7e8"] * n + ["orange", "crimson"]

    bars = axes[1].bar(range(len(vol_data)), vol_data, color=colors_vol,
                       edgecolor="black", linewidth=0.6, alpha=0.9)
    axes[1].set_xticks(range(len(vol_data)))
    axes[1].set_xticklabels(vol_labels, fontsize=9)
    axes[1].set_ylabel("연간 변동성 (%)")
    axes[1].set_title("변동성 비교: 개별 종목 vs 포트폴리오", fontsize=12)
    axes[1].grid(True, alpha=0.3, axis="y")
    for bar, val in zip(bars, vol_data):
        axes[1].text(bar.get_x() + bar.get_width() / 2, val + 0.3,
                     f"{val:.1f}%", ha="center", va="bottom", fontsize=8.5, fontweight="bold")

    plt.suptitle("분산투자 효과 분석", fontsize=13, fontweight="bold")
    plt.tight_layout()
    plt.show()

    print("\n=== 분산투자 효과 ===")
    avg_stock_vol = vols.mean()
    print(f"개별 종목 평균 변동성: {avg_stock_vol:.1f}%")
    print(f"균등 B&H 포트폴리오:  {pf_vol:.1f}%  (개별 대비 {pf_vol/avg_stock_vol:.0%})")
    print(f"09번 포트폴리오:       {pf09_vol:.1f}%  (개별 대비 {pf09_vol/avg_stock_vol:.0%})")


def plot_yearly_returns(
    pf_09: vbt.Portfolio,
    pf_bh: vbt.Portfolio,
    pf_bh_ss: vbt.Portfolio,
    bh_ss_name: str = "삼성전자",
    n: int = 5,
) -> None:
    """연도별 성과 비교 바차트"""
    val_09    = pf_09.value()
    val_bh    = pf_bh.value()
    bh_ss_val = pf_bh_ss.value()
    init      = val_09.iloc[0]

    bh_norm    = val_bh / val_bh.iloc[0] * init
    bh_ss_norm = bh_ss_val / bh_ss_val.iloc[0] * init

    def _yearly(equity: pd.Series) -> pd.Series:
        return equity.resample("A").last().pct_change().dropna()

    yr_09 = _yearly(val_09)
    yr_bh = _yearly(bh_norm)
    yr_ss = _yearly(bh_ss_norm)

    years = [str(y.year) for y in yr_09.index]
    x = np.arange(len(years))
    w = 0.28

    fig, ax = plt.subplots(figsize=(13, 5))

    C_SS = ["#4292c6" if v >= 0 else "#9ecae1" for v in yr_ss]
    C_BH = ["#fd8d3c" if v >= 0 else "#fdbe85" for v in yr_bh]
    C_09 = ["#b2182b" if v >= 0 else "#fca69a" for v in yr_09]

    b1 = ax.bar(x - w, yr_ss * 100, w, color=C_SS, edgecolor="#333", lw=0.6, label=f"{bh_ss_name} 단독 B&H")
    b2 = ax.bar(x,     yr_bh * 100, w, color=C_BH, edgecolor="#333", lw=0.6, label=f"{n}종목 균등 B&H")
    b3 = ax.bar(x + w, yr_09 * 100, w, color=C_09, edgecolor="#333", lw=0.6, label="★ 09번 포트폴리오")

    ax.axhline(0, color="black", lw=0.9)
    ax.set_xticks(x)
    ax.set_xticklabels(years, fontsize=10)
    ax.set_ylabel("연간 수익률 (%)")
    ax.set_title("연도별 성과 비교", fontsize=13)
    ax.legend(fontsize=9)
    ax.grid(True, alpha=0.3, axis="y")

    for bars, vals in [(b1, yr_ss), (b2, yr_bh), (b3, yr_09)]:
        for bar, val in zip(bars, vals):
            v  = val * 100
            yp = v + 0.5 if v >= 0 else v - 1.2
            ax.text(bar.get_x() + bar.get_width() / 2, yp,
                    f"{v:.0f}%", ha="center",
                    va="bottom" if v >= 0 else "top",
                    fontsize=7, fontweight="bold")

    plt.tight_layout()
    plt.show()
