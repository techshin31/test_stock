"""
FA/TA 중기 모멘텀 혼합 전략 (FA/TA Momentum Strategy)
===============================================

[성향 요약]
  - 3개월(1개 분기) 중기 스윙 전략
  - DB의 fa_score(종합 퀀트 점수)와 TA 가격 모멘텀(60일 이동평균)을 결합.

[매수 조건]
  - FA: is_eligible=True AND fa_score >= 60 (DB 종합 우량 판정 통과)
  - TA: 골든크로스(단기MA > 장기MA) AND 60일 모멘텀 양수
  - 국면: UPTREND 또는 SIDEWAYS

[매도 조건]
  - 국면이 DOWNTREND로 전환 시 전량 매도
  - TA 추세 꺾임 시 (단기MA < 장기MA 데드크로스)
  - FA 점수 급락 시 (fa_score < 40, 재무 악화 신호)
"""
import numpy as np
import pandas as pd

from .base  import AbstractStrategy, InvestmentType, DefensiveAssetType
from .state import StrategyState
from ..constant.types import MarketRegime

class FaTaMomentumStrategy(AbstractStrategy):
    """FA/TA 혼합 중기 모멘텀 전략"""
    
    INVESTMENT_TYPE      = InvestmentType.AGGRESSIVE
    DEFENSIVE_ASSET_TYPE = DefensiveAssetType.BOND_ETF
    
    POSITION_MAP: dict[str, float] = {
        "UPTREND":    1.0,
        "DOWNTREND":  0.0,
        "SIDEWAYS":   0.5,
        "TRANSITION": 0.0,
    }
    
    def __init__(self, params: dict) -> None:
        self.BENCHMARK = params.get("benchmark", "KOSPI")
        self.TARGET_CAGR = params.get("target_cagr", 0.10)
        self.WARNING_CAGR = params.get("warning_cagr", 0.05)
        self.TARGET_MDD = params.get("target_mdd", -0.25)
        self.WARNING_MDD = params.get("warning_mdd", -0.35)
        self.TARGET_MDD_DURATION = params.get("target_mdd_duration", 24)
        self.WARNING_MDD_DURATION = params.get("warning_mdd_duration", 36)
        self.ENTRY_SIZE = params.get("entry_size", 0.2)
        self.FA_SCORE_MIN = params.get("fa_score_min", 60.0)        # 진입 최소 FA 종합 점수
        self.FA_SCORE_EXIT = params.get("fa_score_exit", 40.0)      # 재무 악화 매도 기준
        self.DEBT_RATIO_MAX = params.get("debt_ratio_max", 2.0)     # 부채비율 상한 (200%)
        self.MIN_SCORE_CONFIDENCE = params.get("min_score_confidence", 0.70)
        self.STOP_LOSS_PCT = params.get("stop_loss_pct", 0.10)
        self.TRAILING_STOP_PCT = params.get("trailing_stop_pct", 0.08)
        self.MA_WINDOW = params.get("ma_window", 60)
        self.MA_WINDOW_FAST = params.get("ma_window_fast", 20)
        if not 0 < self.MIN_SCORE_CONFIDENCE <= 1:
            raise ValueError("min_score_confidence must be in (0, 1]")
        if not 0 < self.STOP_LOSS_PCT < 1 or not 0 < self.TRAILING_STOP_PCT < 1:
            raise ValueError("stop-loss settings must be in (0, 1)")

    def make_defensive_signals(self, regime_df: pd.DataFrame) -> pd.Series:
        return pd.Series(0.0, index=regime_df.index, dtype=float)

    def evaluate_latest(
        self,
        ohlcv: pd.DataFrame,
        regime: str,
        *,
        current_position: float = 0.0,
        average_price: float | None = None,
        current_price: float | None = None,
        peak_price: float | None = None,
    ) -> tuple[float, dict]:
        """완결된 최신 봉과 실제 계좌 포지션으로 오늘의 목표 비중을 계산한다.

        라이브 운용에서 과거 전체 상태를 다시 시뮬레이션하지 않도록 별도 경로를
        제공한다. 지표는 충분한 과거 데이터로 계산하되 의사결정은 마지막 행에서만
        수행한다.
        """
        required = max(self.MA_WINDOW, self.MA_WINDOW_FAST)
        if ohlcv.empty or len(ohlcv) <= required:
            raise ValueError(f"TA 계산에 최소 {required + 1}개 완결 봉이 필요합니다.")

        close = ohlcv["close"].astype(float)
        ma = close.rolling(self.MA_WINDOW, min_periods=self.MA_WINDOW).mean()
        ma_fast = close.rolling(
            self.MA_WINDOW_FAST, min_periods=self.MA_WINDOW_FAST
        ).mean()
        momentum = close.pct_change(self.MA_WINDOW)
        last = ohlcv.iloc[-1]
        fa_score = last.get("fa_score")
        is_eligible = bool(last.get("is_eligible", False))
        debt_ratio = last.get("debt_ratio")
        score_confidence = last.get("score_confidence")
        curr_close = float(close.iloc[-1])
        curr_ma = float(ma.iloc[-1])
        curr_ma_fast = float(ma_fast.iloc[-1])
        curr_momentum = float(momentum.iloc[-1])
        reason = "HOLD"
        target = max(float(current_position), 0.0)

        risk_price = float(current_price) if current_price and current_price > 0 else curr_close
        average_price = float(average_price or 0.0)
        peak_price = float(peak_price or 0.0)

        if current_position > 0 and average_price > 0 and risk_price <= average_price * (1 - self.STOP_LOSS_PCT):
            target, reason = 0.0, "HARD_STOP_LOSS"
        elif (
            current_position > 0
            and peak_price > average_price > 0
            and risk_price <= peak_price * (1 - self.TRAILING_STOP_PCT)
        ):
            target, reason = 0.0, "TRAILING_STOP"
        elif regime in (MarketRegime.DOWNTREND.name, MarketRegime.TRANSITION.name):
            target, reason = 0.0, f"MARKET_{regime}"
        elif current_position > 0:
            if pd.notnull(fa_score) and float(fa_score) < self.FA_SCORE_EXIT:
                target, reason = 0.0, "FA_SCORE_DETERIORATED"
            elif pd.notnull(debt_ratio) and float(debt_ratio) > self.DEBT_RATIO_MAX:
                target, reason = 0.0, "FA_DEBT_LIMIT"
            elif curr_ma_fast < curr_ma:
                target, reason = 0.0, "TA_MOMENTUM_LOSS"
        else:
            valid_fa = (
                is_eligible
                and pd.notnull(fa_score)
                and float(fa_score) >= self.FA_SCORE_MIN
                and pd.notnull(debt_ratio)
                and float(debt_ratio) <= self.DEBT_RATIO_MAX
                and pd.notnull(score_confidence)
                and float(score_confidence) >= self.MIN_SCORE_CONFIDENCE
            )
            valid_ta = (
                curr_close > curr_ma
                and curr_ma_fast > curr_ma
                and curr_momentum > 0
            )
            if regime in (MarketRegime.UPTREND.name, MarketRegime.SIDEWAYS.name):
                if valid_fa and valid_ta:
                    strength = min(max(curr_momentum, 0.0), 0.20)
                    target = round(0.10 + (strength / 0.20) * 0.30, 4)
                    reason = "FA_TA_ENTRY"
                else:
                    target, reason = 0.0, "ENTRY_CONDITIONS_NOT_MET"

        metadata = {
            "regime": regime,
            "target_position": target,
            "signal_reason": reason,
            "fa_score": None if pd.isna(fa_score) else float(fa_score),
            "score_confidence": (
                None if pd.isna(score_confidence) else float(score_confidence)
            ),
            "debt_ratio": None if pd.isna(debt_ratio) else float(debt_ratio),
            "close": curr_close,
            "ma": curr_ma,
            "ma_fast": curr_ma_fast,
            "momentum": curr_momentum,
            "risk_price": risk_price,
            "average_price": average_price or None,
            "peak_price": peak_price or None,
            "stop_loss_pct": self.STOP_LOSS_PCT,
            "trailing_stop_pct": self.TRAILING_STOP_PCT,
        }
        return target, metadata

    def make_signals(
        self,
        ohlcv:     pd.DataFrame,
        regime_df: pd.DataFrame,
        state:     StrategyState | None = None,
    ) -> pd.Series:
        signals, _ = self._make_signals(ohlcv, regime_df, state, include_metadata=False)
        return signals

    def make_signals_with_metadata(
        self,
        ohlcv:     pd.DataFrame,
        regime_df: pd.DataFrame,
        state:     StrategyState | None = None,
    ) -> tuple[pd.Series, pd.DataFrame]:
        return self._make_signals(ohlcv, regime_df, state, include_metadata=True)

    def _make_signals(
        self,
        ohlcv:     pd.DataFrame,
        regime_df: pd.DataFrame,
        state:     StrategyState | None,
        include_metadata: bool,
    ) -> tuple[pd.Series, pd.DataFrame]:
        
        # TA 지표 계산
        close = ohlcv["close"]
        ma = close.rolling(window=self.MA_WINDOW, min_periods=self.MA_WINDOW//2).mean()
        ma_fast = close.rolling(window=self.MA_WINDOW_FAST, min_periods=self.MA_WINDOW_FAST//2).mean()
        mom = close.pct_change(periods=self.MA_WINDOW)
        
        dates = close.index
        size = pd.Series(np.nan, index=dates, dtype=float)
        _state = self._init_state(dates, state)
        metadata_rows = []
        

        # FA 지표 추출 (미리 numpy로 변환)
        fa_score_col = ohlcv["fa_score"].to_numpy() if "fa_score" in ohlcv.columns else np.full(len(dates), np.nan)
        is_eligible_col = ohlcv["is_eligible"].to_numpy() if "is_eligible" in ohlcv.columns else np.full(len(dates), False)
        debt_ratio_col = ohlcv["debt_ratio"].to_numpy() if "debt_ratio" in ohlcv.columns else np.full(len(dates), np.nan)
        confidence_col = ohlcv["score_confidence"].to_numpy() if "score_confidence" in ohlcv.columns else np.full(len(dates), np.nan)
        stale_col = ohlcv["fa_is_stale"].to_numpy() if "fa_is_stale" in ohlcv.columns else np.full(len(dates), True)
        
        close_arr = close.to_numpy()
        ma_arr = ma.to_numpy()
        ma_fast_arr = ma_fast.to_numpy()
        mom_arr = mom.to_numpy()
        
        for i in range(len(dates)):
            d = dates[i]
            regime = regime_df.at[d, "REGIME"] if "REGIME" in regime_df.columns else MarketRegime.SIDEWAYS.name
            
            new_target = None
            signal_reason = None
            
            # FA 지표
            fa_score = fa_score_col[i]
            is_eligible = bool(is_eligible_col[i]) if pd.notnull(is_eligible_col[i]) else False
            debt_ratio = debt_ratio_col[i]
            score_confidence = confidence_col[i]
            fa_is_stale = bool(stale_col[i]) if pd.notnull(stale_col[i]) else True
            
            # TA 지표
            curr_close = close_arr[i]
            curr_ma = ma_arr[i]
            curr_ma_fast = ma_fast_arr[i]
            curr_mom = mom_arr[i]
            downtrend_exit = (regime == MarketRegime.DOWNTREND.name)
            
            # [매도 1] DOWNTREND
            if downtrend_exit:
                if _state.position != 0.0:
                    new_target = 0.0
                    signal_reason = "DOWNTREND"
                _state.reset_entry()
                
            # [매도 2] FA 점수 급락 (재무 악화) 또는 TA 추세 꺾임 (데드크로스)
            elif _state.position > 0.0:
                if pd.notnull(fa_score) and fa_score < self.FA_SCORE_EXIT:
                    new_target = 0.0
                    signal_reason = "FA_SCORE_DETERIORATED"
                    _state.reset_entry()
                elif pd.notnull(curr_ma) and pd.notnull(curr_ma_fast) and curr_ma_fast < curr_ma:
                    new_target = 0.0
                    signal_reason = "TA_MOMENTUM_LOSS"
                    _state.reset_entry()
                
            # [매수] FA 우량 판정 통과 + TA 골든크로스 + 모멘텀 양수
            elif new_target is None and _state.position == 0.0:
                if regime in (MarketRegime.UPTREND.name, MarketRegime.SIDEWAYS.name):
                    # FA: DB에서 계산된 종합 점수와 부채비율 조건
                    cond_fa = (
                        is_eligible and
                        pd.notnull(fa_score) and fa_score >= self.FA_SCORE_MIN and
                        pd.notnull(debt_ratio) and float(debt_ratio) <= self.DEBT_RATIO_MAX and
                        pd.notnull(score_confidence) and float(score_confidence) >= self.MIN_SCORE_CONFIDENCE and
                        not fa_is_stale
                    )
                    
                    # 골든크로스(정배열) + 60일 모멘텀 양수
                    cond_ta = (pd.notnull(curr_ma) and pd.notnull(curr_ma_fast)) and \
                              (curr_close > curr_ma) and (curr_ma_fast > curr_ma) and \
                              (pd.notnull(curr_mom) and curr_mom > 0)
                    
                    if cond_fa and cond_ta:
                        # [고무줄 모드] 모멘텀 비례 다이나믹 베팅 (10% ~ 40%)
                        # 상승 강도(curr_mom) 0%~20% 구간을 0.1~0.4 비중으로 선형 매핑
                        mom_clamped = min(max(curr_mom, 0.0), 0.20)
                        dynamic_weight = 0.10 + (mom_clamped / 0.20) * 0.30
                        new_target = round(dynamic_weight, 2)
                        
                        signal_reason = f"DYNAMIC_ENTRY_{int(new_target*100)}%"
                        _state.open_entry1(d)
            
            if new_target is not None:
                size.iloc[i] = new_target
                _state.position = new_target
                
            if include_metadata:
                metadata_rows.append({
                    "regime": regime,
                    "target_position": new_target,
                    "signal_reason": signal_reason,
                    "fa_score": fa_score,
                    "is_eligible": is_eligible,
                    "debt_ratio": debt_ratio,
                    "score_confidence": score_confidence,
                    "fa_is_stale": fa_is_stale,
                    "close_ma": curr_ma,
                    "momentum": curr_mom,
                })
                
            _state.regime = regime
            
        self._finalize_state(state, dates, _state)
        metadata = pd.DataFrame(metadata_rows, index=dates) if include_metadata else pd.DataFrame(index=dates)
        return size, metadata
