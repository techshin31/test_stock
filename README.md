- https://github.com/good593/Investment_crypto
- https://github.com/good593/stock_forecast


```mermaid
gantt
    title 프로젝트 상세 일정 및 상태 (2026)
    dateFormat  YYYY-MM-DD
    axisFormat  %m/%d
    
    section 1. 분석 및 설계
    화면 설계 (김철수)           :done, a1, 2026-02-19, 2d
    데이터 수집 설계 (이영희)     :active, a2, after a1, 2d
    ERD 설계 (박지민)            :crit, a3, 2026-02-21, 2026-02-23

    section 2. 구현
    데이터 수집/전처리 (이영희)    :a4, 2026-02-24, 10d
    화면 구현 (김철수)           :a5, 2026-03-05, 9d

    section 3. 검수
    테스트 시나리오 작성 (박지민)  :a6, 2026-03-16, 2d
    테스트 진행 및 오류 수정      :a7, after a6, 3d

    section 5. 완료
    발표 문서 및 아키텍처 작성    :a8, 2026-03-23, 2d
    최종 발표                  :milestone, 2026-03-25, 0d
```