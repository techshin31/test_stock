"""
적극투자형 전략
===============

[성향 요약]

  "B&H보다 적게 잃고, 더 많이 번다"

  - 비교 기준선: B&H (5종목 균등 보유)
  - 위험중립형과 동일한 분할매수매도 원칙 적용
  - 딱 2가지만 다름:
    ① 상승장: MA10 트리거로 더 빠른 진입 → 수익 극대화
    ② 하락장: 현금 대기 → 인버스 ETF로 수익화

[평가 기준]

  지표           목표    경보선
  ──────────     ──────  ──────
  CAGR           15%     10%
  MDD            -35%    -50%
  MDD기간(월)    24      36
  Calmar         0.45    0.25
  Sortino        1.0     0.6
  Alpha(KOSPI)   +5%     +2%
  Beta           ≤1.3    ≤1.5

─────────────────────────────────────────────────────────────────
위험중립형 대비 차이점 2가지
─────────────────────────────────────────────────────────────────

  ① USE_MA10_TRIGGER = True
      UPTREND 진입 첫날 종가 > MA10 이면 즉시 ENTRY2_SIZE(70%) 진입.
      MA10이 이미 단기 상승 추세를 확인했으므로 1차를 건너뜀.

  ② DOWNTREND_POSITION = -1.0
      DOWNTREND 진입 시 현금 대기 대신 인버스 ETF 100% 편입.
      DOWNTREND 탈출 시 인버스 포지션을 즉시 청산(0.0)하고
      다음 UPTREND 진입을 기다린다.

─────────────────────────────────────────────────────────────────
신호 우선순위
─────────────────────────────────────────────────────────────────

  [전처리] DOWNTREND 종료 → 인버스 청산   → 0.0
  [매도 1] DOWNTREND 진입                → -1.0 (인버스 ETF 100%)
  [최우선] ATR stop                      → 0%  (발동 즉시 continue)
  [매도 2] BB 상단 하향 (SIDE)           → 0%
  [매도 3] 데드크로스                     → DEADCROSS_KEEP (10%)
  [매도 4] UPTREND→TRANSITION           → TRANSITION_KEEP (40%)
  [매수 1] UPTREND 진입 첫날             → MA10 돌파: 70% / 아니면: 40%
  [매수 2] UPTREND 2차                   → ENTRY2_SIZE (70%)
  [매수 3] SIDEWAYS BB 하단              → SIDEWAYS_SIZE (30%)

─────────────────────────────────────────────────────────────────
참고
─────────────────────────────────────────────────────────────────

  obsidian/투자성향/적극투자형_전략.md
  obsidian/매매원칙/인버스ETF_매매원칙.md
  obsidian/매매원칙/분할매수매도_원칙.md
"""
import os
from pathlib import Path

import numpy as np
import pandas as pd

from core.signal.news_signal import NewsSignalGenerator

from .base  import AbstractStrategy, InvestmentType, DefensiveAssetType
from .state import StrategyState

from ..constant.types import MarketRegime

from ..signal.entry.uptrend  import check_uptrend_entry1, check_uptrend_entry2, check_ma10_trigger
from ..signal.entry.sideways import check_bb_lower_breakout
from ..signal.exit.atr_stop  import check_atr_stop
from ..signal.exit.regime    import check_downtrend_exit
from ..signal.exit.bollinger import check_bb_upper_breakdown
from ..signal.exit.deadcross import check_deadcross
from ..signal.exit.transition import check_transition_exit


