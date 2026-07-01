---
title: collector CLI 진입흐름
created: 2026-06-29
source_basis: code_only
tags:
  - collector
  - diagram
  - CLI
---

# collector CLI 진입흐름

이 흐름도는 사용자가 입력한 `python -m apps.worker collect ...` 명령이 실제 Collector Job으로 연결되는 공통 실행 경로를 표현한다.

```mermaid
flowchart TB
    A["python -m apps.worker collect target options<br/>사용자가 실행하는 Collector 명령"] --> B["_parse_args()<br/>argparse로 category, target, option 파싱"]
    B --> C{"category == collect?<br/>데이터 수집 명령인가"}
    C -->|예| D["run_collect(args)<br/>Collector 실행 진입점"]
    C -->|아니오| X["run_analyze 또는 run_audit<br/>분석/감사 명령으로 이동"]

    D --> E["_init()<br/>load_config + PostgreDB 연결 생성"]
    E --> F["show = not args.no_progress<br/>진행바/콘솔 출력 여부 결정"]
    F --> G["_resolve_collect_start(target,start,end)<br/>실제 수집 시작일 결정"]

    G --> G1{"target == all 이고<br/>--start 미입력?"}
    G1 -->|예| G2["collect_start = end - 1일<br/>end도 없으면 KST 오늘 - 1일"]
    G1 -->|아니오| G3["collect_start = --start<br/>target별 직접 수집은 입력값 유지"]
    G2 --> G4["_resolve_collect_end(target,end)<br/>all은 end 없으면 KST 오늘 - 1일"]
    G3 --> G4
    G4 --> H{"target<br/>수집 대상 선택"}

    H -->|macro| M["macro_job.run<br/>매크로 시그널만 수집"]
    H -->|wics| W["wics_job.run collect_prices=True<br/>WICS 스냅샷과 구성종목 가격 수집"]
    H -->|company| C1["company_job.run<br/>기업/DART/재무 데이터 수집"]
    H -->|all| A1["macro -> wics snapshot -> company -> wics price<br/>전체 수집을 순서대로 실행"]

    W --> W1["_wics_date_list(start,end,frequency)<br/>weekly: 주별 마지막 KRX 거래일<br/>daily: 기간 내 날짜 후보"]
    C1 --> C2["effective_years + dart_start_date 계산<br/>--years 우선, 없으면 start/end 기준"]
    A1 --> A2["collect all 내부 순서 고정<br/>WICS 가격은 company_job 이후 별도 실행"]

    M --> R{"--check-readiness?<br/>준비도 검사 요청"}
    W1 --> R
    C2 --> R
    A2 --> R

    R -->|예, target all| R1["readiness.run(cutoff_date)<br/>Analyzer 입력 준비도 JSON 출력"]
    R -->|예, target all 아님| R2["ValueError<br/>--check-readiness is only valid with collect all"]
    R -->|아니오| Z["db.close()<br/>DB 연결 종료"]
    R1 --> Z
    R2 --> Z
```

구현상 중요한 점:

- `collect all`에서 `--end`를 생략하면 종료일은 KST 오늘 기준 전일이며, `--start`도 생략하면 시작일도 같은 전일로 맞춘다.
- `target wics`는 `wics_job.run(... collect_prices=True)`라서 스냅샷과 가격을 같이 수집한다.
- `target all`은 먼저 `wics_job.run(... collect_prices=False)`로 스냅샷만 채운 뒤, `company_job` 이후 `wics_industry_job.run`으로 가격을 수집한다.
- `--check-readiness`는 `target all`에서만 허용되며, 결과는 테이블에 저장하지 않고 콘솔 JSON으로 출력한다.

관련 노트:

- [[../01_실행가이드/collector_실행방법|collector 실행방법]]
- [[../01_실행가이드/collector_파라미터_레퍼런스|collector 파라미터 레퍼런스]]
- [[collect_all_전체흐름|collect all 전체흐름]]
