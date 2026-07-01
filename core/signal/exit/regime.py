"""
국면 전환 청산 조건 판별
========================

[역할]

  DOWNTREND 국면 진입 여부를 판별하는 순수 함수.
  포지션 보유 중 DOWNTREND가 되면 strategy 레이어가 전량 청산한다.

─────────────────────────────────────────────────────────────────
참고
─────────────────────────────────────────────────────────────────

  obsidian/투자성향/위험중립형_전략.md — 2. 매수/매도 신호 > 매도 신호
"""
from ...constant.types import MarketRegime


def check_downtrend_exit(regime: str) -> bool:
    """DOWNTREND 국면 진입 여부 판별 (전량 청산 트리거).

    Parameters
    ----------
    regime : str
        당일 국면 (MarketRegime.name).

    Returns
    -------
    bool
        True이면 strategy 레이어가 하락장 방어 자산으로 전환한다.
        위험중립형: 현금(0.0) → 단기채 ETF 주차
        적극투자형: 인버스 ETF(-1.0) 진입

    Examples
    --------
    >>> check_downtrend_exit("DOWNTREND")
    True
    >>> check_downtrend_exit("UPTREND")
    False
    """
    return regime == MarketRegime.DOWNTREND.name
