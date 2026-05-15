"""분할 매수/매도 신호 생성

[분할 매수] 3단계
  1차: 비UPTREND → UPTREND 전환 첫날                → entry1_size (40%)
  2차: UPTREND 유지 + 종가가 MA20 위에서 유지 확인   → entry2_size (70%)
  횡보: SIDEWAYS + BB 하단 터치                     → entry_range_size (30%)

[분할 매도] 3단계
  1차: UPTREND → TRANSITION 전환 첫날               → exit1_size (40%) 유지
  2차: 데드크로스 (MA20 < MA60)                     → exit2_size (10%) 유지
  3차: DOWNTREND 진입                               → 0% 전량 청산 (최우선)
  횡보 청산: SIDEWAYS + BB 상단 터치                 → 0% 전량 청산

[ATR stop-loss] 최우선
  당일 낙폭 > ATR × multiplier → 0% 즉시 전량 청산

KOSPI 필터는 calc_regime() 내부에서 처리됨
"""

import numpy as np
import pandas as pd

from .regime import calc_regime
from ..indicators.volatility.bollinger import calc_bollinger
from ..indicators.volatility.atr import calc_atr


def make_signals(
    close: pd.Series,
    high: pd.Series,
    low: pd.Series,
    ma_windows: tuple = (20, 60, 120),
    adx_window: int = 14,
    adx_threshold: float = 25.0,
    adx_sideways: float = 20.0,
    bb_window: int = 20,
    bb_std: float = 2.0,
    entry1_size: float = 0.4,
    entry2_size: float = 0.7,
    entry_range_size: float = 0.3,
    exit1_size: float = 0.4,
    exit2_size: float = 0.1,
    recent_window: int = 60,
    kospi: pd.Series = None,
    kospi_ma: int = 120,
    atr_multiplier: float = 2.0,
    atr_period: int = 14,
) -> tuple:
    """분할 매수/매도 신호 생성

    Returns
    -------
    entries, exits, size_series, detail
      size_series: targetpercent — NaN=유지, 0.0=전량청산, 양수=목표비중
    """
    regime, masks, adx_df = calc_regime(
        close, high, low, ma_windows, adx_window, adx_threshold, adx_sideways,
        kospi=kospi, kospi_ma=kospi_ma,
    )

    UPTREND    = masks["UPTREND"]
    DOWNTREND  = masks["DOWNTREND"]
    SIDEWAYS   = masks["SIDEWAYS"]
    TRANSITION = masks["TRANSITION"]
    ma_s       = masks["ma_s"]   # MA20
    ma_m       = masks["ma_m"]   # MA60

    # ── 매수 신호 ──────────────────────────────────────────────────────────────
    # 1차: 비UPTREND → UPTREND 전환 첫날
    entry1 = UPTREND & ~UPTREND.shift(1).fillna(False)

    # 2차: UPTREND 유지 + 종가가 MA20 위에서 유지
    #   1차 매수 후 recent_window 거래일 이내에만 유효, 1차 진입일 중복 제외
    ma20_support = close > ma_s
    has_position = entry1.rolling(recent_window, min_periods=1).max().astype(bool)
    entry2 = ma20_support & UPTREND & has_position & ~entry1

    # 횡보: SIDEWAYS + BB 하단 터치 (과매도 반전)
    upper, mid, lower = calc_bollinger(close, bb_window, bb_std)
    bb_entry = (close > lower) & (close.shift(1) <= lower.shift(1))
    bb_exit  = (close < upper) & (close.shift(1) >= upper.shift(1))
    entry_range = bb_entry & SIDEWAYS

    entries = entry1 | entry2 | entry_range

    # ── 매도 신호 ──────────────────────────────────────────────────────────────
    # 데드크로스 (MA20이 MA60을 하향 돌파)
    dead_cross = (ma_s < ma_m) & (ma_s.shift(1) >= ma_m.shift(1))

    # UPTREND → TRANSITION 전환 첫날
    transition_from_up = (
        TRANSITION
        & ~TRANSITION.shift(1).fillna(False)
        & UPTREND.shift(1).fillna(False)
    )

    exits = dead_cross | DOWNTREND | (bb_exit & SIDEWAYS)

    # ── size_series (목표 비중) — 나중 할당이 앞 값을 덮어씀 ────────────────────
    size_series = pd.Series(np.nan, index=close.index, dtype=float)

    # [낮은 우선순위] 매수
    size_series[entry_range]  = entry_range_size   # 횡보 30%
    size_series[entry1]       = entry1_size         # 1차 40%
    size_series[entry2]       = entry2_size         # 2차 70%

    # [높은 우선순위] 매도
    size_series[transition_from_up] = exit1_size    # TRANSITION: 40% 유지
    size_series[dead_cross]         = exit2_size    # 데드크로스: 10% 유지
    size_series[bb_exit & SIDEWAYS] = 0.0           # 횡보 목표 달성: 전량 청산
    size_series[DOWNTREND]          = 0.0           # 하락 확정: 전량 청산

    # ── ATR Stop-Loss: 최우선 ──────────────────────────────────────────────────
    atr        = calc_atr(high, low, close, period=atr_period)
    daily_drop = close.pct_change()
    atr_stop   = daily_drop < -(atr.shift(1) / close.shift(1) * atr_multiplier)
    exits      = exits | atr_stop
    size_series[atr_stop] = 0.0

    detail = {
        "regime":             regime,
        "masks":              masks,
        "adx_df":             adx_df,
        "entry1":             entry1,
        "entry2":             entry2,
        "entry_range":        entry_range,
        "transition_from_up": transition_from_up,
        "dead_cross":         dead_cross,
        "bb_exit_sideways":   bb_exit & SIDEWAYS,
        "atr_stop":           atr_stop,
    }
    return entries, exits, size_series, detail
