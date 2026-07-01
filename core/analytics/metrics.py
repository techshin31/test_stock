"""개별 성과 지표 계산 함수
| 지표            | 설명          |
| ------------- | ----------- |
| CAGR          | 연평균 수익률     |
| Sharpe Ratio  | 위험 대비 수익    |
| Sortino Ratio | 하방 위험 대비 수익 |
| MDD           | 최대 낙폭       |
| Win Rate      | 승률          |
| Profit Factor | 총수익 / 총손실   |
| Volatility    | 변동성         |
| Calmar Ratio  | CAGR / MDD  |
| Alpha/Beta    | 벤치마크 비교     |

"""
import pandas as pd


def calc_cagr(prices: pd.Series, trading_days_per_year: int = 252) -> float:
    """CAGR (Compound Annual Growth Rate) 계산

    Parameters
    ----------
    prices : pd.Series
        1.0 기준 누적 자산 곡선.
    trading_days_per_year : int, optional
        연간 거래일 수, 기본값 252.

    Returns
    -------
    float
        연평균 수익률. 데이터 부족 또는 시작값 0이면 0.0 반환.
    """
    prices = prices.dropna()
    if len(prices) < 2 or prices.iloc[0] <= 0:
        return 0.0
    n_years = len(prices) / trading_days_per_year
    return float((prices.iloc[-1] / prices.iloc[0]) ** (1.0 / n_years) - 1.0)


def calc_mdd(prices: pd.Series) -> float:
    """MDD (Maximum Drawdown) 계산

    Parameters
    ----------
    prices : pd.Series
        1.0 기준 누적 자산 곡선.

    Returns
    -------
    float
        최대 낙폭 (0.0 ~ -1.0). 손실 없으면 0.0 반환.
    """
    prices = prices.dropna()
    if len(prices) == 0:
        return 0.0
    rolling_peak = prices.cummax()
    drawdown = (prices - rolling_peak) / rolling_peak
    return float(drawdown.min())


def calc_calmar(prices: pd.Series, trading_days_per_year: int = 252) -> float:
    """Calmar Ratio = CAGR / |MDD|

    Walk-Forward IS score 평가 기준으로 사용된다.

    Parameters
    ----------
    prices : pd.Series
        1.0 기준 누적 자산 곡선.

    Returns
    -------
    float
        Calmar Ratio.
        - > 0  → ADX 모드 사용 가능
        - ≤ 0  → MA+KOSPI 모드로 전환
        - MDD = 0 (손실 없음) → CAGR 그대로 반환

    References
    ----------
    obsidian/성과지표/Calmar비율.md
    obsidian/투자성향/위험중립형_전략.md — 4. Walk-Forward 최적화
    """
    cagr = calc_cagr(prices, trading_days_per_year)
    mdd  = calc_mdd(prices)
    if mdd == 0.0:
        return cagr
    return cagr / abs(mdd)
