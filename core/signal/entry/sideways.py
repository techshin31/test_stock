"""
SIDEWAYS 진입 조건 판별
========================

[역할]

  SIDEWAYS(횡보) 국면에서 매수 신호 발생 여부를 판별하는 순수 함수.
  볼린저밴드 하단 상향 돌파를 감지한다.

─────────────────────────────────────────────────────────────────
참고
─────────────────────────────────────────────────────────────────

  obsidian/투자성향/위험중립형_전략.md — 2. 매수/매도 신호 > 매수 신호
  obsidian/TA지표/변동성/볼린저밴드.md
"""
import math


def check_bb_lower_breakout(
    price:      float,
    prev_price: float,
    lower_bb:   float,
    prev_lower_bb: float,
) -> bool:
    """볼린저밴드 하단 상향 돌파 여부 판별 (횡보 매수 트리거).

    전일 종가가 볼린저밴드 하단을 터치(≤)했다가
    당일 종가가 하단을 상향 돌파(>)하면 True를 반환한다.

    Parameters
    ----------
    price : float
        당일 종가.
    prev_price : float
        전일 종가.
    lower_bb : float
        당일 볼린저밴드 하단값. NaN이면 False 반환.
    prev_lower_bb : float
        전일 볼린저밴드 하단값. NaN이면 False 반환.

    Returns
    -------
    bool
        True이면 strategy 레이어가 횡보 매수(30%)를 실행한다.

    Notes
    -----
    볼린저밴드 워밍업 기간(기본 20일) 동안 NaN이 발생하므로
    NaN 체크가 필수다.

    Examples
    --------
    >>> check_bb_lower_breakout(101.0, 99.0, 100.0, 100.0)
    True   # 전일 99 ≤ 100 (터치), 당일 101 > 100 (돌파)
    >>> check_bb_lower_breakout(99.0, 98.0, 100.0, 100.0)
    False  # 당일도 하단 아래
    >>> check_bb_lower_breakout(101.0, 102.0, 100.0, 100.0)
    False  # 전일이 하단 위 (터치 없음)
    """
    if math.isnan(prev_lower_bb) or math.isnan(lower_bb):
        return False
    return prev_price <= prev_lower_bb and price > lower_bb
