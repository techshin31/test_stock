"""
MA 정렬 + ADX 시장국면 기반 통합 전략 스위처

국면 → 전략 매핑 (4국면):
  UPTREND   (상승 추세): MA bull정렬 AND ADX > threshold AND ADX >= 20
    → 골든크로스 진입 | 포지션 100%
  DOWNTREND (하락 추세): MA bear정렬 AND ADX > threshold AND ADX >= 20
    → 전량 청산, 현금 보유 | 포지션 0%
  SIDEWAYS  (횡보장):   ADX < 20
    → 볼린저 밴드 하단 진입 | 포지션 50%
  TRANSITION(전환 구간): 위 3가지 조건 미해당
    → 신규 진입 차단, 기존 포지션 유지 | 포지션 NaN

판별 우선순위: SIDEWAYS → UPTREND → DOWNTREND → TRANSITION

포지션 크기 조절 원리:
  UPTREND  (확신)   → 100% 풀 포지션  ← 수익 극대화
  SIDEWAYS (불확실) →  50% 절반 포지션 ← 손실 제한
  DOWNTREND(위험)   →   0% 전량 청산  ← 손실 방어
  TRANSITION(모호)  →  NaN 유지       ← 불필요한 조기 청산 방지

청산 방식 (run_backtest 기준):
  DOWNTREND 전환 → 유일한 전량 청산 조건 (size=0.0)
  UPTREND / SIDEWAYS / TRANSITION → DOWNTREND 전환 전까지 포지션 유지
  ※ 개별 종목 손절(%손실 기준)은 미구현
"""

import numpy as np
import pandas as pd
import vectorbt as vbt

from ..trend_strength.adx_strategy import calc_adx
from ..volatility.bollinger_band import make_signals as bb_make_signals
from ..trend.golden_cross import make_signals as gc_make_signals


# ── 국면 상수 ─────────────────────────────────────────────────────────────────
REGIME_UPTREND    = "UPTREND"
REGIME_DOWNTREND  = "DOWNTREND"
REGIME_SIDEWAYS   = "SIDEWAYS"
REGIME_TRANSITION = "TRANSITION"

REGIME_COLORS = {
    REGIME_UPTREND:    ("green",     0.20),
    REGIME_DOWNTREND:  ("red",       0.20),
    REGIME_SIDEWAYS:   ("lightgray", 0.40),
    REGIME_TRANSITION: ("gold",      0.20),
}


def calc_regime(
    close: pd.Series,
    high: pd.Series,
    low: pd.Series,
    ma_windows: tuple[int, int, int] = (20, 60, 120),
    adx_window: int = 14,
    adx_threshold: float = 25.0,
    adx_sideways: float = 20.0,
) -> tuple[pd.Series, dict, pd.DataFrame]:
    """
    MA 3중 구조 + ADX로 4가지 시장 국면 판별

    판별 우선순위
    1. ADX < adx_sideways  → SIDEWAYS
    2. MA bull정렬 AND ADX > adx_threshold → UPTREND
    3. MA bear정렬 AND ADX > adx_threshold → DOWNTREND
    4. 그 외 → TRANSITION

    Returns
    -------
    regime   : Series     - 국면 이름 문자열
    masks    : dict       - {'UPTREND': bool Series, ..., 'ma_s': Series, ...}
    adx_df   : DataFrame  - ADX, plus_di, minus_di
    """
    ma_s = close.rolling(ma_windows[0]).mean()
    ma_m = close.rolling(ma_windows[1]).mean()
    ma_l = close.rolling(ma_windows[2]).mean()

    adx_df = calc_adx(high, low, close, adx_window)
    adx    = adx_df["ADX"]

    # 우선순위 적용
    SIDEWAYS   = adx < adx_sideways
    UPTREND    = (ma_s > ma_m) & (ma_m > ma_l) & (adx > adx_threshold) & ~SIDEWAYS
    DOWNTREND  = (ma_s < ma_m) & (ma_m < ma_l) & (adx > adx_threshold) & ~SIDEWAYS
    TRANSITION = ~SIDEWAYS & ~UPTREND & ~DOWNTREND

    regime = pd.Series(REGIME_TRANSITION, index=close.index)
    regime[SIDEWAYS]   = REGIME_SIDEWAYS
    regime[UPTREND]    = REGIME_UPTREND
    regime[DOWNTREND]  = REGIME_DOWNTREND

    masks = {
        "UPTREND":    UPTREND,
        "DOWNTREND":  DOWNTREND,
        "SIDEWAYS":   SIDEWAYS,
        "TRANSITION": TRANSITION,
        "ma_s": ma_s,
        "ma_m": ma_m,
        "ma_l": ma_l,
        "adx":  adx,
    }

    return regime, masks, adx_df


