---
title: sector 점수선정 상세
created: 2026-06-30
source_basis: code_only
tags:
  - analyzer
  - diagram
  - sector
---

# sector 점수선정 상세

근거 코드: `apps/worker/analyzer/sector_job.py`

```mermaid
flowchart TB
    subgraph INPUT["1. 마감일 기준 입력 모으기"]
        A["업종 분석 시작<br/>코드: run_sector_analysis<br/>주석: 어떤 업종을 살지 점수화"] --> B["마감일 기준 최신 WICS 구성 조회<br/>코드: fetch_latest_wics_snapshot<br/>주석: 현재 업종 구성원을 확인"]
        B --> C["스냅샷 내 종목 목록<br/>코드: stock_codes<br/>주석: 업종 점수 계산에 들어갈 구성 기업"]
        C --> D["사용 가능한 최신 기업 FA 조회<br/>코드: fetch_latest_company_fa_as_of<br/>주석: cutoff 이후 재무 정보는 제외"]
        C --> E["기업 상장/거래 상태 조회<br/>코드: fetch_company_statuses<br/>주석: 거래 가능한 KOSPI 기업인지 확인"]
        C --> F["매수 차단 위험상태 조회<br/>코드: fetch_active_company_risk_states<br/>주석: 신규 매수를 막아야 하는 종목 제외"]
        A --> G["매크로-업종 민감도<br/>코드: macro_results.relationships<br/>주석: 매크로가 업종 점수에 미치는 근거"]
    end

    subgraph MEMBERS["2. 업종별 살 수 있는 대형주 확인"]
        B --> H["지원 업종만 남김<br/>코드: SUPPORTED_INDUSTRIES<br/>주석: 전략이 다루기로 한 WICS 업종만 사용"]
        H --> I["업종별 구성종목 묶기<br/>코드: industry_code<br/>주석: 업종별 후보 풀이 얼마나 되는지 계산"]
        D --> J["종목별 재무 점수 사전<br/>코드: fa_by_stock<br/>주석: 업종 구성 기업의 재무 품질 재료"]
        E --> K["종목별 거래 상태 사전<br/>코드: status_by_stock<br/>주석: 비활성/비KOSPI 여부 확인"]
        F --> L["매수 차단 종목 집합<br/>코드: risk_blocked_codes<br/>주석: 공시/운영 리스크로 매수 금지된 종목"]
        I --> M["업종별 반복<br/>주석: 업종마다 살 수 있는 대형주 수를 셈"]
        M --> N{"이 종목을 살 수 있는 후보로 볼 수 있나?<br/>코드: member eligibility check"}
        N -->|대형주 아님| N1["제외<br/>코드: company_size != LARGE<br/>주석: 운용 유동성 기준 미달"]
        N -->|비활성 또는 KOSPI 아님| N2["제외<br/>주석: 운영 전략 대상 아님"]
        N -->|위험 공시 유효| N3["제외<br/>주석: 신규 매수 차단"]
        N -->|쓸 수 있는 FA 없음| N4["제외<br/>주석: 재무 판단 불가"]
        N -->|점수/신뢰도 부족| N5["제외<br/>코드: low score/confidence<br/>주석: 업종 대표 종목으로 쓰기 어려움"]
        N -->|통과| O["업종 내 살 수 있는 대형주 +1<br/>코드: eligible_large_count"]
    end

    subgraph SCORE["3. 업종 점수 구성"]
        G --> P["업종별 매크로 근거 모음<br/>코드: relationships[industry]<br/>주석: 각 업종에 유리/불리한 매크로 근거"]
        P --> Q["믿을 만한 관계만 사용<br/>코드: eligible_relations<br/>주석: 샘플과 신뢰도가 부족한 관계는 제외"]
        Q --> R["한 종류의 매크로가 과도하게 지배하지 않게 제한<br/>코드: _cap_macro_category_contributions<br/>주석: 특정 카테고리 쏠림 방지"]
        R --> S["매크로 총 기여도<br/>코드: macro_raw<br/>주석: -1은 매우 불리, +1은 매우 유리"]
        S --> T["매크로 적합도 점수<br/>코드: macro_fit_score<br/>주석: 0~100으로 변환"]
        J --> U["업종 내 재무 품질 폭<br/>코드: median_fa, improvement_rate, confidence_rate<br/>주석: 좋은 기업이 업종 안에 넓게 분포하는지"]
        U --> V["업종 구성 기업들의 재무 폭 점수<br/>코드: company_fa_breadth_score<br/>주석: 한두 종목이 아니라 업종 전체 체력이 좋은지"]
        I --> W["업종 거래대금 규모<br/>코드: liquidity_raw<br/>주석: 실제 운용할 때 사고팔기 쉬운지"]
        O --> X["살 수 있는 대형주 수용력<br/>코드: eligible_large_count"]
        W --> Y["유동성/수용력 점수<br/>코드: liquidity_capacity_score<br/>주석: 거래대금과 대형주 후보 수를 함께 평가"]
        X --> Y
        Q --> Z["매크로 관계 평균 신뢰도<br/>코드: relationship_confidence<br/>주석: 매크로 근거를 얼마나 믿을 수 있는지"]
        I --> AA["구성종목 커버리지/집중도<br/>코드: coverage, member count, concentration<br/>주석: 데이터가 충분하고 특정 종목에 과도하게 쏠리지 않았는지"]
        U --> AB["업종 재무 품질 미달 패널티<br/>코드: cohort_quality_penalty<br/>주석: 업종 전체 재무 품질이 약하면 감점"]
        Z --> AC["업종 리스크 차감<br/>코드: sector_risk_penalty<br/>주석: 신뢰도/커버리지/품질 부족을 점수에서 차감"]
        AA --> AC
        AB --> AC
        T --> AD["최종 업종 점수<br/>코드: sector_score<br/>주석: 매크로 45 + 재무 폭 35 + 유동성 20 - 리스크"]
        V --> AD
        Y --> AD
        AC --> AD
    end

    subgraph CANDIDATE["4. 1차 후보 업종 8개"]
        AD --> AE["상승 환경 수혜 점수<br/>코드: up_benefit_score<br/>주석: 좋은 매크로 환경에서 더 오를 업종"]
        AD --> AF["하락/위험 환경 방어 점수<br/>코드: down_hedge_score<br/>주석: 나쁜 환경에서도 상대적으로 버틸 업종"]
        AE --> AG["수혜 후보 상위 5개<br/>코드: candidate_source_code=UP<br/>주석: 공격적 후보 풀"]
        AF --> AH["방어 후보 상위 3개<br/>코드: candidate_source_code=DOWN<br/>주석: 방어적 후보 풀"]
        AG --> AI["1차 후보 업종<br/>코드: candidate_rows<br/>주석: 최종 5개를 고르기 전 후보 묶음"]
        AH --> AI
    end

    subgraph SELECT["5. 최종 업종 최대 5개"]
        AI --> AJ["후보를 점수순 정렬<br/>코드: sector_score desc, industry_code asc<br/>주석: 점수가 같으면 업종코드로 재현 가능하게 정렬"]
        AJ --> AK{"업종 안에 살 수 있는 대형주가 2개 이상인가?"}
        AK -->|예| AL["최종 업종으로 선택<br/>주석: 종목 선정 단계로 넘어갈 수 있음"]
        AK -->|아니오| AM["탈락 사유 저장<br/>코드: INSUFFICIENT_LARGE<br/>주석: 좋아 보여도 실제 살 종목이 부족"]
        AL --> AN{"최종 5개를 다 채웠나?"}
        AN -->|후보 부족| AO["후보 밖 업종에서 보충<br/>코드: fallback_rows<br/>주석: 최종 업종 수를 맞추기 위한 예비 후보"]
        AO --> AP{"보충 업종도 대형주 조건을 만족하나?"}
        AP -->|예| AQ["보충 선택<br/>코드: candidate_source_code=FALLBACK<br/>주석: 후보 부족 시 채워 넣은 업종"]
        AP -->|아니오| AR["건너뜀"]
        AN -->|충분| AS["최종 순위 부여<br/>코드: final_rank, reason_code=SELECTED<br/>주석: Trader 후보군으로 이어질 업종 순서"]
        AQ --> AS
        AM --> AT["비선정 사유 저장<br/>코드: LOW_SCORE 또는 INSUFFICIENT_LARGE<br/>주석: 왜 탈락했는지 감사 가능하게 남김"]
        AR --> AT
        AS --> AU["업종 결과 저장<br/>코드: insert_sector_results<br/>주석: 선택/비선택 업종 모두 DB에 저장"]
        AT --> AU
        AU --> AV[("업종 분석 결과<br/>테이블: fa_sector_results<br/>주석: 선택/비선택 업종 모두 저장")]
    end
```

투자자에게 설명할 때는 `sector_score` 하나만 보지 말고 아래 조합을 같이 본다.

| 질문 | 확인 컬럼 | 주석 |
|---|---|---|
| 매크로 때문에 오른 점수인가 | `macro_fit_score`, `macro_contributions` | 현재 시장 환경이 이 업종에 얼마나 유리하게 작용했는지 |
| 업종 내 재무 폭이 좋은가 | `company_fa_breadth_score`, `company_coverage_rate` | 업종 전체에 재무적으로 괜찮은 기업이 충분히 있는지 |
| 실제 매수 가능한 대형주가 충분한가 | `eligible_large_count` | 업종을 선택해도 실제로 담을 수 있는 대형주 후보가 있는지 |
| 후보였는데 왜 탈락했나 | `candidate_source_code`, `reason_code` | 수혜/방어/보충 후보였는지와 최종 탈락 사유 |
