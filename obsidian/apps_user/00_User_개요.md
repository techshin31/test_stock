---
title: User 앱 개요
created: 2026-06-30
source_basis: code_only
tags:
  - quantpilot
  - user
  - credential
  - trader
---

# User 앱 개요

`apps/user`는 QuantPilot에서 트레이딩 사용자를 등록하고, 증권사 API 자격증명을 PostgreSQL에 저장하는 CLI 도구다.

이 앱은 Collector나 Analyzer처럼 투자 후보를 만들지 않는다. 대신 Trader가 실제 실행 단계에서 사용할 사용자, 계좌, API 키/시크릿의 기준 데이터를 만든다.

```text
apps/user
  -> users
  -> user_broker_credentials
  -> apps/trader 초기화
  -> KisBroker.from_db_credential
```

## 문서 구조

```text
apps_user/
├── 01_사용자_가이드
├── 02_투자자_해석
├── 03_개발자_구현
└── 04_다이어그램
```

## 먼저 읽기

| 독자 | 먼저 볼 문서 | 목적 |
|---|---|---|
| 사용자/운영자 | [[01_사용자_가이드/user_등록_조회|user 등록 조회]] | `.env` 준비, 등록, 목록 확인 |
| 사용자/운영자 | [[01_사용자_가이드/환경변수_레퍼런스|환경변수 레퍼런스]] | 필수 환경 변수와 기본값 확인 |
| 투자자 | [[02_투자자_해석/계좌와_거래환경_해석|계좌와 거래환경 해석]] | PAPER/REAL, 실주문 안전장치, 자격증명의 투자 의미 |
| 개발자 | [[03_개발자_구현/CLI_실행흐름|CLI 실행흐름]] | `register`, `list`의 실제 함수 경로 |
| 개발자 | [[03_개발자_구현/storage_contract|storage contract]] | DB 스키마, 암호화, upsert 계약 |

## 실제 코드 경로

| 파일 | 역할 |
|---|---|
| `apps/user/__main__.py` | `python -m apps.user register/list` CLI 진입점 |
| `apps/user/config.py` | `.env` 로드, 필수 환경 변수 검증, DB config 생성 |
| `apps/user/.env.sample` | 사용자 등록에 필요한 환경 변수 템플릿 |
| `storage/postgres/repositories/user_repo.py` | `users` 생성/조회 |
| `storage/postgres/repositories/credential_repo.py` | 자격증명 저장/조회/비활성화, API 키/시크릿 암복호화 |
| `storage/postgres/schema/03_user_schema.sql` | `users`, `user_broker_credentials` 테이블 정의 |
| `core/utils/crypto.py` | `CREDENTIAL_ENCRYPTION_KEY` 기반 Fernet 암복호화 |
| `apps/trader/__main__.py` | 등록된 사용자와 주식 계좌 자격증명을 읽어 Trader 시작 |
| `core/trade/kis_broker.py` | DB 자격증명 행을 `KisBroker` 설정으로 변환 |

## 저장되는 핵심 데이터

| 테이블 | 의미 |
|---|---|
| `users` | QuantPilot 사용자 식별자. 이메일이 unique key다. |
| `user_broker_credentials` | 사용자별 증권사 계좌와 API 자격증명. API 키/시크릿은 암호화되어 저장된다. |

`account_number`는 평문으로 저장되고, `api_key`, `api_secret`만 앱 레이어에서 암호화된다. 운영 문서나 로그에는 계좌번호를 마스킹해서 다루는 것이 기본 전제다.

## 운영 경계

- `apps/user register`는 자격증명을 저장할 뿐 주문을 내지 않는다.
- `KIS_ENV=real`로 등록된 자격증명이 있어도 Trader의 실주문은 별도 gate와 `ALLOW_LIVE_ORDER=true`를 통과해야 한다.
- Trader는 현재 `account_type=STOCK` 자격증명을 조회한다. 선물 계좌 저장은 지원되지만 현재 Trader 초기화 경로의 주 사용 대상은 주식 계좌다.
- `CREDENTIAL_ENCRYPTION_KEY`를 잃어버리면 DB에 저장된 API 키/시크릿을 복호화할 수 없다.

관련 다이어그램:

- [[04_다이어그램/00_다이어그램_지도|User 다이어그램 지도]]
- [[04_다이어그램/register_list_흐름|register/list 흐름]]
- [[04_다이어그램/trader_자격증명_연결흐름|Trader 자격증명 연결흐름]]
