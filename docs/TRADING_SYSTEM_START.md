# 자동매매 시스템 설정과 운영 검증

기존 QuantPilot의 수집·분석·백테스트·매매 구성 위에 초기 설정, 진단, 격리 검증
경로를 추가했다. 아래 검증은 소프트웨어 개발 기반에 대한 것이다. 실제 데이터로
FA 백테스트를 마치고 계좌 운영 증거를 쌓기 전에는 운영 완료로 판단하지 않는다.

## 구성과 실행 순서

```text
DB 초기 설정 → 읽기 전용 환경 진단 → 격리 전략·체결 검증
             → 실제 데이터 수집 → 입력 준비도 PASS
             → 시점 안전 FA 분석·발행 → 실제 FA 백테스트
             → DRY_RUN 운영 관측 → PAPER 운영 관측 → REAL 승격 게이트
```

Python 3.10, uv와 PostgreSQL 16이 필요하다. 저장소 루트에서 `uv sync --frozen --dev`로
의존성을 설치하고 DB 환경변수를 설정한다. 초기 설정·진단 명령은
`apps/backtester/.env`를 우선 사용하고, 없으면 루트 `.env`를 읽는다. 파일을 명시하려면
`QUANTPILOT_ENV_FILE`로 지정한다. API 키와 DB 비밀번호는 커밋하지 않는다.

```bash
export QUANTPILOT_ENV_FILE=.env
uv run python -m storage.postgres.bootstrap
uv run python -m apps.system doctor --output reports/development-doctor.json
uv run python -m apps.system local-check --output reports/local-check.json
```

`bootstrap`은 이미 생성된 빈 DB에 기본 스키마·시드를 한 트랜잭션으로 설치하고,
주문 환경 분리 마이그레이션을 적용한다. 반복 실행은 기존 데이터를 유지한다.
기본 테이블이 일부만 있는 DB는 자동 복구 대신 초기화를 거부한다. 연결 오류는
종료 코드 1, 불완전한 DB는 2를 반환한다. Docker Compose로 초기화한 DB에도
동일 명령을 사용하여 후속 마이그레이션을 적용할 수 있다.

`doctor`는 읽기 전용 DB 트랜잭션으로 스키마, 마이그레이션과 데이터 준비도를
확인한다. 인증정보는 변수별 존재 여부만 출력하고 브로커를 초기화하지 않는다.
DB 개발 기반이 준비되면 종료 코드 0을 반환한다. `--require-data`를 추가하면
데이터 준비도까지 PASS여야 0을 반환하며 그 외에는 2로 중단한다. 인증정보 존재가
인증 성공을 의미하지는 않는다.

`local-check`는 임시 폴더의 가상계좌와 합성 가격·재무 입력으로 실제 전략·포트폴리오·
주문 계획·체결 구성요소를 호출한다. DRY_RUN의 무체결, 투자 한도, 비용 포함 매수,
재시작 후 동일 주문 중복 방지, 손절 신호, 진입 차단기에서도 매도 허용, 과매도 거부,
현금 원장 정합성을 검사한다. 운영 DB, 외부 브로커와 네트워크는 사용하지 않으며
임시 계좌는 검증 뒤 삭제된다. 성공은 0, 검사 실패는 2로 반환한다. 이 검증은
합성 입력을 쓰므로 실제 FA 백테스트 완료나 수익률 증거로 사용할 수 없다.

## 데이터 확보 이후

