"""Drawdown analytics."""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass
class DrawdownPeriod:
    start: pd.Timestamp
    trough: pd.Timestamp
    end: pd.Timestamp | None
    drawdown: float
    duration_days: int
    recovery_days: int | None


def calc_drawdown_series(equity_curve: pd.Series) -> pd.Series:
    """Return the underwater curve for an equity series."""
    equity = equity_curve.dropna().astype(float)
    if equity.empty:
        return pd.Series(dtype=float, name="drawdown")
    peak = equity.cummax()
    drawdown = (equity - peak) / peak
    drawdown.name = "drawdown"
    return drawdown.fillna(0.0)


def calc_drawdown_periods(equity_curve: pd.Series) -> list[DrawdownPeriod]:
    """Return peak-to-recovery drawdown periods."""
    drawdown = calc_drawdown_series(equity_curve)
    if drawdown.empty:
        return []

    dates = list(drawdown.index)
    periods: list[DrawdownPeriod] = []
    in_drawdown = False
    peak_date = dates[0]
    start = dates[0]
    trough = dates[0]
    trough_dd = 0.0
    start_pos = 0
    trough_pos = 0

    for pos, dt in enumerate(dates):
        dd = float(drawdown.loc[dt])
        if dd == 0.0:
            peak_date = dt
            if in_drawdown:
                end = pd.Timestamp(dt)
                periods.append(DrawdownPeriod(
                    start=pd.Timestamp(start),
                    trough=pd.Timestamp(trough),
                    end=end,
                    drawdown=trough_dd,
                    duration_days=pos - start_pos,
                    recovery_days=pos - trough_pos,
                ))
                in_drawdown = False
            continue

        if not in_drawdown:
            in_drawdown = True
            start = peak_date
            start_pos = max(pos - 1, 0)
            trough = dt
            trough_pos = pos
            trough_dd = dd
        elif dd < trough_dd:
            trough = dt
            trough_pos = pos
            trough_dd = dd

    if in_drawdown:
        periods.append(DrawdownPeriod(
            start=pd.Timestamp(start),
            trough=pd.Timestamp(trough),
            end=None,
            drawdown=trough_dd,
            duration_days=len(dates) - 1 - start_pos,
            recovery_days=None,
        ))

    return periods


def calc_mdd_duration(equity_curve: pd.Series) -> int:
    """Return the longest drawdown duration in trading days."""
    periods = calc_drawdown_periods(equity_curve)
    if not periods:
        return 0
    return int(max(period.duration_days for period in periods))

