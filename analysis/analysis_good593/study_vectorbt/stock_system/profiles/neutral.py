import numpy as np
import pandas as pd

from .base import FEES, SLIPPAGE, WF_TRAIN_MONTHS, WF_TEST_MONTHS, ADX_PARAM_GRID  # noqa: F401

ADX_THRESHOLD    = 25.0
ADX_SIDEWAYS     = 20.0
ENTRY1_SIZE      = 0.4
ENTRY2_SIZE      = 0.7
ENTRY_RANGE_SIZE = 0.3
EXIT1_SIZE       = 0.4
EXIT2_SIZE       = 0.1
RECENT_WINDOW    = 60
MOMENTUM_WINDOW  = {"UPTREND": 126, "TRANSITION": 63, "SIDEWAYS": 21}
MIN_MOMENTUM     = 0.0
ATR_PERIOD       = 14
ATR_MULTIPLIER   = 2.0
KOSPI_MA         = 60
CASH_RETURN      = 0.035

METRICS_TARGET = {
    "cagr":              0.06,
    "mdd":              -0.25,
    "mdd_duration":       12,
    "calmar":             0.3,
    "sortino":            0.5,
    "alpha":              0.02,
    "beta":               0.8,
    "mdd_reduction":      0.20,
    "calmar_improvement": 0.1,
    "info_ratio":         0.3,
    "win_rate":           0.5,
}
METRICS_ALERT = {
    "cagr":              0.04,
    "mdd":              -0.35,
    "mdd_duration":       18,
    "calmar":             0.2,
    "sortino":            0.3,
    "alpha":              0.0,
    "beta":               1.0,
    "mdd_reduction":      0.10,
    "calmar_improvement": 0.0,
    "info_ratio":         0.0,
    "win_rate":           0.4,
}


def make_signals(
    close: pd.Series,
    high: pd.Series,
    low: pd.Series,
    adx_threshold: float = ADX_THRESHOLD,
    adx_sideways: float = ADX_SIDEWAYS,
    kospi: pd.Series = None,
    use_adx_mode: bool = True,
) -> tuple:
    """분할 매수/매도 신호 생성 — 위험중립형 전략

    [분할 매수] 3단계
      1차: 비UPTREND → UPTREND 전환 첫날                → ENTRY1_SIZE (40%)
      2차: UPTREND 유지 + 종가 > MA20 (RECENT_WINDOW 이내) → ENTRY2_SIZE (70%)
      횡보: SIDEWAYS + BB 하단 상향 돌파                 → ENTRY_RANGE_SIZE (30%)

    [분할 매도] 3단계
      1차: UPTREND → TRANSITION 전환 첫날               → EXIT1_SIZE (40%) 유지
      2차: 데드크로스 (MA20 < MA60)                     → EXIT2_SIZE (10%) 유지
      3차: DOWNTREND 진입                               → 0% 전량 청산
      횡보 청산: SIDEWAYS + BB 상단 하향 돌파             → 0% 전량 청산

    [ATR stop-loss] 최우선
      당일 낙폭 > ATR × ATR_MULTIPLIER → 0% 즉시 전량 청산

    Returns
    -------
    entries, exits, size_series, detail
      size_series: targetpercent — NaN=유지, 0.0=전량청산, 양수=목표비중
    """
    from ..strategies.regime import calc_regime
    from ..indicators.volatility.bollinger import calc_bollinger
    from ..indicators.volatility.atr import calc_atr

    regime, masks, adx_df = calc_regime(
        close, high, low,
        adx_threshold=adx_threshold,
        adx_sideways=adx_sideways,
        kospi=kospi,
        kospi_ma=KOSPI_MA,
        use_adx_mode=use_adx_mode,
    )

    UPTREND    = masks["UPTREND"]
    DOWNTREND  = masks["DOWNTREND"]
    SIDEWAYS   = masks["SIDEWAYS"]
    TRANSITION = masks["TRANSITION"]
    ma_s       = masks["ma_s"]   # MA20
    ma_m       = masks["ma_m"]   # MA60

    # ── 매수 신호 ──────────────────────────────────────────────────────────────
    entry1 = UPTREND & ~UPTREND.shift(1).fillna(False)

    ma20_support        = close > ma_s
    had_entry1_recently = entry1.rolling(RECENT_WINDOW, min_periods=1).max().astype(bool)
    entry2 = ma20_support & UPTREND & had_entry1_recently & ~entry1

    upper, _, lower = calc_bollinger(close, 20, 2.0)
    bb_exit_sideways  = (close < upper) & (close.shift(1) >= upper.shift(1)) & SIDEWAYS
    entry_range       = (close > lower) & (close.shift(1) <= lower.shift(1)) & SIDEWAYS

    entries = entry1 | entry2 | entry_range

    # ── 매도 신호 ──────────────────────────────────────────────────────────────
    dead_cross = (ma_s < ma_m) & (ma_s.shift(1) >= ma_m.shift(1))
    transition_from_up = (
        TRANSITION
        & ~TRANSITION.shift(1).fillna(False)
        & UPTREND.shift(1).fillna(False)
    )

    exits = dead_cross | DOWNTREND | bb_exit_sideways

    # ── size_series (목표 비중) — 나중 할당이 앞 값을 덮어씀 ────────────────────
    size_series = pd.Series(np.nan, index=close.index, dtype=float)

    size_series[entry_range]        = ENTRY_RANGE_SIZE
    size_series[entry1]             = ENTRY1_SIZE
    size_series[entry2]             = ENTRY2_SIZE
    size_series[transition_from_up] = EXIT1_SIZE
    size_series[dead_cross]         = EXIT2_SIZE
    size_series[bb_exit_sideways]   = 0.0
    size_series[DOWNTREND]          = 0.0

    # ── ATR Stop-Loss: 최우선 ──────────────────────────────────────────────────
    atr        = calc_atr(high, low, close, period=ATR_PERIOD)
    daily_drop = close.pct_change()
    atr_stop   = daily_drop < -(atr.shift(1) / close.shift(1) * ATR_MULTIPLIER)
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
        "bb_exit_sideways":   bb_exit_sideways,
        "atr_stop":           atr_stop,
    }
    return entries, exits, size_series, detail


def get_signal(close_df, high_df, low_df, kospi=None, use_adx_mode: bool = True):
    """오늘의 매매 신호 생성 — 자동매매 시스템 진입점

    Parameters
    ----------
    close_df     : DataFrame  최소 150일 이상의 과거 종가 (MA120 warmup 필요)
    use_adx_mode : WF IS score > 0이면 True(ADX 모드), ≤ 0이면 False(MA+KOSPI 모드)

    Returns
    -------
    dict  종목명 → 오늘 목표 비중 (NaN=유지, 0.0=전량청산, 양수=목표비중)
    """
    result = {}
    for name in close_df.columns:
        _, _, size_s, _ = make_signals(
            close_df[name], high_df[name], low_df[name],
            kospi=kospi,
            use_adx_mode=use_adx_mode,
        )
        result[name] = size_s.iloc[-1]
    return result
