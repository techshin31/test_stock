---
title: analyzer 실행방법
created: 2026-06-30
source_basis: code_only
tags:
  - analyzer
  - execution
  - CLI
---

# analyzer 실행방법

기본 명령:

```powershell
python -m apps.worker analyze <macro|sector|company|all>
```

공식 월간 운영은 `analyze all`을 사용한다. 부분 target은 개발과 진단용이다.

## 선행 조건

Analyzer는 실행 시작 시 `apps.worker.collector.readiness.run()`을 호출한다. severity가 `FAIL`인 readiness check가 있으면 `fa_analysis_runs`를 만들기 전에 중단한다.

선행 수집:

```powershell
python -m apps.worker collect all --check-readiness --no-progress
```

관련 문서:

- [[../../apps_worker_collector/01_실행가이드/target_all|Collector target all]]
- [[../../apps_worker_collector/03_전처리_저장/readiness_검사_흐름|readiness 검사 흐름]]

## 분석만 실행

```powershell
python -m apps.worker analyze all `
  --analysis-month 2026-07 `
  --cutoff 2026-06-30 `
  --effective-date 2026-07-01 `
  --no-progress
```

이 명령은 분석 결과를 저장하지만 운영 `universe`를 바꾸지 않는다. 저장 대상은 `fa_analysis_runs`, `fa_macro_results`, `fa_sector_results`, `fa_company_results`다.

## 운영 universe 발행

```powershell
python -m apps.worker analyze all `
  --analysis-month 2026-07 `
  --cutoff 2026-06-30 `
  --effective-date 2026-07-01 `
  --publish `
  --no-progress
```

`--publish`는 `target=all`에서만 허용된다. PASS 또는 WARNING 상태의 run만 발행할 수 있다.

발행 후 동작:

| 대상 | 처리 |
|---|---|
| 이번 run의 선택 기업 | `universe`에 `ACTIVE`로 upsert |
| 기존 ACTIVE 중 미선정 기업 | `SELL_ONLY`로 전환하고 청산 기한 부여 |
| 이미 PUBLISHED인 run | 중복 발행하지 않고 현재 ACTIVE 목록 반환 |

## 날짜 기본값

`pipeline.build_request()` 기준 기본값:

| 값 | 생략 시 |
|---|---|
| `cutoff_date` | KST 오늘 |
| `effective_date` | cutoff와 같은 날짜 |
| `analysis_month` | effective date가 속한 달의 1일 |

월간 운영에서는 생략하지 말고 `--analysis-month`, `--cutoff`, `--effective-date`를 명시한다. 그래야 데이터 마감일과 Trader 적용일이 분리되어 기록된다.

## 재사용과 강제 재실행

Analyzer는 readiness input hash, config fingerprint, target, analysis month, cutoff, effective date를 합쳐 `input_hash`를 만든다.

같은 입력의 FAIL이 아닌 run이 있으면 재계산하지 않고 기존 run을 재사용한다.

```powershell
python -m apps.worker analyze all --force
```

`--force`는 새 `run_version`을 만든다. 운영 발행 이력이 있는 월에는 기존 PUBLISHED 상태와 universe를 먼저 확인한 뒤 사용한다.

## 운영 확인

최근 실행:

```powershell
docker exec postgres-db psql -U admin -d quantpilot_db -c `
  "SELECT id, analysis_month, cutoff_date, effective_date, run_version, status_code, selected_industry_count, selected_company_count, failure_reason FROM fa_analysis_runs ORDER BY id DESC LIMIT 10;"
```

선택 기업:

```powershell
docker exec postgres-db psql -U admin -d quantpilot_db -c `
  "SELECT stock_code, industry_code, fa_score, score_confidence, industry_rank, is_selected, exclusion_reason_code FROM fa_company_results WHERE run_id = (SELECT MAX(id) FROM fa_analysis_runs) ORDER BY is_selected DESC, industry_code, industry_rank NULLS LAST, stock_code;"
```

운영 감사:

```powershell
python -m apps.worker audit
```

