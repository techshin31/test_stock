"""ATR(Average True Range) — 변동성 지표"""

import pandas as pd


def calc_atr(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    period: int = 14,
) -> pd.Series:
    """ATR 계산 — Wilder's smoothing 방식

    True Range = max(고가-저가, |고가-전일종가|, |저가-전일종가|)
    ATR = TR의 지수이동평균 (com = period - 1)
    """
    prev_close = close.shift(1)
    tr = pd.concat(
        [
            high - low,
            (high - prev_close).abs(),
            (low  - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return tr.ewm(com=period - 1, min_periods=period).mean()
