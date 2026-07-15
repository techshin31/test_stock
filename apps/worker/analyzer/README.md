# Analyzer 실행 가이드

`apps/worker/analyzer`는 Collector가 PostgreSQL에 적재한 시점 안전 데이터를 읽어
월간 매크로 분석, 업종 선정, 기업 선정과 운영 `universe` 발행을 수행한다.
외부 데이터 API는 직접 호출하지 않으며 모든 명령은 저장소 루트에서 실행한다.

## 1. 빠른 실행

분석 결과만 생성하고 운영 universe에는 반영하지 않는다.
이것이 기본 동작이다.

```powershell
python -m apps.worker analyze all `
  --analysis-month 2026-07 `
  --cutoff 2026-06-30 `
  --effective-date 2026-07-01
```

검증 상태가 PASS 또는 WARNING인 결과를 운영 universe에 발행한다. 발행은
effective date가 지난 뒤에는 불가능하지만, effective date 당일의 시간 제한은 두지
않는다. 운영 반영 시에는 `--publish`를 명시해야 한다.

```powershell
python -m apps.worker analyze all `
  --analysis-month 2026-07 `
  --cutoff 2026-06-30 `
  --effective-date 2026-07-01 `
  --publish
```

날짜 옵션을 모두 생략하면 실행일(KST)의 오늘을 cutoff와 effective date로
사용하고, analysis month는 그 달의 1일로 잡는다. 단, `--publish`를 붙이지 않으면
이 명령도 운영 universe를 변경하지 않는다.

```powershell
python -m apps.worker analyze all
```

## 2. 실행 준비

### Python과 PostgreSQL

```powershell
uv sync --dev
docker compose -f storage/postgres/docker-compose.yml up -d
docker compose -f storage/postgres/docker-compose.yml ps
```

### 환경변수

Analyzer는 별도 `.env`가 아니라 `apps/worker/.env`를 사용한다.

```powershell
Copy-Item apps/worker/.env.example apps/worker/.env
```

| 환경변수 | 필수 | 기본값 | 설명 |
|---|:---:|---|---|
| `POSTGRES_HOST` | O | - | PostgreSQL 호스트 |
| `POSTGRES_PORT` | | `5433` | PostgreSQL 포트 |
| `POSTGRES_DB` | O | - | 데이터베이스 이름 |
| `POSTGRES_USER` | O | - | 접속 사용자 |
| `POSTGRES_PASSWORD` | O | - | 접속 비밀번호 |
| `STRATEGY_NAME` | | `risk_neutral` | 활성 `strategies.name` 조회 키 |
| `QUANTPILOT_ENV_FILE` | | `apps/worker/.env` | 다른 환경 파일을 사용할 때의 경로 |

`STRATEGY_NAME`과 같은 이름의 활성 전략이 `strategies` 테이블에 있어야 한다.
현재 `run_live_trader.py`의 FA/TA 전략은 `aggressive` 발행본을 사용하므로, 라이브
운영 유니버스를 만들 때는 Analyzer의 `STRATEGY_NAME`도 `aggressive`로 맞춘다.

## 3. Collector 선행 조건

Analyzer는 실행할 때마다 cutoff 기준 Collector 준비도를 먼저 검사한다. 다음 항목이
모두 준비되지 않으면 분석 실행을 생성하기 전에 중단한다.

- 필수 원천 테이블과 시점 안전 컬럼
- 8개 매크로 시그널의 최신 데이터와 CPI 발표 이력
- LARGE 기업의 분기 재무제표 커버리지
- 약 3년의 WICS 스냅샷과 업종 가격 이력
- 원천 데이터 중복 여부
- `company_risk_states` 계약

원천 데이터 적재와 readiness 확인 명령은
[Collector 실행 가이드](../collector/README.md)를 참고한다. Analyzer도 실행 시작
시 같은 readiness 검사를 수행하며, FAIL이면 분석 run을 만들기 전에 중단한다.

## 4. 명령 구조

```powershell
python -m apps.worker analyze <target> [options]
```

```powershell
python -m apps.worker analyze --help
```

Analyzer target은 선행 단계를 자동으로 포함하는 누적 실행이다.

| target | 실행 단계 | 용도 |
|---|---|---|
| `macro` | readiness -> 분기 FA 갱신 -> 매크로 분석 | 매크로 단계 개발·검증 |
| `sector` | macro 단계 -> 업종 관계·후보·최종 업종 선정 | 업종 단계 개발·검증 |
| `company` | sector 단계 -> 기업 하드 필터·점수·선정 | 기업 단계 개발·검증 |
| `all` | company 단계 -> 전체 결과 재검증 -> 선택적 발행 | 공식 월간 운영 |

개별 target은 개발과 진단용이다. 공식 유니버스 생성에는 `analyze all`을 사용한다.

## 5. 날짜 규칙

날짜 옵션을 생략하면 다음 규칙을 적용한다.

| 값 | 기본 규칙 |
|---|---|
| `analysis_month` | effective date가 속한 달의 1일. effective date도 생략하면 실행일이 속한 달의 1일 |
| `cutoff_date` | 실행일(KST)의 오늘 |
| `effective_date` | cutoff date와 같은 날. `--effective-date`를 주면 해당 날짜 |

즉 그냥 `python -m apps.worker analyze all`을 실행하면 오늘 기준으로 FA 분석한다.
월간 배치처럼 `2026-06-30` cutoff와 `2026-07-01` 적용일을 고정해야 할 때는
`--analysis-month`, `--cutoff`, `--effective-date`를 명시한다.

## 6. 공식 월간 실행

### 왜 `--publish`가 명시 옵션인가

`python -m apps.worker analyze all`은 기본적으로 FA 분석 결과를 만들고 검증하는
명령이다. 이 상태에서는 `fa_analysis_runs`, `fa_macro_results`,
`fa_sector_results`, `fa_company_results`만 갱신하며, trader가 읽는 운영
`universe`는 변경하지 않는다.

`--publish`를 붙이면 운영 상태가 바뀐다. 품질 조건을 통과해 선택된 모든 기업은
`ACTIVE`로 반영되고, 기존 ACTIVE 중 미선정 기업은 `SELL_ONLY`와 청산 기한을
받는다. 이후 `run_live_trader.py --premarket`이 새 universe를 장전 매매 후보로
동기화한다.

이 플래그를 기본값으로 두지 않는 이유는 검증, 재분석, 백필, 모델 비교 실행 중에
운영 universe가 실수로 바뀌는 것을 막기 위해서다. 월간 운영 배치에서는 먼저
발행 없이 PASS 또는 WARNING을 확인하고, 운영 반영이 확정된 실행에만 같은 인자로
`--publish`를 추가한다.

### 분석과 검증만 실행

먼저 발행 없이 전체 결과가 PASS 또는 WARNING인지 확인할 수 있다.

```powershell
python -m apps.worker analyze all `
  --analysis-month 2026-07 `
  --cutoff 2026-06-30 `
  --effective-date 2026-07-01
```

