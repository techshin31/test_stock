"""
MA 정렬 + ADX 시장국면 기반 통합 전략 스위처

국면 → 전략 매핑:
  STRONG_BULL (강한 상승): MA bull정렬 AND ADX > threshold
    → 골든크로스 OR MACD 상향 돌파 (추세 이중 확인) | 포지션 100%
  WEAK_BULL (약한 상승): MA bull정렬 AND ADX ≤ threshold
    → MA20 눌림목 (저가 MA20 터치 후 종가 위에서 마감) AND OBV 이동평균 위 | 포지션 70%
  RANGING (횡보/조정): MA 혼재
    → 볼린저 밴드 하단 반등 | 포지션 50%
  BEAR (하락 추세): MA bear정렬
    → 미진입 (현금 보유) | 포지션 0%

포지션 크기 조절 원리:
  확신도가 높을수록 비중 확대 → 기대수익/리스크 비율 최적화
"""

import numpy as np
import pandas as pd
import vectorbt as vbt

from .adx_strategy import calc_adx
from .bollinger_band import make_signals as bb_make_signals
from .golden_cross import make_signals as gc_make_signals
from .macd_strategy import calc_macd
from .obv_strategy import calc_obv


# ── 국면 상수 ─────────────────────────────────────────────────────────────────
REGIME_STRONG_BULL = "강한 상승"
REGIME_WEAK_BULL = "약한 상승"
REGIME_RANGING = "횡보/조정"
REGIME_WEAK_BEAR = "약한 하락"
REGIME_STRONG_BEAR = "강한 하락"

REGIME_COLORS = {
    REGIME_STRONG_BULL: ("green", 0.20),
    REGIME_WEAK_BULL: ("limegreen", 0.12),
    REGIME_RANGING: ("lightgray", 0.25),
    REGIME_WEAK_BEAR: ("lightsalmon", 0.15),
    REGIME_STRONG_BEAR: ("red", 0.20),
}


def calc_regime(
    close: pd.Series,
    high: pd.Series,
    low: pd.Series,
    ma_windows: tuple[int, int, int] = (20, 60, 120),
    adx_window: int = 14,
    adx_threshold: float = 25.0,
) -> tuple[pd.Series, dict, pd.DataFrame]:
    """
    MA 3중 구조 + ADX로 5가지 시장 국면 판별

    Returns
    -------
    regime   : Series  - 국면 이름 문자열
    masks    : dict    - {'STRONG_BULL': bool Series, ...}
    adx_df   : DataFrame - ADX, plus_di, minus_di
    """
    ma_s = close.rolling(ma_windows[0]).mean()
    ma_m = close.rolling(ma_windows[1]).mean()
    ma_l = close.rolling(ma_windows[2]).mean()

    adx_df = calc_adx(high, low, close, adx_window)
    adx = adx_df["ADX"]

    bull_align = (ma_s > ma_m) & (ma_m > ma_l)
    bear_align = (ma_s < ma_m) & (ma_m < ma_l)
    mixed = ~bull_align & ~bear_align

    STRONG_BULL = bull_align & (adx > adx_threshold)
    WEAK_BULL = bull_align & (adx <= adx_threshold)
    RANGING = mixed
    WEAK_BEAR = bear_align & (adx <= adx_threshold)
    STRONG_BEAR = bear_align & (adx > adx_threshold)

    regime = pd.Series(REGIME_RANGING, index=close.index)
    regime[WEAK_BULL] = REGIME_WEAK_BULL
    regime[STRONG_BULL] = REGIME_STRONG_BULL
    regime[WEAK_BEAR] = REGIME_WEAK_BEAR
    regime[STRONG_BEAR] = REGIME_STRONG_BEAR

    masks = {
        "STRONG_BULL": STRONG_BULL,
        "WEAK_BULL": WEAK_BULL,
        "RANGING": RANGING,
        "WEAK_BEAR": WEAK_BEAR,
        "STRONG_BEAR": STRONG_BEAR,
        "ma_s": ma_s,
        "ma_m": ma_m,
        "ma_l": ma_l,
    }

    return regime, masks, adx_df


