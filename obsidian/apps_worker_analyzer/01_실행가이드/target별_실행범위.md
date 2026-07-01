---
title: target별 실행범위
created: 2026-06-30
source_basis: code_only
tags:
  - analyzer
  - target
---

# target별 실행범위

근거 코드: `apps/worker/fa_contract.py::ANALYZE_TARGET_STEPS`, `apps/worker/analyzer/pipeline.py::run`

Analyzer target은 서로 독립적인 작은 job이 아니라 누적 실행 범위다.

| target | 실행 단계 | 저장 테이블 |
|---|---|---|
| `macro` | readiness, 분기 FA 갱신, 매크로 분석 | `company_quarter_fa`, `fa_analysis_runs`, `fa_macro_results` |
| `sector` | `macro` 범위 + 업종 분석 | 위 테이블 + `fa_sector_results` |
| `company` | `sector` 범위 + 기업 선정 | 위 테이블 + `fa_company_results` |
| `all` | `company` 범위 + 결과 검증 + 선택적 발행 | 위 테이블 + 선택 시 `universe` |

## target macro

개발 목적:

- 매크로 방향 분류가 정상인지 확인
- `macro_signals`의 point-in-time 조회가 충분한지 확인
- 매크로-업종 관계 JSON이 생성되는지 확인

주의:

- `company_quarter_fa`도 먼저 갱신된다.
- 업종과 기업 결과는 생성하지 않는다.

## target sector

개발 목적:

- 업종 후보 8개와 최종 업종 최대 5개 선정 점검
- `macro_category_contribution_cap`, `eligible_large_count`, `sector_risk_penalty` 확인

주의:

- 최종 종목은 아직 선정하지 않는다.

## target company

개발 목적:

- 선택 업종 안에서 기업 필터와 업종별 top 2 선정 확인
- `NO_QUARTER_FA`, `LOW_CONFIDENCE`, `LOW_FA_SCORE`, `BUY_BLOCKED` 같은 제외 사유 확인

주의:

- 결과 검증과 `universe` 발행은 하지 않는다.

## target all

공식 운영 목적:

- 전체 FA 결과 생성
- `validate_run()`으로 결과 계약 검증
- `--publish`가 있으면 운영 `universe` 발행

공식 월간 투자 후보는 `target all` 결과와 `universe.source_fa_company_result_id` 계보로 추적한다.

