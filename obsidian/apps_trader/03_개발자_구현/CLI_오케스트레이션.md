---
title: CLI 오케스트레이션
created: 2026-06-30
source_basis: code_only
tags:
  - trader
  - developer
  - cli
---

# CLI 오케스트레이션

근거 코드: `apps/trader/__main__.py`

## 진입점

```text
python -m apps.trader planner
python -m apps.trader executor
python -m apps.trader reconciler
```

`_parse_args()`는 command 3개와 `--test` 옵션을 받는다.

| command | 함수 | 역할 |
|---|---|---|
| `planner` | `run_planner(test=args.test)` | 장전 계획 생성 |
| `executor` | `run_executor()` | 장중 실행 루프 |
| `reconciler` | `run_reconciler()` | 장마감 정산 |

`--test`가 있으면 `main()`이 `os.environ["TRADER_SKIP_WAIT"] = "true"`를 설정한다.

## 공통 초기화 `_init`

```text
_init
  -> load_config()
  -> check_live_order_gate()
  -> audit.log_gate()
  -> PostgreDB(build_db_config())
  -> fetch_user_by_email(cfg.user_email)
  -> fetch_credential_by_account_type(
       user_id=user["id"],
       broker_code=cfg.broker_code,
       account_type="STOCK",
       environment_code=cfg.environment_code
     )
  -> KisBroker.from_db_credential(credential)
  -> audit.log_startup()
  -> return cfg, db, broker
```

초기화 실패 조건:

| 실패 지점 | 동작 |
|---|---|
| 필수 env 누락 | `load_config()`가 stderr 출력 후 `sys.exit(1)` |
| `KIS_ENV=real` + `ALLOW_LIVE_ORDER` 부재 | `load_config()` 또는 gate에서 종료 |
| 사용자 없음 | DB close 후 `sys.exit(1)` |
| STOCK 자격증명 없음 | DB close 후 `sys.exit(1)` |

## run_planner

```text
_init
  -> plan_date = date.today()
  -> is_trading_day()
  -> wait_until(PRE_MARKET_START)
  -> pre_market_sync()
  -> run_strategy_planning(..., balance=balance)
  -> print_status(fetch_status(...))
  -> db.close()
```

`pre_market_sync()`가 반환한 KIS balance 응답은 `run_strategy_planning()`으로 전달된다. 같은 balance API 호출을 중복하지 않기 위한 경로다.

## run_executor

```text
_init
  -> plan_date = date.today()
  -> is_trading_day()
  -> has_executable_plans(PENDING/ORDERED)
  -> wait_until(MARKET_OPEN)
  -> while is_market_hours():
       run_one_cycle()
       status = fetch_status()
       print_status(status)
       if status.pending_plans == 0: break
       sleep(cycle_interval_sec - elapsed)
  -> db.close()
```

루프 시작 전과 사이클 후 모두 실행 대상 plan 존재 여부를 본다. 실행 대상의 기준은 `PENDING/ORDERED`다.

## run_reconciler

```text
_init
  -> status = fetch_status()
  -> if total_plans > 0 and pending_plans == 0:
       15:40 대기 skip
     else:
       wait_until(EOD_START)
  -> reconcile_orders_from_broker_history()
  -> pre_market_sync()
  -> mark_empty_sell_only_removed()
  -> balance_history snapshot 저장
  -> final status 출력
  -> optional Slack notify
  -> db.close()
```

reconcile 예외는 잡아서 audit/log 출력 후 다음 단계로 진행한다. 포지션 동기화 또는 잔고 조회가 실패하면 `balance_history` 저장은 건너뛴다.

## 시간 상수

근거 코드: `apps/trader/scheduler.py`

| 상수 | 값 | 의미 |
|---|---|---|
| `PRE_MARKET_START` | 08:30 | planner 시작 대기 |
| `MARKET_OPEN` | 09:00 | executor 루프 시작 |
| `MARKET_CLOSE` | 15:20 | executor 루프 종료 |
| `EOD_START` | 15:40 | reconciler 시작 대기 |

거래일 여부는 `core.utils.trading_calendar.is_krx_trading_day()`로 확인한다. `TRADER_SKIP_WAIT=true`이면 거래일/시간 검사를 통과한다.

## 개발상 주의점

- `KIS_ENV`는 `config.py`에서 lower 처리하지 않는다. 대문자 `REAL`은 현재 코드에서 PAPER처럼 취급될 수 있다.
- `PostgreDB`는 Singleton이므로 같은 프로세스에서 서로 다른 DB config를 섞는 테스트는 주의한다.
- `run_executor()`의 `--test`는 시간 조건을 계속 통과시킨다. 테스트에서 `fetch_status().pending_plans == 0`이 되도록 monkeypatch하거나 별도 중단 조건을 둔다.
- `run_reconciler()`는 reconcile 실패 후에도 balance snapshot 단계로 진행한다. 이 설계는 장마감 잔고 기준을 최대한 남기려는 방향이다.
