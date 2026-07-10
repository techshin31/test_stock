"""포트폴리오 목표 비중 배분."""
from __future__ import annotations

import numpy as np
import pandas as pd

from core.constant.types import UniverseStatus, Tickers
from core.strategy.base import AbstractStrategy, DefensiveAssetType
from .universe import PortfolioUniverse


def _align_current_weights(
    signals: pd.DataFrame,
    current_weights: pd.DataFrame | pd.Series | None,
) -> pd.DataFrame:
    """현재 비중을 signals와 같은 shape의 DataFrame으로 정렬한다."""
    if current_weights is None:
        return pd.DataFrame(0.0, index=signals.index, columns=signals.columns)

    if isinstance(current_weights, pd.Series):
        row = current_weights.reindex(signals.columns).fillna(0.0)
        return pd.DataFrame(
            np.tile(row.to_numpy(dtype=float), (len(signals.index), 1)),
            index=signals.index,
            columns=signals.columns,
        )

    return current_weights.reindex(index=signals.index, columns=signals.columns).ffill().fillna(0.0)


def _apply_universe_filter(
    signals: pd.DataFrame,
    universe: PortfolioUniverse,
    current: pd.DataFrame,
) -> pd.DataFrame:
    """REMOVED 제외, SELL_ONLY 신규/추가 매수 차단."""
    filtered = signals.copy()

    for ticker in filtered.columns:
        status = universe.get_status(ticker)

        if status == UniverseStatus.REMOVED:
            filtered[ticker] = 0.0
            continue

        if status == UniverseStatus.SELL_ONLY:
            is_extra_buy = filtered[ticker].notna() & (filtered[ticker] > current[ticker])
            filtered.loc[is_extra_buy, ticker] = np.nan

    return filtered


def _allocate_stock_targets(
    signals: pd.DataFrame,
    momentum: pd.DataFrame,
    capacity: pd.Series,
) -> pd.DataFrame:
    """종목별 원 신호를 포트폴리오 목표 비중으로 변환한다."""
    raw = signals.clip(lower=0.0)
    allocated = pd.DataFrame(np.nan, index=signals.index, columns=signals.columns, dtype=float)

    for dt in signals.index:
        row = raw.loc[dt].dropna()
        if row.empty:
            continue

        available = float(capacity.loc[dt])
        total = float(row.sum())
        if total <= available:
            allocated.loc[dt, row.index] = row
            continue

        mom = momentum.reindex(columns=row.index).loc[dt].fillna(0.0).clip(lower=0.0)
        score = row * mom

        if float(score.sum()) <= 0.0:
            score = row

        allocated.loc[dt, row.index] = (score / float(score.sum())) * max(available, 0.0)

    return allocated


def allocate_portfolio(
    signals: pd.DataFrame,
    momentum: pd.DataFrame,
    universe: PortfolioUniverse,
    strategy: AbstractStrategy,
    regime_df: pd.DataFrame,
    current_weights: pd.DataFrame | pd.Series | None = None,
    defensive_ticker: str = Tickers.BOND_ETF.name,
    min_defensive_weight: float = 0.01,
) -> pd.DataFrame:
    """여러 종목 신호를 최종 포트폴리오 목표 비중으로 변환한다.

    Parameters
    ----------
    signals : pd.DataFrame
        종목별 목표 비중 신호. NaN은 주문 없음, 0.0은 청산, 양수는 목표 비중이다.
    momentum : pd.DataFrame
        종목별 모멘텀 점수. 신호 합계가 100%를 넘을 때 정규화에 사용한다.
    universe : PortfolioUniverse
        종목별 ACTIVE/SELL_ONLY/REMOVED 상태.
    strategy : AbstractStrategy
        남는 자금의 방어자산 배정 가능 신호를 제공한다.
    regime_df : pd.DataFrame
        strategy.make_defensive_signals()에 전달할 국면 DataFrame.
    current_weights : pd.DataFrame | pd.Series | None
        현재 보유 비중. SELL_ONLY 추가 매수 차단과 잔여 현금 계산에 사용한다.
    defensive_ticker : str
        남는 자금을 배정할 방어자산 티커.
    min_defensive_weight : float
        방어자산 목표 비중이 이 값보다 작으면 NaN으로 두어 소액 주문을 피한다.

    Returns
    -------
    pd.DataFrame
        종목과 방어자산을 포함한 날짜별 목표 비중.
    """
    signals = signals.astype(float)
    momentum = momentum.reindex(index=signals.index, columns=signals.columns).fillna(0.0)
    current = _align_current_weights(signals, current_weights)

    filtered = _apply_universe_filter(signals, universe, current)
    maintained_stock = current.where(filtered.isna(), 0.0).clip(lower=0.0)
    capacity = (1.0 - maintained_stock.sum(axis=1)).clip(lower=0.0, upper=1.0)
    stock_targets = _allocate_stock_targets(filtered, momentum, capacity)

    effective_stock = stock_targets.where(stock_targets.notna(), current)
    invested = effective_stock.clip(lower=0.0).sum(axis=1).clip(lower=0.0, upper=1.0)
    residual_cash = (1.0 - invested).clip(lower=0.0)

    defensive_signal = strategy.make_defensive_signals(regime_df).reindex(signals.index).fillna(0.0)
    defensive_weight = (residual_cash * defensive_signal).clip(lower=0.0, upper=1.0)

    if strategy.DEFENSIVE_ASSET_TYPE == DefensiveAssetType.INVERSE_ETF:
        inverse_weight = signals.clip(upper=0.0).abs().max(axis=1).fillna(0.0).clip(upper=1.0)
        defensive_weight = pd.concat([defensive_weight, inverse_weight], axis=1).max(axis=1)

    defensive_weight = defensive_weight.where(defensive_weight >= min_defensive_weight, np.nan)

    result = stock_targets.copy()
    result[defensive_ticker] = defensive_weight
    return result
