import pandas as pd
import numpy as np

def calculate_forward_per(current_price: float, forward_eps: float) -> float:
    """선행 PER 계산 (Forward PER = 현재주가 / 미래 추정 EPS)"""
    if forward_eps <= 0:
        return np.inf
    return current_price / forward_eps

def calculate_earnings_surprise_ratio(estimated_op: float, prev_op: float) -> float:
    """어닝 서프라이즈(또는 예상 실적 성장률) 비율 계산 (%)"""
    if prev_op <= 0:
        return 0.0
    return ((estimated_op - prev_op) / prev_op) * 100
