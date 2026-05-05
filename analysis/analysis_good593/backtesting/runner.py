"""탑다운 백테스팅 실행기

run_backtest()      — 단일 파이프라인 실행
compare_backtests() — 복수 파이프라인 비교 실행

Usage::

    from backtesting.runner import run_backtest, compare_backtests
    from backtesting.strategy.pipeline import default_pipeline, TopDownPipeline
    from backtesting.strategy.macro_signal import BdiCopperMacroSignal
    from backtesting.strategy.sector_selector import RegimeBasedSectorSelector
    from backtesting.strategy.stock_scorer import FaStockScorer

    # 기본 파이프라인으로 실행
    result = run_backtest(year=2023)
    print(result.summary())

    # 파이프라인을 직접 구성해서 실행
    pipeline = TopDownPipeline(
        macro_signal=BdiCopperMacroSignal(high_rate_tnx=3.0),
        sector_selector=RegimeBasedSectorSelector(),
        stock_scorer=FaStockScorer(top_n=3),
        name="Aggressive",
    )
    result = run_backtest(year=[2022, 2023], pipeline=pipeline)

    # 복수 전략 비교
    results = compare_backtests(
        pipelines=[
            default_pipeline(top_n=3),
            default_pipeline(top_n=10),
            TopDownPipeline(..., name="Custom"),
        ],
        year=2023,
    )
    for r in results:
        print(r.summary())
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

import backtrader as bt
import pandas as pd

from .data.loader_dart import load_fa_data
from .data.loader_wics import build_stock_feeds, get_benchmark_returns, load_wics
from .strategy.pipeline import TopDownPipeline, default_pipeline


# ── Backtrader 데이터 피드 ─────────────────────────────────────

class WICSData(bt.feeds.PandasData):
    """WICS 역산 종가 기반 피드. O=H=L=C (종가 기준 체결 가정)."""
    params = (
        ("datetime", None),
        ("open",     "open"),
        ("high",     "high"),
        ("low",      "low"),
        ("close",    "close"),
        ("volume",   "volume"),
        ("openinterest", -1),
    )


# ── Backtrader 전략 ───────────────────────────────────────────

class _ScheduleStrategy(bt.Strategy):
    """미리 계산된 리밸런싱 스케줄을 그대로 실행하는 범용 Backtrader 전략.

    rebalance_schedule: {date: {CMP_CD: weight}}
        TopDownPipeline.build_schedule() 가 계산한 결과를 주입한다.
    """
    params = (
        ("rebalance_schedule", None),
        ("verbose", False),
    )

    def __init__(self):
        self._schedule: dict[date, dict[str, float]] = self.p.rebalance_schedule or {}
        self._data_map: dict[str, bt.feeds.PandasData] = {
            d._name: d for d in self.datas
        }
        self._pending_orders: list[bt.Order] = []

    def next(self):
        today = self.datas[0].datetime.date(0)
        if today in self._schedule:
            self._rebalance(self._schedule[today])

    def _rebalance(self, target_weights: dict[str, float]):
        """셀 먼저 → 바이 순서로 리밸런싱."""
        for o in self._pending_orders:
            if o and o.status in [o.Submitted, o.Accepted]:
                self.cancel(o)
        self._pending_orders.clear()

        # Pass 1: 목표 비중 0인 포지션 청산
        for name, data in self._data_map.items():
            if name not in target_weights and self.getposition(data).size > 0:
                o = self.order_target_percent(data, target=0.0)
                if o:
                    self._pending_orders.append(o)

        # Pass 2: 목표 비중 설정
        for name, weight in target_weights.items():
            if name in self._data_map:
                o = self.order_target_percent(self._data_map[name], target=weight)
                if o:
                    self._pending_orders.append(o)

        if self.p.verbose:
            today = self.datas[0].datetime.date(0)
            print(f"  [{today}] 리밸런싱: {len(target_weights)}개 종목 "
                  f"| 포트폴리오={self.broker.getvalue():,.0f}원")

    def notify_order(self, order):
        if order.status == order.Rejected:
            print(f"  ⚠ 주문 거부: {order.data._name} ({order.size:.0f}주)")

    def notify_trade(self, trade):
        if self.p.verbose and trade.isclosed:
            print(f"  ✔ 체결: {trade.data._name} PnL={trade.pnl:,.0f}원")


# ── 결과 컨테이너 ─────────────────────────────────────────────

@dataclass
class BacktestResult:
    pipeline_name: str
    initial_cash: float
    final_value: float
    strategy: bt.Strategy
    rebalance_schedule: dict[date, dict[str, float]]
    benchmark_returns: pd.Series
    time_returns: pd.Series = field(default_factory=pd.Series)

    @property
    def total_return(self) -> float:
        return (self.final_value - self.initial_cash) / self.initial_cash

    def summary(self) -> str:
        from .metrics import calc_metrics
        m = calc_metrics(self.time_returns, self.initial_cash, self.final_value)
        lines = [
            "=" * 50,
            f"  전략: {self.pipeline_name}",
            "=" * 50,
            f"  초기 자본:    {self.initial_cash:>15,.0f} 원",
            f"  최종 자산:    {self.final_value:>15,.0f} 원",
            f"  총 수익률:    {self.total_return:>14.2%}",
            f"  CAGR:         {m['cagr']:>14.2%}",
            f"  MDD:          {m['mdd']:>14.2%}",
            f"  Sharpe:       {m['sharpe']:>14.2f}",
            f"  Sortino:      {m['sortino']:>14.2f}",
            f"  Calmar:       {m['calmar']:>14.2f}",
            "=" * 50,
        ]
        return "\n".join(lines)


# ── 내부 유틸리티 ──────────────────────────────────────────────

def _get_rebalance_dates(
    wics_df: pd.DataFrame,
    years: list[int],
    quarter: int | None,
    month: int | None,
) -> list[date]:
    """거래일 중 분기 말(또는 지정 기간 말) 날짜 목록."""
    trading_days = sorted(wics_df["DATE"].unique())

    target_dates: list[date] = []
    for yr in years:
        if month is not None:
            candidates = [d for d in trading_days if d.year == yr and d.month == month]
            if candidates:
                target_dates.append(candidates[-1].date())
        elif quarter is not None:
            q_months = {1: 3, 2: 6, 3: 9, 4: 12}
            m = q_months[quarter]
            candidates = [d for d in trading_days if d.year == yr and d.month == m]
            if candidates:
                target_dates.append(candidates[-1].date())
        else:
            for m in [3, 6, 9, 12]:
                candidates = [d for d in trading_days if d.year == yr and d.month == m]
                if candidates:
                    target_dates.append(candidates[-1].date())

    return sorted(set(target_dates))


def _build_cerebro(
    stock_feeds: dict[str, pd.DataFrame],
    rebalance_schedule: dict[date, dict[str, float]],
    initial_cash: float,
    commission: float,
    slippage: float,
    verbose: bool,
) -> bt.Cerebro:
    """Cerebro 인스턴스를 구성하고 반환한다."""
    cerebro = bt.Cerebro(stdstats=False)
    cerebro.broker.setcash(initial_cash)
    cerebro.broker.setcommission(commission=commission)
    cerebro.broker.set_slippage_perc(
        perc=slippage,
        slip_open=True,
        slip_limit=True,
        slip_match=True,
        slip_out=False,
    )

    for cmp_cd, price_df in stock_feeds.items():
        feed = WICSData(dataname=price_df)
        cerebro.adddata(feed, name=cmp_cd)

    cerebro.addstrategy(
        _ScheduleStrategy,
        rebalance_schedule=rebalance_schedule,
        verbose=verbose,
    )
    cerebro.addanalyzer(bt.analyzers.TimeReturn,  _name="time_return")
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name="sharpe",
                        riskfreerate=0.03, annualize=True)
    cerebro.addanalyzer(bt.analyzers.DrawDown,    _name="drawdown")
    return cerebro


# ── 공개 API ──────────────────────────────────────────────────

def run_backtest(
    year: int | list[int],
    pipeline: TopDownPipeline | None = None,
    quarter: int | None = None,
    month: int | None = None,
    initial_cash: float = 100_000_000,
    commission: float = 0.00015,
    slippage: float = 0.0005,
    verbose: bool = False,
) -> BacktestResult:
    """단일 파이프라인으로 백테스팅을 실행한다.

    Args:
        year:         백테스팅 연도 (단수 또는 리스트).
        pipeline:     실행할 TopDownPipeline. None 이면 default_pipeline() 사용.
        quarter:      1~4 지정 시 해당 분기 말만 리밸런싱.
        month:        1~12 지정 시 해당 월 말만 리밸런싱.
        initial_cash: 초기 자본금 (원).
        commission:   매매 수수료 비율.
        slippage:     슬리피지 비율.
        verbose:      체결 로그 및 리밸런싱 로그 출력 여부.

    Returns:
        BacktestResult
    """
    if pipeline is None:
        pipeline = default_pipeline()

    years = [year] if isinstance(year, int) else list(year)

    print(f"[1/4] 데이터 로딩 — 연도: {years} | 전략: {pipeline.name}")
    wics_df   = load_wics(years)
    fa_df     = load_fa_data(years)
    benchmark = get_benchmark_returns(wics_df)

    print("[2/4] 리밸런싱 스케줄 계산")
    rebal_dates = _get_rebalance_dates(wics_df, years, quarter, month)
    rebalance_schedule = pipeline.build_schedule(
        years, rebal_dates, wics_df, fa_df, verbose=verbose
    )

    all_candidates: set[str] = set()
    for weights in rebalance_schedule.values():
        all_candidates.update(weights.keys())

    if not all_candidates:
        raise RuntimeError("선택된 종목이 없습니다. FA 데이터 또는 WICS 데이터를 확인하세요.")

    print(f"[3/4] Backtrader 피드 구성 — 후보 종목 {len(all_candidates)}개")
    stock_feeds = build_stock_feeds(wics_df, all_candidates)

    cerebro = _build_cerebro(
        stock_feeds, rebalance_schedule, initial_cash, commission, slippage, verbose
    )

    print("[4/4] 백테스팅 실행 중...")
    results = cerebro.run()
    strat   = results[0]

    time_returns = pd.Series(
        strat.analyzers.time_return.get_analysis()
    ).sort_index()

    return BacktestResult(
        pipeline_name=pipeline.name,
        initial_cash=initial_cash,
        final_value=cerebro.broker.getvalue(),
        strategy=strat,
        rebalance_schedule=rebalance_schedule,
        benchmark_returns=benchmark,
        time_returns=time_returns,
    )


def compare_backtests(
    pipelines: list[TopDownPipeline],
    year: int | list[int],
    quarter: int | None = None,
    month: int | None = None,
    initial_cash: float = 100_000_000,
    commission: float = 0.00015,
    slippage: float = 0.0005,
    verbose: bool = False,
) -> list[BacktestResult]:
    """복수 파이프라인을 동일 조건으로 실행해 결과 목록을 반환한다.

    데이터 로딩은 한 번만 수행하고 각 파이프라인에 공유한다.

    Args:
        pipelines:    비교할 TopDownPipeline 목록
        year:         백테스팅 연도
        quarter:      분기 지정 (선택)
        month:        월 지정 (선택)
        initial_cash: 초기 자본금
        commission:   수수료
        slippage:     슬리피지
        verbose:      상세 로그 출력 여부

    Returns:
        각 파이프라인에 대응하는 BacktestResult 목록 (입력 순서 동일)

    Example::

        results = compare_backtests(
            pipelines=[
                default_pipeline(top_n=3),
                default_pipeline(top_n=10),
            ],
            year=2023,
        )
        for r in results:
            print(r.summary())
    """
    years = [year] if isinstance(year, int) else list(year)
    names = [p.name for p in pipelines]
    print(f"[비교 백테스팅] 전략 {len(pipelines)}개: {names}")

    print(f"[1/3] 데이터 로딩 — 연도: {years}")
    wics_df   = load_wics(years)
    fa_df     = load_fa_data(years)
    benchmark = get_benchmark_returns(wics_df)
    rebal_dates = _get_rebalance_dates(wics_df, years, quarter, month)

    bt_results: list[BacktestResult] = []

    for i, pipeline in enumerate(pipelines, start=1):
        print(f"\n[{i}/{len(pipelines)}] 전략 실행: {pipeline.name}")

        schedule = pipeline.build_schedule(
            years, rebal_dates, wics_df, fa_df, verbose=verbose
        )

        all_candidates: set[str] = set()
        for weights in schedule.values():
            all_candidates.update(weights.keys())

        if not all_candidates:
            print(f"  ⚠ [{pipeline.name}] 선택된 종목 없음 — 스킵")
            continue

        stock_feeds = build_stock_feeds(wics_df, all_candidates)
        cerebro = _build_cerebro(
            stock_feeds, schedule, initial_cash, commission, slippage, verbose
        )

        strat_results = cerebro.run()
        strat = strat_results[0]

        time_returns = pd.Series(
            strat.analyzers.time_return.get_analysis()
        ).sort_index()

        bt_results.append(BacktestResult(
            pipeline_name=pipeline.name,
            initial_cash=initial_cash,
            final_value=cerebro.broker.getvalue(),
            strategy=strat,
            rebalance_schedule=schedule,
            benchmark_returns=benchmark,
            time_returns=time_returns,
        ))

    return bt_results
