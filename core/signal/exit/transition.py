"""
UPTREND → TRANSITION 전환 청산 조건 판별
==========================================

[역할]

  UPTREND에서 TRANSITION으로 국면이 전환되는 첫날을 감지하는 순수 함수.
  전환 첫날 strategy 레이어가 포지션을 40%까지 줄인다(1차 익절).

─────────────────────────────────────────────────────────────────
판별 기준
─────────────────────────────────────────────────────────────────

  전일: UPTREND
  당일: TRANSITION

  전환 이후 TRANSITION이 지속되는 날은 False를 반환한다.
  추세 종료 가능성이 커진 첫 신호 시점에만 익절한다.

─────────────────────────────────────────────────────────────────
참고
─────────────────────────────────────────────────────────────────

  obsidian/투자성향/위험중립형_전략.md — 2. 매수/매도 신호 > 매도 신호
"""
from ...constant.types import MarketRegime


def check_transition_exit(regime: str, prev_regime: str) -> bool:
    """UPTREND → TRANSITION 전환 첫날 여부 판별 (1차 익절 트리거).

    Parameters
    ----------
    regime : str
        당일 국면 (MarketRegime.name).
    prev_regime : str
        전일 국면 (MarketRegime.name).

    Returns
    -------
    bool
        True이면 strategy 레이어가 잔여 포지션을 40%로 줄인다(1차 익절).
        발생 당일 한 번만 True — 이후 TRANSITION이 지속돼도 False.

    Examples
    --------
    >>> check_transition_exit("TRANSITION", "UPTREND")
    True
    >>> check_transition_exit("TRANSITION", "TRANSITION")
    False  # 이미 TRANSITION 지속 중
    >>> check_transition_exit("SIDEWAYS", "UPTREND")
    False  # TRANSITION이 아님
    """
    return (
        prev_regime == MarketRegime.UPTREND.name
        and regime  == MarketRegime.TRANSITION.name
    )
