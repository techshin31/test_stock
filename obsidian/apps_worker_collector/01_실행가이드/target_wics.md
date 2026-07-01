---
title: target wics
created: 2026-06-29
source_basis: code_only
tags:
  - collector
  - target
  - WICS
---

# target wics

실행:

```powershell
python -m apps.worker collect wics
```

## 실행 코드 경로

```text
apps.worker.__main__.run_collect
  -> apps.worker.collector.wics_job.run
  -> data.loaders.wics_data.collect_wics_companies
  -> storage.postgres.repositories.wics_repo.upsert_wics_companies
  -> apps.worker.collector.wics_industry_job.run
  -> storage.postgres.repositories.wics_industry_repo.upsert_wics_constituent_prices
```

## 주요 옵션

| 옵션 | 영향 |
|---|---|
| `--start` | WICS 스냅샷 날짜 목록 시작 |
| `--end` | WICS 스냅샷 날짜 목록 종료와 가격 수집 종료 |
| `--wics-snapshot-frequency` | `weekly` 또는 `daily` |
| `--force-refresh` | 기수집 스냅샷 재조회 |
| `--no-progress` | tqdm 진행바 억제 |

## 저장

- [[../03_전처리_저장/wics_companies_전처리_저장|wics_companies 전처리 저장]]
- [[../03_전처리_저장/wics_constituent_prices_전처리_저장|wics_constituent_prices 전처리 저장]]

