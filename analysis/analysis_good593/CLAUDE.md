# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

한국 주식 펀더멘털 분석(FA) 시스템. WICS(Worldwide Industry Classification Standard) 분류와 DART 재무제표를 기반으로 Top-Down 투자 분석을 수행한다.

**분석 계층:** 글로벌 매크로 → 산업(WICS 섹터) → 기업(개별 종목)

## Environment Setup

```bash
# Virtual environment activation (Windows)
.venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Launch Jupyter
jupyter notebook
```

## Common Commands

```bash
# Regenerate sector analysis notebook (e.g., IT sector)
python create_nb.py

# Regenerate Samsung (005930) company analysis notebook
python create_samsung_nb.py

# Add Samsung data to existing notebook
python add_samsung.py
```

No build, lint, or test tooling — this is a research/analysis project.

## Architecture

### Data Flow

```
data/ (CSV files)
  └─ common/load.py          ← data loading & filtering
  └─ common/analysis.py      ← metric calculation & correlations
  └─ common/plots.py         ← visualization functions
       ↓
create_nb.py / create_samsung_nb.py  ← programmatic notebook generation (nbformat)
       ↓
*.ipynb                      ← primary user interface (Jupyter)
       ↓
obsidian/                    ← knowledge capture & analysis notes
```

### Key Modules (`common/`)

- **load.py** — loads WICS market cap data (zip or CSV), DART financial statements, and global asset price CSVs. Filters by WICS major sector code (e.g., `G45` = IT, `G25` = 경기관련소비재, `G20` = 산업재, `G15` = 소재, `G30` = 필수소비재).
- **analysis.py** — aggregates sector-level market capitalization, merges with monthly macro data, computes correlation matrices between sector performance and global asset indicators.
- **plots.py** — time-series capitalization trends, sector composition charts, correlation heatmaps, normalized index (base-100) comparisons.

### Notebook Numbering Convention

| Prefix | Scope |
|--------|-------|
| `1. analysis_asset.ipynb` | 글로벌 자산 상관관계 (copper, gold, SOX, WTI, BDI, treasury, CPI) |
| `2. analysis_<sector>.ipynb` | 5대 섹터별 FA 분석 (WICS 기준) |
| `3. analysis_<sector>.ipynb` | 섹터 심화 분석 (최신 버전) |

### 7-Metric FA Framework (`FA; Fundamental Analysis.md`)

| # | 지표 | 기준 | Green | Red |
|---|------|------|-------|-----|
| 1 | 수익성 (OPM) | 영업이익률 | ≥10% | <5% |
| 2 | 성장성 | YoY 매출 성장률 | ≥10% | <0% |
| 3 | 재무안정성 | 부채비율 | <100% | >200% |
| 4 | 현금흐름 | OCF vs 순이익 | — | — |
| 5 | 밸류에이션 | PER, PBR | — | — |
| 6 | 주주환원 | 배당수익률 | ≥3% | — |
| 7 | 재무생존성 | Cash burn (적자기업) | — | — |

### Data Directory Layout

```
data/
├── 재무제표/       ← DART 재무제표 (2021-2025): balance_sheet, income_statement, cash_flow CSVs
│                    + dart_company_2026.csv, wics_company_2026.csv
├── wics/           ← 연도별 WICS 분류 + 시가총액 (zip/csv)
├── asset/          ← 글로벌 자산 가격 (구리/금/SOX/WTI/BDI/국채/CPI/달러)
├── analysis/       ← 전처리된 통합 자산 데이터 (asset_combined_*.csv)
└── wics_major.json ← WICS 섹터 코드 매핑
```

### Notebook Generation Pattern

`create_nb.py` and `create_samsung_nb.py` use `nbformat` to programmatically build notebooks — combining markdown explanation cells with executable code cells. When adding new analysis metrics, update these generator scripts (not the `.ipynb` files directly) so regeneration stays consistent.

---

## Backtrader 백테스팅 서비스 할일 목록

### Phase 1 — 기반 인프라

- [ ] **`backtest/data/loader.py`** — 자산별 CSV 파싱 어댑터 구현
  - `asset_combined_close.csv` 기본 진입점으로 `PandasData` 피드 변환
  - CPI(월봉) → 일봉 forward-fill 처리
  - BDI/SCFI 혼재 포맷 분리 파싱
- [ ] **`backtest/runner.py`** — Cerebro 래퍼
  - 전략 클래스 + 기간 + 초기자금 인자 수신
  - `start_date` / `end_date` 파라미터로 in-sample / out-of-sample 구간 분리
  - 수수료·슬리피지 기본값 설정 (0.05%)
- [ ] **`backtest/metrics.py`** — 성과 지표 계산
  - CAGR, MDD, Sharpe Ratio, Sortino Ratio, Calmar Ratio
  - 월별 수익률 히트맵 (Jupyter 출력용)

### Phase 2 — 내장 전략

- [ ] **`backtest/strategies/momentum.py`** — 자산 모멘텀 로테이션 전략 (S-1)
  - 매월 말 전 자산 N개월 수익률 계산, 상위 K개 자산 균등 투자
  - 파라미터: `lookback` (1/3/6/12개월), `top_k` (1~3개)
- [ ] **`backtest/strategies/regime.py`** — 매크로 국면 감지 전략 (S-2)
  - BDI + 구리 MA 기준 Risk-On/Off 판별
  - Risk-On → SOX/구리 매수 / Risk-Off → 금/국채 매수
- [ ] **`backtest/strategies/hedge.py`** — 금/달러 역상관 헷지 전략 (S-3)
  - 달러 강세 → 금 비중 축소 / 약세 → 금 비중 확대
  - CPI YoY ≥ 4% → 실물자산(금+구리) 오버웨이트

### Phase 3 — 분석 및 시각화

- [ ] **`backtest/report.py`** — 전략 비교 리포트
  - 복수 전략 성과 테이블 출력
  - Buy & Hold 벤치마크 비교
- [ ] **`backtest/optimizer.py`** — 파라미터 최적화
  - Backtrader `optstrategy` 그리드 서치
  - 결과 히트맵 시각화 (in/out-of-sample 분리 표시)
- [ ] **`4_backtest_analysis.ipynb`** — 백테스팅 진입점 노트북 생성

### 구현 순서

1. `loader.py` → `asset_combined_close.csv` PandasData 변환 검증
2. `runner.py` → Buy & Hold로 E2E 파이프라인 검증
3. `metrics.py` → CAGR/MDD/Sharpe 계산 검증
4. S-1 모멘텀 전략 구현
5. S-2 매크로 국면 전략 구현
6. `report.py` → 전략 비교 노트북 완성

### 주의사항

- CPI는 월 중순 발표 → 발표월 데이터는 **익월부터** 사용 (룩어헤드 바이어스 방지)
- 슬리피지 0.1% 이상 설정 권장 (상품선물 스프레드)
- BDI는 현물지수 → 직접 투자 불가, **신호 생성 전용**으로만 사용
