# apps/worker

데이터 수집과 FA 분석을 주기적으로 실행하는 워커 프로세스.

## 폴더 구조

```
apps/worker/
├── __main__.py              # CLI 진입점
├── config.py                # WorkerConfig + 환경변수 로딩
├── .env.example             # 환경변수 템플릿
│
├── collector/               # 데이터 수집
│   ├── README.md            # Collector 실행 가이드
│   ├── macro_job.py         # 매크로 시그널 (macro_signals)
│   ├── wics_job.py          # WICS 섹터 구성종목 (wics_companies)
│   └── company_job.py       # 재무제표 + 공시 이벤트 (financial_statements / dart_events)
│
└── analyzer/                # FA 분석 + 운영 universe 발행
    └── README.md            # Analyzer 실행 가이드
```

## 구성 요소

| 구성 요소 | 역할 | 문서 |
|---|---|---|
| Collector | 외부 데이터 수집과 Analyzer 입력 준비도 검사 | [Collector 실행 가이드](collector/README.md) |
| Analyzer | 월간 FA 분석, 기업 선정과 운영 universe 발행 | [Analyzer 실행 가이드](analyzer/README.md) |

## 공통 환경 설정

```powershell
Copy-Item apps/worker/.env.example apps/worker/.env
```

공통 필수 값은 `POSTGRES_HOST`, `POSTGRES_PORT`, `POSTGRES_DB`,
`POSTGRES_USER`, `POSTGRES_PASSWORD`이다. Collector API 키와 수집 옵션,
Analyzer 전략 및 발행 옵션은 각 하위 문서에서 관리한다.

다른 환경 파일을 사용하려면 `QUANTPILOT_ENV_FILE`에 경로를 지정한다.

## CLI 진입점

```powershell
python -m apps.worker --help
```

실행 명령은 역할별 README를 따른다. 상위 문서에는 Collector 또는 Analyzer의
세부 명령과 스케줄을 중복해서 작성하지 않는다.
