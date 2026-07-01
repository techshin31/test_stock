"""거래 비용 계산 공통 모듈."""
from __future__ import annotations

import pandas as pd

from core.constant.types import Market, StockCap
from core.constant.values import TradingCostParam, SlippageParam


def _cost_rates(market: Market, cap: StockCap) -> tuple[float, float, float]:
    """수수료, 매도세, 슬리피지 비율을 반환한다."""
    if not isinstance(market, Market):
        raise Exception(f"올바른 시장을 입력해주세요. >> {market}")
    if not isinstance(cap, StockCap):
        raise Exception(f"올바른 종목 규모를 입력해주세요. >> {cap}")

    commission = TradingCostParam.COMMISSION_BUY.rate()
    tax = (
        TradingCostParam.TAX_KOSPI.rate()
        if market == Market.KOSPI
        else TradingCostParam.TAX_KOSDAQ.rate()
    )
    slippage = SlippageParam.total_slippage_rate(cap)
    return commission, tax, slippage


def calc_transaction_cost(
    market: Market,
    cap: StockCap,
    position: pd.Series,
    position_prev: pd.Series,
) -> pd.Series:
    """단일 자산 포지션 변화에 따른 거래 비용을 계산한다.

    포지션 변화를 기존 포지션 청산과 신규 포지션 진입으로 분리한다.
    position이 1→-1 또는 -1→1로 직접 교차할 때도 청산과 진입 비용을
    각각 반영한다.

    Notes
    -----
    기존 grid_search 평가 로직과 동일하게 포지션 변화일에 비용을 부과한다.
    포지션 크기 차이에 비례한 리밸런싱 비용은 calc_rebalance_cost()를 사용한다.
    """
    commission, tax, slippage = _cost_rates(market, cap)

    position = position.astype(float)
    position_prev = position_prev.reindex(position.index).fillna(0.0).astype(float)
    trade = position != position_prev

    close_long = trade & (position_prev > 0)
    close_short = trade & (position_prev < 0)
    open_long = trade & (position > 0)
    open_short = trade & (position < 0)

    return (
        close_long * (commission + slippage + tax) +
        close_short * (commission + slippage) +
        open_long * (commission + slippage) +
        open_short * (commission + slippage)
    )


def calc_rebalance_cost(
    current_weights: pd.Series,
    target_weights: pd.Series,
    market: Market = Market.KOSPI,
    cap: StockCap = StockCap.LARGE,
) -> float:
    """포트폴리오 목표 비중 변경에 따른 비용 비율을 계산한다.

    롱 온리 주식/ETF 포트폴리오의 리밸런싱 비용 계산용이다.
    매수분에는 수수료+슬리피지, 매도분에는 수수료+슬리피지+거래세를 적용한다.

    Returns
    -------
    float
        포트폴리오 총자산 대비 거래 비용 비율.
    """
    return float(
        calc_rebalance_cost_by_asset(
            current_weights=current_weights,
            target_weights=target_weights,
            market=market,
            cap=cap,
        ).sum()
    )


def calc_rebalance_cost_by_asset(
    current_weights: pd.Series,
    target_weights: pd.Series,
    market: Market = Market.KOSPI,
    cap: StockCap = StockCap.LARGE,
) -> pd.Series:
    """포트폴리오 목표 비중 변경에 따른 비용 비율을 종목별로 계산한다.

    Returns
    -------
    pd.Series
        인덱스는 종목/자산 코드, 값은 포트폴리오 총자산 대비 거래 비용 비율.
    """
    commission, tax, slippage = _cost_rates(market, cap)

    tickers = current_weights.index.union(target_weights.index)
    current = current_weights.reindex(tickers).fillna(0.0).clip(lower=0.0).astype(float)
    target = target_weights.reindex(tickers).fillna(0.0).clip(lower=0.0).astype(float)

    delta = target - current
    buy_turnover = delta.clip(lower=0.0)
    sell_turnover = -delta.clip(upper=0.0)

    return (
        buy_turnover * (commission + slippage) +
        sell_turnover * (commission + slippage + tax)
    )
