"""
부분 매수/매도 전략 (Partial Position Sizing)

08번 대비 핵심 변경:
  1. 진입 비중: 국면별 고정(100/70/50%) → ADX 강도 비례 동적 비중
  2. 청산 방식: 즉시 전량 → 단계적 (WEAK_BEAR 첫날 → 30% 유지, STRONG_BEAR → 0%)
  3. WF 최적화: adx_threshold 1개 → adx_threshold + adx_scale 2D 탐색

ADX 비례 진입 비중 공식:
  size = clip(min_size + (1 - min_size) * (ADX - threshold) / adx_scale, min_size, 1.0)
  ADX = threshold          → min_size (0.3)
  ADX = threshold + scale  → 1.0

단계적 청산:
  WEAK_BEAR 진입 첫날 → weak_bear_size (30%) 유지  ← 반등 가능성 보존
  STRONG_BEAR 진입 첫날 → 0% 전량 청산            ← 확정 하락 대응
"""

import numpy as np
import pandas as pd
import vectorbt as vbt

from .bollinger_band import make_signals as bb_make_signals
from .golden_cross import make_signals as gc_make_signals
from .macd_strategy import calc_macd
from .obv_strategy import calc_obv
from .ma_regime_strategy import calc_regime


def make_signals(
    close: pd.Series,
    high: pd.Series,
    low: pd.Series,
    volume: pd.Series,
    ma_windows: tuple = (20, 60, 120),
    adx_window: int = 14,
    adx_threshold: float = 25.0,
    adx_scale: float = 30.0,
    min_entry_size: float = 0.3,
    weak_bear_size: float = 0.3,
    bb_window: int = 20,
    bb_std: float = 2.0,
    obv_ma_window: int = 20,
) -> tuple:
    """
    ADX 비례 동적 비중 + 단계적 청산 신호 생성

    Returns
    -------
    entries, exits, size_series, detail
    """
    regime, masks, adx_df = calc_regime(
        close, high, low, ma_windows, adx_window, adx_threshold
    )
    adx = adx_df["ADX"]
    STRONG_BULL = masks["STRONG_BULL"]
    WEAK_BULL   = masks["WEAK_BULL"]
    RANGING     = masks["RANGING"]
    WEAK_BEAR   = masks["WEAK_BEAR"]
    STRONG_BEAR = masks["STRONG_BEAR"]
    ma_s        = masks["ma_s"]

    # ── Entry signals (08번과 동일) ──────────────────────────────────────────
    gc_e, gc_x = gc_make_signals(
        close, fast_window=ma_windows[0], slow_window=ma_windows[1]
    )
    macd_df = calc_macd(close)
    macd_cross_up = (macd_df["MACD"] > macd_df["Signal"]) & (
        macd_df["MACD"].shift(1) <= macd_df["Signal"].shift(1)
    )
    macd_cross_dn = (macd_df["MACD"] < macd_df["Signal"]) & (
        macd_df["MACD"].shift(1) >= macd_df["Signal"].shift(1)
    )

    strong_entries = (gc_e | macd_cross_up) & STRONG_BULL
    strong_exits   = gc_x | macd_cross_dn

    touch_ma20  = (low <= ma_s) & (close > ma_s)
    obv         = calc_obv(close, volume)
    obv_ma      = obv.rolling(obv_ma_window).mean()
    obv_confirm = obv > obv_ma
    weak_entries = touch_ma20 & obv_confirm & WEAK_BULL
    weak_exits   = (close < ma_s) & ~WEAK_BULL

    bb_e, bb_x    = bb_make_signals(close, window=bb_window, num_std=bb_std)
    range_entries = bb_e & RANGING
    range_exits   = bb_x

    entries = strong_entries | weak_entries | range_entries

    # ── [09번 변경 1] ADX 비례 동적 진입 비중 ─────────────────────────────
    # ADX 값이 높을수록 → 더 강한 추세 확인 → 더 큰 포지션
    adx_ratio = np.clip(
        min_entry_size + (1.0 - min_entry_size) * (adx - adx_threshold) / adx_scale,
        min_entry_size, 1.0,
    )

    size_series = pd.Series(np.nan, index=close.index, dtype=float)
    size_series[strong_entries] = adx_ratio[strong_entries]
    size_series[weak_entries]   = (adx_ratio * 0.7).clip(lower=min_entry_size * 0.5)[weak_entries]
    size_series[range_entries]  = min_entry_size

    # ── [09번 변경 2] 단계적 청산 ─────────────────────────────────────────
    # 포지션이 있을 가능성이 높은 경우에만 부분 청산 (최근 30일 내 진입 신호)
    recent_entry = entries.rolling(30, min_periods=1).max().astype(bool)

    # WEAK_BEAR 첫날: weak_bear_size로 축소 (포지션 있을 때)
    weak_bear_start  = WEAK_BEAR & ~WEAK_BEAR.shift(1).fillna(False) & recent_entry
    # STRONG_BEAR 첫날: 전량 청산
    strong_bear_start = STRONG_BEAR & ~STRONG_BEAR.shift(1).fillna(False)

    size_series[weak_bear_start]   = weak_bear_size
    size_series[strong_bear_start] = 0.0

    # 기술적 청산 신호 (즉시 전량)
    size_series[strong_exits] = 0.0
    size_series[weak_exits]   = 0.0
    size_series[range_exits]  = 0.0

    exits = strong_exits | weak_exits | range_exits | STRONG_BEAR

    detail = {
        "regime":            regime,
        "masks":             masks,
        "adx_df":            adx_df,
        "adx_ratio":         adx_ratio,
        "strong_entries":    strong_entries,
        "weak_entries":      weak_entries,
        "range_entries":     range_entries,
        "strong_exits":      strong_exits,
        "weak_exits":        weak_exits,
        "range_exits":       range_exits,
        "weak_bear_start":   weak_bear_start,
        "strong_bear_start": strong_bear_start,
    }

    return entries, exits, size_series, detail


def run_backtest(
    close: pd.Series,
    high: pd.Series,
    low: pd.Series,
    volume: pd.Series,
    adx_threshold: float = 25.0,
    adx_scale: float = 30.0,
    fees: float = 0.0015,
    slippage: float = 0.001,
) -> vbt.Portfolio:
    """ADX 비례 동적 비중 + 단계적 청산 백테스트 실행"""
    _, _, size_series, _ = make_signals(
        close, high, low, volume,
        adx_threshold=adx_threshold,
        adx_scale=adx_scale,
    )
    return vbt.Portfolio.from_orders(
        close,
        size=size_series,
        size_type="targetpercent",
        fees=fees,
        slippage=slippage,
        freq="D",
    )
