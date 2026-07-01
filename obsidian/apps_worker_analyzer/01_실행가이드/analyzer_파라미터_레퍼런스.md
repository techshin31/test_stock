---
title: analyzer 파라미터 레퍼런스
created: 2026-06-30
source_basis: code_only
tags:
  - analyzer
  - parameters
---

# analyzer 파라미터 레퍼런스

근거 코드:

- `apps/worker/__main__.py::_parse_args`
- `apps/worker/analyzer/pipeline.py::build_request`
- `apps/worker/analyzer/pipeline.py::AnalysisRequest.validate`

## 위치 인자

| 인자 | 값 | 실행 범위 |
|---|---|---|
| `target` | `macro` | readiness, 분기 FA, 매크로 |
| `target` | `sector` | macro 범위 + 업종 선정 |
| `target` | `company` | sector 범위 + 기업 선정 |
| `target` | `all` | company 범위 + 결과 검증 + 선택적 발행 |

## 옵션

| 옵션 | 형식 | 코드상 의미 |
|---|---|---|
| `--analysis-month` | `YYYY-MM` 또는 `YYYY-MM-DD` | `analysis_month`; 항상 월 1일로 정규화 |
| `--cutoff` | `YYYY-MM-DD` | 이 날짜까지 사용 가능했던 데이터만 조회 |
| `--effective-date` | `YYYY-MM-DD` | 발행된 `universe`가 Trader에 적용될 날짜 |
| `--publish` | flag | `analyze all`에서 PASS/WARNING run을 `universe`에 발행 |
| `--force` | flag | 같은 input hash가 있어도 새 run version 생성 |
| `--no-progress` | flag | tqdm 진행바 비활성화 |

## 날짜 검증

| 조건 | 결과 |
|---|---|
| `analysis_month.day != 1` | `ValueError` |
| `cutoff_date > effective_date` | `ValueError` |
| `--publish`와 target이 `all`이 아님 | `ValueError` |

## input hash 구성

`pipeline._analysis_input_hash()`는 다음 값을 순서대로 묶어 SHA-256 해시를 만든다.

```text
readiness.input_hash
config.fingerprint
target
analysis_month
cutoff_date
effective_date
```

따라서 같은 데이터와 설정이라도 `effective_date`가 달라지면 다른 run이다. 이 값은 운영 적용일이므로 단순한 표시용 라벨이 아니다.

