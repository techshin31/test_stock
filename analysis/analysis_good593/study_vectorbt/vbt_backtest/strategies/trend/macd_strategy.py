"""
MACD(Moving Average Convergence Divergence) 전략
- MACD선이 시그널선을 상향 돌파 → 매수
- MACD선이 시그널선을 하향 돌파 → 매도
"""

import pandas as pd
import vectorbt as vbt


def calc_macd(
    close: pd.Series,
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> pd.DataFrame:
    """MACD, Signal, Histogram 계산"""
    ema_fast = close.ewm(span=fast, adjust=False).mean()
    ema_slow = close.ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    histogram = macd_line - signal_line
    return pd.DataFrame(
        {"MACD": macd_line, "Signal": signal_line, "Histogram": histogram}
    )


def make_signals(
    close: pd.Series,
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> tuple[pd.Series, pd.Series]:
    """
    MACD 골든크로스 진입/청산 시그널 생성

    - MACD가 Signal을 하향에서 상향 돌파 → 매수
    - MACD가 Signal을 상향에서 하향 돌파 → 매도
    """
    macd_df = calc_macd(close, fast, slow, signal)
    macd = macd_df["MACD"]
    sig = macd_df["Signal"]

    entries = (macd > sig) & (macd.shift(1) <= sig.shift(1))
    exits = (macd < sig) & (macd.shift(1) >= sig.shift(1))

    return entries, exits


def run_backtest(
    close: pd.Series,
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
    fees: float = 0.001,
    slippage: float = 0.001,
) -> vbt.Portfolio:
    """MACD 전략 백테스트 실행"""
    entries, exits = make_signals(close, fast, slow, signal)
    return vbt.Portfolio.from_signals(
        close,
        entries,
        exits,
        fees=fees,
        slippage=slippage,
        freq="D",
    )
