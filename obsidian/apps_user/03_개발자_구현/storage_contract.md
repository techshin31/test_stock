---
title: storage contract
created: 2026-06-30
source_basis: code_only
tags:
  - user
  - developer
  - storage
  - credential
---

# storage contract

근거 코드:

- `storage/postgres/schema/03_user_schema.sql`
- `storage/postgres/repositories/user_repo.py`
- `storage/postgres/repositories/credential_repo.py`
- `core/utils/crypto.py`
- `core/trade/kis_broker.py`

## 테이블 관계

```text
users.id
  -> user_broker_credentials.user_id
```

`users.email`은 unique다. `user_broker_credentials`는 사용자별로 증권사, 계좌, 거래 환경 조합을 unique하게 관리한다.

## users

| 컬럼 | 타입 | 의미 |
|---|---|---|
| `id` | `SERIAL PRIMARY KEY` | 사용자 고유 ID |
| `email` | `VARCHAR(255) UNIQUE NOT NULL` | 로그인/조회 식별자 |
| `display_name` | `VARCHAR(100)` | 표시 이름 |
| `is_active` | `BOOLEAN DEFAULT TRUE` | 활성 사용자 여부 |
| `created_at` | `TIMESTAMPTZ DEFAULT NOW()` | 생성 시각 |

Repository 함수:

| 함수 | 역할 |
|---|---|
| `create_user(db, email, display_name)` | 사용자 생성 후 `id` 반환 |
| `fetch_user_by_email(db, email)` | 이메일로 사용자 조회 |
| `fetch_user_by_id(db, user_id)` | ID로 사용자 조회 |

## user_broker_credentials

| 컬럼 | 타입 | 의미 |
|---|---|---|
| `id` | `SERIAL PRIMARY KEY` | 자격증명 ID |
| `user_id` | `INT REFERENCES users(id)` | 소유 사용자 |
| `broker_code` | `VARCHAR(50)` | 증권사 코드 |
| `account_number` | `VARCHAR(50)` | 증권 계좌번호 |
| `api_key` | `TEXT` | 암호화된 API 키 |
| `api_secret` | `TEXT` | 암호화된 API 시크릿 |
| `environment_code` | `VARCHAR(20)` | `REAL` 또는 `PAPER` |
| `extra` | `JSONB DEFAULT '{}'` | 증권사별 확장 인증 정보 |
| `is_active` | `BOOLEAN DEFAULT TRUE` | 활성 자격증명 여부 |
| `created_at` | `TIMESTAMPTZ DEFAULT NOW()` | 등록 시각 |
| `updated_at` | `TIMESTAMPTZ DEFAULT NOW()` | 수정 시각 |

제약:

```text
UNIQUE (user_id, broker_code, account_number, environment_code)
CHECK (environment_code IN ('REAL', 'PAPER'))
```

인덱스:

```text
idx_user_broker_credentials_user_id(user_id)
```

## 자격증명 저장 계약

`save_broker_credential()`은 다음 필드를 받아 insert 또는 update를 수행한다.

```text
user_id
broker_code
account_number
api_key
api_secret
environment_code
extra
```

충돌 기준:

```text
(user_id, broker_code, account_number, environment_code)
```

충돌 시 갱신:

```text
api_key = EXCLUDED.api_key
api_secret = EXCLUDED.api_secret
extra = EXCLUDED.extra
is_active = TRUE
updated_at = NOW()
```

이 동작 때문에 같은 계좌를 다시 등록하면 키 교체와 자격증명 재활성화가 동시에 일어난다.

## 암호화 계약

`credential_repo.py`는 저장 직전에 다음 값을 암호화한다.

| 평문 입력 | 저장 컬럼 | 암호화 함수 |
|---|---|---|
| `api_key` | `user_broker_credentials.api_key` | `core.utils.crypto.encrypt` |
| `api_secret` | `user_broker_credentials.api_secret` | `core.utils.crypto.encrypt` |

`account_number`, `broker_code`, `environment_code`, `extra`는 암호화하지 않는다.

복호화는 조회 repository에서 수행한다.

| 함수 | 복호화 여부 |
|---|---|
| `fetch_credentials_by_user` | 반환 전 `api_key`, `api_secret` 복호화 |
| `fetch_active_credential` | 반환 전 `api_key`, `api_secret` 복호화 |
| `fetch_credential_by_account_type` | 반환 전 `api_key`, `api_secret` 복호화 |

`CREDENTIAL_ENCRYPTION_KEY`가 없거나 저장 당시 키와 다르면 복호화 경로가 실패한다.

## extra JSON 계약

`apps/user register`가 저장하는 KIS `extra` 구조:

```json
{
  "account_product_code": "01",
  "account_type": "STOCK"
}
```

Trader는 `fetch_credential_by_account_type()`에서 다음 조건을 사용한다.

```sql
extra->>'account_type' = %s
```

따라서 `account_type`은 단순 표시용이 아니라 downstream 조회 키다.

## KisBroker 변환 계약

`KisBroker.from_db_credential()`은 복호화된 credential dict를 받아 `KisConfig`를 만든다.

사용하는 필드:

| credential field | KisConfig field |
|---|---|
| `api_key` | `app_key` |
| `api_secret` | `app_secret` |
| `account_number` | `domestic_stock.account_no` |
| `extra.account_product_code` | `domestic_stock.product_code` |
| `environment_code` | `KisEnv.REAL` 또는 `KisEnv.PAPER` |

`extra.account_product_code`가 없으면 기본값 `"01"`을 사용한다.

## 개발 변경 시 체크포인트

- `environment_code` 값을 추가하려면 DB CHECK 제약, User config, Trader config, KisBroker 변환을 함께 바꿔야 한다.
- `account_type` 값을 바꾸면 Trader 조회 조건도 같이 바꿔야 한다.
- 암호화 대상을 늘리면 repository 반환 dict를 사용하는 downstream 코드의 기대 필드를 점검해야 한다.
- `list`에서 복호화가 필요 없다면 `credential_repo`에 마스킹 전용 조회 함수를 분리할 수 있다.
- 사용자 생성과 자격증명 저장을 원자적으로 보장하려면 `PostgreDB.transaction()`을 사용해 `run_register()`를 재구성해야 한다.
