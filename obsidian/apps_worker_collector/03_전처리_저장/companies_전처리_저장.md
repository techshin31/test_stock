---
title: companies 전처리 저장
created: 2026-06-29
source_basis: code_only
tags:
  - collector
  - preprocess
  - company
---

# companies 전처리 저장

> **이전 구현 기록:** 아래 내용은 인증 DART API를 사용하던 구현이다.
> 2026-10-04에 해당 클라이언트와 API 전용 로더를 제거했다. 현재 기업 수집은
> 공식 공개 원본 XBRL과 희석 정책 공시만 사용하며 API 키를 요구하지 않는다.
> 현재 실행법·흐름·검증은 [Collector 가이드](../../../apps/worker/collector/README.md)와
> [공개 재무·공시 검증](../../../docs/PUBLIC_DART_ALTERNATIVE_2026-10-04.md)을 참고한다.


관련 데이터: [[../02_수집데이터/기업_기본정보|기업 기본정보]]

## 입력 데이터

- `wics_companies`의 종목코드
- DART corp code 목록
- KRX market map

## 실행 함수

```text
company_job.run
  -> collect_companies_from_wics
  -> sync_company_status
  -> upsert_companies
```

## 전처리 단계

1. `wics_companies`에서 고유 종목코드를 읽는다.
2. `companies`에 이미 있는 종목은 제외한다.
3. DART corp code 목록에서 `corp_code`, `company_name`을 찾는다.
4. KRX market map에서 `market_type_code`를 찾는다.
5. 누락 종목을 `companies`에 upsert한다.
6. 전체 companies를 다시 KRX 현재 목록과 비교해 상태를 동기화한다.

## 저장 테이블

`companies`

primary key:

```text
stock_code
```

## 다이어그램

```mermaid
flowchart TB
    A[("wics_companies<br/>WICS 구성종목 스냅샷")] --> B["collect_companies_from_wics<br/>신규 기업 기본정보 수집"]
    B --> C["외부 마스터 매핑<br/>DART 고유번호/회사명<br/>KRX KOSPI/KOSDAQ 구분"]
    C --> D[("companies<br/>기업 기본정보 마스터")]
    D --> E["sync_company_status<br/>상장 상태 동기화"]
```
