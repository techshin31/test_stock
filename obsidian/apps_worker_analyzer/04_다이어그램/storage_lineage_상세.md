---
title: storage lineage 상세
created: 2026-06-30
source_basis: code_only
tags:
  - analyzer
  - diagram
  - storage
---

# storage lineage 상세

근거 코드:

- `storage/postgres/schema/06_fa_analysis_schema.sql`
- `storage/postgres/repositories/fa_analysis_repo.py`
- `storage/postgres/repositories/universe_repo.py`

```mermaid
flowchart LR
    subgraph COLLECTOR["Collector가 모아두는 원천 데이터"]
        MS[("매크로 원천<br/>테이블: macro_signals<br/>주석: 관측일과 공개 가능일을 함께 저장")]
        WC[("업종 구성 스냅샷<br/>테이블: wics_companies<br/>주석: 종목의 업종, 대형주 여부, 기준일")]
        WCP[("업종 구성 종목 가격<br/>테이블: wics_constituent_prices<br/>주석: 업종 지수 보강 재료")]
        WIP0[("업종 지수 가격<br/>테이블: wics_industry_prices<br/>주석: 업종별 과거 수익률")]
        FS[("기업 재무제표 원천<br/>테이블: financial_statements<br/>주석: DART 접수번호와 공개 가능일 포함")]
        CRS[("기업 위험 상태<br/>테이블: company_risk_states<br/>주석: 매수 차단, 매도 전용, 만료일")]
        C[("기업 기준정보<br/>테이블: companies<br/>주석: 시장, 거래 상태, 종목명")]
    end

    subgraph ANALYZER["Analyzer가 만드는 분석 원장"]
        CQF[("기업 분기 재무 점수<br/>테이블: company_quarter_fa<br/>주석: fa_score와 재무지표 저장")]
        RUN[("분석 실행 헤더<br/>테이블: fa_analysis_runs<br/>주석: input_hash, 상태, 발행 여부")]
        FMR[("매크로 분석 결과<br/>테이블: fa_macro_results<br/>주석: 방향성과 업종 민감도")]
        FSR[("업종 분석 결과<br/>테이블: fa_sector_results<br/>주석: sector_score와 최종 선택 여부")]
        FCR[("기업 분석 결과<br/>테이블: fa_company_results<br/>주석: 업종 내 순위와 최종 선택 여부")]
    end

    subgraph PUBLISH["Trader가 읽는 운영 후보군"]
        U[("운영 후보군<br/>테이블: universe<br/>주석: ACTIVE=매수 가능, SELL_ONLY=청산 전용, REMOVED=제외")]
    end

    subgraph TRADER["Trader 소비 지점"]
        PLAN["매매 계획 생성<br/>코드: apps.trader.planner, fetch_universe_for_date<br/>주석: 적용일 기준 ACTIVE 후보만 읽음"]
        EXEC["주문 실행<br/>코드: apps.trader.executor<br/>주석: 계획된 매수/매도 주문을 브로커로 전달"]
        RECON["체결/보유 동기화<br/>코드: apps.trader.reconciler<br/>주석: SELL_ONLY 청산과 제거 상태를 정리"]
    end

    FS --> CQF
    WC --> CQF
    C --> CQF
    MS --> FMR
    WIP0 --> FMR
    WCP -. "공식 업종지수 부족 시 보강<br/>코드: refresh_industry_prices" .-> WIP0
    WC --> FSR
    CQF --> FSR
    C --> FSR
    CRS --> FSR
    FMR --> FSR
    FSR --> FCR
    CQF --> FCR
    WC --> FCR
    C --> FCR
    CRS --> FCR
    RUN --> FMR
    RUN --> FSR
    RUN --> FCR
    FCR --> U
    U --> PLAN
    PLAN --> EXEC
    EXEC --> RECON
```

## key relationships

```mermaid
flowchart TB
    A["하나의 분석 실행<br/>키: fa_analysis_runs.id<br/>주석: 이번 달 분석 묶음"] --> B["매크로 결과 연결<br/>키: fa_macro_results.run_id<br/>주석: 같은 분석 run에서 나온 매크로 판단"]
    A --> C["업종 결과 연결<br/>키: fa_sector_results.run_id<br/>주석: 같은 분석 run에서 나온 업종 선택"]
    A --> D["기업 결과 연결<br/>키: fa_company_results.run_id<br/>주석: 같은 분석 run에서 나온 기업 선택"]
    C --> E["기업이 어느 업종 결과에서 왔는지<br/>키: fa_company_results.sector_result_id<br/>주석: 업종 선정 근거와 기업 선정을 연결"]
    F["기업 분기 재무 원장<br/>키: company_quarter_fa.id"] --> G["기업 선정에 쓴 재무점수<br/>키: fa_company_results.company_quarter_fa_id<br/>주석: 어떤 분기 재무점수로 선택됐는지 역추적"]
    D --> H["운영 후보의 선정 근거<br/>키: universe.source_fa_company_result_id<br/>주석: 왜 후보군에 들어왔는지 역추적"]
    I["전략 마스터<br/>키: strategies.id"] --> A
    I --> H
```

## point-in-time guard columns

| 테이블 | 기준 컬럼 | Analyzer 사용 | 주석 |
|---|---|---|---|
| `macro_signals` | `available_date`, `observation_date` | `available_date &lt;= cutoff_date` | 분석일 당시 공개된 매크로만 사용 |
| `financial_statements` | `available_date`, `source_rcept_no` | cutoff 기준 최신 정기보고서 | 아직 공시되지 않은 재무제표를 미리 쓰지 않음 |
| `company_quarter_fa` | `available_date` | 기업 선정 시 cutoff 이후 자료 배제 | 기업 재무 점수도 시점 오염을 막음 |
| `wics_companies` | `base_date` | cutoff 이전 최신 WICS snapshot | 당시 업종 구성과 대형주 여부를 기준으로 판단 |
| `wics_industry_prices` | `price_date` | cutoff 이전 업종 수익률 | 미래 업종 가격 움직임을 관계 분석에 섞지 않음 |
| `company_risk_states` | `effective_date`, `expires_at` | cutoff/effective date 기준 매수 차단 | 적용일에 매수 금지인 종목을 후보군에서 제외 |
