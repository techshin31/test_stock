---
title: daily runtime 전체흐름
created: 2026-06-30
source_basis: code_only
tags:
  - trader
  - diagram
  - runtime
---

# daily runtime 전체흐름

근거 코드: `apps/trader/__main__.py`, `apps/trader/scheduler.py`

```mermaid
flowchart TD
    A["apps/user register"] --> A1["users + user_broker_credentials"]
    B["Analyzer publish"] --> B1["universe"]

    C["python -m apps.trader planner"] --> I1["_init()"]
    I1 --> I2["load_config + live gate"]
    I2 --> I3["DB credential -> KisBroker"]
    I3 --> P1["08:30 wait"]
    P1 --> P2["pre_market_sync"]
    P2 --> P3["run_strategy_planning"]
    B1 --> P3
    P3 --> P4["trade_plans"]
    P4 --> P5["STATUS"]

    D["python -m apps.trader executor"] --> J1["_init()"]
    J1 --> J2["has_executable_plans"]
    J2 --> J3{PENDING/ORDERED 있음?}
    J3 -->|no| J4["STATUS 출력 후 종료"]
    J3 -->|yes| J5["09:00 wait"]
    J5 --> J6["run_one_cycle 반복"]
    J6 --> J7["orders + executions"]
    J6 --> J8["STATUS"]
    J8 --> J9{PENDING/ORDERED = 0?}
    J9 -->|yes| J10["장중 루프 조기 종료"]
    J9 -->|no| J6

    E["python -m apps.trader reconciler"] --> K1["_init()"]
    K1 --> K2["fetch_status"]
    K2 --> K3{total > 0 and PENDING/ORDERED = 0?}
    K3 -->|yes| K4["15:40 wait skip"]
    K3 -->|no| K5["15:40 wait"]
    K4 --> K6["reconcile broker history"]
    K5 --> K6
    K6 --> K7["pre_market_sync"]
    K7 --> K8["SELL_ONLY -> REMOVED"]
    K7 --> K9["balance_history snapshot"]
    K9 --> K10["final STATUS + optional Slack"]
```

## 핵심 연결

| 연결 | 의미 |
|---|---|
| `apps/user register -> _init` | Trader는 DB 자격증명으로 KIS broker를 만든다. |
| `Analyzer publish -> planner` | Trader의 운영 후보는 `universe`다. |
| `planner -> executor` | 장전 `trade_plans`가 장중 실행 입력이다. |
| `executor -> reconciler` | 장중 주문/체결은 장마감 broker history로 다시 맞춘다. |
| `reconciler -> next executor` | `balance_history`가 다음 거래일 손실 한도 기준이다. |
