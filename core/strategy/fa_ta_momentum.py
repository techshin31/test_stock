"""
FA/TA 중기 모멘텀 혼합 전략 (FA/TA Momentum Strategy)
===============================================

[성향 요약]
  - 3개월(1개 분기) 중기 스윙 전략
  - 과거 실적 기반의 FA 밸류에이션(per_proxy, roe)과 TA 가격 모멘텀(60일 이동평균, 단기 수익률)을 결합.

[매수 조건]
  - FA: 0 < per_proxy < 15.0 (저평가) 및 roe > 5.0% (우량성)
  - TA: 종가(close) > 60일 이동평균선(ma_60) 및 60일 가격 모멘텀(수익률) > 0
  - 국면: UPTREND 또는 SIDEWAYS

[매도 조건]
  - 국면이 DOWNTREND로 전환 시 전량 매도
  - FA 고평가 도달 시 (per_proxy > 25.0)
  - 추세 꺾임 시 (close < ma_60)
"""
import numpy as np
import pandas as pd

from .base  import AbstractStrategy, InvestmentType, DefensiveAssetType
from .state import StrategyState
from ..constant.types import MarketRegime
from ..signal.exit.regime import check_downtrend_exit

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
        self.PER_THRESHOLD_BUY = params.get("per_threshold_buy", 15.0)
        self.PER_THRESHOLD_SELL = params.get("per_threshold_sell", 25.0)
        self.ROE_MIN = params.get("roe_min", 0.05)
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
        per_proxy_col = ohlcv["per_proxy"].to_numpy() if "per_proxy" in ohlcv.columns else np.full(len(dates), np.nan)
        roe_col = ohlcv["roe"].to_numpy() if "roe" in ohlcv.columns else np.full(len(dates), np.nan)
        
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
            per_proxy = per_proxy_col[i]
            roe = roe_col[i]
            
            # TA 지표
            curr_close = close_arr[i]
            curr_ma = ma_arr[i]
            curr_ma_fast = ma_fast_arr[i]
            curr_mom = mom_arr[i]
            
            downtrend_exit = check_downtrend_exit(regime)
            
            # [매도 1] DOWNTREND
            if downtrend_exit:
                if _state.position != 0.0:
                    new_target = 0.0
                    signal_reason = "DOWNTREND"
                _state.reset_entry()
                
            # [매도 2] 고평가 또는 추세 꺾임 (Whipsaw 방지를 위해 데드크로스 적용)
            elif _state.position > 0.0:
                if pd.notnull(per_proxy) and per_proxy > self.PER_THRESHOLD_SELL:
                    new_target = 0.0
                    signal_reason = "OVERVALUED_PER"
                    _state.reset_entry()
                elif pd.notnull(curr_ma) and pd.notnull(curr_ma_fast) and curr_ma_fast < curr_ma:
                    new_target = 0.0
                    signal_reason = "TA_MOMENTUM_LOSS"
                    _state.reset_entry()
                
            # [매수] 가치 + 모멘텀 만족
            elif new_target is None and _state.position == 0.0:
                if regime == MarketRegime.UPTREND.name:
                    cond_fa = (pd.notnull(per_proxy) and 0 < per_proxy < self.PER_THRESHOLD_BUY) and \
                              (pd.notnull(roe) and roe > self.ROE_MIN)
                    
                    # 골든크로스(정배열) + 60일 모멘텀 양수
                    cond_ta = (pd.notnull(curr_ma) and pd.notnull(curr_ma_fast)) and \
                              (curr_close > curr_ma) and (curr_ma_fast > curr_ma) and \
                              (pd.notnull(curr_mom) and curr_mom > 0)
                    
                    if cond_fa and cond_ta:
                        new_target = self.ENTRY_SIZE
                        signal_reason = "FA_TA_MOMENTUM_ENTRY"
                        _state.open_entry1(d)
            
            if new_target is not None:
                size.iloc[i] = new_target
                _state.position = new_target
                
            if include_metadata:
                metadata_rows.append({
                    "regime": regime,
                    "target_position": new_target,
                    "signal_reason": signal_reason,
                    "per_proxy": per_proxy,
                    "roe": roe,
                    "close_ma": curr_ma,
                    "momentum": curr_mom,
                })
                
            _state.regime = regime
            
        self._finalize_state(state, dates, _state)
        metadata = pd.DataFrame(metadata_rows, index=dates) if include_metadata else pd.DataFrame(index=dates)
        return size, metadata
