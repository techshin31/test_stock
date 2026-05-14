"""
ADX(Average Directional Index) 기반 추세 강도 필터 전략
- ADX는 방향 없이 추세 강도(0~100)만 측정하는 보조 지표
- 단독 전략보다 다른 방향 전략의 게이트웨이 필터로 사용
- ADX > threshold → 추세 확인, 방향 전략 신호 허용
- ADX < threshold → 횡보 감지, 역추세 전략 신호 허용

단독 전략 예시 (+DI/-DI 교차):
- +DI가 -DI를 상향 돌파 AND ADX > 20 → 매수
- -DI가 +DI를 상향 돌파 AND ADX > 20 → 매도
"""

import pandas as pd
import vectorbt as vbt

from ..volatility.atr import calc_atr


def calc_adx(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    window: int = 14,
) -> pd.DataFrame:
    """
    ADX, +DI, -DI 계산 (Wilder's smoothing 방식)

    Returns
    -------
    DataFrame with columns: ADX, plus_di, minus_di
    """
    # 방향 움직임
    up_move = high - high.shift(1)
    down_move = low.shift(1) - low

    plus_dm = up_move.where((up_move > down_move) & (up_move > 0), 0.0)
    minus_dm = down_move.where((down_move > up_move) & (down_move > 0), 0.0)

    # Wilder's smoothing (EWM com = window - 1)
    atr = calc_atr(high, low, close, period=window)
    plus_di = 100 * plus_dm.ewm(com=window - 1, min_periods=window).mean() / atr
    minus_di = 100 * minus_dm.ewm(com=window - 1, min_periods=window).mean() / atr

    # DX → ADX
    dx = (100 * (plus_di - minus_di).abs() / (plus_di + minus_di)).fillna(0)
    adx = dx.ewm(com=window - 1, min_periods=window).mean()

    return pd.DataFrame({"ADX": adx, "plus_di": plus_di, "minus_di": minus_di})


def is_trending(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    window: int = 14,
    threshold: float = 25.0,
) -> pd.Series:
    """ADX > threshold 이면 True (추세장 판별 마스크)"""
    adx_df = calc_adx(high, low, close, window)
    return adx_df["ADX"] > threshold


def is_ranging(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    window: int = 14,
    threshold: float = 20.0,
) -> pd.Series:
    """ADX < threshold 이면 True (횡보장 판별 마스크)"""
    adx_df = calc_adx(high, low, close, window)
    return adx_df["ADX"] < threshold


def make_signals(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    window: int = 14,
    adx_threshold: float = 20.0,
) -> tuple[pd.Series, pd.Series]:
    """
    ADX 단독 전략: +DI/-DI 교차 + ADX 강도 확인

    진입: +DI가 -DI를 상향 돌파 AND ADX > adx_threshold
    청산: -DI가 +DI를 상향 돌파
    """
    adx_df = calc_adx(high, low, close, window)
    plus_di = adx_df["plus_di"]
    minus_di = adx_df["minus_di"]
    adx = adx_df["ADX"]

    trend_confirmed = adx > adx_threshold

    entries = (
        (plus_di > minus_di)
        & (plus_di.shift(1) <= minus_di.shift(1))
        & trend_confirmed
    )
    exits = (minus_di > plus_di) & (minus_di.shift(1) <= plus_di.shift(1))

    return entries, exits


def run_backtest(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    window: int = 14,
    adx_threshold: float = 20.0,
    fees: float = 0.001,
    slippage: float = 0.001,
) -> vbt.Portfolio:
    """ADX 단독 전략 백테스트 실행"""
    entries, exits = make_signals(high, low, close, window, adx_threshold)
    return vbt.Portfolio.from_signals(
        close,
        entries,
        exits,
        fees=fees,
        slippage=slippage,
        freq="D",
    )
