"""
OBV(On-Balance Volume) 기반 거래량 확인 전략
- 가격이 오른 날 거래량 누적, 내린 날 거래량 차감 → 세력 매집/분산 감지
- OBV가 가격보다 먼저 방향을 신호하는 선행 지표

단독 전략:
- OBV가 단기 이동평균을 상향 돌파 → 매수 (매집 시작)
- OBV가 단기 이동평균을 하향 돌파 → 매도 (분산 시작)

다이버전스 활용:
- 가격 하락 중 OBV 상승 → 세력 매집, 반등 예고 (매수)
- 가격 상승 중 OBV 하락 → 거래량 뒷받침 없음, 하락 예고 (매도 주의)
"""

import pandas as pd
import vectorbt as vbt


def calc_obv(close: pd.Series, volume: pd.Series) -> pd.Series:
    """
    OBV 계산

    종가 상승일: OBV += 거래량
    종가 하락일: OBV -= 거래량
    종가 보합일: OBV 유지
    """
    direction = close.diff().apply(lambda x: 1 if x > 0 else (-1 if x < 0 else 0))
    obv = (direction * volume).cumsum()
    return obv.rename("OBV")


def calc_obv_divergence(
    close: pd.Series,
    volume: pd.Series,
    window: int = 20,
) -> pd.DataFrame:
    """
    OBV 다이버전스 감지

    Returns
    -------
    DataFrame with columns:
      obv          - OBV 값
      price_trend  - 가격 rolling 기울기 방향 (+1 / -1)
      obv_trend    - OBV rolling 기울기 방향 (+1 / -1)
      bullish_div  - 강세 다이버전스 (가격 하락 & OBV 상승)
      bearish_div  - 약세 다이버전스 (가격 상승 & OBV 하락)
    """
    obv = calc_obv(close, volume)

    price_slope = close - close.shift(window)
    obv_slope = obv - obv.shift(window)

    price_trend = price_slope.apply(lambda x: 1 if x > 0 else -1)
    obv_trend = obv_slope.apply(lambda x: 1 if x > 0 else -1)

    bullish_div = (price_trend == -1) & (obv_trend == 1)
    bearish_div = (price_trend == 1) & (obv_trend == -1)

    return pd.DataFrame(
        {
            "obv": obv,
            "price_trend": price_trend,
            "obv_trend": obv_trend,
            "bullish_div": bullish_div,
            "bearish_div": bearish_div,
        }
    )


def make_signals(
    close: pd.Series,
    volume: pd.Series,
    obv_ma_window: int = 20,
) -> tuple[pd.Series, pd.Series]:
    """
    OBV 단독 전략: OBV 이동평균 돌파 시그널

    진입: OBV가 OBV MA를 하향에서 상향 돌파 (매집 시작)
    청산: OBV가 OBV MA를 상향에서 하향 돌파 (분산 시작)
    """
    obv = calc_obv(close, volume)
    obv_ma = obv.rolling(obv_ma_window).mean()

    entries = (obv > obv_ma) & (obv.shift(1) <= obv_ma.shift(1))
    exits = (obv < obv_ma) & (obv.shift(1) >= obv_ma.shift(1))

    return entries, exits


def make_divergence_signals(
    close: pd.Series,
    volume: pd.Series,
    window: int = 20,
) -> tuple[pd.Series, pd.Series]:
    """
    OBV 다이버전스 전략

    진입: 강세 다이버전스 (가격 하락 중 OBV 상승) → 반등 기대 매수
    청산: 약세 다이버전스 (가격 상승 중 OBV 하락) → 추세 약화 매도
    """
    div_df = calc_obv_divergence(close, volume, window)

    entries = div_df["bullish_div"] & ~div_df["bullish_div"].shift(1).fillna(False)
    exits = div_df["bearish_div"] & ~div_df["bearish_div"].shift(1).fillna(False)

    return entries, exits


def run_backtest(
    close: pd.Series,
    volume: pd.Series,
    obv_ma_window: int = 20,
    fees: float = 0.001,
    slippage: float = 0.001,
) -> vbt.Portfolio:
    """OBV MA 돌파 전략 백테스트 실행"""
    entries, exits = make_signals(close, volume, obv_ma_window)
    return vbt.Portfolio.from_signals(
        close,
        entries,
        exits,
        fees=fees,
        slippage=slippage,
        freq="D",
    )


def run_divergence_backtest(
    close: pd.Series,
    volume: pd.Series,
    window: int = 20,
    fees: float = 0.001,
    slippage: float = 0.001,
) -> vbt.Portfolio:
    """OBV 다이버전스 전략 백테스트 실행"""
    entries, exits = make_divergence_signals(close, volume, window)
    return vbt.Portfolio.from_signals(
        close,
        entries,
        exits,
        fees=fees,
        slippage=slippage,
        freq="D",
    )
