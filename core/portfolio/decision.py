"""Portfolio-level target weight decisions."""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from core.strategy.base import AbstractStrategy

from .allocation import allocate_portfolio
from .rotation import force_exit_targets
from .universe import PortfolioUniverse


@dataclass
class PortfolioDecision:
    """One-day portfolio decision output."""

    as_of: pd.Timestamp
    target_weights: pd.Series
    stock_signals: pd.Series
    momentum: pd.Series
    forced_targets: pd.Series
    active_tickers: list[str]


def decide_target_weights_for_day(
    as_of: pd.Timestamp,
    strategy: AbstractStrategy,
    universe: PortfolioUniverse,
    current_weights: pd.Series,
    signals: pd.DataFrame,
    momentum_dict: dict[str, pd.DataFrame],
    regime_dict: dict[str, pd.DataFrame],
    defensive_ticker: str,
) -> PortfolioDecision:
    """하루치 포트폴리오 목표 비중을 결정한다.

    전략 신호를 그대로 반환하지 않고, 강제청산/유니버스 상태/모멘텀/
    방어자산 정책을 반영해 최종 목표 보유 비중으로 변환한다.

    Parameters
    ----------
    as_of : pd.Timestamp
        목표 비중을 결정할 기준 날짜.
    strategy : AbstractStrategy
        방어자산 정책 등 포트폴리오 배분에 필요한 전략 객체.
    universe : PortfolioUniverse
        종목별 ACTIVE/SELL_ONLY/REMOVED 상태를 가진 현재 유니버스.
    current_weights : pd.Series
        현재 보유 중인 자산별 비중.
    signals : pd.DataFrame
        전략이 만든 날짜별/종목별 목표 비중 신호.
    momentum_dict : dict[str, pd.DataFrame]
        종목별 모멘텀 점수. 투자 가능 비중을 나눌 때 우선순위로 사용한다.
    regime_dict : dict[str, pd.DataFrame]
        종목별 시장 국면 데이터. 방어자산 배분 판단에 사용한다.
    defensive_ticker : str
        잔여 비중을 배정할 방어자산 티커.
    """
    # 오늘 날짜에 해당하는 종목별 전략 신호만 분리한다.
    as_of = pd.Timestamp(as_of)
    today_signals = signals.loc[[as_of]].copy()

    # 강제청산 기한이 지난 SELL_ONLY 종목은 목표 비중 0으로 덮어쓴다.
    forced = force_exit_targets(universe, current_weights, as_of)
    for ticker, target in forced.items():
        if ticker in today_signals.columns:
            today_signals.loc[as_of, ticker] = target

    # tradable_tickers()는 기본값으로 ACTIVE뿐 아니라 SELL_ONLY 종목도 함께 반환한다.
    # 즉 여기서의 active는 "순수 ACTIVE"가 아니라 "오늘 의사결정 대상 종목"에 가깝다.
    active = universe.tradable_tickers()
    # 그중 오늘 신호 테이블에 존재하는 종목만 남겨 이후 배분 계산에 넘긴다.
    active = [ticker for ticker in active if ticker in today_signals.columns]
    if not active:
        # 오늘 판단할 종목이 없으면 빈 의사결정 결과를 반환한다.
        return PortfolioDecision(
            as_of=as_of,
            target_weights=pd.Series(dtype=float),
            stock_signals=pd.Series(dtype=float),
            momentum=pd.Series(dtype=float),
            forced_targets=forced,
            active_tickers=[],
        )

    # first_regime: 방어자산 배분 판단에 사용할 오늘의 시장 국면 데이터.
    # 현재는 첫 번째 active 종목의 regime을 포트폴리오 대표 국면처럼 사용한다.
    first_regime = regime_dict[active[0]].reindex([as_of]).ffill()

    # momentum: 오늘 active 종목들의 모멘텀 점수 테이블.
    # 목표 비중 합계가 투자 가능 비중을 넘을 때, 종목별 배분 우선순위로 사용한다.
    momentum = pd.concat(
        [momentum_dict[ticker].reindex([as_of]) for ticker in active],
        axis=1,
    ).reindex(index=[as_of], columns=active).fillna(0.0)

    # 포트폴리오 배분 규칙을 적용해 주식/방어자산의 최종 목표 비중을 만든다.
    target_weights = allocate_portfolio(
        # 오늘 판단할 종목의 원 전략 신호.
        signals=today_signals[active],
        # 목표 비중 합계가 투자 가능 비중을 넘을 때 사용할 종목별 배분 우선순위.
        momentum=momentum,
        # ACTIVE/SELL_ONLY/REMOVED 상태를 보고 매수 가능 여부를 제한한다.
        universe=universe,
        # 방어자산 신호와 방어자산 타입을 제공하는 전략 객체.
        strategy=strategy,
        # 남는 비중을 방어자산에 둘지 판단할 시장 국면 데이터.
        regime_df=first_regime,
        # 현재 보유 비중. 기존 비중 유지와 SELL_ONLY 추가 매수 차단에 사용한다.
        current_weights=current_weights.reindex(active).fillna(0.0),
        # 방어자산 비중이 배정될 티커.
        defensive_ticker=defensive_ticker,
    ).iloc[0]

    # 백테스트/실거래 레이어가 사용할 하루치 의사결정 결과를 묶어 반환한다.
    return PortfolioDecision(
        as_of=as_of,
        target_weights=target_weights,
        stock_signals=today_signals[active].iloc[0],
        momentum=momentum.iloc[0],
        forced_targets=forced,
        active_tickers=active,
    )
