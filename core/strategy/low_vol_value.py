"""
저변동성 가치주 전략 (Low Volatility Value Strategy)
===================================================

[가설]
- 하락/횡보장에서는 주가 변동성이 적은 주식이 결국 시장을 아웃퍼폼한다.
- 펀더멘탈이 우수하면서 주가 변동성이 낮은 종목을 매수하여 복리를 누린다.

[매수 조건]
- FA: 0 < per_proxy < 15.0 및 roe > 5.0%
- TA: 60일 연환산 변동성(Annualized Volatility) < 20% (0.2)
- 국면: KOSPI 지수가 UPTREND일 때만

[매도 조건]
- 국면이 DOWNTREND로 전환 시 전량 매도
- TA: 변동성이 다시 커질 경우 (Volatility > 30%) 매도
"""
import numpy as np
import pandas as pd

from .base import AbstractStrategy, InvestmentType, DefensiveAssetType
from .state import StrategyState
from ..constant.types import MarketRegime
from ..signal.exit.regime import check_downtrend_exit

def calc_annualized_volatility(close_series: pd.Series, window: int = 60) -> pd.Series:
    daily_returns = close_series.pct_change()
    # 일별 수익률의 표준편차 * sqrt(252)
    volatility = daily_returns.rolling(window=window, min_periods=window//2).std() * np.sqrt(252)
    return volatility

class LowVolValueStrategy(AbstractStrategy):
    INVESTMENT_TYPE = InvestmentType.RISK_NEUTRAL
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
        self.VOL_WINDOW = params.get("vol_window", 60)
        self.VOL_THRESHOLD_BUY = params.get("vol_threshold_buy", 0.20)
        self.VOL_THRESHOLD_SELL = params.get("vol_threshold_sell", 0.30)

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
        volatility = calc_annualized_volatility(close, self.VOL_WINDOW)
        
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
            curr_vol = volatility.iloc[i]
            
            downtrend_exit = check_downtrend_exit(regime)
            
            if downtrend_exit:
                if _state.position != 0.0:
                    new_target = 0.0
                    signal_reason = "DOWNTREND"
                _state.reset_entry()
                
            elif _state.position > 0.0:
                if pd.notnull(curr_vol) and curr_vol > self.VOL_THRESHOLD_SELL:
                    new_target = 0.0
                    signal_reason = "HIGH_VOL_EXIT"
                    _state.reset_entry()
                
            elif new_target is None and _state.position == 0.0:
                if regime == MarketRegime.UPTREND.name:
                    cond_fa = (pd.notnull(per_proxy) and 0 < per_proxy < self.PER_THRESHOLD_BUY) and \
                              (pd.notnull(roe) and roe > self.ROE_MIN)
                    cond_ta = pd.notnull(curr_vol) and curr_vol < self.VOL_THRESHOLD_BUY
                    
                    if cond_fa and cond_ta:
                        new_target = self.ENTRY_SIZE
                        signal_reason = "LOW_VOL_ENTRY"
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
                    "volatility": curr_vol,
                })
                
            _state.regime = regime
            
        self._finalize_state(state, dates, _state)
        metadata = pd.DataFrame(metadata_rows, index=dates) if include_metadata else pd.DataFrame(index=dates)
        return size, metadata
