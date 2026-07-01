---
title: reconciler 정산 상세
created: 2026-06-30
source_basis: code_only
tags:
  - trader
  - diagram
  - reconciler
---

# reconciler 정산 상세

근거 코드: `apps/trader/__main__.py`, `core/trade/reconcile.py`, `core/trade/position_sync.py`

```mermaid
flowchart TD
    A["run_reconciler"] --> B["fetch_status"]
    B --> C{total_plans > 0 and PENDING/ORDERED = 0?}
    C -->|yes| D["skip 15:40 wait"]
    C -->|no| E["wait_until(EOD_START)"]
    D --> F["reconcile_orders_from_broker_history"]
    E --> F

    F --> G["broker.history.get"]
    G --> H["for each broker row"]
    H --> I["fetch_order_by_broker_id"]
    I --> J{managed order?}
    J -->|no| J1["skip"]
    J -->|yes| K["filled/remaining/avg price parse"]
    K --> L["execution delta"]
    L --> M["insert_execution if delta > 0"]
    M --> N["update_order_status EOD_RECONCILE"]

    F --> O["pre_market_sync"]
    O --> P["broker.account.balance"]
    P --> Q["upsert/zero positions"]
    Q --> R["mark_empty_sell_only_removed"]
    R --> S["balance_history snapshot"]
    S --> T["final STATUS"]
    T --> U{"SLACK_WEBHOOK_URL?"}
    U -->|yes| V["notify_slack"]
    U -->|no| W["done"]
    V --> W
```

## 정산 산출물

| 산출물 | 의미 |
|---|---|
| `orders` 갱신 | 브로커 이력 기준 주문 상태 보정 |
| `executions` 추가 | 아직 저장되지 않은 체결 delta 저장 |
| `positions` 갱신 | 장마감 실제 보유 상태 |
| `universe REMOVED` | SELL_ONLY 청산 완료 반영 |
| `balance_history` | 다음 거래일 손실 한도 기준 |