def make_signals(
    close: pd.Series,
    high: pd.Series,
    low: pd.Series,
    ma_windows: tuple[int, int, int] = (20, 60, 120),
    adx_window: int = 14,
    adx_threshold: float = 25.0,
    adx_sideways: float = 20.0,
    bb_window: int = 20,
    bb_std: float = 2.0,
) -> tuple[pd.Series, pd.Series, pd.Series, dict]:
    """
    국면별 최적 전략 신호 생성

    UPTREND    → 골든크로스 진입 (100%)
    SIDEWAYS   → 볼린저 밴드 하단 반등 (50%)
    DOWNTREND  → 전량 청산, 현금 보유 (0%)
    TRANSITION → 신규 진입 차단, 기존 포지션 유지 (NaN)

    Returns
    -------
    entries, exits, size_series, detail
      detail: dict — 국면/개별 신호 Series 묶음 (시각화용)
    """
    regime, masks, adx_df = calc_regime(
        close, high, low, ma_windows, adx_window, adx_threshold, adx_sideways
    )
    UPTREND   = masks["UPTREND"]
    DOWNTREND = masks["DOWNTREND"]
    SIDEWAYS  = masks["SIDEWAYS"]

    # ── 1) UPTREND: 골든크로스 ────────────────────────────────────────────────
    gc_entries_raw, gc_exits_raw = gc_make_signals(
        close, fast_window=ma_windows[0], slow_window=ma_windows[1]
    )
    gc_entries = gc_entries_raw & UPTREND      # UPTREND 국면에서만 진입
    gc_exits   = gc_exits_raw | DOWNTREND     # 데드크로스(MA20<MA60) 또는 DOWNTREND 전환 시 청산

    # ── 2) SIDEWAYS: 볼린저 밴드 ─────────────────────────────────────────────
    bb_entries_raw, bb_exits_raw = bb_make_signals(close, window=bb_window, num_std=bb_std)
    bb_entries = bb_entries_raw & SIDEWAYS    # SIDEWAYS 국면에서만 진입
    bb_exits   = bb_exits_raw | DOWNTREND    # BB 상단 터치 또는 DOWNTREND 전환 시 청산

    # TRANSITION: 신규 진입 없음, 기존 포지션 유지 → 별도 청산 신호 없음

    # ── 전략 병합 ────────────────────────────────────────────────────────────
    entries = gc_entries | bb_entries
    exits   = gc_exits   | bb_exits

    # ── 포지션 크기 (targetpercent) ──────────────────────────────────────────
    size_series = pd.Series(np.nan, index=close.index, dtype=float)
    size_series[gc_entries] = 1.0   # UPTREND → 100%
    size_series[bb_entries] = 0.5   # SIDEWAYS → 50%
    size_series[DOWNTREND]  = 0.0   # DOWNTREND → 전량 청산
    # TRANSITION → NaN 유지 (기존 포지션 그대로)

    detail = {
        "regime":         regime,
        "masks":          masks,
        "adx_df":         adx_df,
        "gc_entries_raw": gc_entries_raw,
        "bb_entries_raw": bb_entries_raw,
        "gc_entries":     gc_entries,
        "bb_entries":     bb_entries,
        "gc_exits":       gc_exits,
        "bb_exits":       bb_exits,
    }

    return entries, exits, size_series, detail


def run_backtest(
    close: pd.Series,
    high: pd.Series,
    low: pd.Series,
    ma_windows: tuple[int, int, int] = (20, 60, 120),
    adx_threshold: float = 25.0,
    adx_sideways: float = 20.0,
    fees: float = 0.0015,
    slippage: float = 0.001,
) -> vbt.Portfolio:
    """MA 정렬 + ADX 4국면 기반 통합 전략 백테스트 실행

    청산은 DOWNTREND 전환(size=0.0)만 적용된다.
    make_signals()의 gc_exits/bb_exits(데드크로스·BB상단)는 사용하지 않는다.
    """
    _, _, size_series, _ = make_signals(
        close, high, low,
        ma_windows=ma_windows,
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
