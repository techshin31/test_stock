---
title: storage contract
created: 2026-06-30
source_basis: code_only
tags:
  - trader
  - developer
  - storage
---

# storage contract

근거 코드:

- `storage/postgres/schema/04_trader_schema.sql`
- `storage/postgres/repositories/strategy_repo.py`
- `storage/postgres/repositories/universe_repo.py`
- `storage/postgres/repositories/trade_plan_repo.py`
- `storage/postgres/repositories/order_repo.py`
- `storage/postgres/repositories/execution_repo.py`
- `storage/postgres/repositories/position_repo.py`
- `storage/postgres/repositories/balance_repo.py`
- `storage/postgres/repositories/trade_monitor_repo.py`

## 테이블 역할

| 테이블 | 운영 의미 | 주 사용 코드 |
|---|---|---|
| `strategies` | 전략 이름과 params, 활성 여부 | `strategy_repo.py` |
| `universe` | Analyzer가 발행한 운영 투자 대상과 SELL_ONLY/REMOVED 상태 | `universe_repo.py`, `planner.py`, `reconciler` |
| `trade_plans` | 장전 생성된 당일 주문/미주문 계획 | `planner.py`, `runner.py` |
| `orders` | 브로커 주문 단위 이력 | `execution.py`, `order_repo.py` |
| `order_status_history` | 주문 상태/조회 이벤트 append-only 로그 | `order_repo.py` |
| `executions` | 실제 체결 delta | `execution.py`, `reconcile.py` |
| `positions` | 브로커 잔고 기준 현재 보유 상태 | `position_sync.py` |
| `balance_history` | 장마감 총자산 스냅샷 | `reconciler`, `gate.py` |

## strategies

Trader는 `STRATEGY_NAME`으로 활성 전략을 조회한다.

```sql
SELECT params FROM strategies
WHERE name = %s AND is_active = TRUE
```

전략이 없거나 비활성 상태면 planner는 전략 계산을 할 수 없다.

## universe

`universe`는 Trader의 공식 투자 후보 입력이다. Analyzer publish가 이 테이블을 채우고, Trader는 상태를 운영 관점에서 갱신한다.

| 상태 | 생성/갱신 경로 |
|---|---|
| `ACTIVE` | Analyzer publish 또는 test seed |
| `SELL_ONLY` | Analyzer publish에서 제외된 기존 ACTIVE, 보유 중인데 universe 밖인 종목 |
| `REMOVED` | reconciler가 포지션 0 확인 후 전환 |

`source_fa_company_result_id`는 `04_trader_schema.sql`의 최초 `universe` 정의가 아니라 `06_fa_analysis_schema.sql`에서 `ALTER TABLE universe`로 추가된다. 현재 `publish_fa_run()`은 이 컬럼으로 FA 선정 근거를 연결한다.

## trade_plans

unique key:

```text
(plan_date, strategy_id, symbol)
```

`upsert_trade_plan()`은 같은 날짜/전략/종목의 계획을 갱신한다.

중요 컬럼:

| 컬럼 | 의미 |
|---|---|
| `order_side_code` | BUY/SELL. SKIPPED면 NULL 가능 |
| `planned_qty` | 계획 수량. SKIPPED면 NULL 가능 |
| `planned_price` | 계획 가격 |
| `plan_status_code` | `PENDING`, `ORDERED`, `DONE`, `SKIPPED`, `CANCELLED` |
| `trade_reason_code` | 전략 또는 스킵 사유 |
| `prev_weight`, `target_weight` | 계획 당시 비중 |
| `regime_code` | 계획 당시 시장 국면 |
| `price_deviation_limit` | executor의 호가 편차 제한 |

executor 조회 기준:

```text
plan_status_code IN ('PENDING', 'ORDERED')
```

## orders와 order_status_history

`create_order()`는 `orders`를 만들고 같은 transaction에서 `order_status_history`에 `CREATE` 이벤트를 남긴다.

초기 상태:

```text
orders.order_status_code = SUBMITTED
```

`attach_broker_order_id()`는 브로커 주문번호를 붙이고 `ACCEPTED`로 바꾼다.

`update_order_status()`는 `orders`를 갱신하면서 상태 이력을 추가한다. `order_status_history`는 삭제/수정 대상이 아니라 추적 로그다.

## executions

`insert_execution()`은 order별 체결 delta를 저장한다.

현재 계산:

```text
amount = qty * price
net_amount = -amount for BUY, +amount for SELL
commission = 0
tax = 0
slippage = 0
```

비용/세금/슬리피지는 컬럼이 있지만 현재 실행 경로에서는 0으로 들어간다.

## positions

`positions`는 KIS balance 기준의 현재 보유 상태다.

unique key:

```text
(strategy_id, symbol, instrument_type_code)
```

동기화 규칙:

| 상황 | 동작 |
|---|---|
| KIS balance에 qty > 0 | `upsert_position` |
| DB에는 qty > 0인데 KIS에 없음 | `zero_out_position` |

`positions`는 backtest 결과나 계획이 아니라 브로커 잔고에 맞춘 운영 상태다.

## balance_history

`balance_history`는 장마감 스냅샷이다.

사용 위치:

| 함수 | 역할 |
|---|---|
| `insert_balance_history` | reconciler가 장마감 잔고 저장 |
| `fetch_latest_total_value` | executor 일일 손실 한도 기준 |
| `fetch_balance_history` | reconciler daily_return 계산 |

스냅샷이 없으면 `check_daily_loss_limit()`은 손실 한도 검사를 건너뛴다.

## monitor query

`trade_monitor_repo.py`가 STATUS의 source of truth다.

| status field | SQL 기준 |
|---|---|
| total | 모든 `trade_plans` |
| done | `plan_status_code = DONE` |
| skipped | `plan_status_code = SKIPPED` |
| pending | `plan_status_code IN (PENDING, ORDERED)` |
| filled qty | 당일 `executions.qty` 합 |
| daily net | 당일 `executions.net_amount` 합 |

## 개발 변경 체크포인트

- plan 상태를 추가하면 `codes`, `trade_monitor_repo.py`, executor 종료 조건, reconciler wait skip 조건을 함께 확인한다.
- 주문 상태를 추가하면 `fetch_open_orders_by_plan()`의 열린 주문 조건과 `_order_status_code()`를 함께 확인한다.
- 비용/세금을 실제 계산하려면 `execution.py`, `reconcile.py`, `executions.net_amount`, STATUS 손익 해석을 같이 수정한다.
- universe 컬럼을 바꾸면 Analyzer publish와 Trader fetch/sync 경로를 함께 점검한다.
- `balance_history` 저장 실패는 다음 거래일 손실 한도 정책에 직접 영향을 준다.
