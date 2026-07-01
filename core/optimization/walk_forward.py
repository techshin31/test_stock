"""
IS/OOS 구간 분할 + Walk-Forward 최적화 오케스트레이션
=======================================================

[위험중립형 전략 — Walk-Forward 최적화 Step 2: 전체 흐름 관리]

3개월마다 종목별로 최적 ADX 파라미터를 자동 갱신한다.
고정 파라미터의 과적합 문제를 방지하고 시장 변화에 적응한다.

─────────────────────────────────────────────────────────────────────
용어 정리
─────────────────────────────────────────────────────────────────────

  IS  (In-Sample)     : 파라미터를 학습하는 구간 (고정 12개월)
  OOS (Out-of-Sample) : 학습된 파라미터를 실전 적용하는 구간 (3개월)

─────────────────────────────────────────────────────────────────────
IS 12개월 고정 근거
─────────────────────────────────────────────────────────────────────

  MA120 신뢰도 확보에 최소 6개월 이상 데이터가 필요하다.
  12개월(≈252 거래일)은 MA120 워밍업 + 충분한 평가 구간을 확보한다.

─────────────────────────────────────────────────────────────────────
롤링 윈도우 구조 (OOS_MONTHS=3 이동)
─────────────────────────────────────────────────────────────────────

  Window 1: IS=[M01~M12]  OOS=[M13~M15]
  Window 2: IS=[M04~M15]  OOS=[M16~M18]
  Window 3: IS=[M07~M18]  OOS=[M19~M21]
  ...

─────────────────────────────────────────────────────────────────────
종목별 독립 실행 근거
─────────────────────────────────────────────────────────────────────

  삼성전자(고변동성)와 KB금융(저변동성)에 동일한 ADX 파라미터를 적용하면
  한쪽은 신호 과다, 다른 쪽은 신호 부재가 발생한다.
  → 종목별로 최적 파라미터가 다르므로 독립적으로 평가한다.

─────────────────────────────────────────────────────────────────────
position_map — 투자성향 연결 지점
─────────────────────────────────────────────────────────────────────

  walk_forward는 position_map을 grid_search로 그대로 전달한다.
  strategy 레이어(core/strategy/)가 구현되면 각 전략이 자신의
  position_map을 들고 와서 이 함수에 주입하는 방식으로 연결한다.

  예시 (미래 연결 구조):
    result = run_walk_forward(
        ohlcv        = ohlcv,
        market_index = kospi,
        position_map = RiskNeutralStrategy.POSITION_MAP,  # strategy 주입
    )

─────────────────────────────────────────────────────────────────────
사용처별 API
─────────────────────────────────────────────────────────────────────

  백테스트 앱  : run_walk_forward()    → OOS 구간별 종목별 params 반환
  실전 트레이더 : get_current_params() → 현재 시점 최신 IS 기준 params 반환
"""
import pandas as pd
from typing import TypedDict

from ..constant.types import StockCap, Market
from ..constant.values import MarketRegimeParam, WalkForwardParam
from .grid_search import run_grid_search


class WalkForwardWindow(TypedDict):
    is_start:     pd.Timestamp   # IS 구간 시작일
    is_end:       pd.Timestamp   # IS 구간 종료일
    oos_start:    pd.Timestamp   # OOS 구간 시작일
    oos_end:      pd.Timestamp   # OOS 구간 종료일
    is_score:     float          # IS 구간 최고 Calmar Ratio
    use_adx_mode: bool           # True → ADX 모드 / False → MA+KOSPI 모드
    best_params:  dict | None    # {"adx_threshold": float, "adx_sideways": float}
                                 # IS score ≤ 0 이면 None


def __run_single_window(
    ohlcv_is:        pd.DataFrame,
    market_index_is: pd.Series,
    oos_start:       pd.Timestamp,
    oos_end:         pd.Timestamp,
    position_map:    dict[str, float],
    cap:             StockCap,
    market:          Market,
    adx_window:      int,
) -> WalkForwardWindow:
    """단일 IS 구간 Grid Search 실행 후 WalkForwardWindow 반환 (공통 헬퍼)."""
    grid_result = run_grid_search(
        ohlcv_is,
        market_index = market_index_is,
        position_map = position_map,
        cap          = cap,
        market       = market,
        adx_window   = adx_window,
    )
    return WalkForwardWindow(
        is_start     = ohlcv_is.index[0],
        is_end       = ohlcv_is.index[-1],
        oos_start    = oos_start,
        oos_end      = oos_end,
        is_score     = grid_result["is_score"],
        use_adx_mode = grid_result["is_score"] > 0,
        best_params  = grid_result["best_params"],
    )


