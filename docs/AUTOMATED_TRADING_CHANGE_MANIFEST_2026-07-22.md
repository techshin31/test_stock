# PAPER 자동매매 변경 전달 Manifest

기준 시각: 2026-07-29 KST
운영 범위: PAPER 자동매매 전용. REAL 환경·주문 경로는 변경하거나 활성화하지 않았다.

## 변경 원칙

- 이 manifest는 현재 dirty worktree의 자동매매 관련 변경을 분류하기 위한 문서다.
- 삭제, `reset`, `checkout`, 일괄 커밋은 수행하지 않았다.
- Git 커밋·원격 반영은 사용자 별도 승인 전까지 수행하지 않는다.
- 실행 반영은 PAPER `trader`와 읽기 전용 대시보드에만 적용했다.

## 파일 분류

| 구분 | 파일 | Git 추적 | 목적 |
|---|---|---:|---|
| 자동매매 핵심 | `core/execution/trader.py` | 기존 추적 | 최종 정산된 `REJECTED` 주문은 제한 재시도 경로로 넘기고, 미정산 `UNKNOWN_RESULT`는 동일 일자 차단을 유지한다. |
| 자동매매 핵심 | `core/execution/inverse_hedge.py` | 신규 | PAPER 전용 1배 인버스 ETF 헤지 상태·목표 비중·보유 한도를 계산한다. |
| 자동매매 핵심 | `core/constant/types.py` | 기존 추적 | 인버스 ETF 종목 상수를 추가한다. |
| 환경 예시 | `.env.example` | 기존 추적 | PAPER 인버스 헤지 설정 예시를 문서화한다. |
| 신규 테스트 | `tests/test_live_trader_and_strategy.py` | 기존 추적 | 브로커 응답 불명 상태 차단과 정산 후 위험청산 재시도를 회귀 검증한다. |
| 신규 테스트 | `tests/test_inverse_hedge.py` | 신규 | 헤지 확인·상한·손절·보유기간·주문 안전을 검증한다. |
| API/대시보드 | `dashboard/src/App.jsx` | 기존 추적 | PAPER 완성도, 주문 상태, 인버스 헤지를 읽기 전용으로 표시한다. |
| API/대시보드 | `dashboard/src/App.css` | 기존 추적 | 운영·헤지 카드의 상태 표현을 보완한다. |
| API/대시보드 | `tests/test_dashboard_api.py` | 기존 추적 | API가 안전한 PAPER 운영 상태를 노출하는지 검증한다. |

## 검증 결과

| 검증 | 결과 |
|---|---|
| Python 전체 회귀 테스트 | `322 passed` |
| Python 컴파일 검사 | `scheduler.py`, `core`, `api`, `apps` 통과 |
| 의존성 잠금 | `uv lock --check` 통과 |
| 대시보드 정적 검사 | `npm run lint` 통과 |
| 대시보드 프로덕션 빌드 | `npm run build` 통과 |
| 변경 형식 | `git diff --check` 통과 |
| 컨테이너 재배포 | PAPER `trader`·대시보드 이미지 재빌드 및 재기동 완료 |
| 런타임 확인 | PostgreSQL, API, trader, dashboard 모두 healthy; API health ready; 대시보드 HTTP 200 |

## 배포 후 주문 안전 확인

- 2026-07-29 14:43 KST에 과거 `UNKNOWN_RESULT`가 최종 `REJECTED`로 정산된 GS 매도 732주가 PAPER에서 1회 전량 체결됐다.
- 체결 후 두 스캔 주기 동안 매도 체결 수는 증가하지 않았고, 보유 포지션·미결 주문·주문 차단은 모두 0으로 유지됐다.
- 당일 체결 주문은 execution ledger에서 연결률과 수량 일치율이 모두 100%로 확인됐다.

## 완료 범위와 남은 운영 증거

코드·대시보드·PAPER 런타임 안전성은 검증됐지만, 전체 자동매매 시스템의 장기 완료 조건은 아직 충족되지 않았다. 실제 운영으로만 다음 증거를 누적해야 한다.

- BUY/SELL 체결 표본 각 30건
- 재진입 shadow 10개 고유 세션
- PAPER 완료 세션 60개와 동일 날짜의 FINAL·READY 보고서 60개
- 비용 차감 벤치마크 초과수익, 낙폭·비용·운영 무결성 기준

이 조건들이 충족되기 전에는 `full_system_complete=false`와 REAL 실행 차단을 유지한다.
