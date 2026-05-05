"""탑다운 3단계 전략 인터페이스 (ABC)

각 단계를 독립적으로 구현·교체·비교할 수 있도록 추상 기반 클래스를 정의한다.

  1단계 BaseMacroSignal    — 매크로 국면 판단
  2단계 BaseSectorSelector — 섹터 비중 결정
  3단계 BaseStockScorer    — 종목 선택 및 비중 산정
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

import pandas as pd


class BaseMacroSignal(ABC):
    """1단계: 매크로 국면 판단 인터페이스.

    구현 예시: BdiCopperMacroSignal (구리 + BDI MA 기반)

    새 구현체를 만들 때는 이 클래스를 상속하고
    compute() 가 반환하는 객체에 get_regime(date) 메서드를 제공하면 된다.
    """

    @abstractmethod
    def compute(self, years: list[int]) -> Any:
        """날짜별 국면 조회 객체를 반환한다.

        반환 객체는 반드시 get_regime(date: pd.Timestamp) 메서드를 가져야 한다.

        Args:
            years: 백테스팅 대상 연도 목록
        """
        ...


class BaseSectorSelector(ABC):
    """2단계: 섹터 비중 결정 인터페이스.

    구현 예시: RegimeBasedSectorSelector (국면별 고정 비중 테이블)

    다른 방식(모멘텀 기반, 동일 가중 등)을 실험하려면 이 클래스를 상속한다.
    """

    @abstractmethod
    def get_weights(self, regime: Any, date: pd.Timestamp) -> dict[str, float]:
        """{SEC_CD: 비중} 딕셔너리를 반환한다. 합계는 1.0.

        Args:
            regime: BaseMacroSignal.compute().get_regime() 반환값
            date:   리밸런싱 기준일 (날짜에 따라 비중이 달라지는 전략에서 사용)
        """
        ...


class BaseStockScorer(ABC):
    """3단계: 종목 선택 및 비중 산정 인터페이스.

    구현 예시: FaStockScorer (FA 7지표 점수 기반)

    다른 방식(모멘텀, 시가총액 가중 등)을 실험하려면 이 클래스를 상속한다.
    """

    @abstractmethod
    def score(
        self,
        date: pd.Timestamp,
        sector_weights: dict[str, float],
        wics_df: pd.DataFrame,
        fa_df: pd.DataFrame,
    ) -> dict[str, float]:
        """{CMP_CD: 포트폴리오 비중} 딕셔너리를 반환한다.

        Args:
            date:           리밸런싱 기준일
            sector_weights: {SEC_CD: 섹터 비중} (BaseSectorSelector 결과)
            wics_df:        WICS 시가총액 전체 데이터
            fa_df:          DART 재무제표 전체 데이터
        """
        ...
