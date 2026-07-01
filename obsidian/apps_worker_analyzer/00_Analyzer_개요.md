---
title: Analyzer 개요
created: 2026-06-30
source_basis: code_only
tags:
  - analyzer
  - overview
  - FA
---

# Analyzer 개요

`apps/worker/analyzer`는 Collector가 적재한 시점 안전 원천 데이터를 읽어 월간 FA 투자 후보를 만든다. 외부 API를 직접 호출하지 않고, DB에 저장된 `macro_signals`, `wics_*`, `financial_statements`, `company_risk_states`만 사용한다.

운영 경계:

```text
Collector 원천 적재
  -> Analyzer FA 분석 실행
  -> universe 발행
  -> Trader 매매 계획/실행
```

중요한 점은 Trader가 `fa_company_results`를 직접 읽지 않는다는 것이다. Analyzer는 선택 결과를 `universe`에 발행하고, Trader는 `universe`를 운영 입력으로 사용한다.

## 대상 독자별 입구

| 독자 | 먼저 볼 문서 | 목적 |
|---|---|---|
| 운영자 | [[01_실행가이드/analyzer_실행방법|analyzer 실행방법]] | 월간 `analyze all` 실행과 발행 절차 |
| 개발자 | [[03_개발자_구현/파이프라인_오케스트레이션|파이프라인 오케스트레이션]] | 코드 진입점, run 재사용, 단계별 함수 흐름 |
| 투자자 | [[02_투자자_해석/00_투자자_요약|투자자 요약]] | 어떤 논리로 업종과 종목이 선택되는지 해석 |
| 감사/리스크 담당 | [[03_개발자_구현/validation_publish_audit|검증 발행 감사]] | PASS/WARNING/FAIL/PUBLISHED 조건 |

## 실제 코드 경로

| 파일 | 역할 |
|---|---|
| `apps/worker/__main__.py` | `python -m apps.worker analyze ...` CLI 진입 |
| `apps/worker/analyzer/pipeline.py` | 날짜 요청 생성, readiness, run 생성, 단계 오케스트레이션 |
| `apps/worker/analyzer/macro_job.py` | 매크로 방향과 매크로-업종 관계 계산 |
| `apps/worker/analyzer/sector_job.py` | 업종 지수 재구성, 업종 점수와 최종 업종 선정 |
| `apps/worker/analyzer/company_job.py` | 분기 기업 FA 원장 생성, 업종별 종목 선정 |
| `apps/worker/analyzer/validation.py` | Collector readiness와 결과 검증 |
| `apps/worker/analyzer/universe_job.py` | 검증된 run을 운영 `universe`에 발행 |
| `apps/worker/analyzer/operations.py` | point-in-time 위반, 고착 RUNNING, universe mismatch 감사 |
| `apps/worker/fa_contract.py` | Analyzer와 Collector가 공유하는 신호/업종/스코어 계약 |

## 저장 결과

| 테이블 | 의미 |
|---|---|
| `company_quarter_fa` | DART 분기 재무제표에서 만든 시점 안전 기업 FA 원장 |
| `fa_analysis_runs` | 월간 분석 실행 헤더, input hash, 상태, 발행 시점 |
| `fa_macro_results` | 실행별 매크로 방향, trend, 신뢰도, 관계 상세 |
| `fa_sector_results` | 실행별 WICS 중분류 평가, 후보/선정 여부 |
| `fa_company_results` | 실행별 기업 평가, 제외 사유, 최종 선정 여부 |
| `universe` | Trader가 실제로 읽는 운영 투자 가능/청산 전용 종목 집합 |

## 실행 단계 요약

```text
readiness
  -> quarterly company FA refresh
  -> macro analysis
  -> sector selection
  -> company selection
  -> validation
  -> optional universe publish
```

관련 다이어그램:

- [[04_다이어그램/00_다이어그램_지도|Analyzer 다이어그램 지도]]
- [[04_다이어그램/analyze_all_전체흐름|analyze all 전체흐름]]
- [[04_다이어그램/투자자_의사결정_흐름|투자자 의사결정 흐름]]
