# Collector 실행 가이드

`apps/worker/collector`는 Analyzer가 사용할 원천 데이터를 외부 API에서 수집해
PostgreSQL에 저장한다. 모든 명령은 저장소 루트에서 `apps.worker` CLI로 실행한다.

> 이 문서는 `collect` 명령 전용이다. FA 분석과 universe 발행은
> [Analyzer 실행 가이드](../analyzer/README.md)를 참고한다.

## 1. 실행 준비

### Python 의존성 설치

```powershell
uv sync --dev
```

### PostgreSQL 실행

```powershell
docker compose -f storage/postgres/docker-compose.yml up -d
docker compose -f storage/postgres/docker-compose.yml ps
```

Docker 초기화 SQL은 데이터 디렉터리가 비어 있을 때만 자동 실행된다. 기존 DB를
사용한다면 Collector 실행 전에 최신 스키마가 적용되어 있어야 한다.

### 환경변수 설정

```powershell
Copy-Item apps/worker/.env.example apps/worker/.env
```

`apps/worker/.env`에 다음 값을 입력한다. 다른 파일을 사용하려면
`QUANTPILOT_ENV_FILE`에 해당 경로를 지정한다.

| 환경변수 | 필수 대상 | 설명 |
|---|---|---|
| `POSTGRES_HOST` | 전체 | PostgreSQL 호스트 |
| `POSTGRES_PORT` | 전체 | PostgreSQL 포트, 기본값 `5432` |
| `POSTGRES_DB` | 전체 | 데이터베이스 이름 |
| `POSTGRES_USER` | 전체 | 접속 사용자 |
| `POSTGRES_PASSWORD` | 전체 | 접속 비밀번호 |
| `FRED_API_KEY` | `macro` | CPI 최초 발표일과 개정 이력(vintage) 수집에 필수 |
| `KTO_API_KEY` | `macro` | KR_TOURIST 외국인 관광객 월별 입국자 수 수집에 필수 |
| `KTO_TOURIST_ENDPOINT` | `macro` | KTO API 엔드포인트를 직접 지정할 때 사용, 미입력 시 기본 data.go.kr 엔드포인트 사용 |
| `DART_API_KEY` | `company` | 재무제표와 공시 이벤트 수집에 필수 |
| `COMPANY_YEARS` | `company` | 기본 수집 연도, 예: `2023,2024,2025` |
| `DART_START_DATE` | `company` | 공시 이벤트 수집 하한일, 기본값 `20200101` |
| `SHOW_PROGRESS` | 전체 | `false`이면 진행바를 표시하지 않음 |

설정이 끝나면 CLI 도움말을 확인할 수 있다.

```powershell
python -m apps.worker collect --help
```

## 2. 수집 대상

| 대상 | 저장 데이터 | 주요 테이블 | 증분 처리 |
|---|---|---|---|
| `macro` | COPPER, GOLD, WTI, TNX, CPI, SOX, BDRY, DXY, VIX, USDKRW, US2Y, GPR, ISM_PMI, SEMIPROD, GTREND_KPOP, GTREND_KDRAMA, KR_TOURIST | `macro_signals` | 시그널별 최신 저장일 이후 수집 |
| `wics` | WICS 구성종목과 업종 가격 | `wics_companies`, `wics_industry_prices` | 기수집 스냅샷 생략 |
| `company` | 기업, DART 공시, 분기 재무제표, 위험상태 | `companies`, `dart_events`, `financial_statements`, `company_risk_states` | 공시 중첩 재조회와 보고서 단위 upsert |
| `all` | 위 세 대상을 순서대로 수집 | 위 테이블 전체 | `macro -> wics -> company` |

## 3. 기본 실행

```powershell
# 매크로 시그널 수집
python -m apps.worker collect macro

# 오늘 WICS 스냅샷과 업종 가격 수집
python -m apps.worker collect wics

# 기본 연도의 재무제표, DART 이벤트와 기업 위험상태 수집
python -m apps.worker collect company

# 전체 수집
python -m apps.worker collect all
```

`collect all`에서 `--end`를 생략하면 기본 종료일은 KST 오늘 기준 전날이다.
`--start`도 생략하면 같은 전날을 시작일로 사용해 실행 당일 데이터가 섞이지
않게 한다. `--end`를 지정하고 `--start`를 생략하면 `--end` 기준 전날부터
`--end`까지 수집한다.

가상환경 Python을 직접 사용할 때는 `python` 대신 다음 경로를 사용한다.

```powershell
.\.venv\Scripts\python.exe -m apps.worker collect all
```

## 4. 초기 적재

Analyzer 준비도 검사는 WICS 약 3년 이력, 매크로 최신성, 기업별 분기 재무제표
커버리지를 확인한다. 신규 DB는 충분한 기간을 지정해 초기 적재한다.

