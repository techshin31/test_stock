# QuantPilot
주식 트레이딩 시스템

---
### 개발 환경 구축 
```shell
# uv 패키지 설치
uv sync
# 개발 의존성 포함 설치 (pytest 등)
uv sync --dev
```

#### PostgreSQL 실행 (Docker)
```shell
# Docker Desktop 실행 후
docker compose -f storage/postgres/docker-compose.yml up -d

```

---
### apps 실행 예제

#### apps/worker — 데이터 수집
```shell
# 환경변수 설정 (최초 1회)
cp apps/worker/.env.example apps/worker/.env
# .env 에 POSTGRES_*, DART_API_KEY, FRED_API_KEY 입력

# 매크로 시그널 수집 (마지막 저장일 이후 자동 증분)
python -m apps.worker collect macro

# WICS 섹터 구성종목 스냅샷 수집
python -m apps.worker collect wics

# 재무제표 + DART 공시 이벤트 수집
python -m apps.worker collect company

# 전체 한 번에 수집 (cron 환경)
python -m apps.worker collect all --no-progress

# 날짜 범위 지정
python -m apps.worker collect macro --start 2024-01-01 --end 2025-12-31
python -m apps.worker collect wics  --start 2025-01-01 --end 2025-12-31

# 재무제표 연도 직접 지정
python -m apps.worker collect company --years 2023 2024 2025
```

#### apps/backtester — 백테스트 실행
```shell
# 환경변수 설정 — apps/backtester/.env 에 POSTGRES_* 입력

# 기본 실행 (위험중립형, 2018~2025, 초기 투자금 1천만원)
python -m apps.backtester run

# 옵션 지정 예
python -m apps.backtester run \
  --strategy-name risk_neutral \
  --start 2020-01-01 \
  --end 2025-12-31 \
  --capital 20000000 \
  --universe-size 5 \
  --rotation-size 2 \
  --rotation-interval-years 2 \
  --seed 42

# 차트 저장 없이 빠르게 실행
python -m apps.backtester run --no-charts

# 출력 디렉토리 지정
python -m apps.backtester run --output-dir reports/my_test
```

결과는 `--output-dir`(기본 `reports/backtester/<timestamp>/`)에 저장됩니다:
- `report.md` — KPI 표, Top Drawdown, 투자자 해석 코멘터리
- `metrics.json` — 성과지표 전체
- `figures/*.png` — 자산곡선, 드로우다운, 월별수익률 등 차트

#### apps/trader — 자동매매
```shell
# 환경변수 설정 — apps/trader/.env 에 KIS_APP_KEY, KIS_APP_SECRET, KIS_DOMESTIC_STOCK_ACCOUNT_NO, POSTGRES_* 입력

# 장전 (08:30) — 포지션 동기화 → 전략 계산 → trade_plans 저장
python -m apps.trader planner

# 장중 (09:00~15:20) — trade_plans 조회 → 주문 실행
python -m apps.trader executor

# 장마감 (15:40) — 체결 reconcile, 포지션 재동기화, Slack 알림
python -m apps.trader reconciler

# 테스트 모드 (시간 대기 없이 즉시 실행, 모의투자)
python -m apps.trader planner --test
# 주의: executor --test 는 무한 루프이므로 반드시 시간 제한 또는 Ctrl+C 로 종료
```

---
### 폴더 구조

