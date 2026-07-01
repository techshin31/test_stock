# apps/trader

QuantPilot 자동매매 서비스. `risk_neutral` 전략을 하루 3단계(planner → executor → reconciler)로 나눠 실행한다.

## 명령어

```bash
python -m apps.trader planner    [--test]
python -m apps.trader executor   [--test]
python -m apps.trader reconciler [--test]
```

| 명령 | 시점 | 역할 |
|---|---|---|
| `planner` | 장전 (08:30) | 포지션 동기화 → 전략 계산 → `trade_plans` 저장 |
| `executor` | 장중 (09:00~15:20) | `trade_plans`를 사이클마다 조회해 주문 실행 (오더북 슬라이싱) |
| `reconciler` | 장마감 (15:40) 또는 실행 계획 완료 후 | 체결 내역 reconcile, 포지션 재동기화, Slack 알림 |

`--test`를 주면 `TRADER_SKIP_WAIT=true`가 설정되어 `wait_until()`/`is_market_hours()`/`is_trading_day()`의 시간 대기가 모두 즉시 통과한다 ([scheduler.py](scheduler.py)). `planner --test`는 universe가 비어 있으면 [`seed_test_universe`](../../storage/postgres/repositories/universe_repo.py)로 테스트용 종목을 채운다.

> **주의**: `executor --test`는 `while is_market_hours():` 루프가 `TRADER_SKIP_WAIT=true`일 때 시간 조건으로는 자연 종료되지 않는다. `PENDING/ORDERED` 계획이 0개가 되면 조기 종료하지만, 계속 재시도 가능한 계획이 남아 있으면 매 사이클(`CYCLE_INTERVAL_SEC`, 기본 60초)마다 모의투자 계좌에 실제 주문을 제출하므로 별도의 시간 제한(타임아웃) 없이 실행하지 말 것.

## 사전 준비 (환경 변수)

`apps/trader/.env`에 설정한다 ([config.py](config.py)):

| 변수 | 필수 | 기본값 | 설명 |
|---|---|---|---|
| `KIS_APP_KEY` / `KIS_APP_SECRET` | ✅ | - | KIS API 인증 |
| `KIS_DOMESTIC_STOCK_ACCOUNT_NO` (또는 `KIS_ACCOUNT_NO`) | ✅ | - | 계좌번호 |
| `POSTGRES_HOST` / `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB` | ✅ | - | DB 접속 정보 |
| `POSTGRES_PORT` | | `5432` | |
| `KIS_ENV` | | `paper` | `paper`(모의투자) / `real`(실거래) |
| `ALLOW_LIVE_ORDER` | | `false` | `KIS_ENV=real`일 때 실주문을 명시적으로 허용 |
| `STRATEGY_NAME` | | `risk_neutral` | `strategies` 테이블 조회 키 |
| `DAILY_LOSS_LIMIT` | | `0.10` | 일일 손실 한도. `0 < 값 <= 1`이면 전일 마감 총자산 대비 비율(`0.10` = 10%), `1`보다 크면 원화 고정 한도 |
| `CYCLE_INTERVAL_SEC` | | `60` | executor 사이클 간격(초) |
| `SLACK_WEBHOOK_URL` | | - | reconciler 종료 알림 (없으면 알림 생략) |
| `AUDIT_LOG_PATH` | | `logs/trader_audit.jsonl` | 감사 로그 경로 |

`KIS_ENV=real`인데 `ALLOW_LIVE_ORDER=true`가 없으면 시작 시 즉시 종료된다. 그 외에도 [`core/trade/gate.py`](../../core/trade/gate.py)의 `check_live_order_gate()`를 통과해야 한다.

## planner 동작 ([planner.py](planner.py))