```powershell
python -m apps.worker collect all `
  --start 2023-01-01 `
  --end 2026-05-31 `
  --years 2023 2024 2025 2026 `
  --company-size LARGE `
  --wics-snapshot-frequency weekly `
  --check-readiness
```

`--check-readiness`는 `collect all`에서만 사용할 수 있다. 출력 JSON의 `status`가
`PASS`인지 확인한다. 현재 CLI는 readiness가 `FAIL`이어도 보고서를 출력하며
프로세스 오류로 종료하지는 않는다.

## 5. 증분 실행

초기 적재 이후에는 같은 명령을 반복 실행해도 upsert와 최신일 판정으로 중복을
제어한다.

```powershell
# 일상 증분 수집과 Analyzer 입력 준비도 확인
python -m apps.worker collect all --check-readiness --no-progress

# 지정 cutoff까지 매크로 데이터 수집
python -m apps.worker collect macro --start 2026-06-01 --end 2026-06-23

# 기간 내 각 주의 마지막 KRX 거래일 스냅샷 수집
python -m apps.worker collect wics `
  --start 2026-01-01 `
  --end 2026-06-23 `
  --wics-snapshot-frequency weekly

# WICS 일별 스냅샷 수집
python -m apps.worker collect wics `
  --start 2026-06-01 `
  --end 2026-06-23 `
  --wics-snapshot-frequency daily

# LARGE와 MID 기업만 수집
python -m apps.worker collect company `
  --years 2024 2025 2026 `
  --company-size LARGE `
  --company-size MID

# 이미 저장된 WICS 스냅샷도 다시 조회
python -m apps.worker collect wics --force-refresh
```

명시한 기간 안에 KRX 거래일이 없으면 WICS 스냅샷은 오늘 날짜로 대체 수집하지
않고 0건으로 종료한다.

## 6. 옵션

| 옵션 | 적용 대상 | 동작 |
|---|---|---|
| `--start YYYY-MM-DD` | `macro`, `wics`, `company`, `all` | 매크로/WICS 시작일, company의 DART 하한일. `collect all`에서는 생략 시 전날 |
| `--end YYYY-MM-DD` | 전체 | 매크로/WICS/DART 종료일, company 연도 범위 계산, readiness cutoff |
| `--years YEAR ...` | `company`, `all` | 재무제표 수집 연도 직접 지정 |
| `--company-size SIZE` | `company`, `all` | `LARGE`, `MID`, `SMALL`; 여러 번 지정 가능 |
| `--wics-snapshot-frequency` | `wics`, `all` | `weekly` 또는 `daily`, 기본값 `weekly` |
| `--force-refresh` | `wics`, `all` | 기수집 WICS 날짜도 다시 조회 |
| `--check-readiness` | `all` | 수집 후 Analyzer 입력 준비도 JSON 출력 |
| `--no-progress` | 전체 | tqdm 진행바 비활성화 |

`company`의 `--end`는 DART 이벤트 종료일도 제한한다. `collect all`에서
`--end`를 생략하면 DART 이벤트, 기업 위험상태 기준일, readiness cutoff 모두
KST 오늘 기준 전날로 맞춰진다.
WICS 가격 수집은 종목별 출력 대신 `tqdm` 진행바로 표시된다.

## 7. 권장 실행 주기

| Job | 권장 주기 | 예시 |
|---|---|---|
| `collect macro` | 매 거래일 장 마감 후 | `python -m apps.worker collect macro --no-progress` |
| `collect wics` | 주 1회 | `python -m apps.worker collect wics --no-progress` |
| `collect company` | 매일 증분 또는 분기 집중 실행 | `python -m apps.worker collect company --company-size LARGE --no-progress` |
| `collect all --check-readiness` | 월간 Analyzer 실행 전 | cutoff를 `--end`로 명시 |

## 8. 확인과 문제 해결

- `FRED_API_KEY is required for point-in-time CPI vintages`: `FRED_API_KEY`를
  설정한다. 일반 FRED CSV 값만으로는 CPI 발표 시점 안전성을 보장할 수 없다.
- `KTO_API_KEY가 필요합니다`: 외국인 관광객 수집용 `KTO_API_KEY`를 설정한다.
  공공데이터포털 응답 구조가 바뀌면 `KTO_TOURIST_ENDPOINT`를 지정하고 콘솔 로그를
  확인한다.
- `환경변수 DART_API_KEY가 필요합니다`: `DART_API_KEY`를 설정한다.
- PostgreSQL 연결 실패: `docker compose -f storage/postgres/docker-compose.yml ps`와
  `apps/worker/.env`의 접속 정보를 확인한다.
- 일부 외부 소스 실패: macro와 company 수집은 항목별 경고 후 계속 진행할 수
  있으므로 콘솔 로그와 readiness JSON을 함께 확인한다.
- readiness `FAIL`: 각 `checks[].name`, `passed`, `detail`을 확인하고 부족한 기간의
  `macro`, `wics`, `company`를 다시 수집한다.
