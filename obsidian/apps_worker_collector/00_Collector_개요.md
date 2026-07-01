---
title: Collector 개요
created: 2026-06-29
source_basis: code_only
tags:
  - quantpilot
  - collector
  - moc
---

# Collector 개요

`apps/worker/collector`는 `python -m apps.worker collect ...` 명령으로 실행되는 데이터 수집 서비스다. 이 노트 묶음은 구현 코드를 기준으로 Collector의 실행법, 수집 데이터, 전처리/저장 흐름을 나누어 설명한다.

## 문서 구조

```text
apps_worker_collector/
├── 01_실행가이드
├── 02_수집데이터
├── 03_전처리_저장
└── 04_다이어그램
```

## 먼저 읽기

1. [[01_실행가이드/collector_실행방법|collector 실행방법]]
2. [[01_실행가이드/collector_파라미터_레퍼런스|collector 파라미터 레퍼런스]]
3. [[02_수집데이터/00_수집데이터_지도|Collector 수집 데이터 지도]]
4. [[02_수집데이터/매크로_시그널|매크로 시그널]]
5. [[02_수집데이터/WICS_구성종목_스냅샷|WICS 구성종목 스냅샷]]
6. [[03_전처리_저장/macro_signals_전처리_저장|macro_signals 전처리 저장]]
7. [[04_다이어그램/collector_CLI_진입흐름|collector CLI 진입흐름]]
8. [[04_다이어그램/collect_all_전체흐름|collect all 전체흐름]]

## 코드 기준 실행 단위

| target | 실행되는 주요 job |
|---|---|
| `macro` | `apps.worker.collector.macro_job.run` |
| `wics` | `apps.worker.collector.wics_job.run` |
| `company` | `apps.worker.collector.company_job.run` |
| `all` | `macro_job -> wics_job -> company_job -> wics_industry_job` |

## Collector가 직접 저장하는 테이블

- `macro_signals`
- `wics_companies`
- `wics_constituent_prices`
- `companies`
- `dart_events`
- `financial_statements`
- `company_risk_states`
- `fa_metrics`

## 구현상 중요한 경계

- `wics_industry_prices`는 현재 Collector가 직접 저장하지 않는다. Collector는 `wics_constituent_prices`를 저장하고 Analyzer가 업종 지수를 재구성한다.
- `company_quarter_fa`, `fa_analysis_runs`, `fa_*_results`, `universe`는 Collector 산출물이 아니다.
- `collect all` 완료는 모든 데이터가 준비됐다는 뜻이 아니다. `--check-readiness` 결과를 같이 봐야 한다.
