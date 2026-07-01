---
title: planner 전략계획
created: 2026-06-30
source_basis: code_only
tags:
  - trader
  - developer
  - planner
---

# planner 전략계획

근거 코드: `apps/trader/planner.py`, `core/trade/position_sync.py`, `storage/postgres/repositories/universe_repo.py`

## 입력과 출력

| 구분 | 항목 |
|---|---|
| 주요 입력 | `universe`, `positions`, KIS balance, yfinance OHLCV, `strategies.params`, `company_risk_states` |
| 주요 출력 | `positions`, `universe` SELL_ONLY 재등록, `trade_plans` |

## generate_plans

`generate_plans()`는 외부에서 이미 만든 decision list를 `upsert_trade_plan()`으로 저장하는 얇은 헬퍼다. 현재 메인 planner 경로는 `run_strategy_planning()` 안에서 직접 `upsert_trade_plan()`을 호출한다.

## run_strategy_planning 흐름

```text
fetch_strategy_params
  -> RiskNeutralStrategy(params)
  -> signal_date = previous_krx_trading_day(plan_date)
  -> fetch_universe_for_date
  -> if empty and test: seed_test_universe
  -> fetch_positions
  -> sync_positions_to_universe
  -> fetch_buy_blocked_stock_codes
  -> yfinance OHLCV download
  -> calc_regime
  -> strategy.make_signals_with_metadata
  -> broker.account.balance 또는 pre_market_sync balance 재사용
  -> decide_target_weights_for_day
  -> upsert_trade_plan for each plan symbol
```

## universe 처리

`fetch_universe_for_date()` 조건:

```text
universe_status_code IN ('ACTIVE', 'SELL_ONLY')
entry_date <= plan_date
exit_deadline IS NULL OR exit_deadline >= plan_date
```

`positions`에 보유 중이지만 현재 universe에 없는 종목은 `sync_positions_to_universe()`가 `SELL_ONLY`로 등록한다.

## 가격 데이터

OHLCV는 yfinance로 조회한다.

| 대상 | ticker |
|---|---|
| KOSPI 지수 | `Tickers.KOSPI_INDEX.ticker` |
| 개별 종목 | `{symbol}.KS` |
| 방어자산 ETF | 전략 params의 `bond_etf_code` 또는 기본 채권 ETF |

`_through_signal_date()`는 직전 KRX 거래일 이후 데이터를 잘라낸다. 장전 계획이 당일 미완성 데이터를 보지 않게 하기 위한 처리다.

## 신호 계산

종목별로 `RiskNeutralStrategy.make_signals_with_metadata(..., state=None)`를 호출한다.

중요 구현 선택:

```text
signals[symbol] = meta_df.loc[signal_ts, "position_after"]
```

`sig_series`가 아니라 `position_after`를 사용한다. trigger가 없는 날에도 현재 유지해야 할 목표 비중을 알 수 있어 신규 편입 종목 catch-up 주문이 가능하다.

## 목표 비중과 SELL_ONLY

`PortfolioUniverse`에 다음 상태를 채운 뒤 `decide_target_weights_for_day()`를 호출한다.

| 입력 상태 | 처리 |
|---|---|
| ACTIVE | `set_active` |
| SELL_ONLY | `set_sell_only` |
| company risk blocked | `set_sell_only(reason="company_risk_states BUY block")` |

planner 내부의 `sell_only_set`은 기존 SELL_ONLY와 위험 차단 종목의 합집합이다. 이 set에 있는 종목이 BUY 방향이면 `SELL_ONLY_BLOCKED`로 SKIPPED 처리된다.

## trade_plans 생성

순회 대상:

```text
trade_symbols + target_weights.keys()
```

즉 주문 가능한 종목뿐 아니라 오늘 주문하지 않는 종목도 기록한다.

| 조건 | 저장 상태 | 사유 |
|---|---|---|
| `target_w is None` | `SKIPPED` | `NO_SIGNAL` |
| 가격 없음 | `SKIPPED` | `NO_SIGNAL` |
| SELL_ONLY인데 BUY | `SKIPPED` | `SELL_ONLY_BLOCKED` |
| 수량 < `MIN_ORDER_QTY` | `SKIPPED` | `BELOW_MIN_QTY` |
| 주문 가능 | `PENDING` | 전략 사유 또는 리밸런싱 사유 |

`upsert_trade_plan()`은 `(plan_date, strategy_id, symbol)` 충돌 시 기존 계획을 갱신한다.

## 가격 편차 제한

`_calc_deviation_limit()`은 신호 사유와 ATR로 `price_deviation_limit`을 계산한다.

| 사유 | 제한 |
|---|---|
| `UPTREND_ENTRY1`, `UPTREND_ENTRY2` | ATR 기반, 상대적으로 넓음 |
| `REBALANCE_BUY`, `DEFENSIVE_ALLOCATION` | ATR 기반 |
| `SIDEWAYS_BB_LOWER_ENTRY`, `REBALANCE_SELL` | ATR 기반 |
| `ATR_STOP`, `DOWNTREND`, `FORCED_EXIT` 등 | `None` |

`None`은 executor에서 가격 편차 조건으로 막지 않는다는 의미다.
