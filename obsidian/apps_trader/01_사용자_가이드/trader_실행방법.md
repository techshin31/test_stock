---
title: trader 실행방법
created: 2026-06-30
source_basis: code_only
tags:
  - trader
  - operator
  - cli
---

# trader 실행방법

근거 코드: `apps/trader/__main__.py`, `apps/trader/scheduler.py`, `apps/trader/config.py`

## 사전 준비

Trader는 DB에 등록된 사용자와 증권사 자격증명을 필요로 한다.

```bash
python -m apps.user register
```

또한 Analyzer가 발행한 운영 universe가 있어야 `planner`가 실제 운영 후보를 읽을 수 있다.

```text
Collector 원천 적재
  -> Analyzer 분석/발행
  -> universe
  -> Trader planner
```

로컬 테스트에서는 `planner --test`가 universe가 비어 있을 때 테스트 universe를 seed할 수 있다. 이 함수는 운영 데이터 경로가 아니라 테스트 편의 경로다.

## 명령어

```bash
python -m apps.trader planner
python -m apps.trader executor
python -m apps.trader reconciler
```

각 command에는 `--test`를 붙일 수 있다.

```bash
python -m apps.trader planner --test
```

`--test`는 `TRADER_SKIP_WAIT=true`를 설정해 거래일 검사와 시간 대기를 건너뛴다.

## command별 역할

| command | 실행 시점 | 코드 흐름 |
|---|---|---|
| `planner` | 장전 08:30 | `_init -> pre_market_sync -> run_strategy_planning -> print_status` |
| `executor` | 장중 09:00-15:20 | `_init -> has_executable_plans -> run_one_cycle 반복 -> print_status` |
| `reconciler` | 장마감 15:40 | `_init -> reconcile_orders_from_broker_history -> pre_market_sync -> balance_history 저장` |

## 공통 초기화

세 command는 모두 `_init()`을 먼저 통과한다.

```text
load_config
  -> check_live_order_gate
  -> PostgreDB(build_db_config)
  -> fetch_user_by_email(USER_EMAIL)
  -> fetch_credential_by_account_type(account_type="STOCK")
  -> KisBroker.from_db_credential
  -> audit.log_startup
```

사용자나 주식 계좌 자격증명이 없으면 Trader는 시작하지 않고 `python -m apps.user register`를 먼저 실행하라고 안내한다.

## planner 실행 결과

`planner`는 장전 포지션 동기화를 먼저 수행한다. KIS 잔고에 있는 종목은 `positions`에 upsert되고, DB에는 있었지만 KIS 잔고에 없어진 종목은 qty 0으로 처리된다.

그 다음 `universe`를 읽어 전략 계산을 수행하고 `trade_plans`를 만든다.

출력 예시의 의미:

| 출력 | 의미 |
|---|---|
| `[PLANNER] 포지션 동기화` | 브로커 잔고를 DB `positions`와 맞춤 |
| `[PLANNER] SELL_ONLY 등록` | 보유 중이지만 universe에 없는 종목을 청산 대상으로 재등록 |
| `[PLANNER] [BUY] ...` | 주문 가능한 `PENDING` 계획 생성 |
| `[PLANNER] [SKIP] ...` | 오늘 주문하지 않는 이유를 `SKIPPED`로 기록 |

## executor 실행 결과

`executor`는 시작 전에 오늘 `PENDING/ORDERED` 계획이 있는지 확인한다.

| 상태 | 동작 |
|---|---|
| 계획 0개 | planner를 먼저 실행하라고 안내하고 종료 |
| 계획은 있지만 `PENDING/ORDERED` 0개 | 장중 루프를 시작하지 않고 종료 |
| 실행 대상 있음 | 09:00까지 대기 후 장중 루프 시작 |

각 사이클은 다음을 수행한다.

```text
broker.account.balance()
  -> check_daily_loss_limit
  -> fetch_executable_trade_plans(PENDING, ORDERED)
  -> execute_plan_with_orderbook_slicing
  -> STATUS 출력
```

손실 한도 기본값은 전일 마감 총자산의 10%(`DAILY_LOSS_LIMIT=0.10`)다. 현재 총자산이 이 기준보다 더 많이 줄어 있으면 `[RUNNER] 손실 한도 초과`를 출력하고 해당 사이클을 중단한다.

사이클 후 `PENDING/ORDERED`가 0개가 되면 조기 종료한다.

## reconciler 실행 결과

`reconciler`는 보통 15:40까지 대기한다. 다만 오늘 계획이 있고 `PENDING/ORDERED`가 0개이면 대기를 건너뛴다.

실행 작업:

1. KIS 일별 주문 이력으로 `orders`와 `executions`를 reconcile한다.
2. KIS 잔고와 `positions`를 다시 동기화한다.
3. SELL_ONLY 종목 중 보유 수량이 0인 항목을 `REMOVED`로 바꾼다.
4. 장마감 잔고를 `balance_history`에 저장한다.
5. `SLACK_WEBHOOK_URL`이 있으면 요약 알림을 보낸다.

## `--test` 주의

`planner --test`는 시간 대기를 건너뛰고, universe가 비어 있으면 테스트 universe를 seed한다.

`executor --test`도 시간 조건을 건너뛰므로 `is_market_hours()`가 계속 True처럼 동작한다. `PENDING/ORDERED`가 0개가 되면 종료하지만, 재시도 가능한 계획이 계속 남으면 계속 주문 사이클을 돈다. 모의투자 계좌라도 별도 타임아웃 없이 오래 실행하지 않는다.

## 상태 출력 읽기

`print_status()`는 다음 형식으로 출력한다.

```text
[STATUS] 2026-06-30 | 계획 15개 | DONE 5개 | SKIPPED 10개 | PENDING/ORDERED 0개 | 체결 502주 | 당일 손익 -7,175,582원
```

| 항목 | 기준 |
|---|---|
| `DONE` | 완료된 `trade_plans` |
| `SKIPPED` | 조건 미충족으로 주문하지 않은 계획 |
| `PENDING/ORDERED` | executor가 계속 살펴볼 실행 대상 |
| `체결` | 당일 `executions.qty` 합 |
| `당일 손익` | 당일 `executions.net_amount` 합. 손실 한도 기준과는 다름 |
