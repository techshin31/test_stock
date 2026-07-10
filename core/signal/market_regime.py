"""
시장 국면 판별 — 4국면: SIDEWAYS / UPTREND / DOWNTREND / TRANSITION
=====================================================================

[위험중립형 전략 — 1단계: 시장 국면 판별]

매일 장 마감 후 OHLC + KOSPI 데이터를 기반으로 ADX·MA·KOSPI 지표를 조합해
4가지 국면 중 하나로 분류한다. 국면 판별 결과가 이후 모든 매매 행동을 결정한다.

  ① 시장 국면 판별  →  ② 매수/매도 신호 생성  →  ③ 자금 배분  →  주문 실행
                                                       ↑
                           ④ Walk-Forward 최적화 (3개월마다 파라미터 갱신)

─────────────────────────────────────────────────────────────────────
운용 모드 — Walk-Forward IS score 기반으로 종목별 자동 전환
─────────────────────────────────────────────────────────────────────

  ADX 모드    (IS score > 0):  ADX로 추세 강도를 추가 확인
      SIDEWAYS → UPTREND → DOWNTREND → TRANSITION

  MA+KOSPI 모드 (IS score ≤ 0): ADX를 신뢰할 수 없으므로 MA 배열 + KOSPI 필터만 사용
      SIDEWAYS 없음, MA 정/역배열 + KOSPI > KOSPI_MA60 조건만 적용

  IS score 산출 기준:
    Walk-Forward IS 구간(12개월)에서 종목 단독 Calmar Ratio를 산출한다.
    IS score > 0 이면 ADX 모드, ≤ 0 이면 MA+KOSPI 모드로 전환한다.
    → 종목마다 독립적으로 평가 (삼성전자와 KB금융은 최적 파라미터가 다를 수 있음)

─────────────────────────────────────────────────────────────────────
국면별 조건 요약
─────────────────────────────────────────────────────────────────────

  국면          ADX 모드                            MA+KOSPI 모드
  ─────────     ─────────────────────────────────   ──────────────────────────────
  SIDEWAYS      ADX < adx_sideways (기본 20)         없음 (SIDEWAYS 구분 안 함)
  UPTREND       MA정배열 + ADX > adx_threshold        MA정배열 + KOSPI > KOSPI_MA60
  DOWNTREND     MA역배열 + ADX > adx_threshold        MA역배열
  TRANSITION    위 3가지 미해당                        위 2가지 미해당

  MA 정배열: MA20 > MA60 > MA120  (단기 > 중기 > 장기 — 상승 추세 구조)
  MA 역배열: MA20 < MA60 < MA120  (단기 < 중기 < 장기 — 하락 추세 구조)

─────────────────────────────────────────────────────────────────────
KOSPI_MA60 필터 — 양쪽 모드 공통 적용
─────────────────────────────────────────────────────────────────────

  KOSPI 지수가 60일 이동평균 아래이면 UPTREND 진입을 차단한다.

  적용 범위:
    - MA+KOSPI 모드: 명시적 조건으로 항상 적용
    - ADX 모드: ADX > adx_threshold 조건이 이미 종목 추세 강도를 확인하므로
                KOSPI 필터가 과도하게 보수적으로 작용할 수 있음
                → 현재는 양쪽 모드 모두 적용, 향후 백테스트로 재검토 예정

  이유: 개별 종목이 정배열이더라도 시장 전체가 하락 중이면
        추세가 단기 반등일 가능성이 높음 → 위험중립 관점에서 진입 보류 (Beta ≤ 0.8 목표)

─────────────────────────────────────────────────────────────────────
WF 최적화 대상 파라미터
─────────────────────────────────────────────────────────────────────

  adx_threshold [15·20·25·30]  — 추세 확인 강도 기준 (기본 25)
  adx_sideways  [10·15·20]     — 횡보 판별 기준 (기본 20)
  → 12가지 조합을 그리드 탐색 후 종목별 Calmar Ratio 최고 조합 채택

─────────────────────────────────────────────────────────────────────
판별 우선순위 (위에서 아래로, 먼저 해당되는 국면으로 확정)
─────────────────────────────────────────────────────────────────────

  [ADX 모드]
    1. ADX < adx_sideways         → SIDEWAYS (횡보)
    2. MA역배열 + ADX > threshold  → DOWNTREND (하락추세)
    3. MA정배열 + ADX > threshold  → UPTREND (상승추세)
       단, KOSPI < KOSPI_MA60 이면 UPTREND 차단 → TRANSITION
    4. 위 모두 해당 없음            → TRANSITION (전환)

  [MA+KOSPI 모드]
    1. MA역배열                    → DOWNTREND (하락추세)
    2. MA정배열 + KOSPI > MA60     → UPTREND (상승추세)
    3. 위 모두 해당 없음            → TRANSITION (전환)
"""
import pandas as pd

