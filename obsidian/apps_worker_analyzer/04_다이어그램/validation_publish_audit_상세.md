---
title: validation publish audit 상세
created: 2026-06-30
source_basis: code_only
tags:
  - analyzer
  - diagram
  - publish
  - audit
---

# validation publish audit 상세

근거 코드:

- `apps/worker/analyzer/validation.py`
- `apps/worker/analyzer/universe_job.py`
- `apps/worker/analyzer/operations.py`
- `storage/postgres/repositories/universe_repo.py::publish_fa_run`

## 결과 검증과 상태 결정

```mermaid
flowchart TB
    A["최종 결과 검증 시작<br/>코드: validate_run<br/>주석: Trader에 넘기기 전에 계약 위반을 찾음"] --> B["분석 실행 정보 조회<br/>코드: fetch_analysis_run"]
    B --> C["매크로 결과 조회<br/>코드: fetch_macro_results_for_run"]
    C --> D{"필수 매크로 결과가 다 있나?<br/>코드: macro_results check"}
    D -->|누락| D1["경고 후보<br/>코드: WARNING candidate<br/>주석: 일부 신호 누락, 발행은 정책상 가능할 수 있음"]
    D -->|완전| D2["통과<br/>코드: pass"]
    C --> E{"미래 데이터를 썼나?<br/>코드: macro_point_in_time"}
    E -->|cutoff 이후 available_date 존재| E1["치명 실패<br/>코드: FAIL critical<br/>주석: 분석 시점에 알 수 없던 데이터 사용"]
    E -->|문제 없음| E2["통과<br/>코드: pass"]
    B --> F["업종 결과 요약 조회<br/>코드: fetch_sector_summary_for_run"]
    F --> G{"선택 업종 수가 허용 범위인가?<br/>코드: final_industry_count"}
    G -->|실패| G1["경고 후보<br/>코드: WARNING candidate<br/>주석: 너무 많거나 적은 업종 선택"]
    G -->|통과| G2["통과<br/>코드: pass"]
    B --> H["선택 기업과 기준정보 조회<br/>코드: fetch_selected_companies_with_company_info"]
    H --> I{"기업 후보 수와 업종별 제한이 맞나?<br/>코드: company_selection shape"}
    I -->|개수/업종 제한 실패| I1["경고 후보<br/>코드: WARNING candidate"]
    I -->|통과| I2["통과<br/>코드: pass"]
    H --> J{"실제 매매 가능한 종목 형식인가?<br/>코드: company_contract"}
    J -->|시장/상태/대형주/날짜 이상| J1["경고 후보<br/>코드: WARNING candidate<br/>주석: 후보군 계약 형식 위반"]
    J -->|통과| J2["통과<br/>코드: pass"]
    B --> K["적용일 기준 매수 차단 종목 조회<br/>코드: fetch_buy_blocked_stock_codes<br/>주석: as_of=effective_date"]
    K --> L{"선택 종목에 매수 차단이 있나?<br/>코드: company_risk"}
    L -->|있음| L1["경고 후보<br/>코드: WARNING candidate<br/>주석: 운영 리스크 때문에 매수 금지"]
    L -->|없음| L2["통과<br/>코드: pass"]
    E1 --> M["실행 상태 실패<br/>코드: status=FAIL"]
    D1 --> N["실행 상태 경고<br/>코드: status=WARNING unless FAIL"]
    G1 --> N
    I1 --> N
    J1 --> N
    L1 --> N
    D2 --> O["실행 상태 통과<br/>코드: status=PASS<br/>주석: 모든 검증이 문제 없음"]
    E2 --> O
    G2 --> O
    I2 --> O
    J2 --> O
    L2 --> O
    M --> P["검증 상태 저장<br/>코드: update_analysis_run_status<br/>테이블: fa_analysis_runs"]
    N --> P
    O --> P
```

## universe 발행 transaction