성공하면 `run_id`, 날짜, 입력 해시, 모델 버전과 신규 생성 여부를 JSON으로
출력한다. 결과 상태와 선정 내역은 `fa_analysis_runs`, `fa_macro_results`,
`fa_sector_results`, `fa_company_results`에 저장된다.

### PASS/WARNING 결과 발행

동일한 인자로 `--publish`를 추가하면 기존 PASS/WARNING 실행을 재사용해 발행할 수
있다.

```powershell
python -m apps.worker analyze all `
  --analysis-month 2026-07 `
  --cutoff 2026-06-30 `
  --effective-date 2026-07-01 `
  --publish
```

발행 조건은 다음과 같다.

- target이 `all`이고 실행 상태가 `PASS` 또는 `WARNING`일 것
- effective date가 아직 지나지 않았을 것
- 선택된 업종과 기업이 각 단계의 품질 필터를 통과했을 것. Analyzer 자체의 개수
  제한은 없으며, 실제 목표 비중은 Trader의 TA 조건과 포트폴리오 한도에서 결정됨
- 기업이 KOSPI·LARGE·ACTIVE이며 cutoff 이후 데이터를 사용하지 않았을 것
- effective date 기준 `BLOCK_BUY` 또는 `SELL_ONLY` 위험상태가 없을 것

발행은 하나의 DB 트랜잭션으로 처리한다. 품질 조건을 통과한 모든 선택 기업을 `ACTIVE`로 upsert하고
기존 ACTIVE 중 미선정 기업은 `SELL_ONLY`와 20거래일 청산 기한으로 전환한다.
각 universe 행은 `source_fa_company_result_id`로 선정 결과를 추적한다. 전 과정이
성공한 뒤에만 실행 상태가 `PUBLISHED`가 되며, 실패하면 기존 universe를 유지한다.

effective date가 지난 뒤의 발행은 `publish effective_date is in the past` 오류로
거부된다. effective date 당일에는 08:30 KST 이후에도 `--publish`를 실행할 수 있다.

공식 월간 운영 순서는 다음과 같다.

```powershell
$env:STRATEGY_NAME = "aggressive"
uv run python -m apps.worker collect all --check-readiness
uv run python -m apps.worker analyze all
uv run python -m apps.worker analyze all --publish
uv run python -m apps.worker audit
uv run python run_live_trader.py --mock --premarket
```

두 번째 `analyze all`은 PASS 확인용이고, 세 번째 `analyze all --publish`가
trader 입력인 운영 universe를 확정하는 단계다.

## 7. 부분 실행

```powershell
# readiness, 분기 FA 갱신과 매크로 방향 분석
python -m apps.worker analyze macro `
  --analysis-month 2026-07 `
  --cutoff 2026-06-30

# 위 단계에 업종 선정까지 포함
python -m apps.worker analyze sector `
  --analysis-month 2026-07 `
  --cutoff 2026-06-30

# 위 단계에 기업 선정까지 포함
python -m apps.worker analyze company `
  --analysis-month 2026-07 `
  --cutoff 2026-06-30
```