from ..indicator.trend.ma import calc_ma
from ..indicator.trend_strength.adx import calc_adx

from ..constant.types import MarketRegime
from ..constant.values import MarketRegimeParam


def __is_sideways(is_score: float, close: pd.Series, adx: pd.Series, adx_sideways: float) -> pd.Series:
    """SIDEWAYS(횡보) 국면 판별

    ADX 값이 adx_sideways 미만이면 추세가 없는 횡보 구간으로 간주한다.

    Parameters
    ----------
    is_score : float
        Walk-Forward IS 구간 Calmar Ratio 점수.
        > 0 이면 ADX 모드(SIDEWAYS 판별 활성), ≤ 0 이면 MA+KOSPI 모드(SIDEWAYS 없음).
    close : pd.Series
        종가 시리즈 (인덱스 기준으로 사용).
    adx : pd.Series
        ADX 시리즈.
    adx_sideways : float
        SIDEWAYS 판별 기준값. ADX < adx_sideways 이면 횡보.
        WF 최적화 탐색 범위: [10·15·20], 기본값 20.

    Returns
    -------
    pd.Series[bool]
        True: SIDEWAYS 국면 해당일.

    Notes
    -----
    MA+KOSPI 모드(IS score ≤ 0)에서는 항상 False를 반환한다.
    ADX를 신뢰할 수 없는 종목에 대해 SIDEWAYS를 억제함으로써
    불필요한 횡보 매수 신호(볼린저밴드 하단 돌파) 발생을 방지한다.
    """
    is_sideways = pd.Series(False, index=close.index)

    if is_score > 0:
        # ADX 모드: ADX가 낮으면 추세 부재 → 횡보로 판별
        is_sideways = adx < adx_sideways

    return is_sideways

def __is_uptrend(is_score: float, is_sideways: pd.Series, is_uptrend_ma: pd.Series, is_uptrend_market_index: pd.Series, adx: pd.Series, adx_threshold: float) -> pd.Series:
    """UPTREND(상승추세) 국면 판별

    MA 정배열 + 시장지수 필터 조건을 기본으로 하며,
    ADX 모드에서는 ADX 강도 조건을 추가하고 SIDEWAYS 구간을 제외한다.

    Parameters
    ----------
    is_score : float
        Walk-Forward IS 구간 Calmar Ratio 점수.
        > 0 이면 ADX 모드, ≤ 0 이면 MA+시장지수 모드.
    is_sideways : pd.Series[bool]
        SIDEWAYS 국면 마스크 (UPTREND와 상호 배타적으로 처리).
    is_uptrend_ma : pd.Series[bool]
        MA 정배열 마스크. MA20 > MA60 > MA120 이면 True.
    is_uptrend_market_index : pd.Series[bool]
        시장지수 상승 마스크. 시장지수 > 시장지수_MA60 이면 True.
        시장 전체가 하락 중인 경우 개별 종목의 UPTREND 진입을 차단한다 (위험중립 핵심 원칙).
    adx : pd.Series
        ADX 시리즈.
    adx_threshold : float
        추세 확인 강도 기준. ADX > adx_threshold 이면 유효한 추세로 인정.
        WF 최적화 탐색 범위: [15·20·25·30], 기본값 25.

    Returns
    -------
    pd.Series[bool]
        True: UPTREND 국면 해당일.

    Notes
    -----
    [ADX 모드]  MA정배열 + ADX > adx_threshold + ~SIDEWAYS + 시장지수 > MA60
    [MA+시장지수]  MA정배열 + 시장지수 > MA60

    시장지수 필터는 양쪽 모드 공통으로 적용된다.
    위험중립형 목표(Beta ≤ 0.8)를 달성하기 위해
    시장 전체 하락 국면에서의 진입을 보류하는 것이 핵심 설계 원칙이다.
    """
    # MA+시장지수 모드 기본값: MA 정배열 + 시장지수가 60일선 위에 있을 때만 UPTREND 인정
    is_uptrend = is_uptrend_ma & is_uptrend_market_index

    if is_score > 0:
        # ADX 모드: ADX가 threshold를 넘어야 추세를 신뢰할 수 있음
        # SIDEWAYS 구간은 명시적으로 제외 (~is_sideways)
        # 시장지수 필터(is_uptrend_market_index)는 ADX 모드에서도 공통 적용 (위험중립 원칙)
        is_uptrend = is_uptrend_ma & (adx > adx_threshold) & ~is_sideways & is_uptrend_market_index

    return is_uptrend

