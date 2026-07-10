"""Backtest execution engine."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import pandas as pd

from core.portfolio.decision import decide_target_weights_for_day
from core.portfolio.momentum import calc_universe_momentum
from core.portfolio.rotation import (
    apply_rotation_plan,
    mark_removed_after_exit,
)
from core.portfolio.signals import make_portfolio_signals
from core.portfolio.universe import PortfolioUniverse, UniverseEntry
from core.risk.cost import calc_rebalance_cost_by_asset
from core.signal.market_regime import calc_regime
from core.strategy.base import DefensiveAssetType
from core.optimization.walk_forward import WalkForwardWindow, run_walk_forward
from core.constant.types import Tickers

from .config import BacktestConfig
from .result import BacktestResult
from .enum import InsufficientHistoryPolicy


def _to_timestamp(value: date | pd.Timestamp) -> pd.Timestamp:
    # date와 Timestamp 입력을 pandas 슬라이싱에 쓰기 좋은 단일 타입으로 맞춘다.
    return pd.Timestamp(value)


def _slice_frame(df: pd.DataFrame, start: date, end: date) -> pd.DataFrame:
    # 원본 데이터 순서가 뒤섞여 있어도 날짜순으로 정렬한 뒤 백테스트 기간만 남긴다.
    return df.sort_index().loc[_to_timestamp(start):_to_timestamp(end)]


def _validate_no_lookahead(
    ohlcv_store: dict[str, pd.DataFrame],
    config: "BacktestConfig",
) -> dict[str, str]:
    """Look-ahead bias 가능성이 있는 데이터 조건을 사전 점검한다.

    체크 항목:
      1. 백테스트 종료일 이후 행이 ohlcv_store에 포함됐는지 (_slice_frame 전)
      2. OHLCV 인덱스가 단조 증가(sorted)인지
      3. 인덱스에 중복이 있는지

    Returns
    -------
    dict[str, str]
        {ticker: 경고메시지}. 이상 없으면 빈 dict.
    """
    found: dict[str, str] = {}
    end_ts = _to_timestamp(config.end_date)
    for ticker, df in ohlcv_store.items():
        if df.empty:
            continue
        if not df.index.is_monotonic_increasing:
            found[ticker] = "OHLCV index is not monotonically increasing"
        elif df.index.duplicated().any():
            found[ticker] = "OHLCV index has duplicate timestamps"
        future_rows = int((df.index > end_ts).sum())
        if future_rows > 0:
            found.setdefault(
                ticker,
                f"{future_rows} rows beyond end_date {config.end_date} — "
                "verify _slice_frame is applied before indicator calculation",
            )
    return found


def _all_config_tickers(config: BacktestConfig, ohlcv_store: dict[str, pd.DataFrame]) -> list[str]:
    # 최초 편입 종목은 백테스트 시작 시점부터 매수/보유를 검토할 기본 대상이다.
    tickers = list(config.initial_universe)

    # 종목 교체 계획에 등장하는 편출/편입 종목도 미리 OHLCV를 준비해야 한다.
    # 편출 종목은 청산 전까지 가격이 필요하고, 편입 종목은 교체일 이후 판단에 필요하다.
    for plan in config.rotation_plans:
        tickers.extend(plan.exits)
        tickers.extend(plan.entries)

    # 사용자가 ohlcv_store에 추가로 넣어둔 종목도 계산 후보에 포함한다.
    # 실제 유니버스 편입 여부는 initial_universe와 rotation_plans가 결정한다.
    tickers.extend(ohlcv_store.keys())

    # dict.fromkeys()로 입력 순서를 유지하면서 중복 티커를 제거한다.
    return list(dict.fromkeys(tickers))


def _params_for_window(window: WalkForwardWindow) -> dict:
    # 최적화 결과가 없으면 is_score=0.0으로 두어 calc_regime이 기본 MA+시장지수 모드로 동작하게 한다.
    if not window.get("use_adx_mode") or not window.get("best_params"):
        return {"is_score": 0.0}

    # best_params에는 ADX 임계값 등이 들어오며, IS 점수는 별도 필드에서 합쳐 넘긴다.
    params = dict(window["best_params"] or {})
    params["is_score"] = float(window.get("is_score", 0.0))
    return params


def _calc_regime_by_windows(
    ohlcv: pd.DataFrame,
    market_index: pd.Series,
    windows: list[WalkForwardWindow],
) -> pd.DataFrame:
    # 먼저 기본 파라미터로 전체 기간의 국면을 계산한다.
    full = calc_regime(
        close=ohlcv["close"],
        high=ohlcv["high"],
        low=ohlcv["low"],
        market_index=market_index,
    )

    # 워크포워드 윈도우별 OOS 구간만 해당 윈도우의 최적 파라미터로 다시 계산해 덮어쓴다.
    for window in windows:
        oos = ohlcv.loc[window["oos_start"]:window["oos_end"]]
        if oos.empty:
            continue
        params = _params_for_window(window)
        param_regime = calc_regime(
            close=ohlcv["close"],
            high=ohlcv["high"],
            low=ohlcv["low"],
            market_index=market_index,
            **params,
        )
        full.loc[oos.index] = param_regime.loc[oos.index]
    return full


def _benchmark_asset_returns(config: BacktestConfig, calendar: pd.DatetimeIndex) -> pd.DataFrame:
    # 시장지수를 백테스트 캘린더와 같은 인덱스로 맞춘 뒤 일별 수익률로 변환한다.
    market_returns = config.market_index.reindex(calendar).ffill().pct_change().fillna(0.0)
    result = pd.DataFrame(index=calendar)

    # 방어자산 수익률이 따로 있으면 우선 사용하고, 없으면 기존 벤치마크 수익률을 대체 입력으로 사용한다.
    defensive_returns = config.defensive_asset_returns
    if defensive_returns is None:
        defensive_returns = config.benchmark_returns

    # 채권형 방어자산 컬럼은 일별 수익률 입력을 그대로 캘린더에 맞춘다.
    if defensive_returns is not None:
        result[Tickers.BOND_ETF.name] = defensive_returns.reindex(calendar).fillna(0.0)
    else:
        result[Tickers.BOND_ETF.name] = 0.0

    # 인버스 방어자산은 단순 모델로 시장지수 일간 수익률의 반대 방향을 사용한다.
    result[Tickers.INVERSE_ETF.name] = -market_returns
    return result


def _defensive_ticker(config: BacktestConfig) -> str:
    # 전략 설정에 따라 잔여 비중을 배정할 방어자산 컬럼명을 고른다.
    return (
        Tickers.INVERSE_ETF.name
        if config.strategy.DEFENSIVE_ASSET_TYPE == DefensiveAssetType.INVERSE_ETF
        else Tickers.BOND_ETF.name
    )


def _snapshot(universe: PortfolioUniverse, as_of: date) -> tuple[date, list[str]]:
    # 스냅샷은 신규 매수 가능한 ACTIVE 종목만 남긴다. SELL_ONLY 종목은 청산 관리 대상이라 제외한다.
    return as_of, universe.tradable_tickers(include_sell_only=False)


def _filter_by_history(
    sliced: dict[str, pd.DataFrame],
    min_history_days: int,
    policy: str,
) -> tuple[dict[str, pd.DataFrame], dict[str, str]]:
    # 최소 이력 미달 종목을 어떻게 처리할지 설정값을 먼저 검증한다.
    if policy not in [p.value for p in InsufficientHistoryPolicy]:
        raise ValueError(
            "insufficient_history_policy must be one of 'exclude', 'raise', or 'allow'"
        )

    # allow 정책이거나 최소 이력 조건이 꺼져 있으면 원본을 그대로 사용한다.
    if policy == InsufficientHistoryPolicy.ALLOW.value or min_history_days <= 0:
        return sliced, {}

    # 기간 내 행 수가 부족한 종목과 제외 사유를 기록한다.
    excluded = {
        ticker: f"history rows {len(df)} < min_history_days {min_history_days}"
        for ticker, df in sliced.items()
        if len(df) < min_history_days
    }

    # raise 정책에서는 제외하지 않고 즉시 사용자에게 부족한 종목을 알려준다.
    if excluded and policy == InsufficientHistoryPolicy.RAISE.value:
        details = ", ".join(f"{ticker} ({reason})" for ticker, reason in excluded.items())
        raise ValueError(f"insufficient OHLCV history: {details}")

    # 기본 exclude 정책에서는 부족한 종목을 제거하고, 결과 객체에 사유를 남긴다.
    return (
        {ticker: df for ticker, df in sliced.items() if ticker not in excluded},
        excluded,
    )


def _optional_metadata(
    signal_metadata: dict[str, pd.DataFrame],
    ticker: str,
    today: pd.Timestamp,
) -> dict[str, object]:
    # 해당 종목/날짜에 신호 메타데이터가 없으면 빈 dict로 통일한다.
    if ticker not in signal_metadata or today not in signal_metadata[ticker].index:
        return {}

    # 중복 인덱스로 여러 행이 잡히면 가장 마지막 행을 그날의 메타데이터로 사용한다.
    row = signal_metadata[ticker].loc[today]
    if isinstance(row, pd.DataFrame):
        row = row.iloc[-1]

    # pandas NaN은 후속 직렬화/표시에서 다루기 쉽도록 None으로 바꾼다.
    return {
        key: (None if pd.isna(value) else value)
        for key, value in row.to_dict().items()
    }


def _trade_reason(
    ticker: str,
    delta_weight: float,
    metadata: dict[str, object],
    forced_targets: dict[str, float],
) -> str:
    # 전략 신호가 명시한 사유가 있으면 가장 우선해서 거래 사유로 사용한다.
    reason = metadata.get("signal_reason")
    if reason:
        return str(reason)

    # 강제청산 대상에서 비중이 줄어드는 거래는 별도 사유로 표시한다.
    if ticker in forced_targets and delta_weight < 0.0:
        return "FORCED_EXIT"

    # 방어자산 매매는 일반 리밸런싱과 구분한다.
    if ticker in {Tickers.BOND_ETF.name, Tickers.INVERSE_ETF.name}:
        return "DEFENSIVE_ALLOCATION"

    # 나머지는 목표 비중 변화 방향에 따라 일반 매수/매도로 분류한다.
    return "REBALANCE_BUY" if delta_weight > 0.0 else "REBALANCE_SELL"


def _trade_ledger_rows(
    today: pd.Timestamp,
    current_weights: pd.Series,
    target_weights: pd.Series,
    cost_by_asset: pd.Series,
    signal_metadata: dict[str, pd.DataFrame],
    forced_targets: dict[str, float],
) -> list[dict[str, object]]:
    # 현재/목표/비용 중 하나라도 등장한 티커를 모두 거래원장 후보로 맞춘다.
    tickers = current_weights.index.union(target_weights.index).union(cost_by_asset.index)
    current = current_weights.reindex(tickers).fillna(0.0).clip(lower=0.0).astype(float)
    target = target_weights.reindex(tickers).fillna(0.0).clip(lower=0.0).astype(float)

    # 목표 비중과 현재 비중이 실질적으로 달라진 종목만 거래로 기록한다.
    delta = target - current
    traded = delta[delta.abs() > 1e-12]

    rows: list[dict[str, object]] = []
    for ticker, delta_weight in traded.items():
        metadata = _optional_metadata(signal_metadata, str(ticker), today)
        # 금액 컬럼은 자산 곡선이 확정된 뒤 run_backtest() 후처리에서 채운다.
        rows.append({
            "date": today,
            "ticker": str(ticker),
            "side": "BUY" if float(delta_weight) > 0.0 else "SELL",
            "prev_weight": float(current.loc[ticker]),
            "target_weight": float(target.loc[ticker]),
            "delta_weight": float(delta_weight),
            "trade_turnover": abs(float(delta_weight)),
            "cost_ratio": float(cost_by_asset.reindex(tickers).fillna(0.0).loc[ticker]),
            "cost_amount": 0.0,
            "trade_value": 0.0,
            "trade_reason": _trade_reason(str(ticker), float(delta_weight), metadata, forced_targets),
            "signal_reason": metadata.get("signal_reason"),
            "exit_reason": metadata.get("exit_reason"),
            "secondary_exit_reason": metadata.get("secondary_exit_reason"),
            "regime": metadata.get("regime"),
            "price": metadata.get("price"),
        })
    return rows


@dataclass
class _BacktestState:
    sliced: dict[str, pd.DataFrame] # 백테스트 기간으로 자른 OHLCV 데이터 (티커 -> DataFrame)
    excluded_tickers: dict[str, str] # 최소 이력 조건 등으로 제외된 티커와 사유 (티커 -> 사유)
    calendar: pd.DatetimeIndex # 백테스트가 실제로 순회할 날짜 인덱스
    market_index: pd.Series # calendar에 맞춘 시장지수 시리즈 (국면 판별용)
    close: pd.DataFrame # calendar에 맞춘 종가 테이블 (날짜 x 티커)
    asset_returns: pd.DataFrame # 주식과 방어자산을 포함한 일별 수익률 테이블 (날짜 x 티커)
    wf_windows: dict[str, list[WalkForwardWindow]] # 워크포워드 결과 윈도우 (티커 -> WalkForwardWindow 리스트)
    regime_dict: dict[str, pd.DataFrame] # 종목별 국면 판별 결과 (티커 -> 국면 DataFrame)
    momentum_dict: dict[str, pd.DataFrame] # 종목별 국면 반영 모멘텀 점수 (티커 -> 모멘텀 DataFrame)
    signals: pd.DataFrame # 전략이 만든 원 포트폴리오 신호 테이블 (날짜 x 티커)
    signal_metadata: dict[str, pd.DataFrame] # 신호 관련 추가 메타데이터 (티커 -> 날짜 x 메타컬럼 DataFrame)
    universe: PortfolioUniverse # ACTIVE/SELL_ONLY/REMOVED 상태를 가진 포트폴리오 유니버스
    snapshots: list[tuple[date, list[str]]] # 유니버스 스냅샷 리스트 (날짜, ACTIVE 티커 리스트)
    rotation_plans: list[object] # review_date 기준으로 정렬된 종목 교체 계획 리스트
    applied_rotations: set[int] # 이미 적용된 종목 교체 계획의 인덱스 집합
    defensive_ticker: str # 방어자산으로 사용하는 티커 (예: 채권형 ETF 또는 인버스 ETF)
    weights: pd.DataFrame # 일별 최종 보유 비중 테이블 (날짜 x 티커)
    costs: pd.Series # 일별 총 거래비용률 시리즈 (날짜 -> 비용률)
    daily_returns: pd.Series # 거래비용을 차감한 일별 포트폴리오 수익률
    gross_return_contributions: pd.DataFrame # 비용 차감 전 자산별 수익률 기여도 (날짜 x 티커)
    cost_contributions: pd.DataFrame # 자산별 거래비용률 기여도 (날짜 x 티커)
    trade_rows: list[dict[str, object]] # 거래원장 원천 행 리스트. 금액 컬럼은 자산 곡선 계산 후 채운다.
    current_weights: pd.Series # 루프 현재 시점에 보유 중인 비중 시리즈 (티커 -> 보유 비중)


def __preprocess_backtest(
    config: BacktestConfig,
    ohlcv_store: dict[str, pd.DataFrame],
) -> _BacktestState:
    ############################################
    # 1. 백테스트 대상 종목 확정
    ############################################
    # 설정/교체계획/입력 데이터에 등장하는 후보 중 실제 OHLCV가 있는 종목만 남긴다.
    tickers = [
        ticker for ticker in _all_config_tickers(config, ohlcv_store)
        if ticker in ohlcv_store
    ]
    if not tickers:
        raise ValueError("ohlcv_store does not contain any configured tickers")
    
    ############################################
    # 2. OHLCV 기간 자르기
    ############################################
    # ohlcv_store에서 백테스트 기간에 해당하는 구간만 남긴다. 이후 단계에서 최소 기간 조건을 통과한 종목만 최종 사용된다.
    sliced = {ticker: _slice_frame(ohlcv_store[ticker], config.start_date, config.end_date) for ticker in tickers}
    # 기간을 자른 후 빈 데이터프레임이 된 종목은 백테스트에서 제외한다.
    sliced = {ticker: df for ticker, df in sliced.items() if not df.empty}
    # 최소 이력 조건을 적용하고, 제외된 종목은 결과 객체에 남길 수 있도록 사유를 보관한다.
    sliced, excluded_tickers = _filter_by_history(
        sliced,
        config.min_history_days,
        config.insufficient_history_policy,
    )
    # 기간 필터와 최소 이력 필터를 통과한 종목이 없으면 백테스트를 진행할 수 없다.
    if not sliced:
        raise ValueError("no OHLCV rows remain inside the configured backtest period")
    
    ############################################
    # 3. 백테스트 캘린더/수익률 테이블 생성   
    ############################################
    # 백테스트 캘린더는 모든 종목의 OHLCV 인덱스의 합집합으로 만든다. 
    calendar = pd.DatetimeIndex(sorted(set().union(*(df.index for df in sliced.values()))))
    # 시장지수를 calendar와 같은 순서/구성의 인덱스로 재배치하고, 비거래일 결측은 직전 값으로 채운다.
    market_index = config.market_index.reindex(calendar).ffill()

    # 백테스트 대상 종목들의 종가(close) 데이터를 캘린더에 맞춰서 하나의 데이터프레임으로 만든다. 결측은 직전 값으로 채운다.
    close = pd.DataFrame({ticker: df["close"].reindex(calendar).ffill() for ticker, df in sliced.items()})
    # 종가 데이터로 주식 일별 수익률을 만들고, 방어자산 후보 수익률 컬럼을 함께 붙인다.
    stock_returns = close.pct_change().fillna(0.0)
    asset_returns = pd.concat([
        # 종목별 일별 수익률.
        stock_returns,
        # 채권형/인버스 방어자산의 일별 수익률.
        _benchmark_asset_returns(config, calendar)
    ], axis=1)

    ############################################
    # 4. 전략 판단에 필요한 사전 계산
    ############################################
    # 워크포워드 윈도우 계산, 시장 국면 계산, 모멘텀 계산, 포트폴리오 신호 생성 등 전략 판단에 필요한 사전 계산을 수행한다.
    wf_windows: dict[str, list[WalkForwardWindow]] = {
        ticker: run_walk_forward(
            # 해당 종목의 백테스트 기간 OHLCV로 IS/OOS 윈도우를 만든다.
            ohlcv=ohlcv,
            # 워크포워드는 자체 기간으로 시장지수를 슬라이스하므로 원본 시장지수를 넘긴다.
            market_index=config.market_index,
            # 전략의 포지션 맵과 거래비용 조건을 최적화 평가에 사용한다.
            position_map=config.strategy.get_position_map(),
            cap=config.cap,
            market=config.market,
        )
        for ticker, ohlcv in sliced.items()
    }
    # 워크포워드 결과를 반영해 각 종목별 국면을 계산한 뒤, calendar에 맞춰 빈 날짜는 직전 국면으로 채운다.
    regime_dict: dict[str, pd.DataFrame] = {
        ticker: _calc_regime_by_windows(df, market_index, wf_windows[ticker]).reindex(calendar).ffill()
        for ticker, df in sliced.items()
    }
    # 종가와 종목별 국면을 이용해 배분 우선순위로 쓸 모멘텀 점수를 계산한다.
    momentum_dict = calc_universe_momentum(
        close=close,
        regime_dict=regime_dict,
        tickers=list(sliced.keys()),
    )
    # 전략을 종목별로 실행해 calendar 기준 신호 테이블과 메타데이터를 만든다.
    portfolio_signals = make_portfolio_signals(
        strategy=config.strategy,
        ohlcv_store=sliced,
        regime_dict=regime_dict,
        calendar=calendar,
    )
    # 날짜 x 티커 형태의 원 신호 테이블.
    signals = portfolio_signals.signals
    # 거래 사유/국면/가격 등 원장에 붙일 수 있는 종목별 메타데이터.
    signal_metadata = portfolio_signals.metadata

    ############################################
    # 5. 백테스트 상태 초기화
    ############################################
    # 백테스트 시작 시점에 유니버스에 편입될 종목을 확정한다. config.initial_universe에 있더라도 sliced에 없으면 편입되지 못한다.
    universe = PortfolioUniverse([
        UniverseEntry(ticker=ticker, added_at=config.start_date)
        for ticker in config.initial_universe
        if ticker in sliced
    ])
    # 백테스트 시작 시점의 유니버스 스냅샷을 만든다. 이후 종목 교체 계획이 적용될 때마다 스냅샷이 추가된다.
    snapshots = [_snapshot(universe, config.start_date)]
    # 종목 교체 계획을 검토 날짜 기준으로 정렬한다. 백테스트 루프에서 오늘 날짜에 도래한 계획이 있는지 빠르게 확인할 수 있다.
    rotation_plans = sorted(config.rotation_plans, key=lambda plan: plan.review_date)
    # 백테스트 루프에서 종목 교체 계획이 오늘 날짜에 도래했는지 확인할 때, 이미 적용한 계획인지도 함께 체크한다. applied_rotations는 적용한 계획의 인덱스 집합이다.
    applied_rotations: set[int] = set()

    # 전략 설정에 맞는 방어자산 티커를 정하고, 일별 결과를 담을 빈 회계 테이블을 준비한다.
    defensive_ticker = _defensive_ticker(config)
    # weights는 루프 중 매일의 목표 비중을 채워나갈 테이블이다. 초기값은 모든 자산이 0 비중인 상태로 시작한다.
    weights = pd.DataFrame(index=calendar, columns=asset_returns.columns, dtype=float)
    # costs, daily_returns, gross_return_contributions, cost_contributions은 루프 중 매일의 거래비용률과 수익률 기여도를 채워나갈 테이블이다. 초기값은 모두 0으로 시작한다.
    costs = pd.Series(0.0, index=calendar, dtype=float) # 일별 총 거래비용률 시리즈
    daily_returns = pd.Series(0.0, index=calendar, dtype=float) # 거래비용을 차감한 일별 포트폴리오 수익률 시리즈
    gross_return_contributions = pd.DataFrame(0.0, index=calendar, columns=asset_returns.columns, dtype=float) # 비용 차감 전 자산별 수익률 기여도 테이블
    cost_contributions = pd.DataFrame(0.0, index=calendar, columns=asset_returns.columns, dtype=float) # 자산별 거래비용률 기여도 테이블
    # 거래원장은 루프 중 비중 변화만 쌓고, 실제 금액은 자산 곡선 계산 후 채운다.
    trade_rows: list[dict[str, object]] = []
    # 첫날 루프 시작 전에는 모든 자산의 보유 비중이 0이라고 본다.
    current_weights = pd.Series(0.0, index=asset_returns.columns, dtype=float)
    
    return _BacktestState(
        sliced=sliced, # 백테스트 기간으로 자른 OHLCV 데이터 (티커 -> DataFrame)
        excluded_tickers=excluded_tickers, # 최소 이력 조건 등으로 제외된 티커와 사유 (티커 -> 사유)
        calendar=calendar, # 백테스트가 실제로 순회할 날짜 인덱스
        market_index=market_index, # calendar에 맞춘 시장지수 시리즈 (국면 판별용)
        close=close, # calendar에 맞춘 종가 테이블 (날짜 x 티커)
        asset_returns=asset_returns, # 주식과 방어자산을 포함한 일별 수익률 테이블 (날짜 x 티커)
        wf_windows=wf_windows, # 워크포워드 결과 윈도우 (티커 -> WalkForwardWindow 리스트)
        regime_dict=regime_dict, # 종목별 국면 판별 결과 (티커 -> 국면 DataFrame)
        momentum_dict=momentum_dict, # 종목별 국면 반영 모멘텀 점수 (티커 -> 모멘텀 DataFrame)
        signals=signals,
        signal_metadata=signal_metadata,
        universe=universe,
        snapshots=snapshots,
        rotation_plans=rotation_plans,
        applied_rotations=applied_rotations,
        defensive_ticker=defensive_ticker,
        weights=weights,
        costs=costs,
        daily_returns=daily_returns,
        gross_return_contributions=gross_return_contributions,
        cost_contributions=cost_contributions,
        trade_rows=trade_rows,
        current_weights=current_weights,
    )


def __backtest_loop(
    config: BacktestConfig,
    state: _BacktestState,
) -> _BacktestState:
    for idx, today in enumerate(state.calendar):
        # rotation_plan은 date 타입 기준이라 Timestamp를 date로 변환해 비교한다.
        today_date = today.date()
        # 오늘 이후 거래일만 넘겨 강제청산 기한을 실제 백테스트 캘린더 기준으로 계산한다.
        trading_calendar = state.calendar[state.calendar >= today]

        ############################################
        # 1. 오늘 날짜에 도래한 종목 교체 계획 적용
        ############################################
        for plan_idx, plan in enumerate(state.rotation_plans):
            # 이미 적용했거나 review_date가 아직 오지 않은 계획은 건너뛴다.
            if plan_idx in state.applied_rotations or plan.review_date > today_date:
                continue
            # 편출 종목은 SELL_ONLY, 편입 종목은 ACTIVE로 바꾸고 강제청산일을 설정한다.
            apply_rotation_plan(state.universe, plan, trading_calendar=trading_calendar)
            state.applied_rotations.add(plan_idx)
            state.snapshots.append(_snapshot(state.universe, today_date))

        ############################################
        # 2. 오늘의 목표 비중 결정
        ############################################
        # 유니버스 상태, 원 신호, 모멘텀, 국면을 반영해 하루치 최종 목표 비중을 받는다.
        decision = decide_target_weights_for_day(
            as_of=today,
            strategy=config.strategy,
            universe=state.universe,
            current_weights=state.current_weights,
            signals=state.signals,
            momentum_dict=state.momentum_dict,
            regime_dict=state.regime_dict,
            defensive_ticker=state.defensive_ticker,
        )
        target_row = decision.target_weights
        forced = decision.forced_targets

        ############################################
        # 3. target weight 완성
        ############################################
        # NaN 신호는 "주문 없음"으로 보고 기존 비중을 유지한다.
        target = state.current_weights.copy()
        # 명시된 목표 비중만 기존 비중 위에 덮어쓴다.
        for col, value in target_row.dropna().items():
            if col not in target.index:
                target.loc[col] = 0.0
            target.loc[col] = float(value)

        # 수익률 테이블에 있는 자산과 새로 등장한 자산을 모두 포함하도록 인덱스를 맞춘다.
        target = target.reindex(state.asset_returns.columns.union(target.index)).fillna(0.0)
        # 현재 엔진은 롱 포지션만 회계 처리하므로 음수 비중은 0으로 제한한다.
        target = target.clip(lower=0.0)
        # 목표 비중 합계가 100%를 넘으면 비례 축소해 레버리지를 방지한다.
        if float(target.sum()) > 1.0:
            target = target / float(target.sum())

        ############################################
        # 4. 오늘 수익률과 거래비용 계산
        ############################################
        # 첫 거래일에는 전일 보유분의 수익률이 없으므로 수익률/비용 회계를 건너뛴다.
        if idx > 0:
            # 오늘 진입 전 보유 비중에 오늘 자산별 수익률을 곱해 비용 차감 전 기여도를 계산한다.
            gross_by_asset = (
                state.current_weights.reindex(state.asset_returns.columns).fillna(0.0)
                * state.asset_returns.loc[today]
            )
            # 현재 비중에서 목표 비중으로 리밸런싱할 때 발생하는 종목별 거래비용률을 계산한다.
            raw_cost_by_asset = calc_rebalance_cost_by_asset(
                current_weights=state.current_weights,
                target_weights=target,
                market=config.market,
                cap=config.cap,
            )
            # 회계 테이블 컬럼에 맞춰 비용 시리즈를 정렬한다.
            cost_by_asset = raw_cost_by_asset.reindex(state.asset_returns.columns).fillna(0.0)
            state.gross_return_contributions.loc[today] = gross_by_asset
            state.cost_contributions.loc[today] = cost_by_asset
            state.costs.loc[today] = float(cost_by_asset.sum())
            state.daily_returns.loc[today] = float(gross_by_asset.sum() - cost_by_asset.sum())
            # 비중이 바뀐 종목을 거래원장 행으로 기록한다. 금액은 run_backtest() 후처리에서 채운다.
            state.trade_rows.extend(_trade_ledger_rows(
                today=today,
                current_weights=state.current_weights,
                target_weights=target,
                cost_by_asset=raw_cost_by_asset,
                signal_metadata=state.signal_metadata,
                forced_targets=forced,
            ))

        ############################################
        # 5. 보유 비중 갱신
        ############################################
        # 오늘 리밸런싱 이후의 목표 비중을 다음 날짜의 현재 보유 비중으로 넘긴다.
        state.current_weights = target
        state.weights.loc[today, state.current_weights.index] = state.current_weights
        # SELL_ONLY 종목이 완전히 청산되면 REMOVED 상태로 전환한다.
        mark_removed_after_exit(state.universe, state.current_weights, today)

    return state


def run_backtest(
    config: BacktestConfig,
    ohlcv_store: dict[str, pd.DataFrame],
) -> BacktestResult:
    """포트폴리오 백테스트를 처음부터 끝까지 실행한다."""
    # 백테스트 기간 외 데이터 포함 여부, 인덱스 정렬/중복 등 look-ahead bias 조건을 사전 점검한다.
    lookahead_warnings = _validate_no_lookahead(ohlcv_store, config)
    # 백테스트 실행에 필요한 모든 사전 계산과 초기화 작업을 수행한다.
    state = __preprocess_backtest(config, ohlcv_store)
    # 백테스트 캘린더를 순회하면서 매일의 포트폴리오 결정과 평가 작업을 수행한다.
    state = __backtest_loop(config, state)

    # 일별 수익률 회계를 누적 자산 곡선과 자산별 평가금액으로 변환한다.
    weights = state.weights.fillna(0.0)
    # daily_returns는 비율 수익률이므로 누적 곱에 초기자본을 곱해 포트폴리오 가치로 바꾼다.
    equity_curve = (1.0 + state.daily_returns).cumprod() * float(config.initial_capital)
    # 일별 포트폴리오 가치에 각 자산 비중을 곱해 자산별 평가금액을 계산한다.
    values = weights.multiply(equity_curve, axis=0)
    # 순 기여도는 비용 차감 전 수익률 기여도에서 거래비용률 기여도를 뺀 값이다.
    net_return_contributions = state.gross_return_contributions - state.cost_contributions

    # 포트폴리오 가치가 확정된 뒤, 전일 자산 기준으로 거래 금액과 비용 금액을 채운다.
    trade_columns = [
        "date",
        "ticker",
        "side",
        "prev_weight",
        "target_weight",
        "delta_weight",
        "trade_turnover",
        "cost_ratio",
        "cost_amount",
        "trade_value",
        "trade_reason",
        "signal_reason",
        "exit_reason",
        "secondary_exit_reason",
        "regime",
        "price",
    ]
    trade_ledger = pd.DataFrame(state.trade_rows, columns=trade_columns)
    if not trade_ledger.empty:
        # 거래 금액은 리밸런싱 직전 자산 기준이므로 전일 equity_curve를 사용한다.
        value_before = equity_curve.shift(1).fillna(float(config.initial_capital))
        mapped_value = trade_ledger["date"].map(value_before).astype(float)
        trade_ledger["trade_value"] = trade_ledger["trade_turnover"].astype(float) * mapped_value
        trade_ledger["cost_amount"] = trade_ledger["cost_ratio"].astype(float) * mapped_value

    return BacktestResult(
        config=config,
        equity_curve=equity_curve,
        daily_returns=state.daily_returns,
        cost_series=state.costs,
        weights=weights,
        values=values,
        signals=state.signals,
        regime_dict=state.regime_dict,
        wf_windows=state.wf_windows,
        universe_snapshots=state.snapshots,
        signal_metadata=state.signal_metadata,
        excluded_tickers=state.excluded_tickers,
        trade_ledger=trade_ledger,
        gross_return_contributions=state.gross_return_contributions,
        cost_contributions=state.cost_contributions,
        net_return_contributions=net_return_contributions,
        lookahead_warnings=lookahead_warnings or None,
    )
