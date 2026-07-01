---
title: collector 실행방법
created: 2026-06-29
source_basis: code_only
tags:
  - collector
  - execution
---

# collector 실행방법

근거 코드:

- `apps/worker/__main__.py`
- `apps/worker/config.py`

## 기본 명령

```powershell
python -m apps.worker collect <target>
```

`target`은 다음 네 가지다.

| target | 목적 | 상세 |
|---|---|---|
| `macro` | 매크로 시그널 수집 | [[target_macro]] |
| `wics` | WICS 구성종목 스냅샷과 구성종목 가격 수집 | [[target_wics]] |
| `company` | 기업, DART 이벤트, 위험상태, 재무제표 수집 | [[target_company]] |
| `all` | 전체 수집 파이프라인 실행 | [[target_all]] |

## 환경 로딩

`apps.worker.config.load_config()`는 기본적으로 `apps/worker/.env`를 읽는다.

다른 env 파일을 쓰려면:

```powershell
$env:QUANTPILOT_ENV_FILE="path/to/.env"
python -m apps.worker collect all
```

필수 DB 환경변수:

- `POSTGRES_HOST`
- `POSTGRES_USER`
- `POSTGRES_PASSWORD`
- `POSTGRES_DB`

## 실행 예시

매크로만:

```powershell
python -m apps.worker collect macro --start 2026-06-01 --end 2026-06-28
```

WICS 주간 스냅샷:

```powershell
python -m apps.worker collect wics --start 2026-01-01 --end 2026-06-28 --wics-snapshot-frequency weekly
```

기업 LARGE만:

```powershell
python -m apps.worker collect company --years 2024 2025 2026 --company-size LARGE
```

전체 수집과 readiness 출력:

```powershell
python -m apps.worker collect all --end 2026-06-28 --check-readiness --no-progress
```

## 실행 후 확인

`collect all --check-readiness`는 JSON 리포트를 콘솔에 출력한다. 이 리포트는 DB에 저장되지 않는다.

관련 노트:

- [[collector_파라미터_레퍼런스]]
- [[../04_다이어그램/collect_all_전체흐름|collect all 전체흐름]]

