# WICS-DART 분석 파이프라인

이 폴더는 `2021~2025` 기간의 DART 재무데이터를 바탕으로 `WICS 대분류` 기준 분석을 수행하는 Python 파이프라인을 담고 있습니다.

폴더 구조:

- `core/`: 점수 기준처럼 여러 단계에서 재사용하는 핵심 로직
- `pipeline/`: 마스터 테이블, 검증, 섹터 랭킹 등 데이터 생성 단계
- `reports/`: Markdown 분석 보고서 생성 단계
- `text/`: 텍스트 수집 대상 선정 및 DART 사업개요 수집 단계
- `notebooks/`: 탐색 분석과 백테스트용 Jupyter Notebook
- `output/`: 생성된 CSV 및 Markdown 결과물 저장 폴더
- `run_pipeline.py`: 전체 5개년 파이프라인을 한 번에 실행하는 진입점
- `requirements.txt`: 필요한 Python 패키지 목록

주요 파일:

- `core/scoring.py`: FA 점수 기준, 이벤트 가중치, percentile, 업종별 가중치 계산
- `core/wics_prices.py`: WICS 종목 데이터에서 추정 종가와 보유수익률 계산
- `pipeline/build_master_table.py`: 다개년 마스터 테이블과 섹터 벤치마크 생성
- `pipeline/validate_master_table.py`: 다개년 검증 리포트 생성
- `pipeline/build_sector_rankings.py`: 연도별·섹터별 기업 상대평가 생성 진입점
- `pipeline/build_available_reference_bundle.py`: 점수화 가능한 참조 데이터 묶음 생성
- `reports/build_top_companies_report.py`: 다개년 상위 기업 요약 보고서 생성
- `reports/build_all_sector_analysis_report.py`: 2021~2025 종합 분석 보고서 생성
- `text/prepare_text_targets.py`: 최신 연도 기준 텍스트 수집 대상 기업 선정
- `text/fetch_business_overview.py`: DART API를 이용한 사업개요 텍스트 수집
- `notebooks/single_sector_score_backtest.ipynb`: 한 개 WICS 대분류 섹터의 FA 스코어 백테스트 노트북

기본 생성 결과:

- `company_year_master_2021_2025.csv`
- `sector_benchmark_wics_large_2021_2025.csv`
- `master_table_validation_2021_2025.md`
- `company_sector_rankings_2021_2025.csv`
- `top_companies_report_2021_2025.md`
- `text_targets_latest.csv`
- `all_sector_analysis_report_2021_2025.md`

선택 생성 결과:

- `business_overview_text_latest.csv`
  - `text/fetch_business_overview.py`를 별도로 실행할 때 생성됩니다.
  - 이 단계는 `DART_API_KEY`, 네트워크 연결, `OpenDartReader` 설치가 필요합니다.

주의사항:

- 현재 5개년 분석은 `wics_company_2026.csv`의 최신 WICS 분류를 2021~2025 전체 기간에 공통 적용합니다.
- 따라서 과거 시점의 실제 당시 섹터 분류와 완전히 일치하지 않을 수 있습니다.
- 이 점은 시계열 해석에서 반드시 감안해야 합니다.

실행 예시:

```powershell
C:\Users\shin\AppData\Local\Python\bin\python.exe -m pip install -r etl\wics_dart\requirements.txt
```

```powershell
C:\Users\shin\AppData\Local\Python\bin\python.exe etl\wics_dart\run_pipeline.py
```
