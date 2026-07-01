"""
ATR Stop 조건 판별
==================

[역할]

  ATR(Average True Range) 기반 손절 발동 여부를 판별하는 순수 함수.
  모든 청산 신호 중 최우선 순위를 가진다.

─────────────────────────────────────────────────────────────────
발동 조건
─────────────────────────────────────────────────────────────────

  당일 종가 < 전일 종가 − 전일 ATR × 2.0

  즉, 하루 낙폭이 전일 ATR의 2배를 초과하면 즉시 전량 청산한다.

─────────────────────────────────────────────────────────────────
고정 파라미터 근거
─────────────────────────────────────────────────────────────────

  atr_multiplier = 2.0  (고정 — 최적화 대상 아님)
    ATR 값 자체가 매일 시장 변동성을 반영해 변하므로
    배수를 추가로 최적화하면 과적합 위험이 있다.

  atr_period = 14  (고정 — Wilder 표준)
    MarketRegimeParam.ADX_WINDOW와 동일.

─────────────────────────────────────────────────────────────────
참고
─────────────────────────────────────────────────────────────────

  obsidian/투자성향/위험중립형_전략.md — 2. 매수/매도 신호 > ATR stop
  obsidian/TA지표/변동성/ATR_평균진폭.md
"""
import math

# ATR stop 고정 배수 (obsidian 정의: 2.0 고정)
ATR_MULTIPLIER: float = 2.0


def check_atr_stop(
    price:      float,
    prev_close: float,
    prev_atr:   float,
) -> bool:
    """ATR stop 발동 여부 판별.

    당일 종가가 전일 종가에서 전일 ATR × 2.0 이상 하락했을 때 True를 반환한다.

    Parameters
    ----------
    price : float
        당일 종가.
    prev_close : float
        전일 종가.
    prev_atr : float
        전일 ATR 값. NaN이면 False 반환 (워밍업 기간 보호).

    Returns
    -------
    bool
        True이면 strategy 레이어가 전량 청산(0%)을 즉시 실행한다.
        ATR stop은 모든 다른 신호보다 우선한다.

    Notes
    -----
    발동 시 strategy 레이어는 반드시 continue로 이하 신호를 모두 스킵해야 한다.
    ATR stop이 발동한 날 같은 방향의 신호가 겹치면 이중 처리가 발생할 수 있다.

    Examples
    --------
    >>> check_atr_stop(970.0, 1000.0, 10.0)
    True   # 낙폭 30 > ATR(10) × 2.0 = 20
    >>> check_atr_stop(985.0, 1000.0, 10.0)
    False  # 낙폭 15 < ATR(10) × 2.0 = 20
    >>> check_atr_stop(970.0, 1000.0, float("nan"))
    False  # ATR 워밍업 미완료
    """
    if math.isnan(prev_atr):
        return False
    return price < prev_close - prev_atr * ATR_MULTIPLIER
