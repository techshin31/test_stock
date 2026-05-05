"""탑다운 3단계 파이프라인

TopDownPipeline 은 3개의 교체 가능한 단계를 하나로 묶는다.
각 단계 구현체를 바꾸거나 파라미터를 조정해 다양한 전략을 실험할 수 있다.

Usage::

    from backtesting.strategy.pipeline import TopDownPipeline, default_pipeline
    from backtesting.strategy.macro_signal import BdiCopperMacroSignal
    from backtesting.strategy.sector_selector import RegimeBasedSectorSelector
    from backtesting.strategy.stock_scorer import FaStockScorer
    from backtesting.strategy.macro_signal import Regime

    # 기본 파이프라인
    pipeline = default_pipeline(top_n=5)

    # 단계별 파라미터 조정
    aggressive = TopDownPipeline(
        macro_signal=BdiCopperMacroSignal(high_rate_tnx=3.0),  # 금리 기준 완화
        sector_selector=RegimeBasedSectorSelector(),
        stock_scorer=FaStockScorer(top_n=3),                   # 섹터당 3종목
        name="Aggressive",
    )

    # 섹터 비중 테이블 교체
    custom_weights = {
        Regime.A: {"G45": 0.60, "G25": 0.40},  # IT 집중
        ...
    }
    custom = TopDownPipeline(
        macro_signal=BdiCopperMacroSignal(),
        sector_selector=RegimeBasedSectorSelector(weights_table=custom_weights),
        stock_scorer=FaStockScorer(top_n=5),
        name="IT_Focus",
    )
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import pandas as pd

from .base import BaseMacroSignal, BaseSectorSelector, BaseStockScorer


@dataclass
class TopDownPipeline:
    """탑다운 3단계 파이프라인.

    Attributes:
        macro_signal:    1단계 — 매크로 국면 판단 구현체
        sector_selector: 2단계 — 섹터 비중 결정 구현체
        stock_scorer:    3단계 — 종목 선택 구현체
        name:            결과 비교 시 식별용 이름
    """
    macro_signal: BaseMacroSignal
    sector_selector: BaseSectorSelector
    stock_scorer: BaseStockScorer
    name: str = "TopDown"

    def build_schedule(
        self,
        years: list[int],
        rebal_dates: list[date],
        wics_df: pd.DataFrame,
        fa_df: pd.DataFrame,
        verbose: bool = False,
    ) -> dict[date, dict[str, float]]:
        """리밸런싱 날짜별 {CMP_CD: 비중} 스케줄을 계산한다.

        Args:
            years:       백테스팅 연도 목록 (매크로 신호 warmup에 필요)
            rebal_dates: 리밸런싱 실행일 목록
            wics_df:     WICS 전체 데이터
            fa_df:       DART 재무제표 전체 데이터
            verbose:     날짜별 로그 출력 여부

        Returns:
            {date: {CMP_CD: weight}} 스케줄 딕셔너리
        """
        macro = self.macro_signal.compute(years)

        schedule: dict[date, dict[str, float]] = {}
        for rd in rebal_dates:
            rd_ts = pd.Timestamp(rd)
            regime = macro.get_regime(rd_ts)
            sector_weights = self.sector_selector.get_weights(regime, rd_ts)
            target_weights = self.stock_scorer.score(rd_ts, sector_weights, wics_df, fa_df)

            schedule[rd] = target_weights
            if verbose:
                regime_str = getattr(regime, "value", str(regime))
                print(
                    f"  [{self.name}] {rd} | 국면={regime_str}"
                    f" | 섹터={len(sector_weights)}개 | 종목={len(target_weights)}개"
                )

        return schedule


def default_pipeline(top_n: int = 5) -> TopDownPipeline:
    """기본 탑다운 파이프라인을 반환한다.

    - 1단계: BdiCopperMacroSignal (구리 + BDI MA)
    - 2단계: RegimeBasedSectorSelector (국면별 고정 비중)
    - 3단계: FaStockScorer (FA 7지표 점수)

    Args:
        top_n: 섹터당 편입 종목 수
    """
    from .macro_signal import BdiCopperMacroSignal
    from .sector_selector import RegimeBasedSectorSelector
    from .stock_scorer import FaStockScorer

    return TopDownPipeline(
        macro_signal=BdiCopperMacroSignal(),
        sector_selector=RegimeBasedSectorSelector(),
        stock_scorer=FaStockScorer(top_n=top_n),
        name=f"TopDown_FA_top{top_n}",
    )
