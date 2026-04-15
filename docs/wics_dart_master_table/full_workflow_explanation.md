# WICS-DART 5개년 분석 전체 설명서

## 1. 문서 목적

이 문서는 지금까지 만든 WICS-DART 5개년 분석 작업을 처음부터 끝까지 이해할 수 있도록 정리한 설명서입니다.  
단순히 "어떤 파일이 있다"를 나열하는 것이 아니라, 왜 만들었는지, 어떤 순서로 돌아가는지, 각 파일이 무슨 역할을 하는지, 결과를 어떻게 읽어야 하는지까지 한 번에 이해할 수 있도록 작성했습니다.

이 문서는 특히 아래와 같은 상황에서 도움이 됩니다.

- 프로젝트를 다시 볼 때 전체 흐름이 헷갈릴 때
- 발표나 보고서 전에 작업 내용을 정리하고 싶을 때
- 다른 사람에게 이 분석 체계를 설명해야 할 때
- 나중에 기능을 확장하기 전에 현재 상태를 점검하고 싶을 때

---

## 2. 전체 작업의 목표

이번 작업의 목표는 다음과 같습니다.

1. DART 재무데이터를 2021년부터 2025년까지 모은다.
2. WICS 대분류를 기준으로 기업들을 섹터별로 묶는다.
3. 섹터별 기준선(중앙값, 분위수 등)을 만든다.
4. 같은 섹터 안에서 기업의 상대 위치를 계산한다.
5. 그 결과를 사람이 읽을 수 있는 보고서 형태로 정리한다.

즉, 이 작업은 단순히 CSV를 모으는 것이 아니라  
**"WICS 대분류 기준으로 5개년 재무분석이 가능한 구조를 만든 것"**이라고 볼 수 있습니다.

---

## 3. 전체 흐름 한눈에 보기

전체 파이프라인 흐름은 아래와 같습니다.

1. 원본 데이터 준비
2. 기업-연도 기준 마스터 테이블 생성
3. 섹터 기준 벤치마크 생성
4. 데이터 품질 검증
5. 기업별 섹터 상대평가 생성
6. 상위 기업 보고서 생성
7. 텍스트 수집 대상 기업 선정
8. 전체 섹터 종합 보고서 생성

이 과정을 실제로 실행하는 진입 파일이 [run_pipeline.py](/C:/dev/project/Service_Stock_Analysis/etl/wics_dart/run_pipeline.py)입니다.

---

## 4. 사용한 원본 데이터

이번 분석에서 사용한 주요 원본 데이터는 아래와 같습니다.

### 4.1 WICS 기업 분류 데이터

- [wics_company_2026.csv](/C:/dev/project/Service_Stock_Analysis/etl/wics/data/csv/wics_company_2026.csv)

이 파일은 기업별 WICS 분류를 담고 있습니다.  
이번 분석에서는 이 파일의 최신 분류를 사용해서 2021~2025 전체 기간에 공통 적용했습니다.

중요한 점:

- 이것은 현재 보유한 최신 분류 기준입니다.
- 따라서 과거 시점의 실제 당시 섹터 분류와 다를 수 있습니다.
- 즉, 시계열 해석에서는 반드시 이 한계를 알고 있어야 합니다.

### 4.2 DART 기업 코드 데이터

- [dart_company_2026.csv](/C:/dev/project/Service_Stock_Analysis/etl/company/data/dart_company_2026.csv)

이 파일은 종목코드와 DART `corp_code`를 연결하는 데 사용됩니다.

### 4.3 재무제표 데이터

- [income_statement_2021.csv](/C:/dev/project/Service_Stock_Analysis/etl/company/data/income_statement_2021.csv) ~ [income_statement_2025.csv](/C:/dev/project/Service_Stock_Analysis/etl/company/data/income_statement_2025.csv)
- [balance_sheet_2021.csv](/C:/dev/project/Service_Stock_Analysis/etl/company/data/balance_sheet_2021.csv) ~ [balance_sheet_2025.csv](/C:/dev/project/Service_Stock_Analysis/etl/company/data/balance_sheet_2025.csv)
- [cash_flow_2021.csv](/C:/dev/project/Service_Stock_Analysis/etl/company/data/cash_flow_2021.csv) ~ [cash_flow_2025.csv](/C:/dev/project/Service_Stock_Analysis/etl/company/data/cash_flow_2025.csv)

이 파일들은 각각 손익계산서, 재무상태표, 현금흐름표 데이터를 담고 있습니다.

---

## 5. 핵심 코드 파일 설명

이제 실제로 만든 Python 파일들을 하나씩 설명합니다.

### 5.1 [build_master_table.py](/C:/dev/project/Service_Stock_Analysis/etl/wics_dart/build_master_table.py)

