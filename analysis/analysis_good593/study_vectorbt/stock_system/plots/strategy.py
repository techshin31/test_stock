"""전략 시각화 — 국면 시각화"""

import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import koreanize_matplotlib

from ..strategies.regime import (
    REGIME_SIDEWAYS, REGIME_UPTREND, REGIME_DOWNTREND, REGIME_TRANSITION,
)

REGIME_COLORS = {
    REGIME_UPTREND:    "#2ecc71",   # 선명한 초록
    REGIME_DOWNTREND:  "#e74c3c",   # 선명한 빨강
    REGIME_SIDEWAYS:   "#f39c12",   # 선명한 주황
    REGIME_TRANSITION: "#95a5a6",   # 중간 회색
}


def plot_regime(
    close: pd.Series,
    regime: pd.Series,
    title: str = "시장 국면 시각화",
) -> None:
    """종가 위에 국면 배경색을 표시"""
    fig, ax = plt.subplots(figsize=(14, 5))
    ax.plot(close, color="black", lw=1.2, label="종가")

    prev_regime = None
    start_date  = close.index[0]
    for date, reg in regime.items():
        if reg != prev_regime and prev_regime is not None:
            ax.axvspan(start_date, date, alpha=0.25,
                       color=REGIME_COLORS.get(prev_regime, "white"))
            start_date = date
        prev_regime = reg
    if prev_regime is not None:
        ax.axvspan(start_date, close.index[-1], alpha=0.25,
                   color=REGIME_COLORS.get(prev_regime, "white"))

    patches = [
        mpatches.Patch(color=REGIME_COLORS[REGIME_UPTREND],    label="UPTREND",    alpha=0.7),
        mpatches.Patch(color=REGIME_COLORS[REGIME_DOWNTREND],  label="DOWNTREND",  alpha=0.7),
        mpatches.Patch(color=REGIME_COLORS[REGIME_SIDEWAYS],   label="SIDEWAYS",   alpha=0.7),
        mpatches.Patch(color=REGIME_COLORS[REGIME_TRANSITION], label="TRANSITION", alpha=0.7),
    ]
    ax.legend(handles=patches, fontsize=9, loc="upper left")
    ax.set_title(title, fontsize=13)
    ax.set_ylabel("주가")
    ax.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.show()

    counts = regime.value_counts()
    total  = len(regime)
    print("\n=== 국면 비율 ===")
    for r in [REGIME_UPTREND, REGIME_DOWNTREND, REGIME_SIDEWAYS, REGIME_TRANSITION]:
        cnt = counts.get(r, 0)
        print(f"  {r:12s}: {cnt:4d}일  ({cnt/total:.1%})")
