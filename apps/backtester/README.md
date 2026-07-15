# apps/backtester

`notebooks/위험중립형_전략_백테스팅.ipynb`를 재사용 가능한 CLI로 옮긴 것. `core/backtest` + `core/analytics` + `data/loaders/kospi_data.py`는 그대로 사용하고, 이 앱은 입력 준비(랜덤 유니버스/교체 계획) → 파이프라인 실행 → 결과를 파일로 저장하는 오케스트레이션만 담당한다.

## 명령어

```bash
python -m apps.backtester run [옵션]
```

| 옵션 | 기본값 | 설명 |
|---|---|---|
| `--strategy-name` | `risk_neutral` | `strategies` 테이블 조회 키 |
| `--fa-source-strategy` | `risk_neutral` | `fa-published` 유니버스를 제공할 분석 전략 |
| `--universe-source` | `random` | `random` 또는 시점 안전 `fa-published` |
| `--start` / `--end` | `2018-01-01` / `2025-12-31` | 백테스트 기간 |
| `--capital` | `10000000` | 초기 투자금 (원) |
| `--risk-free-rate` | `0.030` | Sharpe/Sortino 계산용 무위험 이자율 |
| `--universe-size` | `5` | 초기 유니버스 종목 수 |
| `--rotation-size` | `2` | 교체 시점당 편출/편입 종목 수 |
| `--rotation-interval-years` | `2` | 종목 교체 주기 (년) |
| `--seed` | `42` | 랜덤 유니버스 생성 시드 |
| `--output-dir` | `reports/backtester/<timestamp>` | 결과 저장 경로 |
| `--no-charts` | - | 차트 PNG 저장을 건너뛴다 (빠른 실행) |

## 사전 준비 (환경 변수)

`apps/backtester/.env`에 설정한다 ([config.py](config.py)):

| 변수 | 필수 | 기본값 | 설명 |
|---|---|---|---|
| `POSTGRES_HOST` / `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB` | ✅ | - | 공통 PostgreSQL 접속 정보 |
| `POSTGRES_PORT` | | `5433` | |

Docker Compose DB는 호스트 포트 `5433`을 사용한다. DB에는 `strategies` 테이블과
사용할 전략 파라미터가 미리 seed되어 있어야 한다
(`storage/postgres/schema/04_trader_schema.sql` → `07_strategy_seed.sql`).

## 동작 ([pipeline.py](pipeline.py))

1. `fetch_strategy_params(db, strategy_name)`로 전략 파라미터 조회 → `RiskNeutralStrategy` 생성.
2. `random`이면 [universe.py](universe.py)의 랜덤 유니버스를, `fa-published`이면
   지정한 전략의 PUBLISHED FA 유니버스를 시점별 교체 계획으로 구성한다. 이후 KOSPI
   지수와 대상 종목 OHLCV를 지표 워밍업 기간까지 포함해 내려받는다.
3. 단기채 ETF 방어자산 수익률 생성, `BacktestConfig` 구성 후 `core.backtest.engine.run_backtest()` 실행.

`--universe-source fa-published`는 `fa_analysis_runs.status_code=PUBLISHED`인 실행만
읽어 각 `effective_date`의 선택 종목(개수 제한 없음)을 교체 계획으로 변환한다. 백테스트 시작일
이전 PUBLISHED 유니버스가 없거나 입력 사용 가능일이 cutoff를 넘으면 실행하지 않는다.
4. `calc_performance()`로 성과 계산, 단기채 100%/KOSPI B&H 자산 곡선과 `summarize_compare_assets()`로 비교.

> `random`은 노트북과 동일한 데모·회귀검증용 입력이다. 운영 FA 흐름을 검증할 때는
> `--universe-source fa-published`와 올바른 `--fa-source-strategy`를 명시한다.

## 출력 ([report.py](report.py))

`--output-dir`(기본 `reports/backtester/<timestamp>/`)에 다음을 저장한다:

- `report.md` — KPI 표, Top Drawdown, Walk-Forward 윈도우, 유니버스 스냅샷 + 투자자 해석 코멘터리 (`core/analytics/report.py`의 `to_markdown` + `build_investor_commentary`)
- `metrics.json` — `PerformanceReport` 전체 필드 + 비교자산 요약 + 초기 유니버스
- `figures/*.png` — 자산곡선/드로우다운/월별 수익률/국면/Walk-Forward/유니버스 타임라인/종목 기여도/거래비용 차트 (`--no-charts`로 생략 가능)

콘솔에는 `print_summary()`의 요약만 출력된다.
