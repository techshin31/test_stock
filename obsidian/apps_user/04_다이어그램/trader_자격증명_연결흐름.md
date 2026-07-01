---
title: Trader 자격증명 연결흐름
created: 2026-06-30
source_basis: code_only
tags:
  - user
  - trader
  - diagram
---

# Trader 자격증명 연결흐름

근거 코드: `apps/trader/__main__.py`, `apps/trader/config.py`, `storage/postgres/repositories/credential_repo.py`, `core/trade/kis_broker.py`

```mermaid
flowchart TD
    U["apps/user register"] --> U1["users"]
    U --> U2["user_broker_credentials"]
    U2 --> U3["api_key/api_secret 암호화 저장"]
    U2 --> U4["extra.account_type = STOCK"]
    U2 --> U5["environment_code = PAPER or REAL"]

    T["python -m apps.trader planner/executor/reconciler"] --> T1["load_config()"]
    T1 --> T2["check_live_order_gate()"]
    T2 --> T3{gate allowed?}
    T3 -->|no| T4["sys.exit(1)"]
    T3 -->|yes| T5["fetch_user_by_email(USER_EMAIL)"]
    T5 --> T6{user exists?}
    T6 -->|no| T7["apps.user register 안내 후 종료"]
    T6 -->|yes| T8["fetch_credential_by_account_type(STOCK, env)"]
    T8 --> T9{credential exists?}
    T9 -->|no| T10["apps.user register 안내 후 종료"]
    T9 -->|yes| T11["api_key/api_secret 복호화"]
    T11 --> T12["KisBroker.from_db_credential()"]
    T12 --> T13["KisConfig 생성"]
    T13 --> T14["Trader 업무 실행"]

    U1 -. "USER_EMAIL" .-> T5
    U2 -. "broker_code + account_type + environment_code" .-> T8
```

## Trader가 기대하는 저장 상태

| 조건 | 코드 기준 |
|---|---|
| 사용자 존재 | `fetch_user_by_email(db, cfg.user_email)` |
| 활성 STOCK 자격증명 존재 | `fetch_credential_by_account_type(..., account_type="STOCK")` |
| 증권사 일치 | `broker_code=cfg.broker_code` |
| 거래 환경 일치 | `environment_code=cfg.environment_code` |
| 복호화 가능 | `CREDENTIAL_ENCRYPTION_KEY`가 저장 시점과 동일 |

## 실패 시 안내

Trader는 사용자 또는 주식 계좌 자격증명을 찾지 못하면 다음 명령을 먼저 실행하라고 안내한다.

```bash
python -m apps.user register
```

이 안내는 단순 친절 메시지가 아니라 실제 dependency다. Trader는 `.env`에서 API 키/시크릿을 직접 읽지 않고 DB 자격증명을 사용한다.