[Collector 초기 적재 가이드](../apps/worker/collector/README.md#4-초기-적재)에 따라
공시·재무, 업종, 매크로와 가격 이력을 준비한다. 분석과 백테스트의 기준일 및 전략을
일치시키고, 최초 공시 시점과 정정 이력을 보존한다.

```bash
uv run python -m apps.system doctor --require-data
uv run python -m apps.worker readiness --require-ready
```

준비도 PASS 이후 [Analyzer 가이드](../apps/worker/analyzer/README.md)에 따라 분석·
검증·발행하고 [Backtester 가이드](../apps/backtester/README.md)에 따라
`--universe-source fa-published`로 실행한다. 입력 부족이나 수집 실패를 빈 성공으로
처리해서는 안 된다. 인증형 DART API는 제거되었으며 공식 공개 XBRL·정책 공시를
사용한다. 원본 재무 결손·충돌은 제외 사유로 보존하고, 전송 실패는 성공으로 처리하지 않는다.

## 주문 모드와 운영 완료 조건

직접 Trader CLI와 Python Scheduler의 기본값은 DRY_RUN이다. 직접 CLI에서 KIS
모의 주문은 `--mock`, 가상 체결은 `--simulate`로 선택한다. 직접 CLI의 외부 알림은
`--notify`로 활성화한다. 가상 계좌는 유효한 가격·정수 수량만 허용하며, 저장 실패 시
기존 잔고와 메모리 상태를 보존한다. 동일 주문 식별 키의 체결은 재시작 뒤에도 반복
청구하지 않는다. 가상 계좌 파일은 Trader의 프로세스 잠금 아래 단일 프로세스로 운용한다.

Windows 배치의 기본 모드와 PAPER 승격 조건은 [README](../README.md#자동-실행)에
따른다. REAL에는 기존 전체 시스템 준비도, 승격 게이트와 명시적 환경 잠금이 필요하다.
장기간 관측 조건은 [완료 판정표](AUTOMATED_TRADING_COMPLETION_MATRIX.md)에 따른다.
초기 구축 검증이 이 운영 조건을 대체하지 않는다.

## 회귀 검증

```bash
uv run --frozen pytest tests -q
QUANTPILOT_RUN_DB_INTEGRATION=1 uv run --frozen pytest integration -q
```

DB 연동 검사는 고유한 임시 DB를 생성·삭제할 권한이 필요하다. 빈 DB 초기화,
반복 초기화, 불완전한 DB 보호와 SQL 실패 시 트랜잭션 전체 롤백을 실제 PostgreSQL에서
검증한다. 기존 애플리케이션 DB의 데이터는 테스트에서 변경하지 않는다.

## 통합 실행 명령

저장소 루트에서 실행한다. 기존 자료의 최초 적재가 끝났다면 다음 순서로 시작한다.

```bash
uv run python -m apps.system prepare
uv run python -m apps.system run
uv run python -m apps.system run --mode simulate --watch --interval 300
```

`prepare`는 직전 완료 거래일을 cutoff로 사용하는 `aggressive` 분석을 실행한다.
기본 적용일은 다음 준비 가능한 KRX 거래일이며 `--effective-date YYYY-MM-DD`로
명시할 수 있다. 과거 적용일·휴장일·아직 완료되지 않은 cutoff는 거부한다.
준비도 PASS, 최신 공개 공시 수집 증거와 분석 PASS를 확인한 후 현재 설정된 DB의 운영 유니버스에 발행하고
시점·유니버스 정합성을 감사한다. 이미 발행된 동일 분석은 재사용한다. 분석 발행은
클라우드 환경 게시와 별개이며, 연구 검증에는 별도 DB를 사용한다.

`prepare --collect`는 분석 전 증분 수집을 추가한다. `run --collect --watch`는 거래일마다
수집 및 준비가 처음 성공할 때까지 재시도하고 이후에는 수집을 반복하지 않는다.
기존 원본의 CFS 결손·중복 사실 충돌·적격 공시 없음에 해당하는 PARTIAL만 허용하며,
그 경우에도 8분기 요건과 준비도·분석 PASS를 통과해야 한다. HTTP 오류나 불완전한
정책 공시 수집은 중단한다. 최초 장기 이력 적재는 이 증분 명령의 역할이 아니다.

`run`은 KST 기준 KRX 거래일 08:00~15:20에만 준비하며, 09:00~15:20에만 매매 주기를
실행한다. 휴장·시간 외에는 WAITING, 장전에는 PREPARED를 기록한다. `--watch`가
없으면 한 번 실행한다. 기본 반복 간격은 300초, 최소 30초이며 Ctrl+C로 종료한다.
중복 watcher와 주기는 프로세스 잠금으로 차단한다. 수집·Trader 자식 프로세스에는
15분 제한이 있다. 준비 실패·Trader 실패·오래된 결과·운영 상태 이상은 BLOCKED와
종료 코드 2로 기록한다. 반복 모드에서는 다음 주기에 재시도한다. BLOCKED 중에는
신규 진입을 차단하며 장중에는 보유분 위험관리와 대사를 별도로 시도한다.
위험 점검이 실패하거나 일부만 완료되면 운영자가 보유 계좌를 확인해야 한다.

결과는 `logs/system/preparation.json`, `logs/system/<mode>/cycle.json`에 기록한다.
반복 실행 상태는 `logs/system/watch.heartbeat.json`으로 확인한다. Trader 로그와 FA
후보는 `logs/dry_run/`, `logs/simulate/`, `logs/paper/`로 분리하며 후보의 모델·전략·
실행 환경·신호일을 검증한다. 오래된 `logs/fa_candidates.json`은 더 이상 읽지 않는다.
DRY_RUN·SIMULATE·PAPER는 현재 FA v1.1을 검증하고 REAL의 기존 모델·승격 잠금은 유지한다.

DRY_RUN은 매 실행 가상 현금을 기준으로 계획만 계산한다. 실제 계좌 잔고와 체결을
검증하지 않으며 상태를 누적하지 않는다. 기본 현금은 1,000만 원이고
`DRY_RUN_INITIAL_CASH`로 바꿀 수 있다. SIMULATE는 `SIM_INITIAL_CASH`(기본 5억 원),
`SIM_ACCOUNT_PATH`의 영속 가상계좌를 사용한다. 두 모드의 금액을 비교하려면 초기
현금을 맞추고 새 가상계좌 파일로 시작한다. 기존 파일을 삭제해 운영 이력을 지우지 않는다.

이 통합 watcher는 준비·매매·마감 보고서를 연결한다. 장기 운영 승격 증거는 실제
관측 로그를 기반으로 별도로 심사하며, 기존 `scheduler.py`와 동시에 실행하지 않는다.

## KIS 모의투자 연결 준비

모의투자용으로 발급한 아래 값을 환경 설정 또는 Git에서 제외된 `.env`에 등록한다.
키 값·계좌번호를 문서나 채팅에 붙이지 않는다.

| 변수 | 용도 |
|---|---|
| `KIS_APP_KEY` | 모의투자 앱 키 |
| `KIS_APP_SECRET` | 모의투자 앱 시크릿 |
| `KIS_DOMESTIC_STOCK_ACCOUNT_NO` | 계좌 앞 8자리 |
| `KIS_DOMESTIC_STOCK_ACCOUNT_PRODUCT_CODE` | 계좌 뒤 2자리, 기본 `01` |
| `KIS_ENV` | `paper` |
| `ALLOW_LIVE_ORDER` | `false` |

KIS 모의투자 HTTPS 목적지는 `openapivts.koreainvestment.com:29443`이다.
인증정보가 없으면 `paper-check`는 MISSING_PAPER_CREDENTIALS로 중단한다.
정보를 등록한 뒤 다음 명령으로 실제 인증과 잔고 응답 형식만 확인한다.

```bash
uv run python -m apps.system paper-check --output logs/system/paper-check.json
```

이 검사는 항상 `mock=True`를 사용하고 주문을 보내지 않으며 최대 60초로 제한한다.
출력에는 비밀값이나 잔고 금액을 넣지 않는다. 연결 PASS는 모의 주문 체결·정산 검증이나
운영 승격을 뜻하지 않는다. 직접 모의 주문을 실행할 때만 `run --mode paper` 또는
`run --mode paper --watch`를 명시한다. 새 통합 명령에는 REAL 모드가 없다.

## 데이터 장애 중 위험관리와 주문 시점 검사

통합 실행의 준비·장전 단계가 실패해도 장중에는 `--risk-only` 경로로 계좌 대사와
보유분의 가격 기반 손절·트레일링을 시도한다. 이 경로는 FA·일봉·시장 국면을 요청하지
않고 매도만 계획한다. 계좌/DB 조회 불가나 미정산 주문은 계속 차단하고 결과에 남긴다.
준비 실패 상태는 BLOCKED로 유지하며 위험관리 실행 결과는 `risk_management`에 기록한다.
위험 평가 완료율은 Trader의 `data_health.risk_check_coverage`로 확인한다.

KIS 주문은 매 주문의 DB 선점 전과 해시키 처리 후 실제 전송 직전에 거래일·세션·
09:00~15:20 시간 범위와 중지 설정을 재확인한다. `TRADING_CONTROL_PATH` 또는 기본
`logs/system/trading-control.json`은 매번 읽는다. `{"entries_paused":true}`는 매수만,
`{"orders_paused":true}`는 모든 주문을 막는다. 파일이 손상되면 모든 주문을 차단한다.
Telegram 알림 활성화와 실계좌 승격 조건은 기존 명시적 경로를 사용한다.

PAPER 정책을 외부 주문 없이 비교하려면 `apps.system run --mode simulate --paper-policy`
또는 `run_live_trader.py --simulate --paper-policy`를 사용한다. DRY_RUN도 지원한다.
기본 로컬 정책은 유지하며, 명시한 경우 PAPER와 같은 손절·트레일링·비중·리밸런싱 및
인버스 헤지 설정을 재현한다. REAL에서는 이 옵션을 거부한다. 비교에는 같은 초기
현금·같은 가격·같은 정책을 사용하고 가상 체결 비용과 실제 체결 차이는 별도로 평가한다.

## 인증·감독·마감 보고서·관제

KIS 인증은 10초 제한의 요청을 사용하며 `token.dat` pickle 캐시는 읽지 않는다.
새 JSON 토큰은 계좌·모의/실 서버·키 식별별로 분리한 `logs/credentials/`에 0600으로
저장한다. 키·시크릿 원문은 저장하지 않는다. 인증 오류는 안전한 오류 유형만 기록한다.
`KIS_TOKEN_CACHE_DIR`로 전용 비공개 디렉터리를 지정할 수 있다.

`apps.system run --mode simulate --supervise`는 통합 watcher를 감독한다. 진행 파일이
30분 동안 바뀌지 않거나 프로세스가 실패하면 자신이 생성한 프로세스를 종료하고 최대
3회 복구한다. 단순 heartbeat와 진행 정체는 별도로 판정한다. 사용자 종료·잠금 충돌은
복구 대상으로 삼지 않는다. `--collect`·`--paper-policy`도 전달할 수 있다.
기존 스케줄러와 통합 watcher는 같은 전역 scheduler 잠금·heartbeat를 사용한다.
종료·timeout 시 하위 프로세스를 정리하며, 새 supervisor는 기존 supervisor와도 잠금을 공유한다.

15:30 이후 오늘의 실제 관측 로그가 있을 때만 EOD를 생성한다. PAPER는 기존 공식
성과 보고서 경로를 사용하고, SIMULATE는 실제 가상계좌·비용·상태 검사를 기록한다.
DRY_RUN은 계획 관측 보고서이며 계좌 수익률을 만들지 않는다. 성공한 날짜는 재생성하지
않고 실패는 다음 주기에 재시도한다. 파일은 `reports/promotion/<mode>/daily/`와
`latest.json`, 상태는 `logs/<mode>/eod_report_status.json`에 저장한다.

대시보드의 조회 환경 선택은 PAPER·DRY_RUN·SIMULATE·REAL 기록을 분리해서 읽는다.
실제 실행 모드나 주문 권한을 바꾸지 않는다. 자동 실행 단계·차단 사유·보유분 위험관리
결과는 읽기 전용 `/api/workflow` 및 운영 요약에서 확인할 수 있다.

## 재무 결손·수집 최신성·전략 진단

```bash
uv run python -m apps.system data-quality --output logs/system/data-quality.json
uv run python -m apps.system strategy-review --directory /path/to/backtest \
  --benchmark /path/to/kospi.csv --output reports/strategy-review.json
```

`data-quality`는 직전 완료 거래일 기준 최신 LARGE 구성종목의 유효 재무 분기 수,
지원 시장·상태, 제외 사유와 수집 기록을 읽기 전용으로 확인한다. `eligible_source_history`는
원천 8분기 조건이며 FA 점수·가격·위험 상태까지 통과한 매수 적격 판정이 아니다.
불충분한 이력과 원본 결손은 채워 넣지 않는다. 원본 결손이 남아도 전체 운영 준비도와
개별 종목 조건을 별도로 검사한다.

회사 수집 성공·부분 성공·실패는 DB 식별별 `logs/collection/`에 저장한다.
`COLLECTION_HEALTH_DIR`로 위치를 바꿀 수 있다. 준비 단계는 최근 2일 이내 기록,
cutoff 포함 범위와 다섯 정책 공시 유형의 원본 페이지 증거를 요구한다. 알려진 원본
재무 결손만 있는 PARTIAL을 허용하며 전송 실패·증거 누락·오래된 기록은 차단한다.
`doctor --require-data`에도 이 조건을 적용한다. 첫 적용이나 복원 뒤에는 회사 수집을
다시 실행해 새 DB의 증거를 생성한다. 다른 DB의 기록을 복사해 통과시키지 않는다.

`strategy-review`는 `equity-curve.csv`, `weights.csv`, `trade-ledger.csv`와 실제 벤치마크
종가를 사용한다. 날짜·결측·비중·회전율을 검증하고 앞 2/3과 뒤 1/3의 성과, MDD,
추가 비용 10/30/50bp와 운영 비중 한도 차이를 보고한다. Sharpe의 무위험수익률은 0이다.
진단 성공 PASS는 전략 승인과 다르며 `promotion_status`는 BLOCKED다.
이미 관측한 경로의 사후 진단이므로 독립적인 최적화·외부 체결·수익성 검증을 대체하지 않는다.

## 백업과 격리 복원

```bash
uv run python -m apps.system backup --directory /path/to/new-backup \
  --source-cache /path/to/public-dart-cache
uv run python -m apps.system restore --directory /path/to/new-backup
```

PostgreSQL `pg_dump`·`pg_restore`가 PATH에 필요하다. 이 클라우드의 pgserver 설치 경로도
지원한다. 명령은 30분 제한이며 DB 비밀번호를 명령 인자로 넘기지 않는다.
새 0700 디렉터리에 DB 덤프와 공개 원본 캐시를 0600으로 보존한다. 공개 캐시만
지정하며 일반 프로젝트 디렉터리·설정·계좌 파일을 지정하지 않는다. SHA256 이름의
`.bin`·`.json`에는 원본 XBRL ZIP·페이지·요청 메타데이터가 포함된다. 숨김 파일과
토큰·자격증명 파일은 제외하고 DB의 `user_broker_credentials` 데이터도 제외한다.
키는 별도 환경 설정에서 다시 등록한다. 백업에는 사용자·거래 자료가 포함될 수 있으므로
공개 게시하거나 Git에 넣지 않는다.

복원은 덤프·아카이브 체크섬을 검증한 뒤 새 `quantpilot_restore_...` DB에만 실행한다.
기존 이름과 원래 운영 DB는 거부한다. 중간 실패 시 새 DB는 조사용으로 남긴다.
원본 행 수가 변하지 않은 백업은 제외 테이블을 고려해 복원 행 수를 비교하며,
공개 원본 파일 집합·크기·SHA256도 검증한다. 행 수 비교는 전체 값의 독립 대사를
대체하지 않는다. 기존 DB·원본 캐시·자격증명 설정은 수정하지 않는다.
복원 DB를 사용할 때는 접속 대상을 의도적으로 변경하고 수집·진단을 다시 수행한다.

최신 구현·검증·남은 조건은 [2026-10-05 개선 결과](IMPROVEMENTS_STATUS_2026-10-05.md)를
기준으로 읽고, 과거 감사·성과 보고서는 해당 시점의 기록으로 취급한다.
