---
title: target company
created: 2026-06-29
source_basis: code_only
tags:
  - collector
  - target
  - company
---

# target company

실행:

```powershell
python -m apps.worker collect company
```

## 실행 코드 경로

```text
apps.worker.__main__.run_collect
  -> apps.worker.collector.company_job.run
  -> collect_companies_from_wics
  -> sync_company_status
  -> collect_dart_events
  -> refresh_company_risk_states
  -> collect_financial_statements
```

## 주요 옵션

| 옵션 | 영향 |
|---|---|
| `--start` | DART 이벤트 시작일로 변환되어 전달 |
| `--end` | DART 이벤트 종료일과 기업 위험상태 기준일 |
| `--years` | 재무제표 수집 사업연도 |
| `--company-size` | 최신 WICS 스냅샷의 규모 코드로 대상 제한 |
| `--no-progress` | tqdm 진행바 억제 |

## 코드상 주의

`--end`를 지정하면 `company_job.run()`의 DART 이벤트 종료일로 전달된다.
`--end`가 없을 때만 실행 당일을 기본 종료일로 사용한다.

## 저장

- [[../03_전처리_저장/companies_전처리_저장|companies 전처리 저장]]
- [[../03_전처리_저장/dart_events_전처리_저장|dart_events 전처리 저장]]
- [[../03_전처리_저장/company_risk_states_전처리_저장|company_risk_states 전처리 저장]]
- [[../03_전처리_저장/financial_statements_전처리_저장|financial_statements 전처리 저장]]
