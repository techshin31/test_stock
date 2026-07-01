from __future__ import annotations

from datetime import date
from typing import Any

import numpy as np
import pandas as pd
import yfinance as yf

from core.constant.types import Tickers, UniverseStatus
from core.constant.values import ADXGridParam
from core.portfolio.decision import decide_target_weights_for_day
from core.portfolio.momentum import calc_universe_momentum
from core.portfolio.universe import PortfolioUniverse
from core.signal.market_regime import calc_regime
from core.strategy.risk_neutral import RiskNeutralStrategy
from core.trade.kis_broker import KisBroker
from core.trade.position_sync import sync_positions_from_broker
from core.utils.trading_calendar import previous_krx_trading_day
from storage.postgres.connection import PostgreDB
from storage.postgres.repositories.position_repo import fetch_positions
from storage.postgres.repositories.company_risk_repo import (
    fetch_buy_blocked_stock_codes,
)
from storage.postgres.repositories.strategy_repo import fetch_strategy_params
from storage.postgres.repositories.trade_plan_repo import (
    fetch_executable_trade_plans,
    upsert_trade_plan,
)
from storage.postgres.repositories.universe_repo import (
    fetch_universe_for_date,
    seed_test_universe,
    sync_positions_to_universe,
)

MIN_ORDER_QTY = 1

# 신호 사유별 ATR 가중치 (None = 항상 즉시 체결, 가격 편차 한도 없음)
_DEVIATION_K: dict[str, float | None] = {
    "UPTREND_ENTRY1": 2.0,
    "UPTREND_ENTRY2": 2.0,
    "REBALANCE_BUY": 1.5,
    "DEFENSIVE_ALLOCATION": 1.5,
    "SIDEWAYS_BB_LOWER_ENTRY": 1.0,
    "REBALANCE_SELL": 1.0,
    "ATR_STOP": None,
    "DOWNTREND": None,
    "BB_UPPER_BREAKDOWN": None,
    "FORCED_EXIT": None,
    "TRANSITION_EXIT": None,
    "DEADCROSS": None,
}


def generate_plans(
    db: PostgreDB,
    strategy_name: str,
    plan_date: date,
    decisions: list[dict[str, Any]],
) -> int:
    """전략 결정 목록을 받아 trade_plans를 DB에 저장한다.

    Parameters
    ----------
    decisions : list[dict]
        core/portfolio, core/strategy 모듈이 계산한 종목별 주문 결정.
        각 dict는 upsert_trade_plan이 요구하는 필드를 포함해야 한다.
        (symbol, market_type_code, order_side_code, planned_qty 필수)

    Returns
    -------
    int
        저장된 계획 수.
    """
    count = 0
    for decision in decisions:
        decision.setdefault("plan_date", plan_date)
        decision.setdefault("strategy_name", strategy_name)
        upsert_trade_plan(db, decision)
        count += 1
    return count


def _normalize_ohlcv(df: pd.DataFrame) -> pd.DataFrame:
    """yfinance DataFrame의 컬럼명을 소문자로 정규화한다."""
    if isinstance(df.columns, pd.MultiIndex):
        df = df.droplevel(level=1, axis=1)
    df.columns = df.columns.str.lower()
    return df.dropna(how="all")


def _through_signal_date(df: pd.DataFrame, signal_date: date) -> pd.DataFrame:
    index = pd.DatetimeIndex(df.index)
    return df.loc[index.date <= signal_date]


def _calc_atr(df: pd.DataFrame, window: int = 14) -> float | None:
    """Wilder's ATR(window) 값을 계산해 반환한다."""
    if len(df) < window + 1:
        return None
    prev_close = df["close"].shift(1)
    tr = pd.concat([
        df["high"] - df["low"],
        (df["high"] - prev_close).abs(),
        (df["low"] - prev_close).abs(),
    ], axis=1).max(axis=1)
    val = tr.ewm(alpha=1 / window, min_periods=window, adjust=False).mean().iloc[-1]
    return float(val) if pd.notna(val) else None


def _calc_deviation_limit(reason_code: str | None, atr: float | None, planned_price: float) -> float | None:
    """신호 사유와 ATR로 price_deviation_limit을 계산한다. None이면 항상 체결."""
    k = _DEVIATION_K.get(reason_code or "")
    if k is None or atr is None or planned_price <= 0:
        return None
    return float(max(0.02, min(0.07, k * atr / planned_price)))