이 파일은 전체 분석의 출발점입니다.

역할:

- WICS 기업 분류를 읽음
- DART 기업 코드를 읽음
- 두 데이터를 연결함
- 2021~2025 재무제표를 읽음
- 매출, 영업이익, 순이익, 자산, 부채, 자본, 영업현금흐름 등을 정리함
- 매출성장률, 영업이익률, ROE, 부채비율, 유동비율 같은 지표를 계산함
- 최종적으로 마스터 테이블과 섹터 벤치마크를 생성함

왜 중요한가:

- 원본 데이터는 파일이 여러 개로 흩어져 있습니다.
- 분석을 하려면 먼저 "기업 1개 + 연도 1개" 기준으로 정리된 표가 필요합니다.
- 이 파일이 바로 그 기준표를 만드는 역할을 합니다.

출력 결과:

- [company_year_master_2021_2025.csv](/C:/dev/project/Service_Stock_Analysis/etl/wics_dart/output/company_year_master_2021_2025.csv)
- [sector_benchmark_wics_large_2021_2025.csv](/C:/dev/project/Service_Stock_Analysis/etl/wics_dart/output/sector_benchmark_wics_large_2021_2025.csv)

### 5.2 [validate_master_table.py](/C:/dev/project/Service_Stock_Analysis/etl/wics_dart/validate_master_table.py)

이 파일은 마스터 테이블이 실제로 분석에 쓸 수 있는 수준인지 확인하는 단계입니다.

역할:

- `corp_code` 누락 확인
- 주요 재무지표 결측치 확인
- 연도별 커버리지 확인
- 섹터별 커버리지 확인
- 이상치 후보 확인
- 검증 리포트 생성

왜 필요한가:

- 데이터는 있다고 해서 바로 믿고 쓰면 안 됩니다.
- 어느 정도 결측이 있는지, 특정 섹터가 약한지 먼저 알아야 결과 해석이 가능합니다.

출력 결과:

- [master_table_validation_2021_2025.md](/C:/dev/project/Service_Stock_Analysis/etl/wics_dart/output/master_table_validation_2021_2025.md)

### 5.3 [build_sector_rankings.py](/C:/dev/project/Service_Stock_Analysis/etl/wics_dart/build_sector_rankings.py)

이 파일은 기업을 같은 섹터 안에서 상대평가하는 단계입니다.

역할:

- 같은 연도, 같은 WICS 대분류 안에서 기업끼리 비교
- 성장성, 수익성, 안정성 축으로 점수 계산
- `overall_score` 계산
- `top_20%`, `middle` 같은 구간 라벨 생성

핵심 개념:

- `growth_score`
- `profitability_score`
- `stability_score`
- `overall_score`

왜 필요한가:

- IT 기업과 금융 기업을 절대값으로 비교하면 왜곡됩니다.
- 그래서 같은 섹터 안에서의 상대 위치를 보는 것이 더 타당합니다.

출력 결과:

- [company_sector_rankings_2021_2025.csv](/C:/dev/project/Service_Stock_Analysis/etl/wics_dart/output/company_sector_rankings_2021_2025.csv)

### 5.4 [build_top_companies_report.py](/C:/dev/project/Service_Stock_Analysis/etl/wics_dart/build_top_companies_report.py)

이 파일은 랭킹 CSV를 사람이 읽기 쉬운 보고서로 바꾸는 단계입니다.

역할:

- 연도별로 기업 수가 많은 섹터를 고름
- 섹터별 상위 기업을 정리
- Markdown 보고서 생성

출력 결과:

- [top_companies_report_2021_2025.md](/C:/dev/project/Service_Stock_Analysis/etl/wics_dart/output/top_companies_report_2021_2025.md)

### 5.5 [prepare_text_targets.py](/C:/dev/project/Service_Stock_Analysis/etl/wics_dart/prepare_text_targets.py)

이 파일은 사업보고서 본문을 직접 수집하는 파일이 아닙니다.

역할:

- 최신 연도 기준으로 상위 기업을 골라서
- 나중에 텍스트 수집 대상으로 사용할 목록을 만듦

출력 결과:

- [text_targets_latest.csv](/C:/dev/project/Service_Stock_Analysis/etl/wics_dart/output/text_targets_latest.csv)

왜 필요한가:

- 모든 기업의 본문 텍스트를 한 번에 수집하기보다
- 우선 분석 가치가 높은 기업부터 뽑기 위해 사용합니다.

### 5.6 [fetch_business_overview.py](/C:/dev/project/Service_Stock_Analysis/etl/wics_dart/fetch_business_overview.py)

이 파일은 DART API를 통해 사업개요 텍스트를 수집하는 선택 단계입니다.

역할:

