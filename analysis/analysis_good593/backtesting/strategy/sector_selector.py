"""2단계: 매크로 국면별 WICS 섹터 비중 결정"""
from __future__ import annotations
from .macro_signal import Regime

# WICS 섹터 코드
SEC = {
    "에너지":         "G10",
    "소재":           "G15",
    "산업재":         "G20",
    "경기소비재":     "G25",
    "필수소비재":     "G30",
    "헬스케어":       "G35",
    "금융":           "G40",
    "IT":             "G45",
    "커뮤니케이션":   "G50",
    "유틸리티":       "G55",
}

# 국면별 섹터 비중 (합계 = 1.0)
_REGIME_WEIGHTS: dict[Regime, dict[str, float]] = {
    # A: Risk-On + 저금리 → IT·경기소비재·산업재
    Regime.A: {
        "G45": 0.35,  # IT
        "G25": 0.25,  # 경기소비재
        "G20": 0.20,  # 산업재
        "G40": 0.10,  # 금융
        "G50": 0.10,  # 커뮤니케이션
    },
    # B: Risk-On + 고금리 → 에너지·소재·금융
    Regime.B: {
        "G10": 0.25,  # 에너지
        "G15": 0.25,  # 소재
        "G40": 0.25,  # 금융
        "G20": 0.15,  # 산업재
        "G30": 0.10,  # 필수소비재
    },
    # C: Risk-Off + 저금리 → 헬스케어·유틸리티·필수소비재
    Regime.C: {
        "G35": 0.30,  # 헬스케어
        "G55": 0.25,  # 유틸리티
        "G30": 0.25,  # 필수소비재
        "G40": 0.10,  # 금융
        "G50": 0.10,  # 커뮤니케이션
    },
    # D: Risk-Off + 고금리 → 필수소비재·헬스케어 방어 포지션
    Regime.D: {
        "G30": 0.35,  # 필수소비재
        "G35": 0.30,  # 헬스케어
        "G55": 0.20,  # 유틸리티
        "G10": 0.15,  # 에너지 (인플레이션 헷지)
    },
}


def get_sector_weights(regime: Regime) -> dict[str, float]:
    """국면에 따른 {SEC_CD: 비중} 반환. 합계는 항상 1.0."""
    weights = _REGIME_WEIGHTS[regime].copy()
    total = sum(weights.values())
    return {k: v / total for k, v in weights.items()}
