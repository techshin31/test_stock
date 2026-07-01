---
title: target all
created: 2026-06-29
source_basis: code_only
tags:
  - collector
  - target
  - all
---

# target all

실행:

```powershell
python -m apps.worker collect all
```

## 실행 순서

근거 코드: `apps.worker.__main__.run_collect`

```text
macro_job.run
wics_job.run(collect_prices=False)
company_job.run
wics_industry_job.run
optional readiness.run
```

## 주요 옵션

| 옵션 | 영향 |
|---|---|
| `--start` | 전체 수집 시작일 |
| `--end` | 수집 종료일과 readiness cutoff |
| `--years` | company 재무제표 연도 |
| `--company-size` | company 수집 대상 규모 |
| `--wics-snapshot-frequency` | WICS 스냅샷 날짜 목록 생성 방식 |
| `--force-refresh` | WICS 스냅샷 재조회 |
| `--check-readiness` | 수집 후 readiness JSON 출력 |
| `--no-progress` | 진행바 억제 |

## collect all의 특이점

`--end`를 생략하면 수집 종료일은 KST 오늘 기준 전날이다. `--start`도 생략한
일상 증분 실행에서는 시작일과 종료일이 모두 전날로 맞춰져 실행 당일 데이터가
섞이지 않는다.

`wics_job`은 `collect_prices=False`로 실행된다. 이후 `company_job`이 `companies`를 채운 뒤 `wics_industry_job`이 별도 실행되어 KOSPI 구성종목 가격을 수집한다.

관련 다이어그램: [[../04_다이어그램/collect_all_전체흐름|collect all 전체흐름]]
