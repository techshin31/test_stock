---
title: company job 기업선정
created: 2026-06-30
source_basis: code_only
tags:
  - analyzer
  - developer
  - company
---

# company job 기업선정

근거 코드: `apps/worker/analyzer/company_job.py`

## 분기 FA 원장 생성

`refresh_quarterly_scores()`는 cutoff 기준 `financial_statements`를 읽어 `company_quarter_fa`를 갱신한다.

```text
fetch_financial_statements_as_of
build_quarter_fundamentals
fetch_company_statuses
fetch_wics_companies
_add_derived_metrics
score_quarter_fundamentals
upsert_company_quarter_fa
```

### 누적 공시의 개별 분기 변환

DART 분기/반기/3분기 보고서는 누적 flow 값을 포함할 수 있다. `build_quarter_fundamentals()`는 같은 연도 이전 분기 누적값을 차감해 개별 분기 flow를 만든다.

flow metric:

- revenue
- operating_income
- net_income
- operating_cashflow
- capex

## score model

`score_model_for(industry_code)`가 업종별 모델을 정한다.

| 모델 | 업종 |
|---|---|
| `FINANCIAL_V1` | 은행, 보험, 증권, 다각화금융 |
| `BIOTECH_V1` | 바이오텍 |
| `GENERAL_V1` | 그 외 WICS 중분류 |
| `UNSUPPORTED` | 알 수 없는 WICS 업종 |

## 기업 FA 점수

`score_quarter_fundamentals()`는 같은 `fiscal_quarter`, `score_model_code` cohort 안에서 percentile을 계산한다.

| 축 | 점수 범위 | 내용 |
|---|---:|---|
| level | 0~60 | 수익성, 안정성, 현금흐름, valuation proxy |
| change | 0~30 | YoY 성장과 개선 |
| risk | 0~10 | 모델별 risk penalty 차감 |

최종:

```text
fa_score = level_score + change_score + risk_score
score_confidence = level_confidence * 0.6 + change_confidence * 0.3 + risk_confidence * 0.1
```

## 기업 선정 입력

`run()`은 선택 업종만 대상으로 기업을 고른다.

| 입력 | 조회 |
|---|---|
| 선택 업종 | `fetch_sector_results(selected_only=True)` |
| 최신 WICS snapshot | `fetch_latest_wics_snapshot` |
| 최신 company FA | `fetch_latest_company_fa_as_of` |
| 기업 상태 | `fetch_company_statuses` |
| 위험상태 | `fetch_active_company_risk_states` |

## 하드 필터

| 제외 코드 | 조건 |
|---|---|
| `MAPPING_ERROR` | 회사 상태/시장/업종 매핑 문제 |
| `BUY_BLOCKED` | 회사 상태가 ACTIVE가 아니거나 위험상태가 유효 |
| `NOT_LARGE` | WICS 규모가 LARGE가 아님 |
| `NO_QUARTER_FA` | cutoff 기준 company FA 없음 |
| `CAPITAL_IMPAIRMENT` | 총자본 <= 0 또는 capital impairment |
| `LOW_CONFIDENCE` | score confidence 미달 |
| `LOW_FA_SCORE` | FA 점수 미달 |

## 업종별 rank

eligible 기업을 다음 순서로 정렬한다.

```text
fa_score desc
score_confidence desc
latest_trd_amt desc
stock_code asc
```

각 선택 업종별 rank 1~2만 `is_selected=True`다.

## 출력

`insert_company_results()`가 `fa_company_results`에 선정/비선정 기업을 저장한다.

`selection_detail`에는 정렬 키, 원천 FA ID, 위험상태 근거가 들어간다.

