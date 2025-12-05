# ETL/크롤러/스케줄러/백테스트
│   ├── collectors/                   # 데이터 수집 (야후/뉴스/기업정보 등)
│   │   ├── stock_price/
│   │   ├── indicators/
│   │   ├── news/
│   │   └── company/
│   ├── processors/                   # 데이터 가공/전처리
│   ├── loaders/                      # DB 적재
│   ├── workflows/                    # ETL 파이프라인 (Airflow/Prefect/Dagster)
│   ├── backtests/                    # 백테스트 엔진
│   ├── notebooks/                    # Jupyter 분석 노트북
│   └── requirements.txt