def run_walk_forward(
    ohlcv:        pd.DataFrame,
    market_index: pd.Series,
    position_map: dict[str, float] | None = None,
    cap:          StockCap = StockCap.LARGE,
    market:       Market   = Market.KOSPI,
    adx_window:   int      = MarketRegimeParam.ADX_WINDOW.value,
) -> list[WalkForwardWindow]:
    """
    [백테스팅 전용]

    단일 종목의 전체 OHLCV를 받아 롤링 윈도우 Walk-Forward를 실행한다.

    각 윈도우마다 IS 구간에서 Grid Search로 최적 ADX 파라미터를 탐색하고,
    OOS 구간에 적용할 params(is_score, use_adx_mode, best_params)를 반환한다.

    Parameters
    ----------
    ohlcv : pd.DataFrame
        단일 종목 전체 OHLCV DataFrame (columns: open·high·low·close·volume).
    market_index : pd.Series
        전체 기간 시장지수 시리즈 (KOSPI·KOSDAQ 등) — IS 구간별로 슬라이싱해서 사용.
    position_map : dict[str, float] | None, optional
        국면별 포지션 크기 매핑. None이면 DEFAULT_POSITION_MAP(위험중립형) 사용.
        strategy 레이어가 구현되면 전략 클래스의 position_map을 전달한다.
    cap : StockCap, optional
        슬리피지 계산용 종목 규모 (LARGE·MID·SMALL).
    market : Market, optional
        세금 계산용 시장 구분 (KOSPI·KOSDAQ).
    adx_window : int, optional
        ADX 계산 창 (Wilder 표준 = 14).

    Returns
    -------
    list[WalkForwardWindow]
        OOS 구간별 params 목록. 백테스트 엔진이 OOS 구간에 순서대로 적용한다.
        빈 리스트 반환 시 데이터 부족 (IS 구간 확보 불가).
    """
    if position_map is None:
        raise Exception(f"position_map(전략)이 올바르지 않음 >> {position_map}")

    results: list[WalkForwardWindow] = []

    first_date = ohlcv.index[0]
    last_date  = ohlcv.index[-1]

    oos_start = first_date + pd.DateOffset(months=WalkForwardParam.IS_MONTHS.value)

    while oos_start <= last_date:
        is_start = oos_start - pd.DateOffset(months=WalkForwardParam.IS_MONTHS.value)
        is_end   = oos_start - pd.DateOffset(days=1)
        oos_end  = min(
            oos_start + pd.DateOffset(months=WalkForwardParam.OOS_MONTHS.value) - pd.DateOffset(days=1),
            last_date,
        )

        ohlcv_is  = ohlcv.loc[is_start:is_end]
        ohlcv_oos = ohlcv.loc[oos_start:oos_end]

        if ohlcv_is.empty or ohlcv_oos.empty:
            break

        results.append(__run_single_window(
            ohlcv_is        = ohlcv_is,
            market_index_is = market_index.loc[is_start:is_end],
            oos_start       = ohlcv_oos.index[0],   # 실제 거래일 기준
            oos_end         = ohlcv_oos.index[-1],
            position_map    = position_map,
            cap             = cap,
            market          = market,
            adx_window      = adx_window,
        ))

        oos_start += pd.DateOffset(months=WalkForwardParam.OOS_MONTHS.value)

    return results


def get_current_params(
    ohlcv:        pd.DataFrame,
    market_index: pd.Series,
    position_map: dict[str, float] | None = None,
    cap:          StockCap = StockCap.LARGE,
    market:       Market   = Market.KOSPI,
    adx_window:   int      = MarketRegimeParam.ADX_WINDOW.value,
) -> WalkForwardWindow:
    """
    [트레이딩 전용]

    현재 시점 기준 최신 IS 구간으로 Grid Search를 실행하고 즉시 적용할 params를 반환한다.

    실전 트레이더가 매 분기 파라미터를 갱신할 때 호출한다.
    run_walk_forward()와 달리 최근 IS 12개월 단 1회만 Grid Search를 수행한다.

    Parameters
    ----------
    ohlcv : pd.DataFrame
        단일 종목 전체 OHLCV DataFrame (columns: open·high·low·close·volume).
    market_index : pd.Series
        전체 기간 시장지수 시리즈 (KOSPI·KOSDAQ 등) — IS 구간만 슬라이싱해서 사용.
    position_map : dict[str, float] | None, optional
        국면별 포지션 크기 매핑. None이면 DEFAULT_POSITION_MAP(위험중립형) 사용.
        strategy 레이어가 구현되면 전략 클래스의 position_map을 전달한다.
    cap : StockCap, optional
        슬리피지 계산용 종목 규모 (LARGE·MID·SMALL).
    market : Market, optional
        세금 계산용 시장 구분 (KOSPI·KOSDAQ).
    adx_window : int, optional
        ADX 계산 창 (Wilder 표준 = 14).

    Returns
    -------
    WalkForwardWindow
        is_start/is_end   : 실제 사용된 IS 구간 날짜
        oos_start/oos_end : 다음 OOS 구간 예정 날짜 (현재일 기준 +3개월, 달력 기준)
        is_score          : 최고 Calmar Ratio
        use_adx_mode      : True → ADX 모드 / False → MA+KOSPI 모드
        best_params       : {"adx_threshold": float, "adx_sideways": float} | None

    Raises
    ------
    ValueError
        IS 구간 확보에 필요한 데이터가 부족할 때.
    """
    if position_map is None:
        raise Exception(f"position_map(전략)이 올바르지 않음 >> {position_map}")

    last_date = ohlcv.index[-1]
    is_start  = last_date - pd.DateOffset(months=WalkForwardParam.IS_MONTHS.value)
    ohlcv_is  = ohlcv.loc[is_start:]

    if ohlcv_is.empty:
        raise ValueError(
            f"IS 구간 데이터 부족: 최소 {WalkForwardParam.IS_MONTHS.value}개월 이상 필요 "
            f"(보유 데이터: {ohlcv.index[0].date()} ~ {last_date.date()})"
        )

    return __run_single_window(
        ohlcv_is        = ohlcv_is,
        market_index_is = market_index.loc[is_start:],
        oos_start       = last_date + pd.DateOffset(days=1),
        oos_end         = last_date + pd.DateOffset(months=WalkForwardParam.OOS_MONTHS.value),
        position_map    = position_map,
        cap             = cap,
        market          = market,
        adx_window      = adx_window,
    )
