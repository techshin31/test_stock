---
title: company_risk_states 전처리 저장
created: 2026-06-29
source_basis: code_only
tags:
  - collector
  - preprocess
  - risk
---

# company_risk_states 전처리 저장

관련 데이터: [[../02_수집데이터/기업_위험상태|기업 위험상태]]

## 입력 데이터

`dart_events` 중 `event_category_code = CAPITAL_CHANGE`

## 실행 함수

```text
company_job.run
  -> refresh_company_risk_states
  -> derive_company_risk_states
  -> upsert_company_risk_states
```

## 전처리 단계

1. `CAPITAL_CHANGE` 이벤트를 조회한다.
2. subtype이 정책 대상인지 확인한다.
3. `risk_action_code = BLOCK_BUY`로 설정한다.
4. `effective_date = rcept_dt`로 설정한다.
5. `expires_at = rcept_dt + 90일`로 설정한다.
6. `detail`에 `rcept_no`, `report_nm`, `block_days`를 저장한다.
7. `policy_version = dart-dilution-v1.0.0`을 기록한다.

## 저장 테이블

`company_risk_states`

upsert 기준:

```text
stock_code, source_dart_event_id, policy_version
```

## 다이어그램

```mermaid
flowchart TB
    A[("dart_events<br/>DART 공시 이벤트")] --> B["CAPITAL_CHANGE 조회<br/>자본변동 이벤트만 선택"]
    B --> C{"희석성 subtype?<br/>유상증자/CB/BW/EB인가"}
    C -->|아니오| D["skip<br/>위험상태 미생성"]
    C -->|예| E["BLOCK_BUY 상태 생성<br/>90일 신규 매수 차단"]
    E --> F[("company_risk_states<br/>기업 위험상태 테이블")]
```
