---
title: target macro
created: 2026-06-29
source_basis: code_only
tags:
  - collector
  - target
  - macro
---

# target macro

실행:

```powershell
python -m apps.worker collect macro
```

## 실행 코드 경로

```text
apps.worker.__main__.run_collect
  -> apps.worker.collector.macro_job.run
  -> data.preprocess.macro_signals.collect_and_save
  -> storage.postgres.repositories.macro_signal_repo.upsert_macro_signals
```

## 주요 옵션

| 옵션 | 영향 |
|---|---|
| `--start` | macro 수집 시작일. 미지정 시 `macro_job`에서 `2010-01-01` |
| `--end` | macro 수집 종료일. 미지정 시 오늘 |
| `--no-progress` | 콘솔 진행 출력 억제 |

## 필요한 API 키

| 변수 | 필요한 데이터 |
|---|---|
| `FRED_API_KEY` | CPI vintage, FRED 계열 일부 월간 지표 |
| `KTO_API_KEY` | `KR_TOURIST` |

## 저장

- [[../03_전처리_저장/macro_signals_전처리_저장|macro_signals 전처리 저장]]

