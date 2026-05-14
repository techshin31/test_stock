"""
분할 매수/매도 전략 (자동화 트레이딩 최적화)

골든크로스 · MA20 · 볼린저 밴드만 사용

[분할 매수] 3단계
  1차: UPTREND + 골든크로스(MA20>MA60 상향돌파)   → entry1_size (기본 40%)
  2차: UPTREND + MA20 지지 재확인 (보유 중일 때)  → entry2_size (기본 70%) 추가매수
  횡보: SIDEWAYS + BB 하단 터치                  → entry_range_size (기본 30%)

[분할 매도] 3단계
  1차: UPTREND → TRANSITION 전환 첫날            → exit1_size (기본 40%) 유지, 나머지 익절
  2차: 데드크로스(MA20<MA60 하향돌파)             → exit2_size (기본 10%) 유지
  3차: DOWNTREND 진입                            → 0% 전량 청산 (최우선)
  횡보 청산: SIDEWAYS + BB 상단 터치              → 0% 전량 청산

[우선순위]
  DOWNTREND > 데드크로스 > TRANSITION > 매수신호
  → size_series 후순위 할당이 앞순위를 덮어씀
"""

import numpy as np
import pandas as pd
import vectorbt as vbt

from ..volatility.bollinger_band import make_signals as bb_make_signals
from .ma_regime_strategy import calc_regime, REGIME_COLORS


def make_signals(
    close: pd.Series,
    high: pd.Series,
    low: pd.Series,
    volume: pd.Series = None,        # walk_forward 호환용 (미사용)
    ma_windows: tuple = (20, 60, 120),
    adx_window: int = 14,
    adx_threshold: float = 25.0,
    adx_sideways: float = 20.0,
    bb_window: int = 20,
    bb_std: float = 2.0,
    entry1_size: float = 0.4,        # 1차 매수: 골든크로스 목표 비중
    entry2_size: float = 0.7,        # 2차 매수: MA20 지지 확인 목표 비중
    entry_range_size: float = 0.3,   # 횡보 매수: BB 하단 목표 비중
    exit1_size: float = 0.4,         # 1차 매도 후 유지 비중 (TRANSITION)
    exit2_size: float = 0.1,         # 2차 매도 후 유지 비중 (데드크로스)
    recent_window: int = 60,         # 2차 매수 유효 기간 (거래일)
) -> tuple:
    """
    분할 매수/매도 신호 생성

    Returns
    -------
    entries, exits, size_series, detail
      size_series: targetpercent 방식 — NaN=유지, 0=전량청산, 양수=목표비중
    """
    regime, masks, adx_df = calc_regime(
        close, high, low, ma_windows, adx_window, adx_threshold, adx_sideways
    )

    UPTREND    = masks["UPTREND"]
    DOWNTREND  = masks["DOWNTREND"]
    SIDEWAYS   = masks["SIDEWAYS"]
    TRANSITION = masks["TRANSITION"]
    ma_s       = masks["ma_s"]   # MA20
    ma_m       = masks["ma_m"]   # MA60

    # ── 매수 신호 ──────────────────────────────────────────────────────────────
    # 1차: UPTREND + 골든크로스 (MA20이 MA60을 상향 돌파)
    golden_cross = (ma_s > ma_m) & (ma_s.shift(1) <= ma_m.shift(1))
    entry1 = golden_cross & UPTREND

    # 2차: UPTREND 유지 + MA20 지지 재확인
    #   - 조건: 저가가 MA20 이하 터치 후 종가가 MA20 위로 마감 (지지 확인)
    #   - 1차 매수 후 recent_window 거래일 이내에만 유효
    ma20_support = (low <= ma_s) & (close > ma_s)
    has_position = entry1.rolling(recent_window, min_periods=1).max().astype(bool)
    entry2 = ma20_support & UPTREND & has_position & ~entry1  # 1차 진입일 중복 제외

    # 횡보: SIDEWAYS + BB 하단 터치 (과매도 반전)
    bb_entry, bb_exit = bb_make_signals(close, window=bb_window, num_std=bb_std)
    entry_range = bb_entry & SIDEWAYS

    entries = entry1 | entry2 | entry_range

    # ── 매도 신호 ──────────────────────────────────────────────────────────────
    # 데드크로스 (MA20이 MA60을 하향 돌파) — 추세 전환 시작 신호
    dead_cross = (ma_s < ma_m) & (ma_s.shift(1) >= ma_m.shift(1))

    # UPTREND → TRANSITION 전환 첫날 — 추세 약화, 부분 익절
    transition_from_up = (
        TRANSITION
        & ~TRANSITION.shift(1).fillna(False)
        & UPTREND.shift(1).fillna(False)
    )

    exits = dead_cross | DOWNTREND | (bb_exit & SIDEWAYS)

    # ── size_series (목표 비중) ────────────────────────────────────────────────
    # 할당 순서 = 우선순위 (나중에 쓸수록 앞 값을 덮어씀)
    size_series = pd.Series(np.nan, index=close.index, dtype=float)

    # [낮은 우선순위] 매수
    size_series[entry_range]  = entry_range_size  # 횡보 30%
    size_series[entry1]       = entry1_size        # 1차 40%
    size_series[entry2]       = entry2_size        # 2차 70%

    # [높은 우선순위] 매도 — 매수 신호를 덮어씀
    size_series[transition_from_up] = exit1_size   # TRANSITION: 40% 유지
    size_series[dead_cross]         = exit2_size   # 데드크로스: 10% 유지
    size_series[bb_exit & SIDEWAYS] = 0.0          # 횡보 목표 달성: 전량 청산
    size_series[DOWNTREND]          = 0.0          # 하락 확정: 전량 청산 (최우선)

    detail = {
        "regime":             regime,
        "masks":              masks,
        "adx_df":             adx_df,
        "entry1":             entry1,             # 골든크로스 진입
        "entry2":             entry2,             # MA20 지지 추가매수
        "entry_range":        entry_range,         # BB 하단 진입
        "transition_from_up": transition_from_up,  # TRANSITION 전환 (1차 익절)
        "dead_cross":         dead_cross,          # 데드크로스 (2차 청산)
        "bb_exit_sideways":   bb_exit & SIDEWAYS,  # 횡보 청산
    }

    return entries, exits, size_series, detail


def run_backtest(
    close: pd.Series,
    high: pd.Series,
    low: pd.Series,
    volume: pd.Series = None,    # walk_forward 호환용 (미사용)
    adx_threshold: float = 25.0,
    adx_sideways: float = 20.0,
    fees: float = 0.0015,
    slippage: float = 0.001,
) -> vbt.Portfolio:
    """분할 매수/매도 전략 백테스트

    청산 우선순위 (높음 → 낮음):
      1. DOWNTREND 진입   → 0% 전량 청산
      2. 데드크로스        → 10% 유지
      3. TRANSITION 전환  → 40% 유지 (나머지 익절)
      4. BB 상단 (횡보)   → 0% 전량 청산
    """
    _, _, size_series, _ = make_signals(
        close, high, low,
        adx_threshold=adx_threshold,
        adx_sideways=adx_sideways,
    )
    return vbt.Portfolio.from_orders(
        close,
        size=size_series,
        size_type="targetpercent",
        fees=fees,
        slippage=slippage,
        freq="D",
    )
