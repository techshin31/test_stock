# apps/user — 사용자 등록 도구

신규 사용자 정보와 증권사 API 자격증명을 PostgreSQL에 등록하는 CLI 도구입니다.  
API 키와 시크릿은 Fernet(AES-128-CBC + HMAC-SHA256)으로 암호화되어 저장됩니다.

---

## 사전 준비

### 1. PostgreSQL 실행 확인

```bash
docker compose -f storage/postgres/docker-compose.yml up -d
```

### 2. `.env` 파일 생성

```bash
cp apps/user/.env.sample apps/user/.env
```

### 3. 암호화 키 생성 (최초 1회)

`CREDENTIAL_ENCRYPTION_KEY`가 없으면 자격증명을 저장할 수 없습니다.  
아래 명령으로 키를 생성하고 `.env`의 `CREDENTIAL_ENCRYPTION_KEY`에 붙여넣으세요.

```bash
python -c "from core.utils.crypto import generate_key; print(generate_key())"
```

> ⚠️ 이 키를 잃어버리면 DB에 저장된 API 키/시크릿을 복호화할 수 없습니다.  
> 안전한 곳에 별도 보관하세요.

---

## `.env` 설정

| 항목 | 필수 | 설명 |
|------|------|------|
| `USER_EMAIL` | ✅ | 등록할 사용자 이메일 |
| `USER_DISPLAY_NAME` | - | 표시 이름 (생략 가능) |
| `BROKER_CODE` | - | 증권사 코드 (기본값: `KIS`) |
| `KIS_APP_KEY` | ✅ | KIS API 앱 키 |
| `KIS_APP_SECRET` | ✅ | KIS API 앱 시크릿 |
| `KIS_ENV` | - | `paper`(모의) / `real`(실거래), 기본값: `paper` |
| `KIS_DOMESTIC_STOCK_ACCOUNT_NO` | ✅ | 주식 계좌번호 |
| `KIS_DOMESTIC_STOCK_ACCOUNT_PRODUCT_CODE` | ✅ | 주식 계좌상품코드 (예: `01`) |
| `KIS_DOMESTIC_FUTURES_ACCOUNT_NO` | - | 선물 계좌번호 (없으면 비워두세요) |
| `KIS_DOMESTIC_FUTURES_ACCOUNT_PRODUCT_CODE` | - | 선물 계좌상품코드 (예: `03`) |
| `ALLOW_LIVE_ORDER` | - | 실주문 허용 여부 (`KIS_ENV=real`일 때만 유효) |
| `CREDENTIAL_ENCRYPTION_KEY` | ✅ | Fernet 암호화 키 |
| `POSTGRES_HOST` | ✅ | PostgreSQL 호스트 |
| `POSTGRES_PORT` | - | PostgreSQL 포트 (기본값: `5432`) |
| `POSTGRES_USER` | ✅ | PostgreSQL 사용자 |
| `POSTGRES_PASSWORD` | ✅ | PostgreSQL 비밀번호 |
| `POSTGRES_DB` | ✅ | 데이터베이스 이름 |

---

## 사용 방법

### 사용자 및 자격증명 등록

```bash
python -m apps.user register
```

실행 흐름:
1. `USER_EMAIL`로 기존 사용자 조회 → 없으면 신규 생성
2. 주식 계좌 자격증명 저장 (API 키/시크릿 암호화)
3. 선물 계좌가 설정된 경우 추가 저장

실행 예시:
```
[INFO] 신규 사용자 생성 완료: id=1, email=trader@example.com
[INFO] 주식 계좌 저장 완료: id=1, broker=KIS, env=PAPER, account=****2156
[INFO] 선물 계좌 저장 완료: id=2, broker=KIS, env=PAPER, account=****4298
```

동일한 `(broker_code, account_number, environment_code)` 조합이 이미 존재하면  
새로 추가하지 않고 API 키/시크릿을 갱신합니다.

---

### 등록된 자격증명 목록 조회

```bash
python -m apps.user list
```

실행 예시:
```
[USER] id=1 | email=trader@example.com | active=True
  [1] broker=KIS | type=STOCK   | env=PAPER | account=****2156 | active=True
  [2] broker=KIS | type=FUTURES | env=PAPER | account=****4298 | active=True
```

---

## DB 저장 구조

```
users
├── id, email, display_name, is_active

user_broker_credentials
├── user_id          → users.id
├── broker_code      → "KIS"
├── account_number   → 계좌번호
├── api_key          → 암호화된 API 키
├── api_secret       → 암호화된 API 시크릿
├── environment_code → "REAL" | "PAPER"
└── extra (JSONB)    → 증권사별 추가 정보
                       KIS 예시: {"account_type": "STOCK", "account_product_code": "01"}
```

`extra` 컬럼은 증권사가 바뀌어도 스키마 변경 없이 필요한 필드를 자유롭게 추가할 수 있습니다.