def run_strategy_planning(
    db: PostgreDB,
    broker: KisBroker,
    strategy_name: str,
    plan_date: date,
    test: bool = False,
    balance: dict[str, Any] | None = None,
) -> int:
    """노트북 STEP 4~8을 이식한 전략 계산 파이프라인.

    universe 조회 → (옵션) 테스트 universe seed → OHLCV 조회 →
    레짐/모멘텀/목표비중 계산 → trade_plans 저장까지 수행한다.

    Parameters
    ----------
    test : bool
        True이고 universe가 비어 있으면 seed_test_universe()로
        테스트용 종목을 채운 뒤 동일한 전략 계산을 진행한다.
    balance : dict | None
        이미 조회한 KIS balance 응답. 제공하면 broker.account.balance()를
        다시 호출하지 않는다 (pre_market_sync()가 이미 조회한 결과 재사용).

    Returns
    -------
    int
        저장된 trade_plans 수.
    """
    params = fetch_strategy_params(db, strategy_name)
    strategy = RiskNeutralStrategy(params)
    bond_etf_code = params.get("bond_etf_code", Tickers.BOND_ETF.ticker.removesuffix(".KS"))
    adx_threshold = params.get("adx_threshold", ADXGridParam.THRESHOLD_3)
    adx_sideways = params.get("adx_sideways", ADXGridParam.SIDEWAYS_2)
    signal_date = previous_krx_trading_day(plan_date)

    # 1. universe 조회 (없고 --test면 테스트 종목 seed)
    universe_rows = fetch_universe_for_date(db, strategy_name=strategy_name, as_of_date=plan_date)
    if not universe_rows:
        if not test:
            print("[PLANNER] universe가 비어 있습니다. FA 분석 결과를 먼저 채워주세요.")
            return 0
        seeded = seed_test_universe(db, strategy_name=strategy_name)
        universe_rows = fetch_universe_for_date(db, strategy_name=strategy_name, as_of_date=plan_date)
        print(f"[PLANNER] 테스트 universe {seeded}건 seed 완료")

    # 2. 보유 중이지만 universe에 없는 종목 → SELL_ONLY 등록
    positions_now = fetch_positions(db, strategy_name=strategy_name)
    orphan_symbols = sync_positions_to_universe(
        db, strategy_name=strategy_name, positions=positions_now, as_of_date=plan_date,
    )
    if orphan_symbols:
        print(f"[PLANNER] SELL_ONLY 등록: {orphan_symbols}")
        universe_rows = fetch_universe_for_date(db, strategy_name=strategy_name, as_of_date=plan_date)

    trade_symbols = [
        r["symbol"] for r in universe_rows
        if r["universe_status_code"] in (UniverseStatus.ACTIVE.name, UniverseStatus.SELL_ONLY.name)
    ]
    if not trade_symbols:
        print("[PLANNER] 거래 대상 종목이 없습니다.")
        return 0
    risk_blocked_set = fetch_buy_blocked_stock_codes(
        db, plan_date, stock_codes=trade_symbols
    )
    if risk_blocked_set:
        print(f"[PLANNER] 기업 위험 매수차단: {sorted(risk_blocked_set)}")
    all_symbols = list(set(trade_symbols + [bond_etf_code]))

    # 3. OHLCV 조회 (KOSPI 지수 + 개별 종목/방어자산 ETF)
    kospi_df = _normalize_ohlcv(
        yf.download(Tickers.KOSPI_INDEX.ticker, period="2y", auto_adjust=True, progress=False)
    )
    kospi_df = _through_signal_date(kospi_df, signal_date)
    price_data: dict[str, pd.DataFrame] = {}
    for symbol in all_symbols:
        df = _normalize_ohlcv(
            yf.download(f"{symbol}.KS", period="2y", auto_adjust=True, progress=False)
        )
        df = _through_signal_date(df, signal_date)
        if len(df) == 0:
            print(f"[PLANNER] {symbol}: 가격 데이터 없음 (건너뜀)")
            continue
        price_data[symbol] = df
    prices = {sym: float(df["close"].dropna().iloc[-1]) for sym, df in price_data.items()}

    # 4. 레짐 계산 (포트폴리오 대표 레짐 + 종목별)
    kospi_regime_df = calc_regime(
        close=kospi_df["close"], high=kospi_df["high"], low=kospi_df["low"],
        market_index=kospi_df["close"], adx_threshold=adx_threshold, adx_sideways=adx_sideways,
    )
    portfolio_regime = kospi_regime_df["REGIME"].iloc[-1]

    regime_dict: dict[str, pd.DataFrame] = {}
    for symbol in trade_symbols:
        if symbol not in price_data:
            continue
        ohlcv = price_data[symbol]
        regime_dict[symbol] = calc_regime(
            close=ohlcv["close"], high=ohlcv["high"], low=ohlcv["low"],
            market_index=kospi_df["close"], adx_threshold=adx_threshold, adx_sideways=adx_sideways,
        )

    # 5. 종목별 전략 신호
    signal_ts = pd.Timestamp(signal_date)
    signals: dict[str, float] = {}
    metadata: dict[str, dict] = {}
    for symbol in trade_symbols:
        if symbol not in price_data or symbol not in regime_dict:
            print(f"[PLANNER] {symbol}: 가격/레짐 데이터 없음 (건너뜀)")
            continue

        # state=None → strategy가 OHLCV 전체 기간을 백테스트 모드로 돌려
        # plan_date 시점의 실제 regime/position을 계산한다 (core/strategy/base.py _init_state 참고)
        _, meta_df = strategy.make_signals_with_metadata(
            ohlcv=price_data[symbol], regime_df=regime_dict[symbol], state=None,
        )
        if signal_ts in meta_df.index:
            # position_after는 트리거 발생일뿐 아니라 모든 날짜에 채워지는
            # "현재 유지해야 할 목표 비중"이다 (sig_series는 트리거 발생일에만
            # 값이 있는 sparse 신호라 신규 종목 캐치업 주문이 생성되지 않음)
            signals[symbol] = meta_df.loc[signal_ts, "position_after"]
            metadata[symbol] = meta_df.loc[signal_ts].to_dict()

    # 6. 현재 비중 계산
    if balance is None:
        balance = broker.account.balance()
    total_eval = int((balance.get("output2") or [{}])[0].get("tot_evlu_amt", "0"))
    portfolio_value = float(total_eval) if total_eval > 0 else 1.0

    current_weights: dict[str, float] = {}
    for p in positions_now:
        symbol = p["symbol"]
        qty = float(p["qty"])
        price = float(prices.get(symbol, p["avg_cost"] or 0.0))
        current_weights[symbol] = qty * price / portfolio_value

    # 7. 목표 비중 결정
    sell_only_set = {
        r["symbol"] for r in universe_rows
        if r["universe_status_code"] == UniverseStatus.SELL_ONLY.name
    } | risk_blocked_set

    portfolio_universe = PortfolioUniverse()
    for r in universe_rows:
        if r["symbol"] in risk_blocked_set:
            portfolio_universe.set_sell_only(
                r["symbol"], sell_only_since=plan_date,
                reason="company_risk_states BUY block",
            )
        elif r["universe_status_code"] == UniverseStatus.ACTIVE.name:
            portfolio_universe.set_active(r["symbol"], added_at=r.get("entry_date"))
        elif r["universe_status_code"] == UniverseStatus.SELL_ONLY.name:
            portfolio_universe.set_sell_only(
                r["symbol"], sell_only_since=r.get("entry_date"), force_exit_date=r.get("exit_deadline"),
            )

    signals_df = pd.DataFrame({sym: [val] for sym, val in signals.items()}, index=[signal_ts])
    close_df = pd.concat(
        {sym: price_data[sym]["close"] for sym in trade_symbols if sym in price_data}, axis=1,
    )
    momentum_dict = calc_universe_momentum(
        close=close_df, regime_dict=regime_dict, tickers=[s for s in trade_symbols if s in price_data],
    )

    decision = decide_target_weights_for_day(
        as_of=signal_ts,
        strategy=strategy,
        universe=portfolio_universe,
        current_weights=pd.Series(current_weights),
        signals=signals_df,
        momentum_dict=momentum_dict,
        regime_dict=regime_dict,
        defensive_ticker=bond_etf_code,
    )
    target_weights: dict[str, float] = decision.target_weights.to_dict()

    # 8. trade_plans 저장
    # universe 전체(trade_symbols) + 방어자산(target_weights에만 있을 수 있음)을
    # 합쳐서 순회한다 — 주문 가능한 종목뿐 아니라 "오늘 왜 주문이 없었는지"도
    # SKIPPED 상태로 trade_plans에 남겨 의사결정 내역을 추적할 수 있게 한다.
    plan_symbols = list(dict.fromkeys(trade_symbols + list(target_weights.keys())))

    plan_count = 0
    for symbol in plan_symbols:
        target_w = target_weights.get(symbol)
        if target_w is not None and pd.isna(target_w):
            target_w = None
        prev_w = current_weights.get(symbol, 0.0)
        price = prices.get(symbol)
        reason_code = metadata.get(symbol, {}).get("signal_reason")

        status = "SKIPPED"
        side = None
        qty = None

        if target_w is None:
            reason_code = reason_code or "NO_SIGNAL"
        elif price is None:
            reason_code = reason_code or "NO_SIGNAL"
        else:
            diff_w = target_w - prev_w
            qty = int(abs(portfolio_value * diff_w) / price)
            side = "BUY" if diff_w > 0 else "SELL"

            if symbol in sell_only_set and side == "BUY":
                reason_code = "SELL_ONLY_BLOCKED"
            elif qty < MIN_ORDER_QTY:
                reason_code = reason_code or "BELOW_MIN_QTY"
            else:
                status = "PENDING"
                if reason_code is None:
                    reason_code = "DEFENSIVE_ALLOCATION" if symbol == bond_etf_code else (
                        "REBALANCE_SELL" if side == "SELL" else "REBALANCE_BUY"
                    )

        atr = _calc_atr(price_data[symbol]) if symbol in price_data else None
        deviation_limit = _calc_deviation_limit(reason_code, atr, price) if price is not None else None

        upsert_trade_plan(db, {
            "strategy_name": strategy_name,
            "plan_date": plan_date,
            "symbol": symbol,
            "market_type_code": "KOSPI",
            "instrument_type_code": "ETF" if symbol == bond_etf_code else "STOCK",
            "order_side_code": side,
            "planned_qty": qty,
            "planned_price": price,
            "order_type_code": "LIMIT",
            "plan_status_code": status,
            "trade_reason_code": reason_code,
            "prev_weight": prev_w,
            "target_weight": target_w,
            "regime_code": portfolio_regime,
            "price_deviation_limit": deviation_limit,
        })

        if status == "PENDING":
            print(f"[PLANNER] [{side}] {symbol} {qty}주 @ {price:,.0f}원 (사유={reason_code})")
            plan_count += 1
        else:
            print(f"[PLANNER] [SKIP] {symbol} (사유={reason_code})")

    print(f"[PLANNER] trade_plans 생성 완료: {plan_count}건 (SKIPPED 포함 총 {len(plan_symbols)}건 기록)")
    return plan_count


