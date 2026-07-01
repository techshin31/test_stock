---
title: planner 계획생성 상세
created: 2026-06-30
source_basis: code_only
tags:
  - trader
  - diagram
  - planner
---

# planner 계획생성 상세

근거 코드: `apps/trader/planner.py`, `core/trade/position_sync.py`, `storage/postgres/repositories/universe_repo.py`

```mermaid
flowchart TD
    A["run_planner"] --> B["pre_market_sync"]
    B --> B1["broker.account.balance"]
    B1 --> B2["upsert positions"]
    B2 --> B3["zero out missing positions"]

    A --> C["run_strategy_planning"]
    C --> C1["fetch_strategy_params"]
    C1 --> C2["RiskNeutralStrategy(params)"]
    C2 --> C3["signal_date = previous KRX trading day"]
    C3 --> C4["fetch_universe_for_date"]
    C4 --> C5{universe empty?}
    C5 -->|yes and test| C6["seed_test_universe"]
    C5 -->|yes and not test| C7["return 0"]
    C5 -->|no| C8["fetch_positions"]
    C6 --> C8

    C8 --> C9["sync_positions_to_universe"]
    C9 --> C10["orphan holdings -> SELL_ONLY"]
    C10 --> C11["fetch_buy_blocked_stock_codes"]
    C11 --> C12["yfinance OHLCV 2y"]
    C12 --> C13["_through_signal_date"]
    C13 --> C14["calc_regime"]
    C14 --> C15["make_signals_with_metadata"]
    C15 --> C16["position_after as target signal"]
    C16 --> C17["current_weights from positions"]
    C17 --> C18["decide_target_weights_for_day"]
    C18 --> C19["upsert_trade_plan per symbol"]
    C19 --> C20{"PENDING or SKIPPED"}

    C20 -->|PENDING| D1["executor target"]
    C20 -->|SKIPPED| D2["decision audit only"]
```

## 상태 생성 기준

| 상태 | 생성 조건 |
|---|---|
| `PENDING` | 목표 비중 차이로 최소 1주 이상 주문 가능 |
| `SKIPPED` | 신호 없음, 가격 없음, 최소 수량 미달, SELL_ONLY BUY 차단 |

## 저장 포인트

| 저장소 | 저장 내용 |
|---|---|
| `positions` | KIS 잔고 기준 보유 수량/평균단가 |
| `universe` | 보유 중이지만 후보 밖인 종목 SELL_ONLY 등록 |
| `trade_plans` | 오늘의 주문/미주문 의사결정 |
