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
