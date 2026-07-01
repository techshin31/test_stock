---
title: reconciler 정산동기화
created: 2026-06-30
source_basis: code_only
tags:
  - trader
  - developer
  - reconciler
---

# reconciler 정산동기화

근거 코드: `apps/trader/__main__.py`, `core/trade/reconcile.py`, `core/trade/position_sync.py`, `storage/postgres/repositories/balance_repo.py`

## 실행 흐름

```text
run_reconciler
  -> _init
  -> fetch_status
  -> wait_until(EOD_START) 또는 skip
  -> reconcile_orders_from_broker_history
  -> pre_market_sync
  -> mark_empty_sell_only_removed
  -> insert_balance_history
  -> final status
  -> optional Slack notify
```

대기 skip 조건:

```text
status.total_plans > 0 and status.pending_plans == 0
```

여기서 `pending_plans`는 `PENDING/ORDERED` 합계다.

## broker history reconcile

`reconcile_orders_from_broker_history()`는 KIS 일별 주문 이력을 조회한다.

```text
broker.history.get(kis_start, kis_end)
  -> output1 rows
  -> broker_order_id(odno)로 local orders 조회
  -> managed order만 처리
  -> execution delta 저장
  -> order 상태 업데이트
```

로컬 `orders`에 없는 브로커 주문은 건너뛴다. 이 함수는 QuantPilot이 관리하는 주문만 정산한다.

## execution delta

이미 저장된 체결 수량을 빼고 새로 확인된 체결만 저장한다.

```text
delta_qty = broker_filled_qty - fetch_execution_qty_by_order(order_id)
```

`delta_qty > 0`이고 평균 체결가가 있으면 `executions`에 insert한다.

현재 구현은 commission, tax, slippage를 0으로 저장한다.

## order 상태 결정

KIS 이력 row의 수량으로 표준 상태를 계산한다.

| 조건 | 상태 |
|---|---|
| `cncl_yn = Y` and filled 0 | `CANCELLED` |
| filled >= requested and remaining 0 | `FILLED` |
| filled > 0 | `PARTIAL` |
| 그 외 | `CANCELLED` |

상태 업데이트는 `order_status_history`에도 `EOD_RECONCILE` 이벤트로 남는다.

## 포지션 재동기화

reconcile 이후 `pre_market_sync()`를 다시 호출한다. 이름은 장전 동기화지만 reconciler에서도 재사용한다.

동작:

```text
broker.account.balance()
  -> KIS output1 holdings upsert to positions
  -> DB qty > 0인데 KIS에 없는 종목 zero_out
```

포지션 동기화가 성공하면 SELL_ONLY 중 보유 수량이 0인 종목을 `REMOVED`로 전환한다.

```text
mark_empty_sell_only_removed()
```

## balance_history 저장

KIS balance 응답의 `output2[0]`에서 값을 읽는다.

| KIS field | 저장 |
|---|---|
| `tot_evlu_amt` | `total_value` |
| `prvs_rcdl_excc_amt` | `cash` |
| `total_value - cash` | `stock_value` |

`daily_return`은 직전 `balance_history.total_value` 대비 계산한다. 기존 이력이 없으면 당일 총자산을 기준으로 0에 가깝게 시작한다.

이 스냅샷은 다음 거래일 executor의 일일 손실 한도 기준이다.

## Slack 알림

`SLACK_WEBHOOK_URL`이 설정되어 있으면 최종 상태를 Slack으로 보낸다.

메시지 내용:

```text
계획 done/total
체결 총수량
당일 손익
```

Slack 전송 실패는 `notify_slack()` 내부에서 출력만 하고 예외를 전파하지 않는다.

## 예외 처리

`reconcile_orders_from_broker_history()` 예외는 잡아서 audit/error 로그로 남긴 뒤 포지션 동기화와 잔고 스냅샷을 계속 시도한다.

포지션 동기화 실패로 `eod_balance`가 없으면 `balance_history` 저장은 건너뛴다.
