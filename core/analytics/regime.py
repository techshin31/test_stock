"""Regime helpers shared by analytics reports and notebooks."""
from __future__ import annotations

import pandas as pd
import matplotlib.pyplot as plt
from matplotlib.patches import Patch


REGIME_ORDER = ("UPTREND", "DOWNTREND", "SIDEWAYS", "TRANSITION")
REGIME_COLORS = {
    "UPTREND": "#A8DDA8",
    "DOWNTREND": "#F3A6A0",
    "SIDEWAYS": "#9EC9F5",
    "TRANSITION": "#C9C9C9",
}
REGIME_LABELS = {
    "UPTREND": "상승장",
    "DOWNTREND": "하락장",
    "SIDEWAYS": "횡보장",
    "TRANSITION": "전환장",
}


def calc_close_regime(
    close: pd.Series,
    short_window: int = 20,
    medium_window: int = 60,
    long_window: int = 120,
    sideways_threshold: float = 0.03,
) -> pd.DataFrame:
    """Classify market regimes from close-only price data.

    This is intentionally simpler than the strategy's per-ticker ADX regime
    logic. It is useful when only an index close series is available, such as
    KOSPI benchmark data in the notebook.
    """
    series = close.dropna().astype(float).sort_index()
    short_ma = series.rolling(short_window, min_periods=short_window).mean()
    medium_ma = series.rolling(medium_window, min_periods=medium_window).mean()
    long_ma = series.rolling(long_window, min_periods=long_window).mean()
    box_position = series / series.rolling(medium_window, min_periods=medium_window).mean() - 1.0

    is_uptrend = (short_ma > medium_ma) & (medium_ma > long_ma) & (series > medium_ma)
    is_downtrend = (short_ma < medium_ma) & (medium_ma < long_ma) & (series < medium_ma)
    is_sideways = (~is_uptrend) & (~is_downtrend) & box_position.abs().le(sideways_threshold)

    regime = pd.Series("TRANSITION", index=series.index, dtype=object)
    regime.loc[is_sideways.fillna(False)] = "SIDEWAYS"
    regime.loc[is_uptrend.fillna(False)] = "UPTREND"
    regime.loc[is_downtrend.fillna(False)] = "DOWNTREND"

    return pd.DataFrame(
        {
            "REGIME": regime,
            f"ma{short_window}": short_ma,
            f"ma{medium_window}": medium_ma,
            f"ma{long_window}": long_ma,
            f"box{medium_window}": box_position,
        },
        index=series.index,
    )


def calc_kospi_regime_from_close(close: pd.Series) -> pd.DataFrame:
    """Return a close-only KOSPI regime approximation."""
    return calc_close_regime(close)


def _as_regime_series(regime: pd.Series | pd.DataFrame) -> pd.Series:
    if isinstance(regime, pd.DataFrame):
        if "REGIME" not in regime.columns:
            raise KeyError("regime DataFrame must contain a 'REGIME' column")
        return regime["REGIME"]
    return regime


def shade_regime_background(
    ax: plt.Axes,
    regime: pd.Series | pd.DataFrame,
    alpha: float = 0.42,
) -> None:
    """Draw contiguous regime background spans on a matplotlib axis."""
    series = _as_regime_series(regime).dropna()
    if series.empty:
        return

    start = series.index[0]
    current = series.iloc[0]
    for dt, value in series.iloc[1:].items():
        if value != current:
            ax.axvspan(start, dt, color=REGIME_COLORS.get(current, "#E7E7E7"), alpha=alpha, linewidth=0)
            start = dt
            current = value

    end = series.index[-1] + pd.Timedelta(days=1) if isinstance(series.index, pd.DatetimeIndex) else series.index[-1]
    ax.axvspan(start, end, color=REGIME_COLORS.get(current, "#E7E7E7"), alpha=alpha, linewidth=0)


def regime_legend(regime: pd.Series | pd.DataFrame | None = None, alpha: float = 0.72) -> list[Patch]:
    """Build legend handles using Korean labels and regime codes."""
    if regime is None:
        present = list(REGIME_ORDER)
    else:
        values = set(_as_regime_series(regime).dropna())
        present = [name for name in REGIME_ORDER if name in values]

    return [
        Patch(
            facecolor=REGIME_COLORS[name],
            edgecolor="none",
            alpha=alpha,
            label=f"{REGIME_LABELS[name]} ({name})",
        )
        for name in present
    ]
