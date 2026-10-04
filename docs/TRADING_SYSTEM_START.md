# 자동매매 시스템 초기 구축

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
처리해서는 안 된다. DART의 `AUTH`, `QUOTA`, `PROXY` 오류를 구분하여 원인을 먼저
해소한다. HTTPS 프록시 장애는 프록시 서비스의 라우팅·연결 설정 확인이 필요할 수 있다.

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