class AggressiveStrategy(AbstractStrategy):
    """적극투자형 전략.

    위험중립형과 동일한 분할매수매도 원칙을 사용하되,
    MA10 트리거(빠른 진입)와 인버스 ETF(하락 수익화) 2가지만 다르다.
    """

    # ── 투자성향 식별 (고정 — 전략 정체성) ──────────────────────────────────
    INVESTMENT_TYPE      = InvestmentType.AGGRESSIVE
    DEFENSIVE_ASSET_TYPE = DefensiveAssetType.INVERSE_ETF

    # ── IS 평가용 포지션 맵 (고정 — optimization 레이어 연결) ───────────────
    POSITION_MAP: dict[str, float] = {
        "UPTREND":    1.0,
        "DOWNTREND":  -1.0,   # 인버스 ETF 100% ← 핵심 차이
        "SIDEWAYS":   0.0,
        "TRANSITION": 0.0,
    }

    def __init__(self, params: dict) -> None:
        """DB에서 조회한 파라미터로 전략 인스턴스를 초기화한다.

        Parameters
        ----------
        params : dict
            strategy_repo.get_params(db, "aggressive") 반환값.
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
        self.news_signal_enabled = bool(
            params.get(
                "enable_news_signal",
                os.getenv("ENABLE_NEWS_SIGNAL", "false").lower() == "true",
            )
        )
        execution_mode = str(
            params.get("execution_mode", os.getenv("TRADING_EXECUTION_MODE", "DRY_RUN"))
        ).upper()
        if execution_mode not in {"DRY_RUN", "PAPER", "REAL", "SIMULATE"}:
            execution_mode = "DRY_RUN"
        self.news_cache_dir = Path("logs") / execution_mode.lower()
        self._news_signal_generator = None

    # ── 유틸리티 메서드 ──────────────────────────────────────────────────────
    def _append_to_dashboard(self, message: str) -> None:
        """대시보드 타임라인에 메시지를 추가합니다."""
        import datetime
        import json

        dashboard_path = self.news_cache_dir / "dashboard_state.json"
        if not dashboard_path.exists():
            return

        try:
            with open(dashboard_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            timeline = data.setdefault("timeline", [])
            now = datetime.datetime.now().strftime("%H:%M")
            timeline.append(f"[{now}] {message}")
            data["timeline"] = timeline[-10:] # 최근 10개 유지

            with open(dashboard_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def _news_score(self, ticker: str) -> float:
        """Return a cached mode-scoped score only when explicitly enabled."""
        if not self.news_signal_enabled:
            return 0.0
        if self._news_signal_generator is None:
            self._news_signal_generator = NewsSignalGenerator(self.news_cache_dir)
        return self._news_signal_generator.generate_signals([ticker]).get(ticker, 0.0)

    # ── 방어 자산 신호 ───────────────────────────────────────────────────────
    def make_defensive_signals(
        self,
        regime_df: pd.DataFrame,
    ) -> pd.Series:
        """방어 자산 신호 없음 — 인버스 ETF는 make_signals()로 처리.

        적극투자형의 DOWNTREND 대응은 make_signals()에서
        개별 주식 포지션을 -1.0으로 반환하는 방식으로 이미 처리된다.
        별도의 방어 자산 티커가 없으므로 항상 0.0을 반환한다.

        Returns
        -------
        pd.Series
            항상 0.0 (방어 자산 미보유)
        """
        return pd.Series(0.0, index=regime_df.index, dtype=float)

    # ── 주식 신호 생성 ───────────────────────────────────────────────────────
    def make_signals(
        self,
        ohlcv:     pd.DataFrame,
        regime_df: pd.DataFrame,
        state:     StrategyState | None = None,
    ) -> pd.Series:
        """적극투자형 분할매수매도 신호 생성.

        위험중립형 대비 차이점:
          - UPTREND 진입 첫날: MA10 돌파 시 즉시 70% (아니면 40%)
          - DOWNTREND: 현금 대신 인버스 ETF 100% 편입 (-1.0)
          - DOWNTREND 종료: 인버스 포지션 즉시 청산 후 다음 신호 대기

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
            -1.0: 인버스 ETF 100% (DOWNTREND 진입 시).
        """
        close = ohlcv["close"]
        dates = close.index

        atr, upper_bb, lower_bb, ma_s, ma_m, ma10 = self._calc_indicators(ohlcv, regime_df)
        size   = pd.Series(np.nan, index=dates, dtype=float)
        _state = self._init_state(dates, state)

        for i in range(len(dates)):
            d          = dates[i]
            regime     = regime_df.at[d, "REGIME"]
            price      = close.iloc[i]
            new_target: float | None = None

            # ── [매도 1] DOWNTREND → 인버스 ETF 분할/전면 진입 ──────────────────────
            # DOWNTREND 진입 시 하락 변동성(ATR 비율)에 따라 50% 또는 100% 진입
            if check_downtrend_exit(regime):
                atr_ratio = atr.iloc[i] / price if price > 0 else 0
                target_inverse = -1.0 if atr_ratio > 0.03 else -0.5
                if _state.position != target_inverse and _state.position > -1.0:
                    new_target = target_inverse
                _state.reset_entry()

            # ── [전처리] 인버스 포지션 자동 청산 ──────────────────────────
            # DOWNTREND가 끝난 첫 날, 인버스 포지션을 즉시 청산한다.
            # DOWNTREND 체크 이후에 위치해야 "여전히 DOWNTREND"인 경우를 거르지 않는다.
            elif _state.position < 0.0:
                _state.position = 0.0
                _state.reset_entry()
                new_target = 0.0

            else:
                # ── [최우선] ATR stop ──────────────────────────────────────
                if _state.position > 0.0 and i > 0:
                    if check_atr_stop(price, close.iloc[i - 1], atr.iloc[i - 1]):
                        new_target      = 0.0
                        _state.position = 0.0
                        _state.reset_entry()
                        size.iloc[i]    = new_target
                        _state.regime   = regime
                        _state.tick_entry1()
                        continue   # 이하 모든 신호 스킵

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
                        _state.reset_entry()

                    # [매도 3] 데드크로스 → DEADCROSS_KEEP(10%) 유지
                    elif (check_deadcross(cur_ma_s, prev_ma_s, cur_ma_m, prev_ma_m)
                            and _state.position > self.DEADCROSS_KEEP):
                        new_target = self.DEADCROSS_KEEP

                    # [매도 4] UPTREND → TRANSITION 전환 첫날 → TRANSITION_KEEP(40%) 유지
                    elif (check_transition_exit(regime, _state.regime)
                            and _state.position > self.TRANSITION_KEEP):
                        new_target = self.TRANSITION_KEEP

                    # [매도 4.5] 모멘텀 조기 급락 방어 (Evasive Maneuver)
                    elif (regime == MarketRegime.UPTREND.name
                            and price < cur_ma_s and prev_price > 0 and (prev_price - price)/prev_price > 0.03
                            and _state.position > 0.4):
                        new_target = 0.4  # 비중을 선제적으로 40%로 축소

                # ── [매수] 신호 ────────────────────────────────────────────
                if new_target is None:

                    if regime == MarketRegime.UPTREND.name:
                        # 변동성 기반 동적 비중 조절 (ATR ratio > 4% 이면 리스크 관리 위해 진입 비중 절반으로 축소)
                        atr_ratio = atr.iloc[i] / price if price > 0 else 0
                        volatility_scale = 0.5 if atr_ratio > 0.04 else 1.0

                        # [매수 1] UPTREND 진입 첫날 → MA10 돌파 시 즉시 70%, 아니면 40%
                        if check_uptrend_entry1(regime, _state.regime):
                            d_date = d.date() if hasattr(d, "date") else d
                            _state.open_entry1(d_date)

                            # 뉴스 감성 분석 오버레이 (TRADING MODE일 때 최신일에만 실행)
                            news_score = 0.0
                            if (
                                self.news_signal_enabled
                                and state is not None
                                and i == len(dates) - 1
                            ):
                                try:
                                    news_score = self._news_score(_state.ticker)
                                except Exception:
                                    pass

                            # 악재(-0.3 이하)면 진입 차단, 호재(0.5 이상)면 비중 확대
                            if news_score <= -0.3:
                                new_target = 0.0
                                # 타임라인 로깅 (하루에 한 번만)
                                if str(d_date) != _state.metadata.get('last_news_log_date'):
                                    _state.metadata['last_news_log_date'] = str(d_date)
                                    self._append_to_dashboard(f"🚨 [{_state.ticker}] 악재 공시/뉴스 감지 (점수: {news_score:.1f}). 매수 진입을 차단합니다.")
                            else:
                                if news_score >= 0.5:
                                    volatility_scale = min(1.0, volatility_scale + 0.5) # 비중 회복/확대
                                    if str(d_date) != _state.metadata.get('last_news_log_date'):
                                        _state.metadata['last_news_log_date'] = str(d_date)
                                        self._append_to_dashboard(f"🚀 [{_state.ticker}] 대형 호재/공시 감지 (점수: {news_score:.1f}). 진입 비중을 확대합니다!")

                                if check_ma10_trigger(price, ma10.iloc[i]):
                                    _state.entry1_days_elapsed = self.ENTRY2_WINDOW + 1  # 중복 2차 방지
                                    new_target = round(self.ENTRY2_SIZE * volatility_scale, 2)
                                else:
                                    new_target = round(self.ENTRY1_SIZE * volatility_scale, 2)

                        # [매수 2] UPTREND 2차 매수 (entry1 이내 + 종가>MA20)
                        elif (_state.is_entry2_available(self.ENTRY2_WINDOW)
                                and _state.position < self.ENTRY2_SIZE
                                and check_uptrend_entry2(regime, price, ma_s.iloc[i])):
                            new_target = round(self.ENTRY2_SIZE * volatility_scale, 2)

                    elif regime == MarketRegime.SIDEWAYS.name and i > 0:
                        # [매수 3] SIDEWAYS BB 하단 상향 돌파 → 횡보 매수
                        if check_bb_lower_breakout(
                                price, close.iloc[i - 1],
                                lower_bb.iloc[i], lower_bb.iloc[i - 1]):
                            new_target = self.SIDEWAYS_SIZE  # 30%

            # ── 결과 기록 및 상태 갱신 ─────────────────────────────────────
            if new_target is not None:
                size.iloc[i]    = new_target
                _state.position = new_target

            _state.tick_entry1()
            _state.regime = regime   # 다음 거래일의 prev_regime

        self._finalize_state(state, dates, _state)
        return size
