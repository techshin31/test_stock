"""전략 시각화 — 국면 배경색, 단일 종목 자산곡선"""

import pandas as pd
import vectorbt as vbt
import matplotlib.pyplot as plt
import koreanize_matplotlib

from ..strategies.combined.ma_regime_strategy import REGIME_COLORS


def plot_regime(
    close: pd.Series,
    regime: pd.Series,
    masks: dict,
    name: str,
    adx_threshold: float = 25.0,
    adx_sideways: float = 20.0,
) -> None:
    """국면 배경색 시각화 — 종가+MA / ADX / 국면 bar 3단 플롯"""
    fig, axes = plt.subplots(3, 1, figsize=(14, 9), sharex=True,
                             gridspec_kw={"height_ratios": [3, 1, 1]})

    axes[0].plot(close,            color="black",  lw=1.2, label="종가")
    axes[0].plot(masks["ma_s"],    color="blue",   lw=1.0, ls="--", label="MA20")
    axes[0].plot(masks["ma_m"],    color="orange", lw=1.0, ls="--", label="MA60")
    axes[0].plot(close.rolling(120).mean(), color="red", lw=1.0, ls="--", label="MA120")
    for r, (color, alpha) in REGIME_COLORS.items():
        axes[0].fill_between(close.index, close.min(), close.max(),
                             where=(regime == r), color=color, alpha=alpha, label=r)
    axes[0].set_title(f"{name} 시장 국면  (ADX threshold={adx_threshold}, sideways={adx_sideways})")
    axes[0].legend(fontsize=8, ncol=4)
    axes[0].grid(True, alpha=0.3)

    axes[1].plot(masks["adx"], color="purple", lw=1.2, label="ADX")
    axes[1].axhline(adx_threshold, color="red",    lw=1, ls="--", label=f"threshold={adx_threshold}")
    axes[1].axhline(adx_sideways,  color="orange", lw=1, ls="--", label=f"sideways={adx_sideways}")
    axes[1].set_ylabel("ADX")
    axes[1].legend(fontsize=8)
    axes[1].grid(True, alpha=0.3)

    regime_num = regime.map({"UPTREND": 1, "SIDEWAYS": 0.5, "TRANSITION": 0.3, "DOWNTREND": -1})
    colors_bar = regime.map({k: v[0] for k, v in REGIME_COLORS.items()})
    axes[2].bar(regime.index, regime_num, color=colors_bar, width=1, alpha=0.8)
    axes[2].set_ylabel("국면")
    axes[2].set_yticks([1, 0.5, 0.3, -1])
    axes[2].set_yticklabels(["UP", "SIDE", "TRANS", "DOWN"], fontsize=8)
    axes[2].grid(True, alpha=0.3)

    plt.tight_layout()
    plt.show()


def plot_single_backtest(
    pf_single: vbt.Portfolio,
    pf_bh_single: vbt.Portfolio,
    close: pd.Series,
    regime: pd.Series,
    name: str,
) -> None:
    """단일 종목 자산곡선 + 드로다운 (국면 배경색 오버레이)"""
    val_s  = pf_single.value()
    val_bh = pf_bh_single.value() / pf_bh_single.value().iloc[0] * val_s.iloc[0]

    fig, axes = plt.subplots(2, 1, figsize=(14, 7), sharex=True,
                             gridspec_kw={"height_ratios": [3, 1]})

    axes[0].plot(val_bh, color="gray",   lw=1.5, ls="--", label=f"{name} B&H")
    axes[0].plot(val_s,  color="crimson", lw=2,   ls="-",  label=f"{name} 위험중립형")
    for r, (color, alpha) in REGIME_COLORS.items():
        axes[0].fill_between(close.index, val_s.min(), val_s.max(),
                             where=(regime == r), color=color, alpha=alpha)
    axes[0].set_title(f"{name} 단일 종목 백테스트")
    axes[0].set_ylabel("자산가치")
    axes[0].legend()
    axes[0].grid(True, alpha=0.3)

    dd = (val_s / val_s.cummax() - 1) * 100
    axes[1].fill_between(dd.index, 0, dd, color="crimson", alpha=0.4)
    axes[1].axhline(-15, color="red", lw=1, ls="--", label="MDD 기준 -15%")
    axes[1].set_ylabel("드로다운 (%)")
    axes[1].legend(fontsize=9)
    axes[1].grid(True, alpha=0.3)

    plt.tight_layout()
    plt.show()
