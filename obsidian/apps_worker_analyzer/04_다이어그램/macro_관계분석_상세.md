---
title: macro 관계분석 상세
created: 2026-06-30
source_basis: code_only
tags:
  - analyzer
  - diagram
  - macro
---

# macro 관계분석 상세

근거 코드:

- `apps/worker/analyzer/macro_job.py`
- `apps/worker/analyzer/relationships.py`
- `apps/worker/fa_contract.py::MACRO_SIGNALS`

```mermaid
flowchart TB
    subgraph INPUT["1. 시점 안전 입력"]
        A["매크로 분석 시작<br/>코드: run_macro_analysis<br/>주석: 현재 시장 환경과 업종 반응도를 함께 계산"] --> B["관계 분석용 과거 기간 설정<br/>코드: start_date = cutoff - lookback<br/>주석: 과거 몇 년치로 업종 민감도를 볼지 결정"]
        B --> C["마감일 이전 매크로만 조회<br/>코드: fetch_macro_signals_as_of<br/>주석: cutoff 이후 공개 데이터는 사용하지 않음"]
        B --> D["마감일 이전 업종 지수 조회<br/>코드: fetch_wics_industry_prices<br/>주석: 업종별 과거 수익률 계산 재료"]
        D --> E["주간 업종 수익률<br/>코드: industry_returns_frame WEEKLY<br/>주석: 빠르게 반응하는 신호와 비교"]
        D --> F["월간 업종 수익률<br/>코드: industry_returns_frame MONTHLY<br/>주석: 느리게 반영되는 경기 신호와 비교"]
    end

    subgraph DIRECTION["2. 매크로 방향 계산"]
        C --> G["신호별 묶기<br/>코드: signal_name_code<br/>주석: CPI, 금리, 환율 같은 신호를 종류별로 분리"]
        G --> H["계약된 17개 신호 순회<br/>코드: MACRO_SIGNALS<br/>주석: 시스템이 투자판단에 쓰기로 정한 매크로 목록"]
        H --> I{"계산할 데이터가 충분한가?<br/>코드: minimum observations"}
        I -->|아니오| I0["해당 신호 제외<br/>주석: 나중에 WARNING 원인이 될 수 있음"]
        I -->|예| J["방향 계산<br/>코드: calculate_macro_direction<br/>주석: 상승/하락/중립 압력을 판정"]
        J --> K{"신호 변환 방식<br/>코드: contract.transform"}
        K -->|CPI_YOY_PRESSURE| K1["물가 압력 변화<br/>주석: CPI YoY가 더 가팔라지는지"]
        K -->|YOY_CHANGE| K2["전년 대비 개선/둔화<br/>주석: 관광객/생산 같은 월간 지표의 YoY 변화"]
        K -->|LEVEL| K3["수준 변화<br/>주석: PMI/검색지수가 올라가는지"]
        K -->|MARKET_RETURN| K4["가격 수익률<br/>주석: 원자재/주가지수/환율이 오르는지"]
        K -->|YIELD_CHANGE| K5["금리 변화<br/>주석: 금리 레벨이 오르는지"]
        K1 --> L["정규화된 방향 점수<br/>코드: trend_raw<br/>주석: 서로 단위가 다른 지표를 비교 가능한 압력값으로 변환"]
        K2 --> L
        K3 --> L
        K4 --> L
        K5 --> L
        L --> M{"방향 판정 기준 통과?<br/>코드: direction threshold"}
        M -->|양수 기준 이상| M1["상승 압력<br/>코드: direction=UP"]
        M -->|음수 기준 이하| M2["하락 압력<br/>코드: direction=DOWN"]
        M -->|기준 사이| M3["중립<br/>코드: direction=FLAT"]
        M1 --> N["매크로 결과<br/>코드: MacroResult<br/>주석: trend_strength=압력 크기, confidence=자료 충분성"]
        M2 --> N
        M3 --> N
    end

    subgraph REL["3. 매크로와 업종 민감도 계산"]
        N --> O["관계 분석용 변화율로 변환<br/>코드: transform_macro_for_relationship<br/>주석: 지표 레벨을 업종 수익률과 비교 가능한 변화값으로 변환"]
        O --> O1{"월간/주간 중 무엇으로 비교할까?<br/>코드: relationship frequency"}
        O1 -->|월간| P1["월간 비교<br/>코드: monthly macro change vs monthly industry return<br/>주석: 경기/소비 신호처럼 느린 반응을 봄"]
        O1 -->|주간| P2["주간 비교<br/>코드: weekly macro change vs weekly industry return<br/>주석: 가격/금리처럼 빠른 반응을 봄"]
        P1 --> Q["지원 WICS 업종 전체 순회<br/>코드: SUPPORTED_INDUSTRIES<br/>주석: 분석 대상 업종마다 민감도를 따로 계산"]
        P2 --> Q
        Q --> R["업종 민감도 계산<br/>코드: calculate_relationship<br/>주석: 이 매크로가 이 업종에 유리한지 불리한지 추정"]
        R --> S["날짜 맞추기<br/>주석: 매크로 변화와 업종 수익률이 동시에 있는 기간만 사용"]
        S --> T{"샘플과 변동성이 충분한가?"}
        T -->|아니오| T0["관계 없음 처리<br/>코드: eligible=false, contribution=0"]
        T -->|예| U["방향성과 민감도<br/>코드: correlation, beta<br/>주석: correlation=같이 움직인 정도, beta=반응 크기"]
        U --> V["관계의 일관성<br/>코드: sign_stability<br/>주석: 최근 구간에서도 같은 방향이 유지됐는지"]
        V --> W["관계 신뢰도<br/>코드: confidence<br/>주석: 샘플 수, 상관 강도, 일관성을 곱한 값"]
        W --> X{"투자 판단에 쓸 만큼 믿을 만한가?"}
        X -->|아니오| X0["점수 기여 없음<br/>코드: eligible=false, contribution=0"]
        X -->|예| Y["업종 점수 기여도<br/>코드: contribution<br/>주석: 매크로 방향 * 업종 민감도 * 신뢰도"]
    end

    subgraph CONTRACT["4. 정책상 적용 업종 제한"]
        Y --> Z{"이 매크로가 적용 가능한 업종인가?<br/>코드: eligible_industry_codes"}
        X0 --> Z
        T0 --> Z
        Z -->|제한 밖| Z1["점수 기여 제거<br/>주석: 예를 들어 한류 신호는 관련 소비/콘텐츠 업종에만 적용"]
        Z -->|허용| Z2["관계 유지<br/>주석: 해당 업종 점수에 반영 가능"]
        Z1 --> AA["업종별 관계 설명 저장<br/>코드: relationships JSON<br/>주석: 나중에 왜 점수가 올랐는지 설명하는 근거"]
        Z2 --> AA
        AA --> AB["매크로 결과 저장<br/>코드: insert_macro_results<br/>주석: 신호별 방향과 업종별 기여도를 DB에 저장"]
        AB --> AC[("매크로 분석 결과<br/>테이블: fa_macro_results<br/>상세: calculation_detail.relationships")]
    end
```

저장되는 설명 가능성:

| 확인 값 | 주석 |
|---|---|
| `fa_macro_results.direction_code` | 현재 매크로 신호가 상승 압력, 하락 압력, 중립 중 어디인지 |
| `fa_macro_results.trend_raw` | 서로 단위가 다른 지표를 비교 가능하게 바꾼 방향 점수 |
| `calculation_detail.relationships[].correlation` | 해당 매크로와 업종 수익률이 과거에 얼마나 같이 움직였는지 |
| `calculation_detail.relationships[].relationship_confidence` | 샘플 수, 상관 강도, 일관성을 반영한 관계 신뢰도 |
| `calculation_detail.relationships[].contribution` | 이 매크로가 특정 업종 점수에 실제로 더하거나 뺀 영향 |
| `calculation_detail.relationships[].is_eligible` | 정책상 해당 매크로를 그 업종 판단에 써도 되는지 |
