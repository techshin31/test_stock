---
title: sector job 업종선정
created: 2026-06-30
source_basis: code_only
tags:
  - analyzer
  - developer
  - sector
---

# sector job 업종선정

근거 코드: `apps/worker/analyzer/sector_job.py`

## 업종 지수 재구성

`refresh_industry_prices()`는 Collector가 저장한 `wics_constituent_prices`와 `wics_companies`를 사용해 `wics_industry_prices`를 재구성할 수 있다.

```text
fetch_wics_constituent_prices
fetch_wics_companies
reconstruct_industry_indices
upsert_wics_industry_prices
```

재구성 방식:

- WICS snapshot의 `mkt_val`을 가중치로 사용
- 종목별 close로 일별 수익률 계산
- 유효 weight coverage가 `minimum_industry_price_coverage` 이상인 날짜만 사용
- 업종별 index value는 1000에서 시작해 누적

## 업종 점수 입력

`run()`은 cutoff 기준 최신 WICS snapshot을 가져온다.

| 입력 | 조회 |
|---|---|
| 최신 WICS snapshot | `fetch_latest_wics_snapshot` |
| 기업 FA 원장 | `fetch_latest_company_fa_as_of` |
| 기업 상태 | `fetch_company_statuses` |
| 위험상태 | `fetch_active_company_risk_states` |
| 매크로 관계 | `macro_results.calculation_detail.relationships` |

## eligible LARGE 계산

업종별로 다음 조건을 통과하는 기업 수를 센다.

- WICS 구성종목
- `company_size_code == allowed_company_size`, 기본 `LARGE`
- company status가 `ACTIVE`
- market type이 enabled market type, 기본 `KOSPI`
- cutoff 기준 위험상태 없음
- 최신 company FA가 `is_eligible=True`
- `fa_score >= minimum_company_fa_score`
- `score_confidence >= minimum_score_confidence`

최종 업종 선정에는 업종별 eligible LARGE가 `companies_per_industry` 이상이어야 한다.

## 점수 축

| 컬럼 | 의미 |
|---|---|
| `macro_fit_score` | capped macro contribution 합계를 0~100으로 변환 |
| `company_fa_breadth_score` | 업종 내 재무 점수 percentile, 개선율, 신뢰도 폭 |
| `liquidity_capacity_score` | 거래대금 percentile과 eligible LARGE 수 |
| `sector_risk_penalty` | 커버리지/관계신뢰도/구성종목수/집중도/cohort 품질 패널티 |
| `sector_score` | 45/35/20 가중합에서 risk penalty 차감 |

## macro category cap

`_cap_macro_category_contributions()`는 같은 macro category의 절대 contribution 총합을 `macro_category_contribution_cap` 이하로 제한한다.

cap이 적용된 항목은 `macro_contributions` 안에 다음 필드가 남는다.

- `raw_contribution`
- `category_cap_applied=True`

## 후보와 최종 선택

1. `up_benefit_score` 상위 5개를 `candidate_source_code=UP` 후보로 표시
2. `down_hedge_score` 상위 3개를 중복 없이 `candidate_source_code=DOWN` 후보로 표시
3. 후보를 `sector_score desc, industry_code asc`로 정렬
4. eligible LARGE 수가 부족하면 `INSUFFICIENT_LARGE`
5. 부족한 최종 업종 수는 non-candidate에서 `FALLBACK`으로 보충
6. 최종 최대 5개 업종에 `is_selected=True`, `final_rank` 부여

## 출력

`insert_sector_results()`가 `fa_sector_results`에 전체 WICS 업종 결과를 저장한다. 선택되지 않은 업종도 audit과 설명 가능성을 위해 저장된다.

