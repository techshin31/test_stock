"""
RSI(Relative Strength Index) 기반 역추세 전략
- RSI < 과매도 기준선 → 매수 신호 (저점 반등 기대)
- RSI > 과매수 기준선 → 매도 신호 (고점 조정 기대)
"""

import pandas as pd
import vectorbt as vbt


def calc_rsi(close: pd.Series, window: int = 14) -> pd.Series:
    """RSI 계산"""
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(com=window - 1, min_periods=window).mean()
    avg_loss = loss.ewm(com=window - 1, min_periods=window).mean()
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    return rsi.rename("RSI")


def make_signals(
    close: pd.Series,
    rsi_window: int = 14,
    oversold: float = 30.0,
    overbought: float = 70.0,
) -> tuple[pd.Series, pd.Series]:
    """
    RSI 역추세 진입/청산 시그널 생성

    - RSI가 oversold 아래에서 위로 올라올 때 매수
    - RSI가 overbought 위에서 아래로 내려올 때 매도
    """
    rsi = calc_rsi(close, rsi_window)

    entries = (rsi > oversold) & (rsi.shift(1) <= oversold)
    exits = (rsi < overbought) & (rsi.shift(1) >= overbought)

    return entries, exits


def run_backtest(
    close: pd.Series,
    rsi_window: int = 14,
    oversold: float = 30.0,
    overbought: float = 70.0,
    fees: float = 0.001,
    slippage: float = 0.001,
) -> vbt.Portfolio:
    """RSI 전략 백테스트 실행"""
    entries, exits = make_signals(close, rsi_window, oversold, overbought)
    return vbt.Portfolio.from_signals(
        close,
        entries,
        exits,
        fees=fees,
        slippage=slippage,
        freq="D",
    )
