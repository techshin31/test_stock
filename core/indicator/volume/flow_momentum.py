import pandas as pd
import numpy as np

def calculate_inst_momentum(flow_df: pd.DataFrame, window: int = 5) -> pd.Series:
    """기관 누적 순매수 모멘텀 (최근 N일간 순매수 합계)"""
    if 'inst_net' not in flow_df.columns:
        return pd.Series(np.nan, index=flow_df.index)
    return flow_df['inst_net'].rolling(window=window, min_periods=1).sum()

def calculate_foreign_ratio_change(flow_df: pd.DataFrame, window: int = 5) -> pd.Series:
    """최근 N일간 외국인 지분율 변동 (% 포인트)"""
    if 'foreigner_ratio' not in flow_df.columns:
        return pd.Series(np.nan, index=flow_df.index)
    return flow_df['foreigner_ratio'].diff(periods=window - 1).fillna(0.0)
