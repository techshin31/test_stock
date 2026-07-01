---
title: macro job 관계분석
created: 2026-06-30
source_basis: code_only
tags:
  - analyzer
  - developer
  - macro
---

# macro job 관계분석

근거 코드:

- `apps/worker/analyzer/macro_job.py`
- `apps/worker/analyzer/relationships.py`
- `apps/worker/fa_contract.py::MACRO_SIGNALS`

## 입력

| 입력 | 조회 함수 |
|---|---|
| 매크로 원천 | `fetch_macro_signals_as_of(cutoff_date, signal_names, start_observation_date, end_observation_date)` |
| 업종 지수 | `fetch_wics_industry_prices(cutoff_date, industry_codes, start_date)` |

매크로 원천은 `available_date <= cutoff_date` 조건으로 조회한다. 업종 지수는 `wics_industry_prices`에 저장된 공식/파생 지수 레벨을 사용한다.

## 매크로 방향 계산

`calculate_macro_direction()`은 contract transform에 따라 trend를 계산한다.

| transform | 계산 |
|---|---|
| `CPI_YOY_PRESSURE` | 월말 CPI YoY 변화의 3/6개월 압력 |
| `YOY_CHANGE` | 월말 값의 YoY 변화 후 3/6개월 변화 |
| `LEVEL` | 월간 level diff 기반 3/6/12개월 변화 |
| `MARKET_RETURN` | 수익률 기반 20/60/120 또는 월간 3/6/12 변화 |
| `YIELD_CHANGE` | 금리 level diff 기반 변화 |

`trend_raw`가 `macro_direction_threshold` 이상이면 `UP`, 음수 기준 이하이면 `DOWN`, 그 사이면 `FLAT`이다.

## 관계 계산

```text
transform_macro_for_relationship
  -> macro_changes
industry_returns_frame
  -> weekly_returns / monthly_returns
calculate_relationship
  -> correlation, beta, sign_stability, confidence, contribution
```

관계 confidence:

```text
sample_confidence
  x correlation_confidence
  x sign_stability
```

eligible 조건:

- sample count가 최소 샘플 이상
- 절대 상관이 최소 기준 이상
- relationship confidence가 최소 기준 이상

## contribution

```text
direction_sign
  x correlation
  x trend_strength
  x relationship_confidence
  x signal_weight
```

`FLAT` 방향은 `direction_sign=0`이라 contribution이 0이다.

## contract 제한

일부 신호는 적용 업종 제한과 상관 기준 override가 있다.

| 신호 | 제한 |
|---|---|
| `GTREND_KPOP` | `G2550`, `G5010`, `G2560` |
| `GTREND_KDRAMA` | `G2550`, `G5010`, `G2560` |
| `KR_TOURIST` | `G2550`, `G2530`, `G5010`, `G5020` |

제한 밖 업종의 relationship은 저장되지만 `is_eligible=False`, `contribution=0`으로 바뀐다.

## 출력

`insert_macro_results()`가 `fa_macro_results`에 저장한다.

중요 컬럼:

- `direction_code`
- `trend_raw`
- `trend_strength`
- `confidence`
- `calculation_detail.relationships`

