"""
투자성향 추상 기반 클래스
========================

[전략 레이어 역할]

  core/strategy/는 세 레이어의 연결 허브다.

  ┌──────────────────────────────────────────────────────────────┐
  │                    core/strategy/                            │
  │                                                              │
  │  POSITION_MAP ────────────────────────────► core/optimization│
  │  (국면 → 포지션 근사값)                      IS 파라미터 탐색 │
  │                                                              │
  │  DEFENSIVE_ASSET_TYPE ─────────────────────► portfolio 레이어│
  │  (하락장 방어 자산 타입)                     자산 배분 결정   │
  │                                                              │
  │  make_signals() ───────────────────────────► portfolio 레이어│
  │  (국면 → 분할 매수/매도 신호)               종목별 신호 수집  │
  └──────────────────────────────────────────────────────────────┘

─────────────────────────────────────────────────────────────────
투자성향별 핵심 차이
─────────────────────────────────────────────────────────────────

  성향          DOWNTREND 포지션    방어 자산         비교 기준선
  ──────────    ────────────────    ──────────────    ────────────
  위험중립형     0.0  (현금)         단기채 ETF         단기채 100%
  적극투자형    -1.0  (숏)           인버스 ETF         B&H 5종목

─────────────────────────────────────────────────────────────────
POSITION_MAP — optimization 레이어 연결
─────────────────────────────────────────────────────────────────

  grid_search IS 평가 기준 = OOS 실행 전략 이어야 Walk-Forward가 유효하다.
  따라서 POSITION_MAP은 전략 클래스가 단 1곳에서 정의하고,
  optimization 레이어로 그대로 주입한다.

  SIDEWAYS = 0.0 근거:
    실제 SIDEWAYS에서는 BB 신호 시 30% 진입이 가능하지만,
    IS 평가 목적(ADX 파라미터 탐색)에서는 단순화한다.
    IS-OOS 일관성 유지가 정확한 SIDEWAYS 시뮬레이션보다 중요하다.

─────────────────────────────────────────────────────────────────
make_signals() — 두 가지 실행 모드
─────────────────────────────────────────────────────────────────

  백테스팅 (state=None):
    전체 기간 OHLCV를 받아 루프로 신호를 생성한다.
    초기 포지션은 0.0으로 시작한다.

  트레이딩 (state=StrategyState):
    최근 N일 OHLCV를 받아 state에서 이어받은 상태로 신호를 생성한다.
    루프 종료 후 state를 in-place로 갱신한다.
    호출자(apps/trader/)가 repo.save(state)로 RDB에 저장한다.
"""
import enum
from abc import ABC, abstractmethod

import pandas as pd

from .state import StrategyState

from core.constant.types                 import MarketRegime, Tickers


# ─────────────────────────────────────────────────────────────────────────────
# 공통 Enum
# ─────────────────────────────────────────────────────────────────────────────

class InvestmentType(enum.Enum):
    """투자성향 식별자"""
    RISK_NEUTRAL = "위험중립형"
    AGGRESSIVE   = "적극투자형"


class DefensiveAssetType(enum.Enum):
    """하락장(DOWNTREND) 방어 자산 타입

    portfolio 레이어가 이 값을 보고 DOWNTREND 시 자금 처리 방식을 결정한다.

    BOND_ETF:
      POSITION_MAP["DOWNTREND"] = 0.0 (현금)
      → portfolio.add_cash_etf()가 잔여 현금을 단기채 ETF에 주차

    INVERSE_ETF:
      POSITION_MAP["DOWNTREND"] = -1.0 (숏 포지션)
      → portfolio.add_inverse_etf()가 인버스 ETF에 해당 비중 배분
    """
    BOND_ETF    = Tickers.BOND_ETF    # 위험중립형: 현금 보존 후 단기채 주차
    INVERSE_ETF = Tickers.INVERSE_ETF  # 적극투자형: 하락장에서 수익 추구


# ─────────────────────────────────────────────────────────────────────────────
# 추상 기반 클래스
# ─────────────────────────────────────────────────────────────────────────────

