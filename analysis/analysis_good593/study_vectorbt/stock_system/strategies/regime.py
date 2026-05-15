"""시장 국면 판별 — 4국면: SIDEWAYS / UPTREND / DOWNTREND / TRANSITION

판별 우선순위: SIDEWAYS → UPTREND → DOWNTREND → TRANSITION
KOSPI < MA120 시 UPTREND 차단 + DOWNTREND 강제 → SIDEWAYS/TRANSITION도 DOWNTREND로 전환
"""

import pandas as pd

from ..indicators.trend.ma import calc_ma
from ..indicators.trend_strength.adx import calc_adx

REGIME_SIDEWAYS   = "SIDEWAYS"
REGIME_UPTREND    = "UPTREND"
REGIME_DOWNTREND  = "DOWNTREND"
REGIME_TRANSITION = "TRANSITION"


def calc_regime(
    close: pd.Series,
    high: pd.Series,
    low: pd.Series,
    ma_windows: tuple = (20, 60, 120),
    adx_window: int = 14,
    adx_threshold: float = 25.0,
    adx_sideways: float = 20.0,
    kospi: pd.Series = None,
    kospi_ma: int = 120,
) -> tuple:
    """4국면 판별

    Returns
    -------
    regime : Series[str]  날짜별 국면 문자열
    masks  : dict         불리언 마스크 + MA/ADX 시리즈
    adx_df : DataFrame    ADX, plus_di, minus_di
    """
    ma_s = calc_ma(close, ma_windows[0])   # MA20
    ma_m = calc_ma(close, ma_windows[1])   # MA60
    ma_l = calc_ma(close, ma_windows[2])   # MA120
    adx_df = calc_adx(high, low, close, adx_window)
    adx    = adx_df["ADX"]

    # 우선순위: SIDEWAYS → UPTREND → DOWNTREND → TRANSITION
    SIDEWAYS   = adx < adx_sideways
    UPTREND    = (ma_s > ma_m) & (ma_m > ma_l) & (adx > adx_threshold) & ~SIDEWAYS
    DOWNTREND  = (ma_s < ma_m) & (ma_m < ma_l) & (adx > adx_threshold) & ~SIDEWAYS
    TRANSITION = ~SIDEWAYS & ~UPTREND & ~DOWNTREND

    if kospi is not None:
        kospi_aligned = kospi.reindex(close.index, method="ffill")
        kospi_below   = kospi_aligned < kospi_aligned.rolling(kospi_ma).mean()
        UPTREND    = UPTREND   & ~kospi_below
        DOWNTREND  = DOWNTREND | kospi_below
        SIDEWAYS   = SIDEWAYS  & ~kospi_below
        TRANSITION = ~SIDEWAYS & ~UPTREND & ~DOWNTREND  # 반드시 재계산

    regime = pd.Series(REGIME_TRANSITION, index=close.index, dtype=object)
    regime[SIDEWAYS]  = REGIME_SIDEWAYS
    regime[UPTREND]   = REGIME_UPTREND
    regime[DOWNTREND] = REGIME_DOWNTREND  # 마지막 할당 → KOSPI 하락 시 최우선

    masks = {
        "UPTREND":    UPTREND,
        "DOWNTREND":  DOWNTREND,
        "SIDEWAYS":   SIDEWAYS,
        "TRANSITION": TRANSITION,
        "ma_s":       ma_s,
        "ma_m":       ma_m,
        "ma_l":       ma_l,
        "adx":        adx,
    }
    return regime, masks, adx_df
