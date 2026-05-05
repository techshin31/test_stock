"""2단계: 매크로 국면별 WICS 섹터 비중 결정

구현체:
    RegimeBasedSectorSelector — 국면별 고정 비중 테이블 (기본값)

다른 섹터 선택 로직을 실험하려면 BaseSectorSelector 를 상속해 구현한다.
"""
from __future__ import annotations

import pandas as pd

from .base import BaseSectorSelector
from .macro_signal import Regime

# WICS 섹터 코드 참조표
SEC = {
    "에너지":       "G10",
    "소재":         "G15",
    "산업재":       "G20",
    "경기소비재":   "G25",
    "필수소비재":   "G30",
    "헬스케어":     "G35",
    "금융":         "G40",
    "IT":           "G45",
    "커뮤니케이션": "G50",
    "유틸리티":     "G55",
}

# 국면별 기본 섹터 비중 테이블
_DEFAULT_WEIGHTS: dict[Regime, dict[str, float]] = {
    # A: Risk-On + 저금리 → IT·경기소비재·산업재 성장주 중심
    Regime.A: {
        "G45": 0.35,  # IT
        "G25": 0.25,  # 경기소비재
        "G20": 0.20,  # 산업재
        "G40": 0.10,  # 금융
        "G50": 0.10,  # 커뮤니케이션
    },
    # B: Risk-On + 고금리 → 에너지·소재·금융 실물/인플레이션 수혜
    Regime.B: {
        "G10": 0.25,  # 에너지
        "G15": 0.25,  # 소재
        "G40": 0.25,  # 금융
        "G20": 0.15,  # 산업재
        "G30": 0.10,  # 필수소비재
    },
    # C: Risk-Off + 저금리 → 헬스케어·유틸리티·필수소비재 방어주
    Regime.C: {
        "G35": 0.30,  # 헬스케어
        "G55": 0.25,  # 유틸리티
        "G30": 0.25,  # 필수소비재
        "G40": 0.10,  # 금융
        "G50": 0.10,  # 커뮤니케이션
    },
    # D: Risk-Off + 고금리 → 필수소비재·헬스케어 + 에너지 인플레이션 헷지
    Regime.D: {
        "G30": 0.35,  # 필수소비재
        "G35": 0.30,  # 헬스케어
        "G55": 0.20,  # 유틸리티
        "G10": 0.15,  # 에너지
    },
}


class RegimeBasedSectorSelector(BaseSectorSelector):
    """국면별 고정 비중 테이블 기반 섹터 선택기.

    weights_table 을 교체해 다른 국면-섹터 매핑을 실험할 수 있다.

    Args:
        weights_table: {Regime: {SEC_CD: 비중}} 딕셔너리.
                       None 이면 기본 테이블(_DEFAULT_WEIGHTS) 사용.

    Example::

        # 기본 테이블
        selector = RegimeBasedSectorSelector()

        # IT 집중형 커스텀 테이블
        from backtesting.strategy.macro_signal import Regime
        custom = {
            Regime.A: {"G45": 0.60, "G25": 0.40},
            Regime.B: {"G10": 0.40, "G15": 0.40, "G40": 0.20},
            Regime.C: {"G35": 0.50, "G30": 0.50},
            Regime.D: {"G30": 0.50, "G35": 0.50},
        }
        selector = RegimeBasedSectorSelector(weights_table=custom)
    """

    def __init__(self, weights_table: dict[Regime, dict[str, float]] | None = None) -> None:
        self._table = weights_table or _DEFAULT_WEIGHTS

    def get_weights(self, regime: Regime, date: pd.Timestamp | None = None) -> dict[str, float]:
        """{SEC_CD: 비중} 반환. 합계를 1.0 으로 정규화한다."""
        weights = self._table[regime].copy()
        total = sum(weights.values())
        return {k: v / total for k, v in weights.items()}


# 하위 호환성 유지
def get_sector_weights(regime: Regime) -> dict[str, float]:
    return RegimeBasedSectorSelector().get_weights(regime)