def make_signals(
    close: pd.Series,
    high: pd.Series,
    low: pd.Series,
    volume: pd.Series,
    ma_windows: tuple[int, int, int] = (20, 60, 120),
    adx_window: int = 14,
    adx_threshold: float = 25.0,
    bb_window: int = 20,
    bb_std: float = 2.0,
    obv_ma_window: int = 20,
) -> tuple[pd.Series, pd.Series, pd.Series, dict]:
    """
    국면별 최적 전략 신호 생성

    STRONG_BULL → 골든크로스 OR MACD 상향 돌파 (추세 이중 확인)
    WEAK_BULL   → MA20 눌림목 (저가 MA20 터치 후 종가 위 마감) AND OBV 이평선 위
    RANGING     → 볼린저 밴드 하단 반등
    BEAR        → 미진입 (현금 보유)

    Returns
    -------
    entries, exits, size_series, detail
      detail: dict — 국면/개별 신호 Series 묶음 (시각화용)
    """
    regime, masks, adx_df = calc_regime(
        close, high, low, ma_windows, adx_window, adx_threshold
    )
    STRONG_BULL = masks["STRONG_BULL"]
    WEAK_BULL = masks["WEAK_BULL"]
    RANGING = masks["RANGING"]
    ma_s = masks["ma_s"]

    # ── 1) STRONG_BULL: 골든크로스 OR MACD 상향 돌파 ────────────────────────
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
    strong_exits = gc_x | macd_cross_dn

    # ── 2) WEAK_BULL: MA20 눌림목 + OBV 거래량 확인 ─────────────────────────
    # 저가가 MA20에 닿았다가 종가가 MA20 위에서 마감 → 기관 지지선 확인
    touch_ma20 = (low <= ma_s) & (close > ma_s)

    obv = calc_obv(close, volume)
    obv_ma = obv.rolling(obv_ma_window).mean()
    obv_confirm = obv > obv_ma  # 거래량 매집 우세

    weak_entries = touch_ma20 & obv_confirm & WEAK_BULL
    # WEAK_BULL 국면이 끝나거나(국면 전환) close가 MA20 아래로 이탈하면 청산
    weak_exits = (close < ma_s) & ~WEAK_BULL

    # ── 3) RANGING: 볼린저 밴드 ──────────────────────────────────────────────
    bb_e, bb_x = bb_make_signals(close, window=bb_window, num_std=bb_std)
    range_entries = bb_e & RANGING
    range_exits = bb_x

    # ── BEAR 국면 강제 청산 ──────────────────────────────────────────────────
    bear_exit = masks["WEAK_BEAR"] | masks["STRONG_BEAR"]

    # ── 전략 병합 ────────────────────────────────────────────────────────────
    entries = strong_entries | weak_entries | range_entries
    exits = strong_exits | weak_exits | range_exits | bear_exit

    # ── 포지션 크기 (targetpercent) ──────────────────────────────────────────
    size_series = pd.Series(np.nan, index=close.index, dtype=float)
    size_series[strong_entries] = 1.0   # 강한 추세 → 100%
    size_series[weak_entries] = 0.7     # 눌림목 + 거래량 확인 → 70%
    size_series[range_entries] = 0.5    # 횡보 → 50%
    size_series[exits] = 0.0
    size_series[bear_exit] = 0.0        # BEAR 전환 시 즉시 0%

    detail = {
        "regime": regime,
        "masks": masks,
        "adx_df": adx_df,
        "strong_entries": strong_entries,
        "weak_entries": weak_entries,
        "range_entries": range_entries,
        "strong_exits": strong_exits,
        "weak_exits": weak_exits,
        "range_exits": range_exits,
        "touch_ma20": touch_ma20,
        "obv": obv,
        "obv_ma": obv_ma,
        "macd_df": macd_df,
    }

    return entries, exits, size_series, detail


def run_backtest(
    close: pd.Series,
    high: pd.Series,
    low: pd.Series,
    volume: pd.Series,
    ma_windows: tuple[int, int, int] = (20, 60, 120),
    adx_threshold: float = 25.0,
    fees: float = 0.0015,
    slippage: float = 0.001,
) -> vbt.Portfolio:
    """MA 정렬 + ADX 국면 기반 통합 전략 백테스트 실행"""
    _, _, size_series, _ = make_signals(
        close, high, low, volume,
        ma_windows=ma_windows,
        adx_threshold=adx_threshold,
    )
    return vbt.Portfolio.from_orders(
        close,
        size=size_series,
        size_type="targetpercent",
        fees=fees,
        slippage=slippage,
        freq="D",
    )
