"""
골든크로스 / 데드크로스 전략
- 단기 이동평균이 장기 이동평균을 상향 돌파(골든크로스) → 매수
- 단기 이동평균이 장기 이동평균을 하향 돌파(데드크로스) → 매도
"""

import pandas as pd
import vectorbt as vbt


def make_signals(
    close: pd.Series,
    fast_window: int = 20,
    slow_window: int = 60,
) -> tuple[pd.Series, pd.Series]:
    """
    골든크로스 진입/청산 시그널 생성

    Returns
    -------
    entries, exits : (bool Series, bool Series)
    """
    fast_ma = close.rolling(fast_window).mean()
    slow_ma = close.rolling(slow_window).mean()

    # 골든크로스: 이전 봉에서는 fast < slow, 현재 봉에서 fast >= slow
    entries = (fast_ma >= slow_ma) & (fast_ma.shift(1) < slow_ma.shift(1))
    # 데드크로스: 이전 봉에서는 fast >= slow, 현재 봉에서 fast < slow
    exits = (fast_ma < slow_ma) & (fast_ma.shift(1) >= slow_ma.shift(1))

    return entries, exits


def run_backtest(
    close: pd.Series,
    fast_window: int = 20,
    slow_window: int = 60,
    fees: float = 0.001,
    slippage: float = 0.001,
) -> vbt.Portfolio:
    """골든크로스 전략 백테스트 실행"""
    entries, exits = make_signals(close, fast_window, slow_window)
    return vbt.Portfolio.from_signals(
        close,
        entries,
        exits,
        fees=fees,
        slippage=slippage,
        freq="D",
    )