부분 실행에는 `--publish`를 사용할 수 없다. 부분 target별로 입력 해시와 run이
별도로 관리되므로 `macro -> sector -> company`를 수동으로 이어 붙일 필요도 없다.

## 8. 옵션

| 옵션 | 동작 |
|---|---|
| `--analysis-month YYYY-MM` | 분석 기준월, 기본값은 effective date가 속한 월 |
| `--cutoff YYYY-MM-DD` | 이 날짜까지 사용 가능했던 데이터만 분석 |
| `--effective-date YYYY-MM-DD` | trader가 새 universe를 적용할 거래일 |
| `--publish` | PASS/WARNING 결과를 운영 universe에 발행, `all` 전용 |
| `--force` | 같은 입력이 있어도 새 `run_version`으로 재분석 |
| `--no-progress` | CLI 호환 옵션; 현재 Analyzer 실행 결과에는 영향 없음 |
| `--reuse-quarter-scores` | 역사 리플레이에서 저장된 시점 안전 분기 FA 점수를 재사용 |

같은 target·입력 데이터·설정이면 기존 `FAIL`이 아닌 실행을 재사용한다. 재사용된
실행의 CLI 출력은 `created: false`이다. 데이터나 모델이 바뀌지 않았는데 다시
계산해야 할 때만 `--force`를 사용한다. 이미 해당 월이 PUBLISHED라면 새 강제
실행을 발행하려 하지 말고 기존 발행 상태를 먼저 점검한다.

## 9. 결과 상태와 검증 계약

| 상태 | 의미 |
|---|---|
| `RUNNING` | 분석 진행 중 |
| `PASS` | target 검증 통과, 아직 universe 미발행 |
| `WARNING` | 핵심 검증은 통과했지만 기업 계약 또는 위험상태 경고가 있음, 발행 가능 |
| `FAIL` | 단계 실행 또는 결과 검증 실패 |
| `PUBLISHED` | PASS/WARNING 결과의 universe 발행 완료 |

`analyze all`의 최종 검증은 다음을 다시 확인한다.

- 매크로 8개 결과와 `last_available_date <= cutoff_date`
- 후보 업종의 품질 조건과 LARGE 기업 존재 여부
- 선택 기업의 FA·신뢰도·유동성·위험상태 조건
- 종목 형식, 시장·규모·활성 상태, 재무 데이터 사용 가능일
- effective date 기준 기업 매수 차단 상태

단계에서 예외가 발생하면 해당 run은 `FAIL`로 기록된다. 1시간 이상 남아 있는
`RUNNING` 실행은 다음 실행 준비 시 `STALE_RUNNING_TIMEOUT`으로 FAIL 처리된다.

## 10. 실행 결과 확인

기본 Docker DB 설정을 사용한다면 다음과 같이 최근 실행을 조회할 수 있다.

```powershell
docker exec postgres-db psql -U admin -d quantpilot_db -c `
  "SELECT id, analysis_month, run_version, status_code, selected_industry_count, selected_company_count, failure_reason FROM fa_analysis_runs ORDER BY id DESC LIMIT 10;"
```

선정 기업과 universe 계보를 확인한다.

```powershell
docker exec postgres-db psql -U admin -d quantpilot_db -c `
  "SELECT r.id AS run_id, c.stock_code, c.industry_code, c.fa_score, c.is_selected FROM fa_analysis_runs r JOIN fa_company_results c ON c.run_id = r.id WHERE r.id = (SELECT MAX(id) FROM fa_analysis_runs) ORDER BY c.is_selected DESC, c.industry_code, c.industry_rank;"

docker exec postgres-db psql -U admin -d quantpilot_db -c `
  "SELECT strategy_id, symbol, universe_status_code, entry_date, exit_deadline, source_fa_company_result_id FROM universe ORDER BY strategy_id, universe_status_code, symbol;"
```

운영 감사는 시점 위반, 1시간 이상 고착된 RUNNING, 최신 PUBLISHED 결과와 ACTIVE
universe의 불일치를 검사한다.

```powershell
python -m apps.worker audit
```

감사 결과의 `status`가 `PASS`인지 확인한다. PUBLISHED 이력이 2개 미만이면
`average_monthly_turnover`는 `null`일 수 있다.

## 11. 문제 해결

- `collector readiness failed`: [Collector 실행 가이드](../collector/README.md)의
  `collect all --check-readiness`를 실행하고 실패한 check의 부족 데이터를 채운다.
- `active strategy not found`: `STRATEGY_NAME`과 `strategies.name`, `is_active`를
  확인한다.
- `only PASS or WARNING run can publish`: `fa_analysis_runs.status_code`와
  `validation_summary`, `failure_reason`을 확인한다.
- `publish effective_date is in the past`: 이미 지난 effective date에는 발행하지
  않는다. 기존 universe가 유지되었는지 `python -m apps.worker audit`로 확인한다.
- `selected companies are buy blocked`: `company_risk_states`에서 effective date에
  유효한 상태와 원본 DART 이벤트를 확인한다.
- 동일 실행이 바로 반환됨: 입력 해시가 같아 기존 실행을 재사용한 것이다. 의도적
  재계산에만 `--force`를 사용한다.
