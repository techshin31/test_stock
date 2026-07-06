"""
브레이크아웃 가속 모멘텀 전략 (Breakout Momentum Strategy)
===================================================

[가설]
- 시장의 주도주는 전고점을 돌파하며 상승 추세를 가속한다.
- 120일(약 6개월) 신고가에 근접하거나 돌파하는 종목을 펀더멘탈 우량주 중에서 매수한다.

[매수 조건]
- FA: 0 < per_proxy < 20.0 및 roe > 5.0% (모멘텀을 위해 PER 상한을 약간 완화)
- TA: 종가(close)가 과거 120일 최고가의 95% 이상 도달 (Breakout 근접 또는 돌파)
- 국면: KOSPI 지수가 UPTREND일 때만

[매도 조건]
- 국면이 DOWNTREND로 전환 시 전량 매도
- TA: 종가가 20일선 아래로 하락 시 (추세 꺾임)
"""
import numpy as np
import pandas as pd

from .base import AbstractStrategy, InvestmentType, DefensiveAssetType
from .state import StrategyState
from ..constant.types import MarketRegime
from ..signal.exit.regime import check_downtrend_exit

class BreakoutMomentumStrategy(AbstractStrategy):
    INVESTMENT_TYPE = InvestmentType.AGGRESSIVE
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
        self.PER_THRESHOLD_BUY = params.get("per_threshold_buy", 20.0)
        self.ROE_MIN = params.get("roe_min", 0.05)
        self.HIGH_WINDOW = params.get("high_window", 120)
        self.BREAKOUT_RATIO = params.get("breakout_ratio", 0.95)
        self.MA_WINDOW_FAST = params.get("ma_window_fast", 20)

    def make_defensive_signals(self, regime_df: pd.DataFrame) -> pd.Series:
        return pd.Series(0.0, index=regime_df.index, dtype=float)

    def make_signals(
        self,
        ohlcv: pd.DataFrame,
        regime_df: pd.DataFrame,
        state: StrategyState | None = None,
    ) -> pd.Series:
        signals, _ = self._make_signals(ohlcv, regime_df, state, include_metadata=False)
        return signals

    def make_signals_with_metadata(
        self,
        ohlcv: pd.DataFrame,
        regime_df: pd.DataFrame,
        state: StrategyState | None = None,
    ) -> tuple[pd.Series, pd.DataFrame]:
        return self._make_signals(ohlcv, regime_df, state, include_metadata=True)

    def _make_signals(
        self,
        ohlcv: pd.DataFrame,
        regime_df: pd.DataFrame,
        state: StrategyState | None,
        include_metadata: bool,
    ) -> tuple[pd.Series, pd.DataFrame]:
        
        close = ohlcv["close"]
        high_120 = close.rolling(window=self.HIGH_WINDOW, min_periods=self.HIGH_WINDOW//2).max()
        ma_fast = close.rolling(window=self.MA_WINDOW_FAST, min_periods=self.MA_WINDOW_FAST//2).mean()
        
        dates = close.index
        size = pd.Series(np.nan, index=dates, dtype=float)
        _state = self._init_state(dates, state)
        metadata_rows = []
        
        for i in range(len(dates)):
            d = dates[i]
            regime = regime_df.at[d, "REGIME"] if "REGIME" in regime_df.columns else MarketRegime.SIDEWAYS.name
            
            new_target = None
            signal_reason = None
            
            per_proxy = ohlcv.at[d, "per_proxy"] if "per_proxy" in ohlcv.columns else np.nan
            roe = ohlcv.at[d, "roe"] if "roe" in ohlcv.columns else np.nan
            
            curr_close = close.iloc[i]
            curr_high = high_120.iloc[i]
            curr_ma_fast = ma_fast.iloc[i]
            
            downtrend_exit = check_downtrend_exit(regime)
            
            if downtrend_exit:
                if _state.position != 0.0:
                    new_target = 0.0
                    signal_reason = "DOWNTREND"
                _state.reset_entry()
                
            elif _state.position > 0.0:
                if pd.notnull(curr_ma_fast) and curr_close < curr_ma_fast:
                    new_target = 0.0
                    signal_reason = "MOMENTUM_BREAK_EXIT"
                    _state.reset_entry()
                
            elif new_target is None and _state.position == 0.0:
                if regime == MarketRegime.UPTREND.name:
                    cond_fa = (pd.notnull(per_proxy) and 0 < per_proxy < self.PER_THRESHOLD_BUY) and \
                              (pd.notnull(roe) and roe > self.ROE_MIN)
                    cond_ta = (pd.notnull(curr_high) and curr_close >= curr_high * self.BREAKOUT_RATIO) and \
                              (pd.notnull(curr_ma_fast) and curr_close > curr_ma_fast)
                    
                    if cond_fa and cond_ta:
                        new_target = self.ENTRY_SIZE
                        signal_reason = "BREAKOUT_ENTRY"
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
                    "close": curr_close,
                    "high_120": curr_high,
                })
                
            _state.regime = regime
            
        self._finalize_state(state, dates, _state)
        metadata = pd.DataFrame(metadata_rows, index=dates) if include_metadata else pd.DataFrame(index=dates)
        return size, metadata
