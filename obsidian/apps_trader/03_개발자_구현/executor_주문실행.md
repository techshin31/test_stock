---
title: executor 주문실행
created: 2026-06-30
source_basis: code_only
tags:
  - trader
  - developer
  - executor
  - order
---

# executor 주문실행

근거 코드: `apps/trader/runner.py`, `core/trade/execution.py`, `core/trade/gate.py`

## run_one_cycle

```text
broker.account.balance()
  -> check_daily_loss_limit()
  -> fetch_executable_trade_plans(PENDING, ORDERED)
  -> audit.log_cycle_start()
  -> for plan:
       execute_plan_with_orderbook_slicing()
       audit.log_order() if filled
       catch exception and continue
  -> audit.log_cycle_end()
```

개별 plan 실행 중 예외가 발생해도 전체 사이클은 중단하지 않는다. 해당 plan은 다음 사이클에서 다시 관찰될 수 있다.

## 손실 한도

`check_daily_loss_limit()`은 `balance_history`의 최신 총자산과 현재 브로커 총자산을 비교한다.

```text
daily_net = current_total_value - latest_balance_history.total_value
0 < abs(DAILY_LOSS_LIMIT) <= 1 이면
  limit = latest_balance_history.total_value * abs(DAILY_LOSS_LIMIT)
그 외에는
  limit = abs(DAILY_LOSS_LIMIT)

daily_net < -limit 이면 차단
```

기본값은 `DAILY_LOSS_LIMIT=0.10`이므로 전일 마감 총자산의 10% 손실을 기준으로 차단한다. `DAILY_LOSS_LIMIT=500000`처럼 `1`보다 큰 값은 기존 방식대로 고정 원화 한도다.

이 기준은 `executions.net_amount`와 다르다. 매수는 현금이 주식으로 바뀔 뿐이므로 체결 현금흐름만으로 손실 한도를 판단하지 않는다.

## 실행 대상 plan

`fetch_executable_trade_plans()` 조건:

```sql
plan_status_code IN ('PENDING', 'ORDERED')
```

정렬은 SELL 먼저, 그 다음 BUY다.

```text
CASE order_side_code WHEN 'SELL' THEN 0 ELSE 1 END, id
```

매도 후 매수를 실행해 현금 확보를 먼저 시도하는 구조다.

## execute_plan_with_orderbook_slicing 흐름

```text
fetch_trade_plan_progress
  -> requested_qty/remaining_qty 계산
  -> open orders sync/cancel
  -> company risk BUY 재확인
  -> BUY 매수가능수량 확인
  -> price_deviation_limit 확인
  -> SELL 매도가능수량 확인
  -> 반복:
       choose_child_order
       create_order
       broker.orders.buy_limit/sell_limit
       attach_broker_order_id
       poll_order_status
       cancel_remaining_order if needed
       update_order_status
       record execution delta
       update trade_plan status
```

## open order 동기화

새 child order를 만들기 전에 `sync_open_orders_for_plan()`이 열린 주문을 먼저 확인한다.

열린 주문 상태:

```text
SUBMITTED, ACCEPTED, PARTIAL, MODIFIED
```

상태 조회가 안 되거나 취소 확인이 안 되면 plan은 `ORDERED`로 남고 새 주문을 만들지 않는다. 이 상태는 reconciler 또는 다음 사이클에서 다시 확인해야 한다.

## child order 결정

`choose_child_order()`는 최우선 호가와 잔량을 읽는다.

| 값 | 기준 |
|---|---|
| 기준 가격 | BUY는 askp1, SELL은 bidp1 |
| 공격적 지정가 | BUY는 tick 위, SELL은 tick 아래 |
| child 수량 | `remaining_qty`, `max_child_qty`, 최우선 잔량 참여율 중 최소 |

기본 `ExecutionConfig`:

| 설정 | 기본값 |
|---|---:|
| `max_child_qty` | 100 |
| `max_attempts` | 20 |
| `child_timeout_sec` | 8 |
| `cancel_confirm_timeout_sec` | 5 |
| `poll_interval_sec` | 1.0 |
| `max_top_level_participation` | 0.20 |
| `aggressive_limit_ticks` | 1 |

## 상태 전이

plan 상태:

| 상황 | 상태 |
|---|---|
| 요청 수량 <= 0 | `SKIPPED` |
| 누적 체결이 계획 수량 이상 | `DONE` |
| 열린 브로커 주문 미확정 | `ORDERED` |
| 기업 위험으로 BUY 차단 | `SKIPPED`, reason `COMPANY_RISK_BLOCKED` |
| 신규 주문 제출 후 브로커 주문번호 연결 | `ORDERED` |
| 전량 체결 확인 | `DONE` |
| 일부 체결/미확정/재시도 필요 | `ORDERED` |
| KeyboardInterrupt | `CANCELLED` |

order 상태:

| 상황 | 상태 |
|---|---|
| 로컬 주문 행 생성 | `SUBMITTED` |
| broker order id 연결 | `ACCEPTED` |
| 일부 체결 | `PARTIAL` |
| 전량 체결 | `FILLED` |
| 잔량 취소 | `CANCELLED` |
| broker order id 전 실패 | `REJECTED` |

`executions`는 누적 체결 수량이 아니라 새로 확인된 delta만 저장한다.

## 재시도되는 조건

다음 조건은 plan을 바로 닫지 않고 이후 사이클에서 다시 볼 수 있다.

- 매수가능수량이 0
- 매도가능수량이 0
- 현재 호가가 `price_deviation_limit`을 벗어남
- open order 상태가 미확정
- 일부 체결 후 잔량이 남음

이 때문에 executor 종료 기준은 단순히 한 사이클 실행 완료가 아니라 `STATUS`의 `PENDING/ORDERED = 0`이다.
