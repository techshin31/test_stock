---
title: storage contract
created: 2026-06-30
source_basis: code_only
tags:
  - analyzer
  - developer
  - storage
---

# storage contract

근거 코드:

- `storage/postgres/schema/06_fa_analysis_schema.sql`
- `storage/postgres/repositories/fa_analysis_repo.py`
- `storage/postgres/repositories/universe_repo.py`

## 분석 실행 헤더

`fa_analysis_runs`는 분석과 발행의 단위다.

중요 컬럼:

| 컬럼 | 의미 |
|---|---|
| `strategy_id` | 발행 대상 전략 |
| `analysis_month` | 분석 대상 월 1일 |
| `cutoff_date` | 사용 가능한 데이터 마감일 |
| `effective_date` | Trader 적용일 |
| `run_version` | 동일 전략/월 내 버전 |
| `input_hash` | 재사용 판정 해시 |
| `status_code` | RUNNING/PASS/WARNING/FAIL/PUBLISHED |
| `validation_summary` | 검증 결과 JSON |

같은 `strategy_id`, `effective_date`에는 PUBLISHED run이 하나만 허용된다.

## macro results

`fa_macro_results`는 실행별 매크로 방향 결과를 저장한다.

unique key:

```text
run_id, signal_name_code
```

`calculation_detail`에는 macro transform 세부와 업종별 relationship 목록이 들어간다.

## sector results

`fa_sector_results`는 모든 WICS 중분류 결과를 저장한다.

unique key:

```text
run_id, industry_code
```

선택되지 않은 업종도 저장하는 이유:

- 후보 탈락 사유 추적
- category cap 적용 내역 추적
- 투자자 설명과 모델 검증

## company results

`fa_company_results`는 선택 업종 내 기업 평가 결과를 저장한다.

unique key:

```text
run_id, stock_code
```

`is_selected=True`인 row만 publish 대상이다.

## universe lineage

`universe.source_fa_company_result_id`는 현재 운영 ACTIVE row가 어떤 `fa_company_results.id`에서 왔는지 연결한다.

운영 계보:

```text
fa_analysis_runs
  -> fa_company_results.is_selected
  -> universe.source_fa_company_result_id
  -> apps.trader planner/executor/reconciler
```

테스트 helper인 `seed_test_universe()`는 production publish 경로가 아니다.