def __is_downtrend(is_score: float, is_sideways: pd.Series, is_downtrend_ma: pd.Series, adx: pd.Series, adx_threshold: float) -> pd.Series:
    """DOWNTREND(하락추세) 국면 판별

    MA 역배열 조건을 기본으로 하며, ADX 모드에서는 ADX 강도 조건을 추가한다.

    Parameters
    ----------
    is_score : float
        Walk-Forward IS 구간 Calmar Ratio 점수.
        > 0 이면 ADX 모드, ≤ 0 이면 MA+KOSPI 모드.
    is_sideways : pd.Series[bool]
        SIDEWAYS 국면 마스크 (ADX 모드에서 DOWNTREND와 상호 배타적으로 처리).
    is_downtrend_ma : pd.Series[bool]
        MA 역배열 마스크. MA20 < MA60 < MA120 이면 True.
    adx : pd.Series
        ADX 시리즈.
    adx_threshold : float
        추세 확인 강도 기준. ADX > adx_threshold 이면 유효한 하락추세로 인정.

    Returns
    -------
    pd.Series[bool]
        True: DOWNTREND 국면 해당일.

    Notes
    -----
    [ADX 모드]  MA역배열 + ADX > adx_threshold + ~SIDEWAYS
    [MA+KOSPI]  MA역배열 (ADX 조건 없음)

    DOWNTREND 진입 시 전략 행동:
      - 매수 신호 없음, 포지션 청산 대기
      - ATR stop 미적용 (포지션 없음 전제)
      - 보유 현금은 단기채 ETF에 전액 주차

    실전 주의:
      MA 후행성으로 DOWNTREND 판별 시점은 이미 10~20% 하락 후인 경우가 많다.
      (2022년 실측: 삼성전자·SK하이닉스·NAVER·현대차·KB금융 = -40~-65%)
    """
    # MA+KOSPI 모드 기본값: MA 역배열이면 바로 DOWNTREND
    is_downtrend = is_downtrend_ma

    if is_score > 0:
        # ADX 모드: ADX가 threshold를 넘어야 유효한 하락추세로 인정
        # 약한 ADX(횡보에 가까운 약한 하락)는 SIDEWAYS 또는 TRANSITION으로 처리
        is_downtrend = is_downtrend & (adx > adx_threshold) & ~is_sideways

    return is_downtrend

def __is_transition(is_sideways: pd.Series, is_uptrend: pd.Series, is_downtrend: pd.Series) -> pd.Series:
    """TRANSITION(전환) 국면 판별

    UPTREND·DOWNTREND·SIDEWAYS 어느 국면에도 해당하지 않는 날을 TRANSITION으로 분류한다.

    Parameters
    ----------
    is_sideways : pd.Series[bool]
        SIDEWAYS 국면 마스크.
    is_uptrend : pd.Series[bool]
        UPTREND 국면 마스크.
    is_downtrend : pd.Series[bool]
        DOWNTREND 국면 마스크.

    Returns
    -------
    pd.Series[bool]
        True: TRANSITION 국면 해당일.

    Notes
    -----
    TRANSITION은 방향이 불확실한 구간이다.

    전략 행동:
      - 신규 매수 없음, 기존 포지션 유지
      - UPTREND → TRANSITION 전환 첫날: 1차 익절 (잔여 40% 유지)
      - 모멘텀 윈도우: 63일 (중기 중간값, 방향 불확실에 대응)
      - 자금 배분: 포지션 없으면 단기채 ETF 주차
    """
    return ~is_sideways & ~is_uptrend & ~is_downtrend


