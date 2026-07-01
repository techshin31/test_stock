---
title: collector 파라미터 레퍼런스
created: 2026-06-29
source_basis: code_only
tags:
  - collector
  - parameters
---

# collector 파라미터 레퍼런스

근거 코드: `apps/worker/__main__.py::_parse_args`

## 위치 인자

| 인자 | 값 | 목적 |
|---|---|---|
| `target` | `macro`, `wics`, `company`, `all` | 실행할 수집 job 묶음 선택 |

## 공통 옵션

| 옵션 | 적용 | 코드상 목적 |
|---|---|---|
| `--start YYYY-MM-DD` | 전체 target | 수집 시작일. `all`에서는 기본값 계산에도 영향 |
| `--end YYYY-MM-DD` | 전체 target | 수집 종료일 또는 readiness cutoff |
| `--no-progress` | 전체 target | `show_progress=False`로 전달 |

## company 옵션

| 옵션 | 적용 | 코드상 목적 |
|---|---|---|
| `--years YEAR ...` | `company`, `all` | DART 재무제표 수집 사업연도 |
| `--company-size LARGE|MID|SMALL` | `company`, `all` | 최신 WICS 스냅샷의 규모 코드로 기업 수집 대상 필터 |

`--company-size`는 `action="append"`이므로 여러 번 지정할 수 있다.

## wics 옵션

| 옵션 | 적용 | 코드상 목적 |
|---|---|---|
| `--wics-snapshot-frequency weekly|daily` | `wics`, `all` | `_wics_date_list()`의 날짜 목록 생성 방식 |
| `--force-refresh` | `wics`, `all` | 이미 저장된 WICS 스냅샷도 다시 조회 |

## readiness 옵션

| 옵션 | 적용 | 코드상 목적 |
|---|---|---|
| `--check-readiness` | `all`만 허용 | 수집 후 `apps.worker.collector.readiness.run()` 실행 |

`--check-readiness`를 `all`이 아닌 target과 함께 쓰면 `ValueError`가 발생한다.

## start 기본값 규칙

근거 함수: `_resolve_collect_start`

| 조건 | 결과 |
|---|---|
| `--start` 지정 | 지정값 사용 |
| target이 `all`이 아님 | `None` |
| target이 `all`, `--end` 있음 | `--end` 전날 |
| target이 `all`, `--end` 없음 | KST 오늘 전날 |

## end 기본값 규칙

근거 함수: `_resolve_collect_end`

| 조건 | 결과 |
|---|---|
| `--end` 지정 | 지정값 사용 |
| target이 `all`이 아님 | `None` |
| target이 `all`, `--end` 없음 | KST 오늘 전날 |

## WICS 날짜 생성 규칙

근거 함수: `_wics_date_list`

| frequency | 결과 |
|---|---|
| `weekly` | 기간 내 각 ISO 주의 마지막 KRX 거래일 |
| `daily` | 기간 내 모든 날짜 문자열 |