class AbstractStrategy(ABC):
    """투자성향 전략 추상 기반 클래스

    모든 전략이 반드시 선언해야 하는 클래스 변수와 메서드를 정의한다.

    하위 클래스 구현 체크리스트
    ---------------------------
    클래스 변수 (상수):
      INVESTMENT_TYPE       : InvestmentType
      DEFENSIVE_ASSET_TYPE  : DefensiveAssetType
      POSITION_MAP          : dict[str, float]
      ENTRY1_SIZE, ENTRY2_SIZE, ENTRY2_WINDOW
      SIDEWAYS_SIZE, DEADCROSS_KEEP, TRANSITION_KEEP
      DOWNTREND_POSITION
      BENCHMARK, TARGET_CAGR, WARNING_CAGR
      TARGET_MDD, WARNING_MDD
      TARGET_MDD_DURATION, WARNING_MDD_DURATION

    메서드:
      make_signals()  — 신호 생성 구현 필수
    """

    # ── 하위 클래스가 반드시 선언해야 하는 클래스 변수 ─────────────────────
    INVESTMENT_TYPE:      InvestmentType
    DEFENSIVE_ASSET_TYPE: DefensiveAssetType

    # optimization 레이어로 주입되는 유일한 연결 값
    # grid_search.run_grid_search(position_map=Strategy.POSITION_MAP)
    # Walk-Forward / Grid Search가 ADX 파라미터를 고를 때 필요한 전략 요약표
    POSITION_MAP: dict[str, float]

    # ── 평가 기준 KPI (obsidian 노트의 목표/경보선 직접 반영) ───────────────
    BENCHMARK:            str    # 비교 기준선 설명
    TARGET_CAGR:          float  # 목표 CAGR
    WARNING_CAGR:         float  # 경보 CAGR (이하면 전략 재검토)
    TARGET_MDD:           float  # 목표 MDD  (음수, 예: -0.30)
    WARNING_MDD:          float  # 경보 MDD  (음수, 예: -0.40)
    TARGET_MDD_DURATION:  int    # 목표 MDD 기간 (개월)
    WARNING_MDD_DURATION: int    # 경보 MDD 기간 (개월)

    # ── 분할매수매도 비중 상수 (서브클래스가 반드시 선언해야 함) ─────────────
    ENTRY1_SIZE:     float  # 1차 매수 목표 비중
    ENTRY2_SIZE:     float  # 2차 매수 목표 비중
    ENTRY2_WINDOW:   int    # 2차 매수 허용 거래일 수
    SIDEWAYS_SIZE:   float  # 횡보 매수 목표 비중
    DEADCROSS_KEEP:  float  # 데드크로스 후 잔여 비중
    TRANSITION_KEEP: float  # UPTREND→TRANSITION 전환 후 잔여 비중
    DOWNTREND_POSITION: float  # DOWNTREND 시 목표 포지션 (위험중립: 0.0, 적극: -1.0)

    # ── 지표 파라미터 (고정값 — 필요 시 서브클래스에서 오버라이드 가능) ───────
    _ATR_PERIOD:  int   = 14
    _BB_WINDOW:   int   = 20
    _BB_STD:      float = 2.0
    _MA10_WINDOW: int   = 10

    # ── optimization 연결 헬퍼 ─────────────────────────────────────────────
    def get_position_map(self) -> dict[str, float]:
        """optimization 레이어 주입용 POSITION_MAP 반환.

        사용 예시::

            result = run_walk_forward(
                ohlcv        = ohlcv,
                market_index = kospi,
                position_map = strategy.get_position_map(),
            )
        """
        return self.POSITION_MAP

    # ── 신호 생성 인터페이스 (서브클래스가 반드시 구현) ───────────────────────
    @abstractmethod
    def make_defensive_signals(
        self,
        regime_df: pd.DataFrame,
    ) -> pd.Series:
        """방어 자산 배정 가능 비율 반환.

        make_signals()가 개별 주식의 포지션을 담당하는 것과 달리,
        이 메서드는 portfolio 레이어가 남는 자금을 방어 자산에
        배정할 수 있는지를 반환한다.

        Parameters
        ----------
        regime_df : pd.DataFrame
            calc_regime() 결과. ohlcv 없이 국면 정보만으로 계산한다.

        Returns
        -------
        pd.Series
            날짜 인덱스, float 값의 목표 비중 시리즈.
            1.0 : 남는 자금을 방어 자산에 배정 가능 (위험중립형 단기채 ETF)
            0.0 : 별도 방어 자산 배정 없음 (적극투자형 인버스는 make_signals 처리)

        Examples
        --------
        백테스팅::

            strategy        = RiskNeutralStrategy(params)
            stock_signals   = strategy.make_signals(ohlcv, regime_df)
            defense_signals = strategy.make_defensive_signals(regime_df)
            # portfolio 레이어: defensive_weight = residual_cash * defense_signals
        """

    @abstractmethod
    def make_signals(
        self,
        ohlcv:     pd.DataFrame,
        regime_df: pd.DataFrame,
        state:     StrategyState | None = None,
    ) -> pd.Series:
        """날짜별 목표 비중 반환 (단일 종목 기준).

        Parameters
        ----------
        ohlcv : pd.DataFrame
            단일 종목 OHLCV (columns: open·high·low·close·volume).
            백테스팅: 전체 기간 / 트레이딩: 지표 워밍업을 포함한 최근 N일.
        regime_df : pd.DataFrame
            calc_regime() 결과. 열: REGIME·UPTREND·DOWNTREND·SIDEWAYS·
            TRANSITION·ma_s·ma_m·ma_l·adx·adx_plus_di·adx_minus_di.
            ohlcv와 동일한 날짜 인덱스를 가져야 한다.
        state : StrategyState | None, optional
            None  → 백테스팅 모드: 초기 포지션 0.0으로 시작.
            값 제공 → 트레이딩 모드: 이전 거래일 상태를 이어받아 시작.
                      루프 종료 후 state가 in-place로 갱신된다.

        Returns
        -------
        pd.Series
            날짜 인덱스, float 값의 목표 비중 시리즈.
            NaN  : 신호 없음 (포지션 유지 — portfolio 레이어가 주문 생략).
            float: 새로운 목표 비중 (0.0 = 전량 청산, 1.0 = 전액 매수).
                   적극투자형 DOWNTREND: -1.0 (인버스 ETF 100%).

        Notes
        -----
        트레이딩 모드에서 state 갱신 후 반드시 repo.save(state)를 호출해야
        다음 거래일에 올바른 상태를 이어받을 수 있다.
        """

    def make_signals_with_metadata(
        self,
        ohlcv:     pd.DataFrame,
        regime_df: pd.DataFrame,
        state:     StrategyState | None = None,
    ) -> tuple[pd.Series, pd.DataFrame]:
        """날짜별 목표 비중과 신호 메타데이터를 함께 반환한다.

        기본 구현은 기존 전략과의 호환성을 위해 ``make_signals()`` 결과만
        메타데이터에 담는다. 세부 전략은 exit_reason, 진입/청산 조건,
        디버그용 지표값 등을 추가한 DataFrame을 반환하도록 오버라이드할 수 있다.
        """
        signals = self.make_signals(ohlcv, regime_df, state)
        metadata = pd.DataFrame({"signal": signals}, index=signals.index)
        return signals, metadata

    # ── 공통 유틸리티 (서브클래스 내부 사용) ──────────────────────────────────


    def _init_state(
        self,
        dates: pd.DatetimeIndex,
        state: StrategyState | None,
    ) -> StrategyState:
        """거래 상태 초기화 — 백테스팅/트레이딩 모드 통일.

        백테스팅(state=None): 임시 StrategyState 생성 (루프 종료 후 폐기).
        트레이딩(state 제공): 전달받은 state를 그대로 반환 (in-place 갱신).
        """
        first_date = dates[0]
        return state if state is not None else StrategyState(
            strategy_type       = "",
            ticker              = "",
            trading_date        = first_date.date() if hasattr(first_date, "date") else first_date,
            regime              = MarketRegime.TRANSITION.name,
            position            = 0.0,
            entry1_date         = None,
            entry1_days_elapsed = None,
        )

    def _finalize_state(
        self,
        state:  StrategyState | None,
        dates:  pd.DatetimeIndex,
        _state: StrategyState,
    ) -> None:
        """트레이딩 모드 한정: trading_date 갱신.

        position·regime은 루프에서 이미 in-place로 반영됨.
        """
        if state is not None:
            last_date           = dates[-1]
            _state.trading_date = last_date.date() if hasattr(last_date, "date") else last_date