1. 포지션 동기화 — 브로커 잔고를 조회해 `positions`/`universe`를 맞춘다. universe에 없는데 보유 중인 종목은 `SELL_ONLY`로 등록한다.
2. universe에서 거래 대상(`ACTIVE`/`SELL_ONLY`) 종목과 방어자산(채권 ETF) OHLCV를 yfinance로 조회한다.
3. KOSPI 지수 기준 레짐(REGIME) 계산, 종목별 레짐 계산.
4. 종목별 전략 신호 계산 — `position_after`(매일 채워지는 "유지해야 할 목표 비중")를 그날의 목표 비중으로 사용한다. *(주의: sparse한 `sig_series`를 직접 쓰면 트리거가 발생하지 않은 신규 편입 종목은 캐치업 주문이 생성되지 않는다.)*
5. 목표 비중 결정(`decide_target_weights_for_day`) → 종목별 최종 `target_weights`.
6. **`trade_plans` 저장** — 거래 대상 종목 전체(`trade_symbols ∪ target_weights.keys()`)를 순회하며 한 건씩 upsert한다. 주문 가능하면 `plan_status_code='PENDING'`, 그렇지 않으면 `'SKIPPED'` + 사유 코드(`NO_SIGNAL`/`BELOW_MIN_QTY`/`SELL_ONLY_BLOCKED`)를 남긴다. → 매일 universe 전체의 의사결정 내역이 DB에 남아 "왜 오늘 이 종목은 주문이 없었는가"를 사후에 조회할 수 있다.

`order_side_code`/`planned_qty`는 `SKIPPED` 계획에서는 `NULL`이 허용된다 ([03_trader_schema.sql](../../storage/postgres/schema/03_trader_schema.sql)).

## executor 동작 ([runner.py](runner.py))

사이클마다 브로커 잔고를 조회해 현재 총자산(`tot_evlu_amt`)을 구하고, [`check_daily_loss_limit`](../../core/trade/gate.py)으로 **"전일 장마감 총자산(`balance_history`) 대비 현재 총자산"** 손익이 한도를 넘는지 확인한다. 기본 손실 한도는 전일 마감 총자산의 10%(`DAILY_LOSS_LIMIT=0.10`)다. 당일 체결의 현금흐름(매수=-, 매도=+) 합을 쓰지 않는 이유는, 그 방식은 매수만 해도 "손실"로 잘못 잡히고 보유 종목의 평가손익을 반영하지 못하기 때문이다. `balance_history`에 전일 스냅샷이 없으면(reconciler 미실행 등) 체크를 건너뛴다.

한도를 넘지 않으면 `trade_plans`에서 `PENDING`/`ORDERED` 상태 계획을 조회해 [`execute_plan_with_orderbook_slicing`](../../core/trade/execution.py)으로 실행한다. 개별 계획에서 예외가 발생해도 해당 계획만 건너뛰고 다음 사이클에 재시도한다.

## reconciler 동작

장마감 후 브로커 체결 내역으로 `orders`/`executions`를 reconcile하고, 포지션을 재동기화한다. 단, 오늘 `trade_plans`가 있고 `PENDING/ORDERED`가 0개이면 15:40 대기를 건너뛰고 즉시 실행한다. 이어서 브로커 잔고(총자산/현금)를 `balance_history`에 스냅샷으로 저장한다 — 다음 거래일 executor의 손실 한도 체크가 이 스냅샷을 "전일 마감 자산" 기준으로 사용한다. 마지막으로 최종 상태를 Slack으로 알린다(`SLACK_WEBHOOK_URL` 설정 시).

## 로그

- 콘솔: `[PLANNER]`/`[EXECUTOR]`/`[RUNNER]`/`[STATUS]` 접두사로 진행 상황 출력.
- 감사 로그: `AUDIT_LOG_PATH`(기본 `logs/trader_audit.jsonl`)에 JSON Lines로 STARTUP/GATE/CYCLE_START/ORDER/CYCLE_END/EOD_RECONCILE/ERROR/LOSS_LIMIT_BREACH/POSITION_SYNC 이벤트를 남긴다 ([audit.py](audit.py)).
