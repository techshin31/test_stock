# QuantPilot

한국 주식 데이터를 수집하고, 시점 안전(point-in-time) FA 분석과 TA 신호를 결합해
유니버스를 발행·매매·검증하는 자동화 시스템입니다. PostgreSQL을 공통 저장소로
사용하며 KIS 모의/실전 계좌, 로컬 시뮬레이션, 백테스트를 지원합니다.

> 이 저장소는 투자 시스템 개발과 검증을 위한 프로젝트입니다. 기본 실행은 주문이
> 발생하지 않는 점검 모드이거나 모의 환경이며, 실전 주문은 별도의 안전 잠금이
> 필요합니다.

## 전체 흐름

```text
외부 데이터 수집
  -> 시점 안전 FA 분석
  -> 검증 결과 발행
  -> 운영 상태 감사
  -> 장전 유니버스 준비
  -> 장중 FA/TA 주문 실행
  -> 체결·포지션·성과 기록
```

| 구성 요소 | 역할 | 상세 문서 |
|---|---|---|
| Worker / Collector | 매크로, WICS, DART 재무·공시 데이터 수집 | [Collector 가이드](apps/worker/collector/README.md) |
| Worker / Analyzer | 매크로·업종·기업 FA 분석과 운영 유니버스 발행 | [Analyzer 가이드](apps/worker/analyzer/README.md) |
| Live Trader | FA/TA 후보 평가, 주문, 체결 확인, 포지션 동기화 | [운영 전략](docs/FA_TA_STRATEGY.md) |
| Scheduler | 장전 준비와 장중 반복 실행, 시뮬레이션 일일 리포트 | 이 문서의 [자동 실행](#자동-실행) |
| Backtester | 랜덤 또는 발행된 FA 유니버스 기반 백테스트 | [Backtester 가이드](apps/backtester/README.md) |

## 빠른 시작

### 1. 요구 사항

- Python 3.10
- [uv](https://docs.astral.sh/uv/)
- Docker Desktop 또는 별도 PostgreSQL 16 인스턴스

```powershell
uv sync --dev
docker compose -f storage/postgres/docker-compose.yml up -d
docker compose -f storage/postgres/docker-compose.yml ps
```

Docker Compose는 호스트의 `5433` 포트를 컨테이너 `5432`에 연결합니다. 로컬에서
Compose DB를 사용할 때는 애플리케이션의 `POSTGRES_PORT`를 `5433`으로 설정하세요.

### 2. 환경변수

Worker 설정 파일을 만든 뒤 DB 접속 정보와 필요한 API 키를 입력합니다.

```powershell
Copy-Item apps/worker/.env.example apps/worker/.env
```

주요 설정은 다음과 같습니다.

| 구분 | 환경변수 |
|---|---|
| PostgreSQL | `POSTGRES_HOST`, `POSTGRES_PORT`, `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD` |
| 데이터 수집 | `DART_API_KEY`, `FRED_API_KEY`, `KTO_API_KEY` |
| 분석 전략 | `STRATEGY_NAME` (Analyzer 기본 `risk_neutral`, 현재 Live Trader는 `aggressive`) |
| KIS 계좌 | `KIS_APP_KEY`, `KIS_APP_SECRET`, `KIS_DOMESTIC_STOCK_ACCOUNT_NO`, `KIS_DOMESTIC_STOCK_ACCOUNT_PRODUCT_CODE` |
| 실전 주문 잠금 | `KIS_ENV=real`, `ALLOW_LIVE_ORDER=true` |

Worker는 기본적으로 `apps/worker/.env`, Trader는 저장소 루트의 `.env`,
Backtester는 `apps/backtester/.env`를 읽습니다. Worker와 Backtester에서 다른
설정 파일을 쓰려면 `QUANTPILOT_ENV_FILE`에 경로를 지정할 수 있습니다.

## 데이터 수집과 FA 발행

모든 명령은 저장소 루트에서 실행합니다.

신규 DB는 약 3년의 WICS·매크로·재무 이력을 먼저 적재해야 합니다. 초기 적재 기간과
옵션은 [Collector 가이드의 초기 적재](apps/worker/collector/README.md#4-초기-적재)를
따르고, 아래 명령은 초기 적재 이후의 일상 증분 운영에 사용하세요.

```powershell
# 일상 증분 수집 후 Analyzer 입력 준비도 검사
uv run python -m apps.worker collect all --check-readiness

# 현재 Live Trader가 사용하는 전략과 Analyzer 발행 전략을 일치시킴
$env:STRATEGY_NAME = "aggressive"

# 분석과 검증만 수행: 운영 유니버스는 바뀌지 않음
uv run python -m apps.worker analyze all

# 위와 동일한 입력의 PASS/WARNING 결과를 운영 유니버스에 반영
uv run python -m apps.worker analyze all --publish

# 시점 안전성과 발행본-유니버스 정합성 검사
uv run python -m apps.worker audit
```

월간 운영에서는 `--analysis-month`, `--cutoff`, `--effective-date`를 명시하고,
검증 실행과 발행 실행에 같은 값을 사용하세요. Analyzer는 적격 업종과 기업을 모두
발행하고, Trader가 TA 조건·총 투자 한도·종목당 한도를 적용해 실제 목표 비중을
결정합니다. 날짜 규칙, 부분 실행, 재분석 옵션은
[Analyzer 가이드](apps/worker/analyzer/README.md)를 참고하세요.

## 매매 실행 모드

### 1회 실행

```powershell
# 주문 없이 계획만 계산
uv run python run_live_trader.py --dry-run

# 로컬 가상 계좌와 즉시 체결 엔진
uv run python run_live_trader.py --simulate

# KIS 모의투자 계좌 주문
uv run python run_live_trader.py --mock

# 장전 FA/TA 후보 생성과 유니버스 동기화
uv run python run_live_trader.py --mock --premarket
```

`run_live_trader.py`에서 모드를 생략하면 KIS 모의투자가 기본값입니다. 로컬
시뮬레이션 상태와 로그는 `logs/simulate/`에 저장됩니다.

### 자동 실행

Scheduler는 KRX 거래일 08:30에 장전 준비를 실행하고, 09:00~15:20에는 매분
매매 사이클을 실행합니다. 대시보드는 `실제 주문`과 `주문 후보`를 분리하고,
보유종목 신호 데이터 또는 위험점검이 누락되면 `NORMAL` 대신 `DEGRADED_*`
상태를 표시합니다.

```powershell
# 기본값: 주문 없는 점검 모드
uv run python scheduler.py

# 로컬 가상 계좌. 장 종료 후 일일 건강 리포트도 생성
uv run python scheduler.py --simulate

# KIS 모의투자 주문
uv run python scheduler.py --paper
```

Windows 운영 배치 `scripts/run_scheduler.bat`는 인수가 없으면 `--paper`를 사용합니다.
최초 PAPER 시작은 DB 마이그레이션, DRY_RUN→PAPER 승격 게이트와 인증 기준선을
요구합니다. 인증된 PAPER 기준선이 이미 있는 재시작은 오래된 DRY_RUN 리포트를
다시 요구하지 않고, 주문 없는 현재 계좌 스냅샷의 계좌 범위·전략 일치를 확인하는
안전한 연속 운영 게이트를 통과한 뒤에만 스케줄러를 시작합니다.
주문 없는 점검이 필요하면 `scripts/run_scheduler.bat --dry-run`을 명시합니다. 직접 실행하는
`uv run python scheduler.py`의 안전 기본값은 계속 DRY_RUN입니다. `--live`는 별도의
REAL 승격 게이트와 수동 확인 없이는 시작되지 않습니다.
`scripts/run_trader.bat`의 메뉴 2번은 주문 없는 DRY_RUN이며, PAPER와 REAL은 별도
메뉴와 게이트로 분리되어 있습니다. DRY_RUN 1거래일의 FINAL EOD 보고서가
통과한 뒤 PAPER를 처음 열기 전에는 메뉴 7번으로
주문 없는 계좌 스냅샷과 인증 기준선을 먼저 만듭니다. 기준선이 없으면 PAPER
실행도 차단됩니다. REAL 기준선은 REAL 최종 확인 뒤 첫 주문 직전에 주문 없이
자동 캡처하며, 캡처 실패 시 실주문을 중단합니다.

DRY_RUN/PAPER/REAL 스케줄러는 거래일 15:30에 EOD 성과·운영 보고서를
`reports/promotion/<mode>/daily/`에 생성합니다. PAPER 보고서는 BAT의 REAL
게이트가 읽는 `reports/promotion/real_readiness.json`도 갱신합니다. 인증 기준선,
동일 계좌 범위, 당일 잔고, KOSPI, 주문·체결 원장, 외부 현금흐름 장부 중 하나라도
검증되지 않으면 `validation_status=BLOCKED`가 되어 REAL 전환이 불가능합니다.
웹 대시보드도 별도 리포트를 계산하지 않고 이 공식 JSON/Markdown 산출물을 직접
읽습니다. 생성 실패 시 스케줄러는 5분 간격으로 재시도하며, 성공한 날짜만 완료로
기록합니다.

```powershell
# 장 마감 보고서를 수동 재생성
uv run python -m core.analytics.trading_performance --mode DRY_RUN
uv run python -m core.analytics.trading_performance --mode PAPER

# 기준선 존재 여부 확인
uv run python -m core.analytics.trading_performance --mode PAPER --check-baseline
```

거래일 라이브러리에 아직 반영되지 않은 임시 휴장일은 쉼표로 추가할 수 있습니다.
잘못된 날짜 형식은 안전을 위해 실행 오류로 처리됩니다.

```powershell
$env:KRX_ADDITIONAL_HOLIDAYS="2026-08-03,2026-10-12"
```

시뮬레이션 리포트는 `logs/simulate/reports/`에 생성되며 필요하면 직접 다시 만들 수
있습니다.

```powershell
uv run python -m core.execution.simulation_report
```

## 실전 주문 안전장치

실전 주문은 다음 세 조건이 모두 충족되어야 합니다.

1. CLI에 `--live` 지정
2. `KIS_ENV=real`
3. `ALLOW_LIVE_ORDER=true`

```powershell
uv run python run_live_trader.py --live
uv run python scheduler.py --live
```

전체 청산은 추가 확인 문자열이 필요합니다.

```powershell
uv run python run_live_trader.py --live --liquidate --confirm-liquidate LIQUIDATE
```

주문 전 KIS 현재가와 전략 기준가의 편차를 검사하고, 브로커 접수 응답이 아니라
KIS 주문·체결 조회 결과만 체결 원장에 기록합니다. 주요 운영 한도는
`MAX_PRICE_DEVIATION`, `MAX_POSITION_WEIGHT`, `BUY_CASH_BUFFER`,
`MAX_ORDER_ATTEMPTS`, `KIS_FILL_POLL_ATTEMPTS`, `KIS_FILL_POLL_INTERVAL`,
`MAX_DAILY_LOSS_RATE`로 조정할 수 있습니다. `TRADING_KILL_SWITCH=true`는 신규
매수와 비중 확대만 즉시 멈추며, 보유 포지션의 매도·손절은 계속 허용합니다.

`scripts/run_scheduler.bat`는 시작할 때 `storage.postgres.migrate`를 실행해 기존 DB에도
주문·포지션·잔고의 전략·실행환경·마스킹 계좌 분리 마이그레이션(08/09)을
자동 적용합니다. 적용 원장은 `schema_migrations`에 체크섬과 함께 기록되며,
이미 적용된 버전은 안전하게 건너뜁니다.
전체 안전 불변식, KPI, DRY_RUN→PAPER→REAL 승격 조건은
[자동매매 시스템 설계 기준](docs/AUTOMATED_TRADING_SYSTEM_DESIGN.md)을 참고하세요.

## 백테스트와 연구

```powershell
# 랜덤 유니버스 기반 기본 백테스트
uv run python -m apps.backtester run

# 발행된 시점 안전 FA 유니버스 기반 백테스트
uv run python -m apps.backtester run `
  --universe-source fa-published `
  --fa-source-strategy risk_neutral `
  --start 2020-01-01 `
  --end 2025-12-31

# FA 점수 배분 방식 비교와 역사 리플레이
uv run python -m apps.backtester.fa_weighting_research
uv run python -m apps.backtester.fa_weighting_replay --pass-only
```

일반 백테스트 결과는 `reports/backtester/<timestamp>/`에, FA 배분 연구 결과는
`reports/fa_weighting_*`에 저장됩니다. 일반 결과에는 `report.md`, `metrics.json`,
`figures/*.png`가 포함됩니다.

## 테스트

```powershell
uv run pytest
```

특정 영역만 확인할 수도 있습니다.

```powershell
uv run pytest tests/test_trading_safety.py tests/test_live_trader_and_strategy.py
uv run pytest tests/test_fa_ta_integrity.py tests/test_23_fa_published_backtest.py
```

## 프로젝트 구조

```text
QuantPilot/
├── apps/
│   ├── worker/                 # 데이터 수집, FA 분석, 발행, 운영 감사
│   └── backtester/             # 백테스트 CLI와 FA 배분 연구
├── core/
│   ├── broker/                 # KIS·로컬 시뮬레이션 브로커
│   ├── execution/              # 주문 실행, 체결 확인, 리포트
│   ├── strategy/               # 위험중립·적극투자·FA/TA 전략
│   ├── signal/                 # 시장 국면과 진입·청산 신호
│   ├── portfolio/              # 배분, 의사결정, 로테이션
│   ├── backtest/               # 백테스트 엔진
│   └── analytics/              # 성과지표와 시각화
├── data/
│   ├── collectors/             # 외부 데이터 수집기
│   ├── loaders/                # DB·시장 데이터 로더
│   └── preprocess/             # 재무·매크로 데이터 전처리
├── storage/postgres/
│   ├── schema/                 # PostgreSQL DDL과 시드
│   ├── repositories/           # 저장소 계층
│   └── docker-compose.yml
├── docs/                       # 전략과 외부 API 참고 문서
├── obsidian/                   # 운영·구현 상세 문서
├── notebooks/                  # 실험용 노트북
├── reports/                    # 백테스트와 연구 결과
├── logs/                       # 모드별 실행·감사 로그
└── tests/                      # 단위·통합 테스트
```

## 추가 문서

- [Worker 개요](apps/worker/README.md)
- [Collector 실행 가이드](apps/worker/collector/README.md)
- [Analyzer 실행 가이드](apps/worker/analyzer/README.md)
- [Backtester 실행 가이드](apps/backtester/README.md)
- [FA/TA 운영 전략](docs/FA_TA_STRATEGY.md)
- [Trader 운영 문서](obsidian/apps_trader/00_Trader_개요.md)
