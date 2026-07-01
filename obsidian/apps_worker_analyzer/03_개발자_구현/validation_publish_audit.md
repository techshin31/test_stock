---
title: validation publish audit
created: 2026-06-30
source_basis: code_only
tags:
  - analyzer
  - developer
  - validation
  - publish
---

# validation publish audit

근거 코드:

- `apps/worker/analyzer/validation.py`
- `apps/worker/analyzer/universe_job.py`
- `apps/worker/analyzer/operations.py`
- `storage/postgres/repositories/universe_repo.py::publish_fa_run`

## source readiness

`validate_source_readiness()`는 Collector readiness를 재사용한다.

```text
run_readiness(db, cutoff_date)
  -> severity FAIL check가 하나라도 실패하면 SourceReadinessError
```

FAIL readiness는 analysis run 생성 전에 중단된다.

## run validation

`validate_run()`은 `analyze all`의 최종 결과 계약을 검사한다.

| check | 실패 심각도 | 내용 |
|---|---|---|
| `macro_results` | WARNING | 필수 macro 결과 누락 |
| `macro_point_in_time` | FAIL | macro last_available_date가 cutoff 이후 |
| `sector_selection` | WARNING | 선택 업종 수가 config 범위 밖 |
| `company_selection` | WARNING | 총 기업 수, 업종 수, 업종별 기업 수 제한 위반 |
| `company_contract` | WARNING | 종목 형식, 시장, 상태, size, available_date 계약 위반 |
| `company_risk` | WARNING | effective date 기준 선택 기업이 buy blocked |

critical check는 `macro_point_in_time` 하나다. 미분류 실패도 FAIL로 처리된다.

## publish 조건

`publish_fa_run()`의 주요 조건:

- run 상태가 `PASS` 또는 `WARNING`
- 현재 KST 날짜가 `effective_date`를 지나지 않음
- strategy가 active이며 이름이 config와 같음
- 선택 기업 수가 expected count 이하
- 선택 기업이 enabled market type, ACTIVE, 6자리 숫자 종목코드
- effective date 기준 `BLOCK_BUY` 또는 `SELL_ONLY` 위험상태가 없음

## publish 처리

DB transaction 안에서 처리한다.

1. `fa_analysis_runs` row lock
2. 기존 ACTIVE 중 미선정 종목을 `SELL_ONLY`로 전환
3. 선택 기업을 `ACTIVE`로 upsert
4. `source_fa_company_result_id`로 선정 근거 연결
5. run 상태를 `PUBLISHED`로 변경

중간에 실패하면 transaction rollback으로 기존 universe가 유지된다.

## audit

`audit_operational_state()`는 다음 값을 확인한다.

| 필드 | 조회 의미 |
|---|---|
| `macro_point_in_time_violations` | `fa_macro_results.last_available_date > fa_analysis_runs.cutoff_date` |
| `company_point_in_time_violations` | `fa_company_results.latest_available_date > cutoff_date` |
| `stale_running_count` | 1시간 이상 RUNNING |
| `published_universe_mismatches` | 최신 PUBLISHED 선택 기업과 ACTIVE universe 차이 |
| `average_monthly_turnover` | PUBLISHED run 사이 선택 기업 교체율 |

감사 status는 위반 값이 하나라도 있으면 `FAIL`이다.

