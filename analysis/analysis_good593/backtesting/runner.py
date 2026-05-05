"""탑다운 3단계 백테스팅 실행기 — Backtrader Cerebro 래퍼"""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import date

import pandas as pd
import backtrader as bt

from .data.loader_wics import load_wics, build_stock_feeds, get_benchmark_returns
from .data.loader_dart import load_fa_data
from .strategy.macro_signal import compute_macro_signals
from .strategy.sector_selector import get_sector_weights
from .strategy.stock_scorer import score_stocks


# ── Backtrader 데이터 피드 ─────────────────────────────────────

class WICSData(bt.feeds.PandasData):
    """WICS 역산 종가 기반 피드. O=H=L=C (종가 기준 체결 가정)."""
    params = (
        ("datetime", None),
        ("open",   "open"),
        ("high",   "high"),
        ("low",    "low"),
        ("close",  "close"),
        ("volume", "volume"),
        ("openinterest", -1),
    )


# ── Backtrader 전략 ───────────────────────────────────────────

class TopDownStrategy(bt.Strategy):
    """탑다운 3단계 전략.

    rebalance_schedule: {date: {CMP_CD: weight}}
        runner가 전략 실행 전에 미리 계산해서 주입.
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
            print(f"[{today}] 리밸런싱: {len(target_weights)}개 종목, "
                  f"포트폴리오 가치={self.broker.getvalue():,.0f}원")

    def notify_order(self, order):
        if order.status == order.Rejected:
            print(f"  ⚠ 주문 거부: {order.data._name} "
                  f"(잔고부족 등) — {order.size:.0f}주")

    def notify_trade(self, trade):
        if self.p.verbose and trade.isclosed:
            print(f"  ✔ 체결: {trade.data._name} PnL={trade.pnl:,.0f}원")


# ── 결과 컨테이너 ─────────────────────────────────────────────

@dataclass
class BacktestResult:
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
            "=" * 45,
            "  탑다운 백테스팅 결과",
            "=" * 45,
            f"  초기 자본:    {self.initial_cash:>15,.0f} 원",
            f"  최종 자산:    {self.final_value:>15,.0f} 원",
            f"  총 수익률:    {self.total_return:>14.2%}",
            f"  CAGR:         {m['cagr']:>14.2%}",
            f"  MDD:          {m['mdd']:>14.2%}",
            f"  Sharpe:       {m['sharpe']:>14.2f}",
            f"  Sortino:      {m['sortino']:>14.2f}",
            f"  Calmar:       {m['calmar']:>14.2f}",
            "=" * 45,
        ]
        return "\n".join(lines)


# ── 공개 API ──────────────────────────────────────────────────

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
            # 특정 월의 마지막 거래일
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
            # 분기별 리밸런싱 (3, 6, 9, 12월 말)
            for m in [3, 6, 9, 12]:
                candidates = [d for d in trading_days if d.year == yr and d.month == m]
                if candidates:
                    target_dates.append(candidates[-1].date())

    return sorted(set(target_dates))


def run_backtest(
    year: int | list[int],
    quarter: int | None = None,
    month: int | None = None,
    initial_cash: float = 100_000_000,
    commission: float = 0.00015,
    slippage: float = 0.0005,
    top_n: int = 5,
    verbose: bool = False,
) -> BacktestResult:
    """탑다운 3단계 백테스팅 실행.

    Args:
        year:         백테스팅 연도 (단수 또는 리스트).
        quarter:      1~4 중 지정 시 해당 분기만 실행.
        month:        1~12 중 지정 시 해당 월만 실행.
        initial_cash: 초기 자본금 (원).
        commission:   매매 수수료 비율.
        slippage:     슬리피지 비율.
        top_n:        섹터당 편입 종목 수.
        verbose:      체결 로그 출력 여부.

    Returns:
        BacktestResult
    """
    years = [year] if isinstance(year, int) else list(year)

    print(f"[1/4] 데이터 로딩 — 연도: {years}")
    wics_df    = load_wics(years)
    fa_df      = load_fa_data(years)
    macro_sig  = compute_macro_signals(years)
    benchmark  = get_benchmark_returns(wics_df)

    print("[2/4] 리밸런싱 스케줄 계산")
    rebal_dates = _get_rebalance_dates(wics_df, years, quarter, month)

    rebalance_schedule: dict[date, dict[str, float]] = {}
    all_candidates: set[str] = set()

    for rd in rebal_dates:
        rd_ts = pd.Timestamp(rd)
        regime         = macro_sig.get_regime(rd_ts)
        sector_weights = get_sector_weights(regime)
        target_weights = score_stocks(rd_ts, sector_weights, wics_df, fa_df, top_n)

        rebalance_schedule[rd] = target_weights
        all_candidates.update(target_weights.keys())

        if verbose:
            print(f"  {rd} | 국면={regime.value} | 종목 수={len(target_weights)}")

    if not all_candidates:
        raise RuntimeError("선택된 종목이 없습니다. FA 데이터 또는 WICS 데이터를 확인하세요.")

    print(f"[3/4] Backtrader 피드 구성 — 후보 종목 {len(all_candidates)}개")
    stock_feeds = build_stock_feeds(wics_df, all_candidates)

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
        TopDownStrategy,
        rebalance_schedule=rebalance_schedule,
        verbose=verbose,
    )
    cerebro.addanalyzer(bt.analyzers.TimeReturn,  _name="time_return")
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name="sharpe",
                        riskfreerate=0.03, annualize=True)
    cerebro.addanalyzer(bt.analyzers.DrawDown,    _name="drawdown")

    print("[4/4] 백테스팅 실행 중...")
    results = cerebro.run()
    strat   = results[0]

    time_return_dict = strat.analyzers.time_return.get_analysis()
    time_returns = pd.Series(time_return_dict).sort_index()

    return BacktestResult(
        initial_cash=initial_cash,
        final_value=cerebro.broker.getvalue(),
        strategy=strat,
        rebalance_schedule=rebalance_schedule,
        benchmark_returns=benchmark,
        time_returns=time_returns,
    )
