"""
볼린저 밴드 전략
- 가격이 하단 밴드(평균 - k*σ) 아래에서 위로 돌파 → 매수 (과매도 반전)
- 가격이 상단 밴드(평균 + k*σ) 위에서 아래로 돌파 → 매도 (과매수 반전)

장단점 비교 (vs 골든크로스)
─────────────────────────────────────────────────────────────
| 항목         | 골든크로스             | 볼린저 밴드            |
|------------|--------------------|--------------------|
| 전략 유형     | 추세 추종             | 변동성 + 평균 회귀       |
| 적합 시장     | 강한 추세장            | 횡보·박스권            |
| 추세장 성과    | ✅ 큰 수익 가능         | ❌ 역추세 진입 위험       |
| 횡보장 성과    | ❌ 휩쏘 반복 손실        | ✅ 반복 매매로 수익       |
| 신호 후행성    | 높음 (MA 평균 특성)     | 낮음 (밴드가 즉시 반응)    |
| 파라미터 민감도 | 낮음                | 중간 (기간·k 배수)      |
| 거짓 신호     | 횡보장에서 다수          | 강한 추세에서 다수        |
─────────────────────────────────────────────────────────────
"""

import pandas as pd
import vectorbt as vbt


def calc_bands(
    close: pd.Series,
    window: int = 20,
    num_std: float = 2.0,
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """볼린저 밴드(중간·상단·하단) 계산"""
    mid = close.rolling(window).mean()
    std = close.rolling(window).std()
    upper = mid + num_std * std
    lower = mid - num_std * std
    return mid, upper, lower


def make_signals(
    close: pd.Series,
    window: int = 20,
    num_std: float = 2.0,
) -> tuple[pd.Series, pd.Series]:
    """
    볼린저 밴드 진입/청산 시그널 생성

    Returns
    -------
    entries, exits : (bool Series, bool Series)
    """
    _, upper, lower = calc_bands(close, window, num_std)

    # 하단 밴드를 아래에서 위로 돌파 → 매수 (과매도 반전)
    entries = (close > lower) & (close.shift(1) <= lower.shift(1))
    # 상단 밴드를 위에서 아래로 돌파 → 매도 (과매수 반전)
    exits = (close < upper) & (close.shift(1) >= upper.shift(1))

    return entries, exits


def run_backtest(
    close: pd.Series,
    window: int = 20,
    num_std: float = 2.0,
    fees: float = 0.001,
    slippage: float = 0.001,
) -> vbt.Portfolio:
    """볼린저 밴드 전략 백테스트 실행"""
    entries, exits = make_signals(close, window, num_std)
    return vbt.Portfolio.from_signals(
        close,
        entries,
        exits,
        fees=fees,
        slippage=slippage,
        freq="D",
    )
