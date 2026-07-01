---
title: executor 주문실행 상세
created: 2026-06-30
source_basis: code_only
tags:
  - trader
  - diagram
  - executor
---

# executor 주문실행 상세

근거 코드: `apps/trader/runner.py`, `core/trade/execution.py`

```mermaid
flowchart TD
    A["run_executor"] --> B["has_executable_plans"]
    B --> C{PENDING/ORDERED 있음?}
    C -->|no| C1["STATUS 후 종료"]
    C -->|yes| D["run_one_cycle"]

    D --> E["broker.account.balance"]
    E --> F["check_daily_loss_limit"]
    F --> G{allowed?}
    G -->|no| G1["LOSS_LIMIT_BREACH + cycle stop"]
    G -->|yes| H["fetch_executable_trade_plans"]

    H --> I["for each plan"]
    I --> J["fetch_trade_plan_progress"]
    J --> K{remaining_qty <= 0?}
    K -->|yes| K1["plan DONE"]
    K -->|no| L["sync_open_orders_for_plan"]
    L --> M{open unresolved?}
    M -->|yes| M1["plan ORDERED, skip new child"]
    M -->|no| N["company risk BUY check"]
    N --> O{BUY blocked?}
    O -->|yes| O1["plan SKIPPED / COMPANY_RISK_BLOCKED"]
    O -->|no| P["buyable/sellable + deviation check"]
    P --> Q{executable now?}
    Q -->|no| Q1["keep for retry"]
    Q -->|yes| R["choose_child_order"]
    R --> S["create_order SUBMITTED"]
    S --> T["broker buy_limit/sell_limit"]
    T --> U["attach broker id ACCEPTED"]
    U --> V["poll_order_status"]
    V --> W{remaining order qty > 0?}
    W -->|yes| X["cancel_remaining_order"]
    W -->|no| Y["update_order_status"]
    X --> Y
    Y --> Z["record execution delta"]
    Z --> AA["mark plan DONE or ORDERED"]
```

## 재시도 설계

| 상황 | 결과 |
|---|---|
| 호가 편차 초과 | plan을 닫지 않고 다음 사이클에서 다시 확인 |
| 매수/매도 가능수량 0 | plan을 닫지 않고 다음 사이클에서 다시 확인 |
| 열린 주문 미확정 | `ORDERED` 유지 |
| 일부 체결 후 잔량 | `ORDERED` 유지 |
| 기업 위험 BUY 차단 | `SKIPPED`으로 닫음 |

## 기록 테이블

| 단계 | 테이블 |
|---|---|
| 계획 상태 | `trade_plans` |
| 주문 생성/상태 | `orders` |
| 상태 이력 | `order_status_history` |
| 체결 delta | `executions` |