def has_executable_plans(db: PostgreDB, strategy_name: str, plan_date: date) -> bool:
    """당일 실행 가능한 PENDING/ORDERED 계획이 있는지 확인한다."""
    return len(fetch_executable_trade_plans(db, plan_date, strategy_name)) > 0


def pre_market_sync(
    db: PostgreDB,
    broker: KisBroker,
    strategy_name: str,
) -> dict[str, Any] | None:
    """장전 포지션 동기화를 수행하고 결과를 감사 로그에 기록한다.

    Returns
    -------
    dict | None
        동기화 중 조회한 KIS balance 응답. run_strategy_planning()이
        같은 응답을 재사용해 balance() 중복 호출을 피할 수 있다.
        동기화 실패 시 None.
    """
    from apps.trader import audit

    try:
        result = sync_positions_from_broker(db, broker, strategy_name)
        audit.log_position_sync(result.synced, result.zeroed, result.zeroed_symbols)
        print(
            f"[PLANNER] 포지션 동기화: upsert {result.synced}개 "
            f"| qty=0 처리 {result.zeroed}개"
            + (f" ({result.zeroed_symbols})" if result.zeroed_symbols else "")
        )
        return result.balance
    except Exception as exc:
        audit.log_error("pre_market_sync", str(exc))
        print(f"[PLANNER] 포지션 동기화 실패 (계속 진행): {exc}")
        return None
