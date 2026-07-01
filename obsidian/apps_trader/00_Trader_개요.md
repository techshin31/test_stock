---
title: Trader 개요
created: 2026-06-30
source_basis: code_only
tags:
  - quantpilot
  - trader
  - execution
  - live
---

# Trader 개요

`apps/trader`는 QuantPilot의 운영 매매 앱이다. Analyzer가 발행한 `universe`와 User 앱이 저장한 증권사 자격증명을 읽어, 하루를 장전 계획 생성, 장중 주문 실행, 장마감 정산으로 나누어 처리한다.

```text
apps/user register
  -> user_broker_credentials

apps/worker analyzer --publish
  -> universe

apps/trader
  -> planner
  -> executor
  -> reconciler
```

## 문서 구조

```text
apps_trader/
├── 01_사용자_가이드
├── 02_투자자_해석
├── 03_개발자_구현
└── 04_다이어그램
```

## 대상 독자별 입구

| 독자 | 먼저 볼 문서 | 목적 |
|---|---|---|
| 사용자/운영자 | [[01_사용자_가이드/trader_실행방법|trader 실행방법]] | `planner`, `executor`, `reconciler` 실행 |
| 사용자/운영자 | [[01_사용자_가이드/일일_운영_체크리스트|일일 운영 체크리스트]] | 장전/장중/장마감 확인 순서 |
| 사용자/운영자 | [[01_사용자_가이드/환경변수_레퍼런스|환경변수 레퍼런스]] | 필수 환경 변수와 실주문 gate |
| 투자자 | [[02_투자자_해석/전략과_주문_흐름_해석|전략과 주문 흐름 해석]] | universe가 주문 계획으로 바뀌는 방식 |
| 투자자 | [[02_투자자_해석/리스크와_상태_해석|리스크와 상태 해석]] | 손실 한도, 기업 위험, SELL_ONLY, 상태 코드 |
| 개발자 | [[03_개발자_구현/CLI_오케스트레이션|CLI 오케스트레이션]] | 공통 초기화와 세 command 분기 |
| 개발자 | [[03_개발자_구현/storage_contract|storage contract]] | 테이블 역할과 repository 소유권 |

## 실제 코드 경로

| 파일 | 역할 |
|---|---|
| `apps/trader/__main__.py` | CLI 진입점, 공통 초기화, planner/executor/reconciler 분기 |
| `apps/trader/config.py` | Trader env 로드와 필수 변수 검증 |
| `apps/trader/scheduler.py` | KST 기준 장전/장중/장마감 시간 대기 |
| `apps/trader/planner.py` | 포지션 동기화, universe 조회, 전략 계산, `trade_plans` 생성 |
| `apps/trader/runner.py` | 장중 사이클, 손실 한도 확인, 실행 대상 plan 순회 |
| `apps/trader/monitor.py` | `STATUS` 출력과 Slack 알림 |
| `apps/trader/audit.py` | JSONL 감사 로그 |
| `core/trade/execution.py` | 오더북 확인, 주문 슬라이싱, 미체결 취소/동기화, 체결 저장 |
| `core/trade/reconcile.py` | KIS 일별 주문 이력 기반 EOD reconcile |
| `core/trade/position_sync.py` | KIS 잔고와 `positions` 동기화 |
| `core/trade/gate.py` | 실주문 gate와 일일 손실 한도 |
| `storage/postgres/repositories/*` | 전략, universe, 계획, 주문, 체결, 포지션, 잔고 저장소 |

## 하루 실행 단위

| command | 기본 시점 | 핵심 역할 | 주요 산출물 |
|---|---|---|---|
| `planner` | 08:30 KST | 포지션 동기화, 전략 계산, 주문 계획 생성 | `positions`, `universe`, `trade_plans` |
| `executor` | 09:00-15:20 KST | `PENDING/ORDERED` 계획을 주문으로 실행 | `orders`, `order_status_history`, `executions` |
| `reconciler` | 15:40 KST | 브로커 이력 정산, 포지션 재동기화, 잔고 스냅샷 | `orders`, `executions`, `positions`, `balance_history`, `universe` |

## 운영 경계

- Trader는 `fa_company_results`를 직접 읽지 않는다. 운영 입력은 발행된 `universe`다.
- Trader는 API 키/시크릿을 `.env`에서 직접 읽지 않는다. `apps/user register`로 저장된 DB 자격증명을 조회한다.
- `executor`가 실행 대상으로 보는 계획 상태는 `PENDING`과 `ORDERED`다.
- `reconciler`는 오늘 계획이 있고 `PENDING/ORDERED`가 0개이면 15:40 대기를 건너뛴다.
- `balance_history`는 다음 거래일 일일 손실 한도 계산의 기준이 된다.

관련 다이어그램:

- [[04_다이어그램/00_다이어그램_지도|Trader 다이어그램 지도]]
- [[04_다이어그램/daily_runtime_전체흐름|daily runtime 전체흐름]]
- [[04_다이어그램/planner_계획생성_상세|planner 계획생성 상세]]
- [[04_다이어그램/executor_주문실행_상세|executor 주문실행 상세]]
- [[04_다이어그램/reconciler_정산_상세|reconciler 정산 상세]]