```
QuantPilot/
│
├── apps/                         # 실행 애플리케이션
│   ├── backtester/               # 백테스트 CLI (pipeline.py → report.py)
│   ├── trader/                   # 자동매매 실행기 (planner / executor / reconciler)
│   └── worker/                   # 데이터 수집 워커 (collector/)
│
├── core/                         # 핵심 비즈니스 로직
│   ├── constant/                 # 공통 상수 및 열거형 (types.py, values.py)
│   │
│   ├── indicator/                # 기술적 지표 계산 (숫자값 반환)
│   │   ├── momentum/             # 모멘텀 지표 (rsi.py)
│   │   ├── trend/                # 추세 지표 (ma.py, macd.py)
│   │   ├── trend_strength/       # 추세 강도 지표 (adx.py)
│   │   ├── volatility/           # 변동성 지표 (atr.py, bollinger.py)
│   │   └── volume/               # 거래량 지표 (obv.py)
│   │
│   ├── signal/                   # 시장 상태 분류 및 매수/매도 시그널
│   │   ├── market_regime.py      # 4국면 판별 (UPTREND/DOWNTREND/SIDEWAYS/TRANSITION)
│   │   ├── entry/                # 매수 진입 시그널 (uptrend.py, sideways.py)
│   │   └── exit/                 # 매도 청산 시그널 (atr_stop, bollinger, deadcross, regime, transition)
│   │
│   ├── strategy/                 # 전략 시스템 (언제, 무엇을, 얼마나 매매할지 결정)
│   │   ├── base.py               # 전략 추상 기반 클래스
│   │   ├── state.py              # StrategyState (트레이딩 모드 상태 관리)
│   │   ├── risk_neutral.py       # 위험중립형 전략 (단기채 ETF 방어, Beta ≤ 0.8)
│   │   └── aggressive.py         # 적극투자형 전략 (인버스 ETF 방어, B&H 초과 수익)
│   │
│   ├── optimization/             # 전략 파라미터 최적화
│   │   ├── walk_forward.py       # Walk-Forward 최적화
│   │   └── grid_search.py        # 그리드 탐색
│   │
│   ├── portfolio/                # 포트폴리오 관리 (allocation, decision, momentum, rotation)
│   ├── risk/                     # 리스크 관리 (cost.py)
│   ├── trade/                    # 증권사 API 래퍼 (kis_broker.py, execution.py, gate.py)
│   ├── backtest/                 # 백테스팅 엔진 (engine.py, config.py, result.py)
│   ├── analytics/                # 성과 분석 (metrics, drawdown, attribution, visualization)
│   └── utils/                    # 유틸리티 (date_utils.py, trading_calendar.py, parsing.py)
│
├── data/
│   ├── collectors/               # 데이터 수집 (dart, fred, krx, macro, wics, yfinance)
│   ├── loaders/                  # 데이터 로더 (kospi, company, macro, fx, rates, wics 등)
│   └── preprocess/               # 전처리 (ohlcv, macro_signals, sector_signals, financial_statements)
│
├── storage/
│   └── postgres/                 # PostgreSQL
│       ├── repositories/         # DB 레포지터리 (company, trade, order, position 등)
│       ├── schema/               # DDL + 시드 SQL
│       ├── docker-compose.yml    # PostgreSQL 컨테이너 설정
│       └── connection.py         # 커넥션 풀
│
├── notebooks/                    # 실험용 Jupyter
│   ├── 위험중립형_전략_백테스팅.ipynb
│   ├── 위험중립형_전략_백테스터_실행.ipynb
│   └── 브로커 핵심기능.ipynb
│
├── obsidian/                     # 투자 지식 관리
│   ├── TA지표/                   # RSI, MA, MACD, ADX, ATR, 볼린저밴드, OBV
│   ├── 성과지표/                 # CAGR, MDD, Sharpe, Calmar, Alpha, Beta 등
│   ├── 최적화/                   # Grid Search, Walk-Forward 방법론
│   ├── 투자성향/                 # 위험중립형·적극투자형 전략 설명
│   ├── 매매원칙/                 # 분할매수매도, 인버스ETF 매매 원칙
│   └── 트레이드/                 # 위험중립형 전략 트레이딩
│
├── docs/                         # 참고 문서
│   ├── 한국투자증권/             # KIS API 문서 (OAuth, 주문, 시세)
│   └── 위험중립형_트레이딩_리스크_주문체결_검토.md
│
├── logs/                         # 감사 로그 (trader_audit.jsonl)
├── tests/                        # 테스트
├── conftest.py
├── main.py
├── pyproject.toml
└── uv.lock
```
