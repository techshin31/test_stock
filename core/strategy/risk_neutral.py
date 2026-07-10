"""
위험중립형 전략
===============

[성향 요약]

  "은행 예금보다는 더 벌되, 시장 하락은 확실히 피한다"

  - 비교 기준선: 단기채 100% 보유
  - 하락장 회피(현금 → 단기채 주차) + 상승장 선별 매수
  - MDD 방어를 수익보다 우선시 (Beta ≤ 0.8 목표)

[평가 기준]

  지표           목표    경보선
  ──────────     ──────  ──────
  CAGR           8%      5%
  MDD            -30%    -40%
  MDD기간(월)    24      36
  Calmar         0.35    0.20
  Sortino        0.8     0.5
  Alpha(KOSPI)   +2%     0%
  Beta           ≤0.8    ≤1.0

─────────────────────────────────────────────────────────────────
레이어 역할 분리
─────────────────────────────────────────────────────────────────

  signal/entry, signal/exit  :  "무슨 일이 일어나고 있는가" (bool 반환)
  AbstractStrategy           :  공통 유틸리티 (_calc_indicators, _init_state 등)
  strategy/risk_neutral      :  "어떻게 매매할 것인가" (분할매수매도 전략 전체)

─────────────────────────────────────────────────────────────────
신호 우선순위
─────────────────────────────────────────────────────────────────

  [최우선] ATR stop             → 0%  (이하 신호 스킵)
  [매도 1] DOWNTREND 진입       → 0.0 (현금 대기)
  [매도 2] BB 상단 하향 (SIDE)  → 0%
  [매도 3] 데드크로스            → DEADCROSS_KEEP (10%)
  [매도 4] UPTREND→TRANSITION  → TRANSITION_KEEP (40%)
  [매수 1] UPTREND 진입 첫날    → ENTRY1_SIZE (40%)
  [매수 2] UPTREND 2차          → ENTRY2_SIZE (70%)
  [매수 3] SIDEWAYS BB 하단     → SIDEWAYS_SIZE (30%)

─────────────────────────────────────────────────────────────────
참고
─────────────────────────────────────────────────────────────────

  obsidian/투자성향/위험중립형_전략.md
  obsidian/매매원칙/분할매수매도_원칙.md
"""
import numpy as np
import pandas as pd

from .base  import AbstractStrategy, InvestmentType, DefensiveAssetType
from .state import StrategyState

from ..constant.types import MarketRegime

from ..signal.entry.uptrend  import check_uptrend_entry1, check_uptrend_entry2
from ..signal.entry.sideways import check_bb_lower_breakout
from ..signal.exit.atr_stop  import check_atr_stop
from ..signal.exit.regime    import check_downtrend_exit
from ..signal.exit.bollinger import check_bb_upper_breakdown
from ..signal.exit.deadcross import check_deadcross
from ..signal.exit.transition import check_transition_exit


