"""
볼린저밴드 상단 하향 돌파 청산 조건 판별
==========================================

[역할]

  SIDEWAYS 국면에서 볼린저밴드 상단 하향 돌파 여부를 판별하는 순수 함수.
  횡보 매수 후 목표가 도달 시 청산 신호를 생성한다.

─────────────────────────────────────────────────────────────────
참고
─────────────────────────────────────────────────────────────────

  obsidian/투자성향/위험중립형_전략.md — 2. 매수/매도 신호 > 매도 신호
  obsidian/TA지표/변동성/볼린저밴드.md
"""
import math


def check_bb_upper_breakdown(
    price:      float,
    prev_price: float,
    upper_bb:   float,
    prev_upper_bb: float,
) -> bool:
    """볼린저밴드 상단 하향 돌파 여부 판별 (SIDEWAYS 청산 트리거).

    전일 종가가 볼린저밴드 상단을 터치(≥)했다가
    당일 종가가 상단 아래로 하향 돌파(<)하면 True를 반환한다.

    Parameters
    ----------
    price : float
        당일 종가.
    prev_price : float
        전일 종가.
    upper_bb : float
        당일 볼린저밴드 상단값. NaN이면 False 반환.
    prev_upper_bb : float
        전일 볼린저밴드 상단값. NaN이면 False 반환.

    Returns
    -------
    bool
        True이면 strategy 레이어가 전량 청산(0%)을 실행한다.
        SIDEWAYS 국면에서만 유효한 신호다.

    Examples
    --------
    >>> check_bb_upper_breakdown(99.0, 101.0, 100.0, 100.0)
    True   # 전일 101 ≥ 100 (터치), 당일 99 < 100 (하향 돌파)
    >>> check_bb_upper_breakdown(101.0, 102.0, 100.0, 100.0)
    False  # 당일도 상단 위
    >>> check_bb_upper_breakdown(99.0, 98.0, 100.0, 100.0)
    False  # 전일이 상단 아래 (터치 없음)
    """
    if math.isnan(prev_upper_bb) or math.isnan(upper_bb):
        return False
    return prev_price >= prev_upper_bb and price < upper_bb
