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
        self.ENTRY_SIZE = params.get("entry_size", 0.2)
        self.FA_SCORE_MIN = params.get("fa_score_min", 60.0)        # 진입 최소 FA 종합 점수
        self.FA_SCORE_EXIT = params.get("fa_score_exit", 40.0)      # 재무 악화 매도 기준
        self.DEBT_RATIO_MAX = params.get("debt_ratio_max", 2.0)     # 부채비율 상한 (200%)
        self.MA_WINDOW = params.get("ma_window", 60)
        self.MA_WINDOW_FAST = params.get("ma_window_fast", 20)

    def make_defensive_signals(self, regime_df: pd.DataFrame) -> pd.Series:
        return pd.Series(0.0, index=regime_df.index, dtype=float)

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
                        (pd.isnull(debt_ratio) or float(debt_ratio) <= self.DEBT_RATIO_MAX)
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
                    "close_ma": curr_ma,
                    "momentum": curr_mom,
                })
                
            _state.regime = regime
            
        self._finalize_state(state, dates, _state)
        metadata = pd.DataFrame(metadata_rows, index=dates) if include_metadata else pd.DataFrame(index=dates)
        return size, metadata
