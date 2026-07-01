---
title: macro 수집흐름
created: 2026-06-29
source_basis: code_only
tags:
  - collector
  - diagram
  - macro
---

# macro 수집흐름

이 흐름도는 `macro_job.run`에서 `macro_signals` 저장까지의 증분 수집, 원천별 분기, 전처리 방식을 보여준다.

```mermaid
flowchart TB
    subgraph JOB["1. macro_job.run<br/>매크로 수집 Job"]
        direction TB
        A["effective_start = start or 2010-01-01<br/>시작일 기본값 결정"] --> B["effective_end = end or today<br/>종료일 기본값 결정"]
        B --> C["collect_and_save(auto_start=True)<br/>시그널별 증분 수집 실행"]
    end

    subgraph INCREMENTAL["2. 증분 수집 범위 결정"]
        direction TB
        C --> D["fetch_latest_signal_dates(start,end)<br/>signal_name_code별 DB 최신 관측일 조회"]
        D --> E["_SIGNAL_META loop<br/>17개 매크로 시그널 순회"]
        E --> F{"기존 최신일 존재?<br/>이미 저장된 시그널인가"}
        F -->|아니오| G["effective_start = 입력 start<br/>최초 또는 지정 기간 수집"]
        F -->|예, CPI| H["latest - 90일 lookback<br/>최근 3개월 수정 발표 재수집"]
        F -->|예, CPI 아님| I["latest + 1일<br/>마지막 저장일 다음 날부터 수집"]
        I --> J{"next_day >= end?<br/>수집할 신규 기간 없음"}
        J -->|예| K["skip<br/>최신 데이터 이미 존재"]
        J -->|아니오| L["원천 수집 진행"]
        G --> L
        H --> L
    end

    subgraph COLLECT["3. 원천별 수집 분기"]
        direction TB
        L --> M{"loader_key == cpi?<br/>FRED CPI vintage인가"}
        M -->|예| N["fetch_fred_vintage_observations(CPIAUCSL)<br/>CPI 발표/수정 이력 수집"]
        N --> O["_cpi_vintages_to_records<br/>revision_no 포함 record 생성"]
        M -->|아니오| P{"loader_key startswith gtrend?<br/>Google Trends 계열인가"}
        P -->|예| Q["15초 대기<br/>Google Trends 호출 제한 완화"]
        P -->|아니오| R["loader 실행<br/>Yahoo/FRED/KTO/Google/CSV 등 원천 시계열 조회"]
        Q --> R
        R --> S["_normalize_series(series, frequency_code)<br/>날짜 정렬, 월초 변환, 일별 ffill 제한"]
        S --> T{"available_date_rule<br/>투자 판단 가능일 규칙"}
        T -->|SOURCE_RELEASE_DATE| U["_series_to_records_release_date<br/>수집일 기준 다음 KRX 거래일 사용"]
        T -->|기본| V["_series_to_records<br/>관측일 기준 다음 KRX 거래일 사용"]
    end

    subgraph SAVE["4. 저장과 실패 처리"]
        direction TB
        O --> W{"records 존재?<br/>저장할 신규 행이 있는가"}
        U --> W
        V --> W
        W -->|아니오| X["skip<br/>신규 데이터 없음"]
        W -->|예| Y["upsert_macro_signals(records)<br/>신호명/관측일/수정번호 기준 upsert"]
        Y --> Z[("macro_signals<br/>매크로 시그널 테이블")]
        L -. 예외 발생 .-> ERR["except Exception<br/>해당 시그널만 실패 로그 후 다음 시그널 계속"]
        K -. 다음 시그널 .-> E
        X -. 다음 시그널 .-> E
        Z -. 다음 시그널 .-> E
        ERR -. 다음 시그널 .-> E
    end
```

구현상 중요한 점:

- 매크로 수집은 한 시그널이 실패해도 전체 Job을 즉시 중단하지 않고 다음 시그널로 넘어간다.
- CPI는 수정 발표 이력이 중요하므로 최신일 이후만 보는 대신 최근 90일을 다시 조회한다.
- `available_date`는 트레이딩 관점에서 “언제부터 사용할 수 있었는가”를 나타내는 날짜다.
- Google Trends 계열은 호출 제한을 피하기 위해 시그널별 수집 전 대기 시간이 있다.

관련 노트:

- [[../02_수집데이터/매크로_시그널|매크로 시그널]]
- [[../03_전처리_저장/macro_signals_전처리_저장|macro_signals 전처리 저장]]
