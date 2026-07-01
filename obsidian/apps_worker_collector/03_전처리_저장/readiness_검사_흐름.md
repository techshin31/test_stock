---
title: readiness 검사 흐름
created: 2026-06-29
source_basis: code_only
tags:
  - collector
  - readiness
---

# readiness 검사 흐름

관련 실행: [[../01_실행가이드/target_all|target all]]

## 실행 함수

```text
run_collect
  -> readiness.run
  -> load_readiness_snapshot
  -> evaluate_readiness
```

## 검사 입력

| check | 입력 테이블 |
|---|---|
| `source_columns` | information_schema |
| `macro_coverage` | `macro_signals` |
| `financial_quarter_coverage` | `wics_companies`, `companies`, `financial_statements` |
| `wics_snapshot_history` | `wics_companies` |
| `wics_price_history` | `wics_industry_prices`, `wics_constituent_prices` |
| `source_duplicates` | `macro_signals`, `wics_companies`, `financial_statements` |

추가로 `fetch_active_company_risk_snapshot`이 `company_risk_states`를 조회한다. 현재 구현에서는 별도 `ReadinessCheck`로 PASS/FAIL을 만들지는 않지만, `ReadinessSnapshot`과 `input_hash`에는 포함된다.

## 저장 여부

readiness 결과는 콘솔 JSON으로 출력된다. 현재 Collector 코드에서는 DB 테이블에 저장하지 않는다.

## 다이어그램

```mermaid
flowchart TB
    subgraph TRIGGER["0. 실행 조건"]
        direction TB
        A["python -m apps.worker collect all --check-readiness<br/>전체 수집 후 준비도 검사 옵션"] --> B["run_collect<br/>target == all 검증"]
        B --> C["cutoff_date = collect_end<br/>--end 없으면 KST 오늘 기준 전날"]
        C --> D["readiness.run(db, cutoff_date)<br/>준비도 검사 실행"]
    end

    subgraph SNAPSHOT["1. load_readiness_snapshot<br/>검사용 DB 스냅샷 구성"]
        direction TB
        D --> E["fetch_schema_columns<br/>SOURCE_INPUT_COLUMNS 필수 컬럼 조회"]
        E --> F["fetch_macro_signal_coverage<br/>필수 매크로 최신 available_date/legacy 여부"]
        F --> G["fetch_finance_industry_coverage<br/>업종별 대형주 8분기 재무제표 커버리지"]
        G --> H["fetch_wics_summary<br/>WICS 스냅샷 earliest/latest/count"]
        H --> I["fetch_industry_price_coverage<br/>공식 WICS 가격 히스토리"]
        I --> J["fetch_constituent_coverage<br/>구성종목 종가 기반 대체 커버리지"]
        J --> K["fetch_source_duplicate_counts<br/>원천 테이블 중복 카운트"]
        K --> L["fetch_active_company_risk_snapshot<br/>활성 위험상태 스냅샷"]
        L --> M["ReadinessSnapshot<br/>검사 입력 묶음 생성"]
    end

    subgraph EVALUATE["2. evaluate_readiness<br/>검사 항목 평가"]
        direction TB
        M --> N["source_columns<br/>필수 입력 컬럼 누락 여부"]
        M --> O["macro_coverage<br/>필수 매크로 누락/노후/legacy 여부"]
        M --> P["financial_quarter_coverage<br/>지원 업종 대형주 8분기 커버리지"]
        M --> Q["wics_snapshot_history<br/>3년 이상 스냅샷 히스토리와 100개 이상 기준일"]
        M --> R["wics_price_history<br/>공식 WISEINDEX 또는 구성종목 종가 기반 3년 가격 히스토리"]
        M --> S["source_duplicates<br/>macro/wics/financial 원천 중복 여부"]
    end

    subgraph REPORT["3. 결과 생성"]
        direction TB
        N --> T["FAIL 우선 판정<br/>source_columns/source_duplicates 실패 시 FAIL"]
        O --> U["WARNING 판정<br/>커버리지/히스토리 부족 시 WARNING"]
        P --> U
        Q --> U
        R --> U
        S --> T
        T --> V["status = FAIL/WARNING/PASS<br/>검사 심각도 종합"]
        U --> V
        V --> W["_stable_hash(snapshot)<br/>검사 입력 해시 생성"]
        W --> X["ReadinessReport.to_dict<br/>status, cutoff_date, input_hash, checks"]
        X --> Y["JSON 출력<br/>콘솔 결과, DB 저장 없음"]
    end
```
