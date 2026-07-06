"""
가치-모멘텀 혼합 전략 (Value-Momentum Strategy)
===============================================

[성향 요약]
  - 3개월(1개 분기) 중기 스윙 전략
  - 펀더멘털(Valuation, 실적 성장)이 우수하면서 동시에 수급(기관/외국인 양매수) 모멘텀이 살아있는 종목을 매수한다.

[매수 조건]
  - Forward PER < 15.0 (저평가)
  - Estimated OP YoY > 10% (실적 성장)
  - 최근 5일 기관 순매수 > 0 및 외국인 지분율 증가 (수급 모멘텀)
  - 기술적 국면: UPTREND 또는 SIDEWAYS

[매도 조건]
  - 국면이 DOWNTREND로 전환 시 전량 매도
  - Forward PER > 25.0 (고평가 도달 시)
"""
import numpy as np
import pandas as pd

from .base  import AbstractStrategy, InvestmentType, DefensiveAssetType
from .state import StrategyState
from ..constant.types import MarketRegime
from ..signal.exit.regime import check_downtrend_exit

class ValueMomentumStrategy(AbstractStrategy):
    """가치-모멘텀 혼합형 스윙 전략"""
    
    INVESTMENT_TYPE      = InvestmentType.AGGRESSIVE
    DEFENSIVE_ASSET_TYPE = DefensiveAssetType.BOND_ETF
    
    POSITION_MAP: dict[str, float] = {
        "UPTREND":    1.0,
        "DOWNTREND":  0.0,
        "SIDEWAYS":   0.5,
        "TRANSITION": 0.0,
    }
    
    def __init__(self, params: dict) -> None:
        """
        Parameters
        ----------
        params : dict
            {
                "target_cagr": 15.0,
                "target_mdd": -20.0,
                ...
            }
        """
        self.BENCHMARK = params.get("benchmark", "KOSPI")
        self.ENTRY_SIZE = params.get("entry_size", 1.0)
        self.PER_THRESHOLD_BUY = params.get("per_threshold_buy", 15.0)
        self.PER_THRESHOLD_SELL = params.get("per_threshold_sell", 25.0)
        self.OP_YOY_MIN = params.get("op_yoy_min", 10.0)

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
        close = ohlcv["close"]
        dates = close.index
        
        # 외부에서 주입된 FA/TA 지표가 ohlcv에 결합되어 있다고 가정
        # (실제 파이프라인에서 fundamental/volume indicator를 merge하여 ohlcv에 담아 전달해야 함)
        
        size = pd.Series(np.nan, index=dates, dtype=float)
        _state = self._init_state(dates, state)
        metadata_rows = []
        
        for i in range(len(dates)):
            d = dates[i]
            regime = regime_df.at[d, "REGIME"] if "REGIME" in regime_df.columns else MarketRegime.SIDEWAYS.name
            
            new_target = None
            signal_reason = None
            
            # 지표 추출
            fwd_per = ohlcv.at[d, "forward_per"] if "forward_per" in ohlcv.columns else np.nan
            inst_mom = ohlcv.at[d, "inst_momentum"] if "inst_momentum" in ohlcv.columns else np.nan
            foreign_diff = ohlcv.at[d, "foreign_ratio_diff"] if "foreign_ratio_diff" in ohlcv.columns else np.nan
            
            downtrend_exit = check_downtrend_exit(regime)
            
            # [매도 1] DOWNTREND 진입
            if downtrend_exit:
                if _state.position != 0.0:
                    new_target = 0.0
                    signal_reason = "DOWNTREND"
                _state.reset_entry()
                
            # [매도 2] Valuation 고평가 도달
            elif _state.position > 0.0 and pd.notnull(fwd_per) and fwd_per > self.PER_THRESHOLD_SELL:
                new_target = 0.0
                signal_reason = "OVERVALUED_PER"
                _state.reset_entry()
                
            # [매수] 가치 + 모멘텀 만족
            elif new_target is None and _state.position == 0.0:
                if regime in [MarketRegime.UPTREND.name, MarketRegime.SIDEWAYS.name]:
                    cond_val = (pd.notnull(fwd_per) and 0 < fwd_per < self.PER_THRESHOLD_BUY)
                    cond_flow = (pd.notnull(inst_mom) and inst_mom > 0) and (pd.notnull(foreign_diff) and foreign_diff > 0)
                    
                    if cond_val and cond_flow:
                        new_target = self.ENTRY_SIZE
                        signal_reason = "VALUE_MOMENTUM_ENTRY"
                        _state.open_entry1(d)
            
            if new_target is not None:
                size.iloc[i] = new_target
                _state.position = new_target
                
            if include_metadata:
                metadata_rows.append({
                    "regime": regime,
                    "target_position": new_target,
                    "signal_reason": signal_reason
                })
                
            _state.regime = regime
            
        self._finalize_state(state, dates, _state)
        metadata = pd.DataFrame(metadata_rows, index=dates) if include_metadata else pd.DataFrame(index=dates)
        return size, metadata
