from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from core.analytics.attribution import summarize_compare_assets
from core.analytics.performance import PerformanceReport, calc_performance
from core.backtest.config import BacktestConfig
from core.backtest.engine import run_backtest
from core.backtest.enum import InsufficientHistoryPolicy
from core.backtest.result import BacktestResult
from core.constant.types import Market, StockCap
from core.strategy.risk_neutral import RiskNeutralStrategy
from core.strategy.fa_ta_momentum import FaTaMomentumStrategy
from core.utils.date_utils import convert_to_str, get_date_n_years_before
from data.loaders.kospi_data import download_kospi_index, download_multiple_stocks, make_defensive_asset_returns
from data.loaders.fa_ta_loader import enrich_ohlcv_with_fa
from storage.postgres.connection import PostgreDB
from storage.postgres.repositories.strategy_repo import fetch_strategy_params

from apps.backtester.config import BacktesterConfig
from apps.backtester.universe import (
    build_fa_published_universe,
    build_random_universe,
    default_rotation_dates,
    drop_failed_tickers,
)

# 지표(MA120, ADX14) 워밍업을 위해 백테스트 시작보다 일찍 데이터를 받는다.
HISTORY_WARMUP_YEARS = 2
MIN_HISTORY_DAYS = 252


@dataclass
class BacktestPipelineResult:
    result: BacktestResult
    performance: PerformanceReport
    compare_summary: pd.DataFrame
    kospi_index: pd.Series
    bond_equity: pd.Series
    kospi_equity: pd.Series
    initial_universe: list[str]


def run_backtest_pipeline(cfg: BacktesterConfig, db: PostgreDB) -> BacktestPipelineResult:
    """위험중립형 전략 백테스트를 처음부터 끝까지 실행한다.

    notebooks/위험중립형_전략_백테스팅.ipynb의 0~6장(환경설정 ~ 비교자산 계산)을
    재사용 가능한 파이프라인으로 옮긴 것이다. 시각화(7장 이후)는 report.py가 담당한다.
    """
    if cfg.strategy_name == "fa_ta_momentum":
        strategy = FaTaMomentumStrategy({
            "entry_size": 0.18, "ma_window": 60, "ma_window_fast": 20,
            "fa_score_min": 60.0, "fa_score_exit": 40.0,
            "debt_ratio_max": 2.0,
        })
    else:
        params = fetch_strategy_params(db, cfg.strategy_name)
        strategy = RiskNeutralStrategy(params)

    download_start = convert_to_str(get_date_n_years_before(cfg.start_date, HISTORY_WARMUP_YEARS))
    download_end = convert_to_str(cfg.end_date)

    print(f"[BACKTESTER] KOSPI 지수 다운로드 중... ({download_start} ~ {download_end})")
    kospi_index = download_kospi_index(download_start, download_end)

    if cfg.universe_source == "fa-published":
        initial_universe, rotation_plans, all_tickers = build_fa_published_universe(
            db, cfg.fa_source_strategy, cfg.start_date, cfg.end_date
        )
    else:
        rotation_dates = default_rotation_dates(
            cfg.start_date, cfg.end_date, interval_years=cfg.rotation_interval_years,
        )
        initial_universe, rotation_plans, all_tickers = build_random_universe(
            rotation_dates=rotation_dates,
            universe_size=cfg.universe_size,
            rotation_size=cfg.rotation_size,
            seed=cfg.random_seed,
        )
    print(f"[BACKTESTER] 초기 유니버스: {initial_universe}")
    print(f"[BACKTESTER] 교체 계획 {len(rotation_plans)}건: {[p.review_date for p in rotation_plans]}")

    print(f"[BACKTESTER] {len(all_tickers)}개 종목 OHLCV 다운로드 중...")
    ohlcv_store = download_multiple_stocks(
        list(all_tickers), start=download_start, end=download_end, show_progress=False,
    )
    if cfg.strategy_name == "fa_ta_momentum":
        ohlcv_store = enrich_ohlcv_with_fa(db, ohlcv_store, cfg.end_date)
    failed_tickers = [t for t in all_tickers if t not in ohlcv_store]
    if failed_tickers:
        print(f"[BACKTESTER] 다운로드 실패 종목 제외: {failed_tickers}")
        initial_universe, rotation_plans = drop_failed_tickers(
            initial_universe, rotation_plans, set(ohlcv_store.keys()),
        )

    backtest_calendar = pd.DatetimeIndex(kospi_index[str(cfg.start_date):str(cfg.end_date)].index)
    bond_returns = make_defensive_asset_returns(
        backtest_calendar, ticker=strategy.DEFENSIVE_ASSET_TYPE.value.ticker,
    )

    config = BacktestConfig(
        strategy=strategy,
        start_date=cfg.start_date,
        end_date=cfg.end_date,
        initial_capital=float(cfg.initial_capital),
        initial_universe=initial_universe,
        market=Market.KOSPI,
        cap=StockCap.LARGE,
        market_index=kospi_index,
        rotation_plans=rotation_plans,
        benchmark_returns=kospi_index.pct_change().fillna(0),
        defensive_asset_returns=bond_returns,
        min_history_days=MIN_HISTORY_DAYS,
        insufficient_history_policy=InsufficientHistoryPolicy.EXCLUDE.value,
    )

    print("[BACKTESTER] 백테스트 실행 중... (시간이 걸릴 수 있습니다)")
    result = run_backtest(config, ohlcv_store)
    print(f"[BACKTESTER] 완료: {len(result.equity_curve):,}거래일")
    if result.excluded_tickers:
        print(f"[BACKTESTER] 최소 이력 부족으로 제외된 종목: {list(result.excluded_tickers.keys())}")

    performance = calc_performance(result, risk_free_rate=cfg.risk_free_rate)

    bt_idx = result.equity_curve.index
    bond_equity = (1 + bond_returns.reindex(bt_idx).fillna(0)).cumprod() * cfg.initial_capital
    kospi_equity = (
        1 + kospi_index.reindex(bt_idx, method="ffill").pct_change().fillna(0)
    ).cumprod() * cfg.initial_capital

    compare_summary = summarize_compare_assets(
        {
            cfg.strategy_name: result.equity_curve,
            "BOND_100": bond_equity,
            "KOSPI": kospi_equity,
        },
        risk_free_rate=cfg.risk_free_rate,
    )

    return BacktestPipelineResult(
        result=result,
        performance=performance,
        compare_summary=compare_summary,
        kospi_index=kospi_index,
        bond_equity=bond_equity,
        kospi_equity=kospi_equity,
        initial_universe=initial_universe,
    )
