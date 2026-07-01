"""
데드크로스 청산 조건 판별
==========================

[역할]

  MA20이 MA60 아래로 내려가는 데드크로스 발생 여부를 판별하는 순수 함수.
  데드크로스 발생 시 strategy 레이어가 포지션을 10%까지 줄인다(2차 청산).

─────────────────────────────────────────────────────────────────
판별 기준
─────────────────────────────────────────────────────────────────

  전일: MA20 ≥ MA60  (정배열 또는 동일)
  당일: MA20 < MA60  (역전 발생 → 데드크로스)

─────────────────────────────────────────────────────────────────
참고
─────────────────────────────────────────────────────────────────

  obsidian/투자성향/위험중립형_전략.md — 2. 매수/매도 신호 > 매도 신호
  obsidian/TA지표/추세/MA_이동평균.md
"""
import math


def check_deadcross(
    ma_s:      float,
    prev_ma_s: float,
    ma_m:      float,
    prev_ma_m: float,
) -> bool:
    """데드크로스 발생 여부 판별.

    MA20이 MA60 아래로 내려가는 순간(전환 첫날)에만 True를 반환한다.
    이미 데드크로스 상태가 지속 중이면 False를 반환한다.

    Parameters
    ----------
    ma_s : float
        당일 단기 이동평균 (MA20). NaN이면 False 반환.
    prev_ma_s : float
        전일 단기 이동평균 (MA20). NaN이면 False 반환.
    ma_m : float
        당일 중기 이동평균 (MA60). NaN이면 False 반환.
    prev_ma_m : float
        전일 중기 이동평균 (MA60). NaN이면 False 반환.

    Returns
    -------
    bool
        True이면 strategy 레이어가 잔여 포지션을 10%로 줄인다(2차 청산).
        발생 당일 한 번만 True — 이후 데드크로스가 지속돼도 False.

    Examples
    --------
    >>> check_deadcross(95.0, 105.0, 100.0, 100.0)
    True   # 전일 MA20(105) ≥ MA60(100), 당일 MA20(95) < MA60(100)
    >>> check_deadcross(95.0, 98.0, 100.0, 100.0)
    True   # 전일 MA20(98) ≥ MA60(100) — 동일선도 포함
    >>> check_deadcross(95.0, 93.0, 100.0, 100.0)
    False  # 전일도 이미 데드크로스 상태
    """
    if math.isnan(prev_ma_s) or math.isnan(prev_ma_m):
        return False
    if math.isnan(ma_s) or math.isnan(ma_m):
        return False
    return prev_ma_s >= prev_ma_m and ma_s < ma_m
