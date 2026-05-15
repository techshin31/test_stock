"""시장 국면 판별 — 4국면: SIDEWAYS / UPTREND / DOWNTREND / TRANSITION

운용 모드 (WF IS score 기반):
  ADX 모드    (IS score > 0): SIDEWAYS → UPTREND → DOWNTREND → TRANSITION
  MA+KOSPI 모드 (IS score ≤ 0): SIDEWAYS 없음, MA 정/역배열 + KOSPI_MA60만 사용

KOSPI < KOSPI_MA 시 UPTREND 차단 — 양쪽 모드 공통 적용
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
    use_adx_mode: bool = True,
) -> tuple:
    """4국면 판별

    Parameters
    ----------
    use_adx_mode : True  → ADX 모드 (IS score > 0일 때 적용)
                   False → MA+KOSPI 모드 (IS score ≤ 0일 때 적용)
                           SIDEWAYS 없음, ADX 조건 제외, KOSPI_MA 필터만 유지

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

    if use_adx_mode:
        # ADX 모드: SIDEWAYS → UPTREND → DOWNTREND → TRANSITION
        SIDEWAYS  = adx < adx_sideways
        UPTREND   = (ma_s > ma_m) & (ma_m > ma_l) & (adx > adx_threshold) & ~SIDEWAYS
        DOWNTREND = (ma_s < ma_m) & (ma_m < ma_l) & (adx > adx_threshold) & ~SIDEWAYS
    else:
        # MA+KOSPI 모드: ADX 조건 제외, SIDEWAYS 없음
        SIDEWAYS  = pd.Series(False, index=close.index)
        UPTREND   = (ma_s > ma_m) & (ma_m > ma_l)
        DOWNTREND = (ma_s < ma_m) & (ma_m < ma_l)

    TRANSITION = ~SIDEWAYS & ~UPTREND & ~DOWNTREND

    if kospi is not None:
        kospi_aligned = kospi.reindex(close.index, method="ffill")
        kospi_below   = kospi_aligned < kospi_aligned.rolling(kospi_ma).mean()
        UPTREND    = UPTREND & ~kospi_below          # 신규 UPTREND 진입만 차단 (양 모드 공통)
        TRANSITION = ~SIDEWAYS & ~UPTREND & ~DOWNTREND  # 반드시 재계산

    regime = pd.Series(REGIME_TRANSITION, index=close.index, dtype=object)
    regime[SIDEWAYS]  = REGIME_SIDEWAYS
    regime[UPTREND]   = REGIME_UPTREND
    regime[DOWNTREND] = REGIME_DOWNTREND

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
