"""
역발상 / 평균회귀 전략 (Mean Reversion Strategy)
===============================================

[가설]
- 시장(코스피)이 상승장일 때, 개별 우량주가 일시적 악재나 수급 불균형으로 과매도(RSI < 30) 상태가 되면 반등할 확률이 높다.

[매수 조건]
- FA: 0 < per_proxy < 15.0 및 roe > 5.0%
- TA: RSI(14일) < 30 (과매도 상태)
- 국면: KOSPI 지수가 UPTREND일 때만

[매도 조건]
- 국면이 DOWNTREND로 전환 시 전량 매도
- TA: RSI > 70 (과매수 상태 도달 시 익절)
"""
import numpy as np
import pandas as pd

from .base import AbstractStrategy, InvestmentType, DefensiveAssetType
from .state import StrategyState
from ..constant.types import MarketRegime
from ..signal.exit.regime import check_downtrend_exit

def calc_rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    up, down = delta.copy(), delta.copy()
    up[up < 0] = 0
    down[down > 0] = 0
    roll_up = up.ewm(span=period, min_periods=period).mean()
    roll_down = down.abs().ewm(span=period, min_periods=period).mean()
    rs = roll_up / roll_down
    rsi = 100.0 - (100.0 / (1.0 + rs))
    return rsi

class MeanReversionStrategy(AbstractStrategy):
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
        self.PER_THRESHOLD_BUY = params.get("per_threshold_buy", 15.0)
        self.ROE_MIN = params.get("roe_min", 0.05)
        self.RSI_PERIOD = params.get("rsi_period", 14)
        self.RSI_OVERSOLD = params.get("rsi_oversold", 30)
        self.RSI_OVERBOUGHT = params.get("rsi_overbought", 70)

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
        rsi = calc_rsi(close, self.RSI_PERIOD)
        
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
            curr_rsi = rsi.iloc[i]
            
            downtrend_exit = check_downtrend_exit(regime)
            
            if downtrend_exit:
                if _state.position != 0.0:
                    new_target = 0.0
                    signal_reason = "DOWNTREND"
                _state.reset_entry()
                
            elif _state.position > 0.0:
                if pd.notnull(curr_rsi) and curr_rsi > self.RSI_OVERBOUGHT:
                    new_target = 0.0
                    signal_reason = "RSI_OVERBOUGHT_EXIT"
                    _state.reset_entry()
                
            elif new_target is None and _state.position == 0.0:
                if regime == MarketRegime.UPTREND.name:
                    cond_fa = (pd.notnull(per_proxy) and 0 < per_proxy < self.PER_THRESHOLD_BUY) and \
                              (pd.notnull(roe) and roe > self.ROE_MIN)
                    cond_ta = pd.notnull(curr_rsi) and curr_rsi < self.RSI_OVERSOLD
                    
                    if cond_fa and cond_ta:
                        new_target = self.ENTRY_SIZE
                        signal_reason = "RSI_OVERSOLD_ENTRY"
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
                    "rsi": curr_rsi,
                })
                
            _state.regime = regime
            
        self._finalize_state(state, dates, _state)
        metadata = pd.DataFrame(metadata_rows, index=dates) if include_metadata else pd.DataFrame(index=dates)
        return size, metadata
