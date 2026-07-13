# apps/backtester

`notebooks/위험중립형_전략_백테스팅.ipynb`를 재사용 가능한 CLI로 옮긴 것. `core/backtest` + `core/analytics` + `data/loaders/kospi_data.py`는 그대로 사용하고, 이 앱은 입력 준비(랜덤 유니버스/교체 계획) → 파이프라인 실행 → 결과를 파일로 저장하는 오케스트레이션만 담당한다.

## 명령어

```bash
python -m apps.backtester run [옵션]
```

| 옵션 | 기본값 | 설명 |
|---|---|---|
| `--strategy-name` | `risk_neutral` | `strategies` 테이블 조회 키 |
| `--start` / `--end` | `2018-01-01` / `2025-12-31` | 백테스트 기간 |
| `--capital` | `10000000` | 초기 투자금 (원) |
| `--risk-free-rate` | `0.030` | Sharpe/Sortino 계산용 무위험 이자율 |
| `--universe-size` | `5` | 초기 유니버스 종목 수 |
| `--rotation-size` | `2` | 교체 시점당 편출/편입 종목 수 |
| `--rotation-interval-years` | `2` | 종목 교체 주기 (년) |
| `--seed` | `42` | 랜덤 유니버스 생성 시드 |
| `--output-dir` | `reports/backtester/<timestamp>` | 결과 저장 경로 |
| `--universe-source` | `random` | `random` 또는 시점 안전 `fa-published` |
| `--no-charts` | - | 차트 PNG 저장을 건너뛴다 (빠른 실행) |

## 사전 준비 (환경 변수)

`apps/backtester/.env`에 설정한다 ([config.py](config.py)):

| 변수 | 필수 | 기본값 | 설명 |
|---|---|---|---|
| `POSTGRES_HOST` / `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB` | ✅ | - | DB 접속 정보 ([apps/trader](../trader)와 동일한 컨벤션) |
| `POSTGRES_PORT` | | `5432` | |

DB에는 `strategies` 테이블에 `risk_neutral` 전략 파라미터가 미리 seed되어 있어야 한다 (`storage/postgres/schema/03_trader_schema.sql` → `06_strategy_seed.sql`).

## 동작 ([pipeline.py](pipeline.py))

1. `fetch_strategy_params(db, strategy_name)`로 전략 파라미터 조회 → `RiskNeutralStrategy` 생성.
2. KOSPI 지수 + 랜덤 유니버스([universe.py](universe.py))로 정한 종목들의 OHLCV를 yfinance로 다운로드 (지표 워밍업을 위해 시작일보다 2년 일찍 받음).
3. 단기채 ETF 방어자산 수익률 생성, `BacktestConfig` 구성 후 `core.backtest.engine.run_backtest()` 실행.

`--universe-source fa-published`는 `fa_analysis_runs.status_code=PUBLISHED`인 실행만
읽어 각 `effective_date`의 선택 종목(개수 제한 없음)을 교체 계획으로 변환한다. 백테스트 시작일
이전 PUBLISHED 유니버스가 없거나 입력 사용 가능일이 cutoff를 넘으면 실행하지 않는다.
4. `calc_performance()`로 성과 계산, 단기채 100%/KOSPI B&H 자산 곡선과 `summarize_compare_assets()`로 비교.

> FA(펀더멘털) 분석 기반 종목 선정은 생략하고 랜덤 유니버스 + 주기적 교체로 대체한다 (노트북과 동일). 실제 운용 검증 시에는 [universe.py](universe.py)의 `build_random_universe()`를 펀더멘털 스크리닝 결과로 교체해야 한다.

## 출력 ([report.py](report.py))

`--output-dir`(기본 `reports/backtester/<timestamp>/`)에 다음을 저장한다:

- `report.md` — KPI 표, Top Drawdown, Walk-Forward 윈도우, 유니버스 스냅샷 + 투자자 해석 코멘터리 (`core/analytics/report.py`의 `to_markdown` + `build_investor_commentary`)
- `metrics.json` — `PerformanceReport` 전체 필드 + 비교자산 요약 + 초기 유니버스
- `figures/*.png` — 자산곡선/드로우다운/월별 수익률/국면/Walk-Forward/유니버스 타임라인/종목 기여도/거래비용 차트 (`--no-charts`로 생략 가능)

콘솔에는 `print_summary()`의 요약만 출력된다.