- `text_targets_latest.csv`를 읽음
- `DART_API_KEY`를 확인함
- 각 기업의 사업개요 텍스트를 수집함

출력 결과:

- `business_overview_text_latest.csv`

현재 상태:

- 이 단계는 선택 단계입니다.
- 정량 분석 파이프라인에는 포함되지 않습니다.
- API 키와 네트워크가 필요합니다.

### 5.7 [build_all_sector_analysis_report.py](/C:/dev/project/Service_Stock_Analysis/etl/wics_dart/build_all_sector_analysis_report.py)

이 파일은 종합 보고서를 생성하는 단계입니다.

역할:

- 연도별 커버리지 정리
- 2025년 섹터별 스냅샷 정리
- 핵심 분석 결과 문장 생성
- 섹터 등급형 정리
- 섹터별 상세 설명 정리
- 종합 보고서 생성

출력 결과:

- [all_sector_analysis_report_2021_2025.md](/C:/dev/project/Service_Stock_Analysis/etl/wics_dart/output/all_sector_analysis_report_2021_2025.md)

### 5.8 [run_pipeline.py](/C:/dev/project/Service_Stock_Analysis/etl/wics_dart/run_pipeline.py)

이 파일은 전체 파이프라인을 한 번에 실행하는 진입점입니다.

역할:

- `build_master_table.py`
- `validate_master_table.py`
- `build_sector_rankings.py`
- `build_top_companies_report.py`
- `prepare_text_targets.py`
- `build_all_sector_analysis_report.py`

를 순서대로 실행합니다.

---

## 6. 최종 생성된 핵심 산출물 설명

현재 `etl/wics_dart/output` 폴더에는 5개년 기준 결과물만 남아 있습니다.

### 6.1 [company_year_master_2021_2025.csv](/C:/dev/project/Service_Stock_Analysis/etl/wics_dart/output/company_year_master_2021_2025.csv)

이 파일은 가장 중요한 기준 테이블입니다.

의미:

- 한 행 = 기업 1개 + 연도 1개
- 재무 원천값과 주요 비율이 함께 들어 있음

이 파일을 기반으로 나머지 모든 분석이 진행됩니다.

### 6.2 [sector_benchmark_wics_large_2021_2025.csv](/C:/dev/project/Service_Stock_Analysis/etl/wics_dart/output/sector_benchmark_wics_large_2021_2025.csv)

이 파일은 섹터별 기준선입니다.

의미:

- 한 행 = WICS 대분류 1개 + 연도 1개
- 중앙값과 분위수 정보가 들어 있음

예를 들어:

- 2025년 IT 영업이익률 중앙값
- 2025년 건강관리 ROE 중앙값

같은 값을 여기서 볼 수 있습니다.

### 6.3 [master_table_validation_2021_2025.md](/C:/dev/project/Service_Stock_Analysis/etl/wics_dart/output/master_table_validation_2021_2025.md)

이 파일은 검증 리포트입니다.

주요 확인 내용:

- 전체 행 수
- `corp_code` 커버리지
- 주요 컬럼 결측치 비율
- 연도별 커버리지
- 섹터별 커버리지

### 6.4 [company_sector_rankings_2021_2025.csv](/C:/dev/project/Service_Stock_Analysis/etl/wics_dart/output/company_sector_rankings_2021_2025.csv)

이 파일은 기업 상대평가 결과입니다.

의미:

- 같은 연도
- 같은 섹터

안에서 기업이 어느 정도 위치인지 점수로 볼 수 있습니다.

### 6.5 [top_companies_report_2021_2025.md](/C:/dev/project/Service_Stock_Analysis/etl/wics_dart/output/top_companies_report_2021_2025.md)

이 파일은 상위 기업 요약 보고서입니다.

용도:

- 섹터별 상위 기업을 빠르게 훑어볼 때 사용
- 발표 전에 대표 기업 후보를 확인할 때 사용

### 6.6 [text_targets_latest.csv](/C:/dev/project/Service_Stock_Analysis/etl/wics_dart/output/text_targets_latest.csv)

이 파일은 나중에 정성 텍스트를 붙이고 싶을 때 사용하는 대상 목록입니다.

### 6.7 [all_sector_analysis_report_2021_2025.md](/C:/dev/project/Service_Stock_Analysis/etl/wics_dart/output/all_sector_analysis_report_2021_2025.md)

이 파일은 현재 최종 종합 보고서입니다.

포함 내용:

- 데이터 규모
- 연도별 커버리지
- 핵심 분석 결과
- 2025년 섹터별 스냅샷
- 섹터 등급형 정리
- 섹터별 상세 설명
- 해석 시 유의사항

---

## 7. 현재 보고서에서 어떻게 해석하는가

지금 보고서는 특히 `2025년 섹터 해석`을 중심으로 읽기 쉽게 구성돼 있습니다.