```mermaid
flowchart TB
    A["운영 후보군 발행 시작<br/>코드: publish_universe<br/>주석: 분석 결과를 Trader가 읽는 후보군으로 반영"] --> B["현재 한국 시간 확인<br/>코드: now_kst"]
    B --> C["기대 후보 수 계산<br/>코드: expected_count = final_industry_count * companies_per_industry<br/>주석: 최종 업종 수 곱하기 업종별 종목 수"]
    C --> D["탈락 보유종목 청산 기한 계산<br/>코드: calc_force_exit_date(now.date, 20)<br/>주석: 빠진 종목은 바로 삭제하지 않고 청산 기간 부여"]
    D --> E["원자적 발행 트랜잭션 시작<br/>코드: publish_fa_run transaction<br/>주석: 중간 실패 시 기존 후보군 유지"]

    subgraph LOCK["1. 중복 발행과 상태 오류 방지"]
        E --> F["분석 run 잠금<br/>SQL: SELECT fa_analysis_runs FOR UPDATE<br/>주석: 동시에 두 번 발행되는 상황 방지"]
        F --> G{"발행 가능한 검증 상태인가?<br/>코드: status_code"}
        G -->|이미 발행됨| G1["현재 ACTIVE 후보군 반환<br/>코드: already_published=true<br/>주석: 같은 run을 다시 바꾸지 않음"]
        G -->|PASS/WARNING 아님| G2["발행 중단<br/>코드: ValueError<br/>주석: 실패한 분석은 운영 반영 불가"]
        G -->|PASS/WARNING| H{"적용일이 지나지 않았나?<br/>코드: local_now.date &lt;= effective_date"}
        H -->|지남| H1["발행 중단<br/>코드: ValueError<br/>주석: 과거 적용일로 후보군을 덮어쓰지 않음"]
        H -->|유효| I["전략 행 잠금<br/>SQL: SELECT strategy FOR UPDATE"]
        I --> J{"전략이 활성이고 이름이 맞나?<br/>코드: strategy active and name matches"}
        J -->|아니오| J1["발행 중단<br/>코드: ValueError<br/>주석: 잘못된 전략에 후보군이 연결되는 것 방지"]
        J -->|예| K["선택 기업만 조회<br/>코드: is_selected and is_eligible<br/>주석: 제외 후보는 universe에 들어가지 않음"]
    end

    subgraph SELECTED["2. 발행 대상 기업 재검증"]
        K --> L{"선택 기업 수가 기대치 이하인가?<br/>코드: selected_count &lt;= expected_count"}
        L -->|초과| L1["발행 중단<br/>코드: ValueError<br/>주석: 과도한 종목 유입 방지"]
        L -->|정상| M{"시장/상태/종목코드가 유효한가?<br/>코드: market/status/symbol valid"}
        M -->|아니오| M1["발행 중단<br/>코드: ValueError invalid selected<br/>주석: 실제 매매 계약에 맞지 않는 종목 제외"]
        M -->|예| N["적용일 기준 위험상태 조회<br/>코드: query company_risk_states<br/>주석: effective_date에 매수 금지인지 확인"]
        N --> O{"매수 차단 또는 매도 전용 상태인가?<br/>코드: BLOCK_BUY or SELL_ONLY"}
        O -->|예| O1["발행 중단<br/>코드: ValueError buy blocked<br/>주석: 매수 차단 종목은 운영 후보군에 넣지 않음"]
        O -->|아니오| P["최종 선택 종목 묶음<br/>코드: symbols tuple"]
    end

    subgraph MUTATE["3. Trader 후보군 갱신"]
        P --> Q["탈락한 기존 후보는 청산 전용으로 전환<br/>코드: UPDATE ACTIVE not selected to SELL_ONLY<br/>주석: exit_deadline까지 매도만 허용"]
        Q --> R["선택 종목은 매수 가능 후보로 저장<br/>코드: INSERT/UPDATE universe_status_code=ACTIVE<br/>주석: 신규 편입은 entry_date=effective_date"]
        R --> S["선정 근거 연결<br/>코드: source_fa_company_result_id<br/>주석: 왜 편입됐는지 fa_company_results로 추적"]
        S --> T["분석 run 발행 완료 표시<br/>코드: status=PUBLISHED, published_at=NOW"]
        T --> U[("운영 후보군 발행 완료<br/>테이블: universe + fa_analysis_runs<br/>주석: Trader 입력이 바뀐 시점")]
    end
```

## 운영 감사

```mermaid
flowchart TB
    A["운영 감사 명령<br/>코드: python -m apps.worker audit"] --> B["운영 상태 점검<br/>코드: audit_operational_state"]
    B --> C["감사 카운트 조회<br/>코드: fetch_audit_counts"]
    C --> C1["미래 매크로 사용 위반<br/>코드: macro_late<br/>주석: fa_macro_results.available_date가 cutoff 이후"]
    C --> C2["미래 기업자료 사용 위반<br/>코드: company_late<br/>주석: fa_company_results.available_date가 cutoff 이후"]
    C --> C3["오래 멈춘 분석 실행<br/>코드: stale_running<br/>주석: RUNNING 상태가 1시간 초과"]
    B --> D["발행 결과와 현재 후보군 비교<br/>코드: fetch_published_universe_mismatch"]
    D --> D1["최신 발행 run의 선택 종목<br/>코드: latest PUBLISHED selected set"]
    D --> D2["현재 매수 가능 후보군<br/>코드: current ACTIVE universe set"]
    D1 --> D3["양방향 차이 계산<br/>코드: EXCEPT both directions<br/>주석: 발행 결과와 실제 운영 후보가 어긋났는지 확인"]
    D2 --> D3
    B --> E["발행 run별 선택 종목 조회<br/>코드: fetch_published_run_selections"]
    E --> F["월간 교체율 계산<br/>코드: _average_turnover<br/>주석: 후보군이 얼마나 자주 바뀌는지 점검"]
    C1 --> G{"운영 위반이 하나라도 있나?<br/>코드: any violation"}
    C2 --> G
    C3 --> G
    D3 --> G
    G -->|있음| H["감사 실패<br/>코드: OperationsReport.status=FAIL"]
    G -->|없음| I["감사 통과<br/>코드: OperationsReport.status=PASS"]
```
