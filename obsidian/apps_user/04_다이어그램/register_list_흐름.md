---
title: register/list 흐름
created: 2026-06-30
source_basis: code_only
tags:
  - user
  - diagram
  - cli
---

# register/list 흐름

근거 코드: `apps/user/__main__.py`, `apps/user/config.py`, `storage/postgres/repositories/*_repo.py`

```mermaid
flowchart TD
    A["python -m apps.user"] --> B["_parse_args()"]
    B --> C{command}

    C -->|register| R1["run_register()"]
    R1 --> R2["load_config()"]
    R2 --> R3["PostgreDB(build_db_config())"]
    R3 --> R4["fetch_user_by_email(USER_EMAIL)"]
    R4 --> R5{user exists?}
    R5 -->|yes| R6["기존 user_id 사용"]
    R5 -->|no| R7["create_user(email, display_name)"]
    R6 --> R8["save_broker_credential(STOCK)"]
    R7 --> R8
    R8 --> R9{futures env 2개 모두 있음?}
    R9 -->|yes| R10["save_broker_credential(FUTURES)"]
    R9 -->|no| R11["db.close()"]
    R10 --> R11

    C -->|list| L1["run_list()"]
    L1 --> L2["load_config()"]
    L2 --> L3["PostgreDB(build_db_config())"]
    L3 --> L4["fetch_user_by_email(USER_EMAIL)"]
    L4 --> L5{user exists?}
    L5 -->|no| L6["사용자 없음 출력"]
    L5 -->|yes| L7["fetch_credentials_by_user(user.id)"]
    L7 --> L8["api_key/api_secret 복호화"]
    L8 --> L9["계좌번호 마스킹 출력"]
    L6 --> L10["db.close()"]
    L9 --> L10
```

## 핵심 분기

| 분기 | 의미 |
|---|---|
| `register` | 사용자가 없으면 만들고, 계좌 자격증명을 저장 또는 갱신한다. |
| `list` | 등록된 사용자와 자격증명을 조회해 마스킹된 계좌 정보만 출력한다. |
| 선물 계좌 env | 계좌번호와 상품코드가 모두 있을 때만 `FUTURES` 자격증명을 저장한다. |

## 구현상 특징

- `register`와 `list` 모두 동일한 `load_config()`를 사용한다.
- 자격증명 저장/조회 모두 `CREDENTIAL_ENCRYPTION_KEY`가 필요하다.
- `list`는 복호화된 dict를 받지만 API 키/시크릿은 출력하지 않는다.