### 7.1 중앙값이 의미하는 것

예를 들어 `2025년 IT 영업이익률 중앙값 2.5%`는:

- 2025년
- IT 섹터
- 영업이익률 값이 있는 기업들

을 정렬했을 때 가운데 수준이 약 2.5%라는 뜻입니다.

즉, 중앙값은 **그 섹터의 전형적인 중간 수준**을 보는 값입니다.

### 7.2 등급형 정리의 의미

보고서의 `좋음 / 보통 / 주의`는 투자등급이 아닙니다.

이건 아래를 보기 쉽게 묶은 참고용 구분입니다.

- 섹터 평균 체질
- 해석의 안정성
- 업종 특성상 주의가 필요한지 여부

예:

- `좋음`: 산업재, 필수소비재, 경기관련소비재
- `보통`: IT, 소재, 커뮤니케이션서비스
- `주의`: 건강관리, 에너지, 금융, 유틸리티

### 7.3 상위 기업과 함께 읽는 법

보고서는 섹터별 상위 기업 예시도 같이 보여줍니다.

읽는 순서:

1. 섹터 중앙값으로 전체 분위기 확인
2. 상위 기업 3개 확인
3. 왜 그 기업이 상위인지 점수 구조 확인

즉, 섹터와 기업을 따로 보는 게 아니라  
**섹터 체질 + 상위 기업 강점**을 함께 읽는 구조입니다.

---

## 8. 실제로 확인된 핵심 수치

현재 검증 결과 기준 핵심 수치는 다음과 같습니다.

- 전체 행 수: `12,890`
- 섹터-연도 벤치마크 행 수: `50`
- `corp_code` 전체 커버리지: `98.5%`

또한 연도별 커버리지도 점차 개선되었습니다.

- 2021년 매출 커버리지: `63.0%`
- 2025년 매출 커버리지: `76.5%`
- 2021년 ROE 커버리지: `63.4%`
- 2025년 ROE 커버리지: `77.8%`

즉, 후반 연도로 갈수록 분석 가능성이 더 좋아졌다고 볼 수 있습니다.

---

## 9. 현재 구조의 한계

가장 중요한 한계는 하나입니다.

### 9.1 WICS 분류 시점 한계

현재 분석은 [wics_company_2026.csv](/C:/dev/project/Service_Stock_Analysis/etl/wics/data/csv/wics_company_2026.csv)의 최신 분류를 2021~2025 전체 기간에 공통 적용합니다.

이 말은:

- 2022년에 실제로는 다른 섹터였던 기업도
- 2026 기준 섹터로 2021~2025 전체가 묶일 수 있다는 뜻입니다.

그래서 지금 결과는:

- 섹터별 상대비교에는 유효
- 구조적 해석에도 유효
- 하지만 과거 당시 섹터 변화까지 완벽히 반영한 시계열 분석은 아님

입니다.

### 9.2 정성 텍스트 분석은 아직 선택 단계

현재는 정량 데이터 중심 분석이 완성된 상태입니다.  
사업보고서 본문 텍스트까지 붙인 정성 분석은 아직 기본 파이프라인에 포함되지 않았습니다.

---

## 10. 지금 상태를 한 문장으로 요약하면

지금은  
**"WICS 대분류를 기준으로 DART 재무데이터를 2021~2025 동안 통합 분석하고, 섹터 기준선과 기업 상대평가, 종합 보고서까지 생성할 수 있는 5개년 정량 분석 체계가 완성된 상태"**  
라고 정리할 수 있습니다.

---

## 11. 다음에 확장할 수 있는 방향

이후 확장 방향은 크게 3가지입니다.

1. 과거 시점 WICS 분류 데이터 확보
   - 시계열 섹터 정확도 향상

2. 사업보고서 본문 텍스트 결합
   - 정량 + 정성 해석 결합

3. 발표용 자료 자동 생성
   - 요약본, PPT, 발표 대본까지 연결

---

## 12. 같이 보면 좋은 파일

- [run_pipeline.py](/C:/dev/project/Service_Stock_Analysis/etl/wics_dart/run_pipeline.py)
- [build_master_table.py](/C:/dev/project/Service_Stock_Analysis/etl/wics_dart/build_master_table.py)
- [company_year_master_2021_2025.csv](/C:/dev/project/Service_Stock_Analysis/etl/wics_dart/output/company_year_master_2021_2025.csv)
- [company_sector_rankings_2021_2025.csv](/C:/dev/project/Service_Stock_Analysis/etl/wics_dart/output/company_sector_rankings_2021_2025.csv)
- [all_sector_analysis_report_2021_2025.md](/C:/dev/project/Service_Stock_Analysis/etl/wics_dart/output/all_sector_analysis_report_2021_2025.md)
