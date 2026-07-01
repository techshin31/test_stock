"""
UPTREND 진입 조건 판별
======================

[역할]

  UPTREND 국면에서 매수 신호 발생 여부를 판별하는 순수 함수 모음.
  indicator 값을 받아 bool 만 반환한다.

  "얼마나 매수할지 (40%·70%)"는 strategy 레이어가 결정한다.
  "entry1 후 몇 거래일인지"는 StrategyState가 추적하며 strategy 레이어가 확인한다.

─────────────────────────────────────────────────────────────────
함수 목록
─────────────────────────────────────────────────────────────────

  check_uptrend_entry1  : UPTREND 진입 첫날 여부 (1차 매수 트리거)
  check_uptrend_entry2  : UPTREND 중 종가 > MA20 여부 (2차 매수 트리거)
  check_ma10_trigger    : 종가 > MA10 여부 (적극투자형 즉시 2차 매수 트리거)

─────────────────────────────────────────────────────────────────
참고
─────────────────────────────────────────────────────────────────

  obsidian/투자성향/위험중립형_전략.md — 2. 매수/매도 신호 > 매수 신호
  obsidian/매매원칙/분할매수매도_원칙.md
"""
import math

from ...constant.types import MarketRegime


def check_uptrend_entry1(regime: str, prev_regime: str) -> bool:
    """UPTREND 진입 첫날 여부 판별 (1차 매수 트리거).

    전일이 UPTREND가 아니었다가 당일 UPTREND로 전환된 첫날에 True를 반환한다.

    Parameters
    ----------
    regime : str
        당일 국면 (MarketRegime.name).
    prev_regime : str
        전일 국면 (MarketRegime.name).

    Returns
    -------
    bool
        True이면 strategy 레이어가 1차 매수(기본 40%)를 실행한다.

    Examples
    --------
    >>> check_uptrend_entry1("UPTREND", "TRANSITION")
    True
    >>> check_uptrend_entry1("UPTREND", "UPTREND")
    False
    >>> check_uptrend_entry1("SIDEWAYS", "TRANSITION")
    False
    """
    return (
        regime      == MarketRegime.UPTREND.name
        and prev_regime != MarketRegime.UPTREND.name
    )


def check_uptrend_entry2(regime: str, price: float, ma_s: float) -> bool:
    """UPTREND 중 종가 > MA20 여부 판별 (2차 매수 트리거).

    2차 매수 조건의 indicator 부분만 판별한다.
    "entry1 후 60거래일 이내" 상태 조건은 strategy 레이어(StrategyState)가 확인한다.

    Parameters
    ----------
    regime : str
        당일 국면. UPTREND 여부를 재확인한다.
    price : float
        당일 종가.
    ma_s : float
        당일 단기 이동평균 (MA20). NaN이면 False 반환.

    Returns
    -------
    bool
        True이면 strategy 레이어가 StrategyState 조건까지 확인 후 2차 매수(70%)를 실행한다.

    Examples
    --------
    >>> check_uptrend_entry2("UPTREND", 110.0, 100.0)
    True
    >>> check_uptrend_entry2("UPTREND", 90.0, 100.0)
    False
    >>> check_uptrend_entry2("SIDEWAYS", 110.0, 100.0)
    False
    """
    return (
        regime == MarketRegime.UPTREND.name
        and not math.isnan(ma_s)
        and price > ma_s
    )


def check_ma10_trigger(price: float, ma10: float) -> bool:
    """종가 > MA10 여부 판별 (적극투자형 즉시 2차 매수 트리거).

    적극투자형 전략에서 UPTREND 진입 첫날 MA10을 상향 돌파했을 때
    즉시 2차 매수 비중(70%)으로 진입하기 위한 조건.

    MA10 아래에서 UPTREND가 시작되면 기존 1차 매수(40%)를 따른다.

    Parameters
    ----------
    price : float
        당일 종가.
    ma10 : float
        당일 10일 이동평균. NaN이면 False 반환.

    Returns
    -------
    bool
        True이면 strategy 레이어가 즉시 70% 진입을 실행한다.

    Examples
    --------
    >>> check_ma10_trigger(105.0, 100.0)
    True
    >>> check_ma10_trigger(95.0, 100.0)
    False
    """
    return not math.isnan(ma10) and price > ma10