class RiskNeutralStrategy(AbstractStrategy):
    """위험중립형 전략.

    하락장에서 현금으로 대피하고 상승장에서 분할 매수하는 보수적 전략.
    portfolio 레이어가 현금 잔여분을 단기채 ETF에 자동 주차한다.
    """

    # ── 투자성향 식별 (고정 — 전략 정체성) ──────────────────────────────────
    INVESTMENT_TYPE      = InvestmentType.RISK_NEUTRAL
    DEFENSIVE_ASSET_TYPE = DefensiveAssetType.BOND_ETF

    # ── IS 평가용 포지션 맵 (고정 — optimization 레이어 연결) ───────────────
    POSITION_MAP: dict[str, float] = {
        "UPTREND":    1.0,
        "DOWNTREND":  0.0,
        "SIDEWAYS":   0.0,
        "TRANSITION": 0.0,
    }

    def __init__(self, params: dict) -> None:
        """DB에서 조회한 파라미터로 전략 인스턴스를 초기화한다.

        Parameters
        ----------
        params : dict
            strategy_repo.get_params(db, "risk_neutral") 반환값.
        """
        self.ENTRY1_SIZE      = params["entry1_size"]
        self.ENTRY2_SIZE      = params["entry2_size"]
        self.ENTRY2_WINDOW    = params["entry2_window"]
        self.SIDEWAYS_SIZE    = params["sideways_size"]
        self.DEADCROSS_KEEP   = params["deadcross_keep"]
        self.TRANSITION_KEEP  = params["transition_keep"]
        self.DOWNTREND_POSITION = params["downtrend_position"]
        self.USE_MA10_TRIGGER = params["use_ma10_trigger"]
        self.BENCHMARK            = params["benchmark"]
        self.TARGET_CAGR          = params["target_cagr"]
        self.WARNING_CAGR         = params["warning_cagr"]
        self.TARGET_MDD           = params["target_mdd"]
        self.WARNING_MDD          = params["warning_mdd"]
        self.TARGET_MDD_DURATION  = params["target_mdd_duration"]
        self.WARNING_MDD_DURATION = params["warning_mdd_duration"]
        self._ATR_PERIOD  = params["atr_period"]
        self._BB_WINDOW   = params["bb_window"]
        self._BB_STD      = params["bb_std"]
        self._MA10_WINDOW = params["ma10_window"]

    # ── 방어 자산 신호 ───────────────────────────────────────────────────────
    def make_defensive_signals(
        self,
        regime_df: pd.DataFrame,
    ) -> pd.Series:
        """단기채 ETF 배정 가능 신호 생성.

        위험중립형은 모든 국면에서 남는 현금을 단기채 ETF에 주차한다.
        실제 단기채 ETF 목표 비중은 portfolio/allocation.py가
        잔여 현금에 이 신호를 곱해 결정한다.

        Returns
        -------
        pd.Series
            항상 1.0 (잔여 현금 단기채 ETF 배정 가능)
        """
        return pd.Series(1.0, index=regime_df.index, dtype=float)

    # ── 주식 신호 생성 ───────────────────────────────────────────────────────
    def make_signals(
        self,
        ohlcv:     pd.DataFrame,
        regime_df: pd.DataFrame,
        state:     StrategyState | None = None,
    ) -> pd.Series:
        """위험중립형 분할매수매도 신호 생성.

        Parameters
        ----------
        ohlcv : pd.DataFrame
            단일 종목 OHLCV (columns: open·high·low·close·volume).
        regime_df : pd.DataFrame
            calc_regime() 결과.
        state : StrategyState | None
            None → 백테스팅 모드 / 값 제공 → 트레이딩 모드 (in-place 갱신).

        Returns
        -------
        pd.Series
            날짜 인덱스, float 값의 목표 비중 시리즈.
            NaN: 신호 없음 (포지션 유지).
        """
        signals, _ = self._make_signals(ohlcv, regime_df, state, include_metadata=False)
        return signals

    def make_signals_with_metadata(
        self,
        ohlcv:     pd.DataFrame,
        regime_df: pd.DataFrame,
        state:     StrategyState | None = None,
    ) -> tuple[pd.Series, pd.DataFrame]:
        """위험중립형 신호와 분석용 메타데이터를 함께 생성한다.

        ``make_signals()``와 같은 목표 비중 Series를 반환하면서, 각 날짜의
        signal_reason, exit_reason, 조건 플래그, 주요 지표값을 DataFrame으로
        함께 제공한다. 백테스트 성과 귀속과 실전 디버깅에서 사용한다.
        """
        return self._make_signals(ohlcv, regime_df, state, include_metadata=True)

    def _make_signals(
        self,
        ohlcv:     pd.DataFrame,
        regime_df: pd.DataFrame,
        state:     StrategyState | None,
        include_metadata: bool,
    ) -> tuple[pd.Series, pd.DataFrame]:
        """위험중립형 분할매수매도 신호 생성 내부 구현."""
        close = ohlcv["close"]
        dates = close.index

        atr, upper_bb, lower_bb, ma_s, ma_m, _ = self._calc_indicators(ohlcv, regime_df)
        size   = pd.Series(np.nan, index=dates, dtype=float)
        _state = self._init_state(dates, state)
        metadata_rows: list[dict[str, object]] = []

        for i in range(len(dates)):
            d          = dates[i]
            regime     = regime_df.at[d, "REGIME"]
            price      = close.iloc[i]
            new_target: float | None = None
            signal_reason: str | None = None
            exit_reason: str | None = None
            secondary_exit_reason: str | None = None
            position_before = float(_state.position)
            prev_regime = _state.regime
            prev_close = close.iloc[i - 1] if i > 0 else np.nan
            prev_atr = atr.iloc[i - 1] if i > 0 else np.nan

            downtrend_exit = check_downtrend_exit(regime)
            atr_stop = (
                _state.position > 0.0
                and i > 0
                and check_atr_stop(price, prev_close, prev_atr)
            )

            # ── [최우선] ATR stop → 개별 종목 청산 ───────────────────────
            # ATR은 각 종목 OHLCV로 계산한 hard risk exit이다.
            # 같은 날 DOWNTREND가 겹쳐도 주문 사유는 ATR_STOP으로 우선 귀속한다.
            if atr_stop:
                new_target = 0.0
                signal_reason = "ATR_STOP"
                exit_reason = "ATR_STOP"
                if downtrend_exit:
                    secondary_exit_reason = "DOWNTREND"
                _state.reset_entry()

            # ── [매도 1] DOWNTREND → 개별 종목 청산 ──────────────────────
            # 이 종목 포지션을 0.0으로 만든다.
            # 남은 현금을 단기채 ETF에 주차하는 것은 portfolio 레이어의 역할
            # (DEFENSIVE_ASSET_TYPE = BOND_ETF 참고)
            elif downtrend_exit:
                if _state.position != 0.0:
                    new_target = 0.0
                    signal_reason = "DOWNTREND"
                    exit_reason = "DOWNTREND"
                _state.reset_entry()

            else:
                # ── [매도 2~4] 포지션 보유 중 매도 신호 ───────────────────
                if _state.position > 0.0 and i > 0:
                    prev_price    = close.iloc[i - 1]
                    cur_upper_bb  = upper_bb.iloc[i]
                    prev_upper_bb = upper_bb.iloc[i - 1]
                    cur_ma_s      = ma_s.iloc[i]
                    prev_ma_s     = ma_s.iloc[i - 1]
                    cur_ma_m      = ma_m.iloc[i]
                    prev_ma_m     = ma_m.iloc[i - 1]

                    # [매도 2] SIDEWAYS + BB 상단 하향 돌파 → 전량 청산
                    if (regime == MarketRegime.SIDEWAYS.name
                            and check_bb_upper_breakdown(
                                price, prev_price, cur_upper_bb, prev_upper_bb)):
                        new_target = 0.0
                        signal_reason = "BB_UPPER_BREAKDOWN"
                        exit_reason = "BB_UPPER_BREAKDOWN"
                        _state.reset_entry()

                    # [매도 3] 데드크로스 → DEADCROSS_KEEP(10%) 유지
                    elif (check_deadcross(cur_ma_s, prev_ma_s, cur_ma_m, prev_ma_m)
                            and _state.position > self.DEADCROSS_KEEP):
                        new_target = self.DEADCROSS_KEEP
                        signal_reason = "DEADCROSS"
                        exit_reason = "DEADCROSS"

                    # [매도 4] UPTREND → TRANSITION 전환 첫날 → TRANSITION_KEEP(40%) 유지
                    elif (check_transition_exit(regime, _state.regime)
                            and _state.position > self.TRANSITION_KEEP):
                        new_target = self.TRANSITION_KEEP
                        signal_reason = "TRANSITION_EXIT"
                        exit_reason = "TRANSITION_EXIT"

                # ── [매수] 신호 ────────────────────────────────────────────
                if new_target is None:

                    if regime == MarketRegime.UPTREND.name:
                        # [매수 1] UPTREND 진입 첫날 → 1차 40% 진입
                        if check_uptrend_entry1(regime, _state.regime):
                            d_date = d.date() if hasattr(d, "date") else d
                            _state.open_entry1(d_date)
                            new_target = self.ENTRY1_SIZE  # 40%
                            signal_reason = "UPTREND_ENTRY1"

                        # [매수 2] UPTREND 2차 매수 (entry1 이내 + 종가>MA20)
                        elif (_state.is_entry2_available(self.ENTRY2_WINDOW)
                                and _state.position < self.ENTRY2_SIZE
                                and check_uptrend_entry2(regime, price, ma_s.iloc[i])):
                            new_target = self.ENTRY2_SIZE  # 70%
                            signal_reason = "UPTREND_ENTRY2"

                    elif regime == MarketRegime.SIDEWAYS.name and i > 0:
                        # [매수 3] SIDEWAYS BB 하단 상향 돌파 → 횡보 매수
                        if check_bb_lower_breakout(
                                price, close.iloc[i - 1],
                                lower_bb.iloc[i], lower_bb.iloc[i - 1]):
                            new_target = self.SIDEWAYS_SIZE  # 30%
                            signal_reason = "SIDEWAYS_BB_LOWER_ENTRY"

            # ── 결과 기록 및 상태 갱신 ─────────────────────────────────────
            if new_target is not None:
                size.iloc[i]    = new_target
                _state.position = new_target

            if include_metadata:
                metadata_rows.append({
                    "regime": regime,
                    "prev_regime": prev_regime,
                    "price": price,
                    "prev_close": prev_close,
                    "prev_atr": prev_atr,
                    "position_before": position_before,
                    "signal": size.iloc[i],
                    "target_position": new_target,
                    "position_after": float(_state.position),
                    "signal_reason": signal_reason,
                    "exit_reason": exit_reason,
                    "secondary_exit_reason": secondary_exit_reason,
                    "atr_stop": bool(atr_stop),
                    "downtrend_exit": bool(downtrend_exit),
                })

            _state.tick_entry1()
            _state.regime = regime   # 다음 거래일의 prev_regime

        self._finalize_state(state, dates, _state)
        metadata = (
            pd.DataFrame(metadata_rows, index=dates)
            if include_metadata
            else pd.DataFrame(index=dates)
        )
        return size, metadata