def calc_regime(
    close: pd.Series,
    high: pd.Series,
    low: pd.Series,
    market_index: pd.Series,
    is_score: float = 0.0,
    adx_threshold: float = 25.0,
    adx_sideways: float = 20.0,
    adx_window: int = MarketRegimeParam.ADX_WINDOW.value,
) -> tuple:
    """4국면 판별 — 위험중립형 전략 1단계

    OHLC + KOSPI 데이터를 기반으로 ADX·MA·KOSPI 지표를 조합해
    날짜별 시장 국면(SIDEWAYS / UPTREND / DOWNTREND / TRANSITION)을 판별한다.

    판별 우선순위 (위에서 아래로):
      [ADX 모드, IS score > 0]
        1. ADX < adx_sideways              → SIDEWAYS
        2. MA역배열 + ADX > adx_threshold   → DOWNTREND
        3. MA정배열 + ADX > adx_threshold   → UPTREND  (KOSPI < MA60 이면 차단)
        4. 나머지                            → TRANSITION

      [MA+KOSPI 모드, IS score ≤ 0]
        1. MA역배열                         → DOWNTREND
        2. MA정배열 + KOSPI > KOSPI_MA60    → UPTREND
        3. 나머지                            → TRANSITION

    Parameters
    ----------
    close : pd.Series
        종목 종가 시리즈.
    high : pd.Series
        종목 고가 시리즈 (ADX 계산에 사용).
    low : pd.Series
        종목 저가 시리즈 (ADX 계산에 사용).
    market_index : pd.Series
        시장지수 시리즈 (KOSPI·KOSDAQ 등).
        close와 거래일이 다를 수 있으므로 forward fill로 정렬한다.
    is_score : float, optional
        Walk-Forward IS 구간 Calmar Ratio 점수, 기본값 0.0.
        > 0: ADX 모드 활성 / ≤ 0: MA+KOSPI 모드 (ADX 신뢰 불가 종목).
    adx_threshold : float, optional
        추세 유효성 판별 ADX 기준값, 기본값 25.0.
        WF 최적화 탐색 범위: [15·20·25·30].
    adx_sideways : float, optional
        횡보 판별 ADX 기준값, 기본값 20.0.
        WF 최적화 탐색 범위: [10·15·20].
        반드시 adx_threshold 이하여야 의미가 있음.

    Returns
    -------
    pd.DataFrame
        날짜를 인덱스로 하는 DataFrame. 열 구성:

        REGIME      : str    날짜별 국면 문자열 ("UPTREND" | "DOWNTREND" | "SIDEWAYS" | "TRANSITION")
        UPTREND     : bool   상승추세 마스크
        DOWNTREND   : bool   하락추세 마스크
        SIDEWAYS    : bool   횡보 마스크
        TRANSITION  : bool   전환 마스크
        ma_s        : float  단기 이동평균 (MA20)
        ma_m        : float  중기 이동평균 (MA60)
        ma_l        : float  장기 이동평균 (MA120)
        adx         : float  ADX 값
        adx_plus_di : float  +DI 값 (상승 방향성)
        adx_minus_di: float  -DI 값 (하락 방향성)

    Notes
    -----
    MA 파라미터 (MarketRegimeParam):
      MA_SHORT = 20  — 단기 이동평균
      MA_MID   = 60  — 중기 이동평균
      MA_LONG  = 120 — 장기 이동평균 (신뢰도 확보에 최소 6개월 이상 데이터 필요)
      ADX_WINDOW = 14
      KOSPI_MA   = 60 — KOSPI 60일 이동평균 필터

    References
    ----------
    obsidian/투자성향/위험중립형_전략.md — 1. 시장 국면 판별
    obsidian/TA지표/추세/MA_이동평균.md
    obsidian/TA지표/추세강도/ADX_추세강도.md
    """
    # ── MA 정배열·역배열 계산 ─────────────────────────────────────────────
    # MA20 > MA60 > MA120: 단기가 중기·장기보다 위 → 상승 추세 구조 (정배열)
    # MA20 < MA60 < MA120: 단기가 중기·장기보다 아래 → 하락 추세 구조 (역배열)
    ma_s = calc_ma(close, MarketRegimeParam.MA_SHORT.value)   # MA20
    ma_m = calc_ma(close, MarketRegimeParam.MA_MID.value)     # MA60
    ma_l = calc_ma(close, MarketRegimeParam.MA_LONG.value)    # MA120
    is_uptrend_ma   = (ma_s > ma_m) & (ma_m > ma_l)  # 정배열: 상승 추세 구조
    is_downtrend_ma = (ma_s < ma_m) & (ma_m < ma_l)  # 역배열: 하락 추세 구조

    # ── ADX 계산 ──────────────────────────────────────────────────────────
    # ADX: 추세 강도 (방향 무관). 높을수록 추세가 뚜렷함
    # +DI: 상승 방향성 지표 / -DI: 하락 방향성 지표
    adx_df = calc_adx(high, low, close, adx_window)
    adx = adx_df["adx"]

    # ── 시장지수 60일 이동평균 필터 ───────────────────────────────────────
    # 시장지수 거래일과 종목 거래일이 불일치할 수 있으므로 forward fill로 정렬
    # 시장지수 > 시장지수_MA60: 시장 전체 상승 국면 → UPTREND 진입 허용
    # 시장지수 ≤ 시장지수_MA60: 시장 전체 하락 국면 → UPTREND 진입 차단 (위험중립 원칙)
    market_index_aligned    = market_index.reindex(close.index, method="ffill")
    is_uptrend_market_index = market_index_aligned > calc_ma(market_index_aligned, MarketRegimeParam.KOSPI_MA.value)

    # ── 4국면 판별 (우선순위 순) ──────────────────────────────────────────
    IS_SIDEWAYS  = __is_sideways(is_score, close, adx, adx_sideways)
    IS_UPTREND   = __is_uptrend(is_score, IS_SIDEWAYS, is_uptrend_ma, is_uptrend_market_index, adx, adx_threshold)
    IS_DOWNTREND = __is_downtrend(is_score, IS_SIDEWAYS, is_downtrend_ma, adx, adx_threshold)
    IS_TRANSITION = __is_transition(IS_SIDEWAYS, IS_UPTREND, IS_DOWNTREND)

    # ── 국면 문자열 시리즈 생성 ───────────────────────────────────────────
    # 기본값을 TRANSITION으로 설정 후 순서대로 덮어씀
    # (SIDEWAYS → UPTREND → DOWNTREND 순으로 덮어쓰므로 우선순위와 무관하게 최종 결과 동일)
    regime = pd.Series(MarketRegime.TRANSITION.name, index=close.index, dtype=object)
    regime[IS_SIDEWAYS]  = MarketRegime.SIDEWAYS.name
    regime[IS_UPTREND]   = MarketRegime.UPTREND.name
    regime[IS_DOWNTREND] = MarketRegime.DOWNTREND.name

    return pd.DataFrame({
        "REGIME":       regime,
        "UPTREND":      IS_UPTREND,
        "DOWNTREND":    IS_DOWNTREND,
        "SIDEWAYS":     IS_SIDEWAYS,
        "TRANSITION":   IS_TRANSITION,
        "ma_s":         ma_s,           # MA20
        "ma_m":         ma_m,           # MA60
        "ma_l":         ma_l,           # MA120
        "adx":          adx,
        "adx_plus_di":  adx_df['adx_plus_di'],   # 상승 방향성
        "adx_minus_di": adx_df['adx_minus_di'],  # 하락 방향성
    })
