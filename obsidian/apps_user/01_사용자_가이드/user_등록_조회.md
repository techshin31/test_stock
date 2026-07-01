---
title: user 등록 조회
created: 2026-06-30
source_basis: code_only
tags:
  - user
  - operator
  - credential
---

# user 등록 조회

근거 코드: `apps/user/__main__.py`, `apps/user/config.py`, `apps/user/.env.sample`

## 사전 준비

PostgreSQL이 실행 중이어야 한다.

```bash
docker compose -f storage/postgres/docker-compose.yml up -d
```

사용자 등록용 환경 파일을 준비한다.

```bash
cp apps/user/.env.sample apps/user/.env
```

암호화 키가 없으면 API 키/시크릿을 저장하거나 조회할 수 없다.

```bash
python -c "from core.utils.crypto import generate_key; print(generate_key())"
```

생성한 값을 `CREDENTIAL_ENCRYPTION_KEY`에 넣는다. 이 키는 이후 Trader가 DB 자격증명을 복호화할 때도 같은 값이어야 한다.

## 실행 명령

사용자와 자격증명을 등록한다.

```bash
python -m apps.user register
```

등록된 사용자의 자격증명 목록을 조회한다.

```bash
python -m apps.user list
```

다른 환경 파일을 쓰려면 `QUANTPILOT_ENV_FILE`로 경로를 지정한다.

```bash
QUANTPILOT_ENV_FILE=apps/user/.env python -m apps.user register
```

PowerShell에서는 다음 형태가 안전하다.

```powershell
$env:QUANTPILOT_ENV_FILE="apps/user/.env"
python -m apps.user register
```

## register 실행 흐름

```text
load_config
  -> PostgreDB(build_db_config)
  -> fetch_user_by_email(USER_EMAIL)
  -> 없으면 create_user
  -> 주식 계좌 save_broker_credential
  -> 선물 계좌 env가 둘 다 있으면 추가 save_broker_credential
  -> db.close
```

등록 결과는 계좌번호 끝자리만 마스킹해서 출력한다.

```text
[INFO] 신규 사용자 생성 완료: id=1, email=trader@example.com
[INFO] 주식 계좌 저장 완료: id=1, broker=KIS, env=PAPER, account=****2156
```

기존 사용자가 있으면 새 사용자를 만들지 않고 같은 `USER_EMAIL`의 `users.id`를 사용한다.

## list 실행 흐름

```text
load_config
  -> PostgreDB(build_db_config)
  -> fetch_user_by_email(USER_EMAIL)
  -> fetch_credentials_by_user(user.id)
  -> api_key/api_secret 복호화
  -> 계좌번호 마스킹 출력
  -> db.close
```

목록 조회 출력은 API 키와 시크릿을 보여주지 않는다.

```text
[USER] id=1 | email=trader@example.com | active=True
  [1] broker=KIS | type=STOCK | env=PAPER | account=****2156 | active=True
```

현재 구현은 `list`도 `load_config()`를 공유한다. 그래서 조회만 하더라도 `KIS_APP_KEY`, `KIS_APP_SECRET`, 주식 계좌번호 같은 등록용 필수 환경 변수까지 필요하다.

## 중복 등록 동작

자격증명 저장은 insert-only가 아니다.

`user_broker_credentials`의 unique key는 다음 조합이다.

```text
(user_id, broker_code, account_number, environment_code)
```

같은 조합이 이미 있으면 새 행을 만들지 않고 다음 값을 갱신한다.

| 갱신 항목 | 의미 |
|---|---|
| `api_key` | 새 값으로 암호화 저장 |
| `api_secret` | 새 값으로 암호화 저장 |
| `extra` | 계좌상품코드와 계좌 유형 갱신 |
| `is_active` | `TRUE`로 재활성화 |
| `updated_at` | 현재 시각으로 갱신 |

## 문제 해결 기준

| 증상 | 확인할 것 |
|---|---|
| `[CONFIG] 필수 환경 변수 누락` | [[환경변수_레퍼런스|환경변수 레퍼런스]]의 필수 항목 |
| 암호화 키 오류 | `CREDENTIAL_ENCRYPTION_KEY`가 Fernet 키 형식인지 확인 |
| DB 연결 실패 | `POSTGRES_HOST`, `POSTGRES_PORT`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB` |
| Trader가 자격증명을 못 찾음 | `USER_EMAIL`, `BROKER_CODE`, `KIS_ENV`가 user 등록 시점과 trader 실행 시점에 같은지 확인 |
| REAL/PAPER 불일치 | `KIS_ENV=real`이면 `environment_code=REAL`, 그 외는 `PAPER`로 저장됨 |

## 안전 주의

- `apps/user/.env`는 비밀값을 담으므로 문서나 커밋에 포함하지 않는다.
- `CREDENTIAL_ENCRYPTION_KEY`는 DB 데이터 복호화 키다. 앱 키/시크릿만큼 중요하게 보관한다.
- 계좌번호는 DB에 평문으로 저장된다. 출력이나 운영 캡처에서는 마스킹된 값만 공유한다.
