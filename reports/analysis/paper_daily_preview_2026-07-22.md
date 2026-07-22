# PAPER 일일 성과·원장 보고서 — 2026-07-22

## Executive Summary

- **운영 모드:** PAPER / 보고서 상태 PRELIMINARY_INTRADAY
- **계좌 성과:** 5억원 대비 -28,806,771원 (-5.76%), 인증 기준선 이후 8,167,639원 (1.76%)
- **데이터 판단:** 성과 검증 BLOCKED; 거래 수준 근거는 LOW_FOR_TRADE_LEVEL_PNL__HIGH_FOR_ENDPOINT_PNL
- **전략 변경:** 추세 재무장 후보는 주문 없는 shadow이며 승격 상태는 BLOCKED입니다.

## 핵심 KPI

| 지표 | 값 |
|---|---:|
| 현재 총자산 | 471,193,229원 |
| 5억원 대비 손익 | -28,806,771원 |
| 인증 기준선 이후 손익 | 8,167,639원 |
| 주문 체결률 | 66.67% |
| 체결 주문-실행 연결률 | 100.00% |
| 현재 보유수량 원장 일치율 | 50.00% |
| 기준선 이후 회전율 | 56.78% |
| 기록 슬리피지 | 3,778,202원 |
| 추정 수수료·세금 | 2,553,459원 |

## 일별 성과 추이

| 날짜 | 총자산 | 일일 수익률 | 누적 수익률 | KOSPI | 낙폭 |
|---|---:|---:|---:|---:|---:|
| 2026-07-20 | 463,025,590 | 0.00% | 0.00% | 0.00% | 0.00% |
| 2026-07-21 | 473,802,699 | 2.33% | 2.33% | 3.56% | 0.00% |
| 2026-07-22 | 471,193,229 | -0.55% | 1.76% | 9.38% | -0.55% |

## 원장 복원과 근거 수준

- 계좌 종점 손익은 브로커 조회값으로 직접 확인합니다. 현재 근거 등급은 `LOW_FOR_TRADE_LEVEL_PNL__HIGH_FOR_ENDPOINT_PNL`입니다.
- 전체 주문 465건 중 체결 128건이며, 체결 주문의 실행 테이블 연결률은 62.50%입니다.
- 현재 보유종목 수량 일치율은 50.00%이고, 미해결 손익 조정항목은 -17,982,978원입니다.

## 추세 재무장 shadow 결과

- 관측 세션: 1/10
- 위험청산 추적 종목: 5개 / 3일 연속 확인 완료 후보: 0개
- 이 후보는 `OBSERVE_ONLY_NO_ORDER`로 고정되어 실제 목표비중·주문 계산에 연결되지 않습니다.

### 승격 기준

- [x] recent_return_improves: current=-1.7503%, shadow=-0.0306%
- [x] recent_max_drawdown_improves: current=-19.0648%, shadow=-17.1647%
- [x] recent_turnover_improves: current=45.83x, shadow=23.65x
- [ ] live_shadow_observation_window: 1/10 completed sessions
- [x] shadow_is_observe_only: order path is disconnected from the shadow candidate
- [ ] held_quantity_ledger_match: 50.00%
- [ ] filled_order_execution_link_coverage: 62.50%
- [x] no_unresolved_order_states: 0 open orders

## 다음 조치

- [ ] 1/10 completed sessions
- [ ] 50.00%
- [ ] 62.50%

### REAL 전환 차단 조건

- [ ] observed_trading_days 2 < 60
- [ ] critical_incidents 8 > 0
- [ ] performance_validation_status BLOCKED != READY
- [ ] submitted_orders 9 < 10
- [ ] excess_return -0.0761 <= 0.0000

## 검증과 한계

- [x] operational_log: 489 completed scans
- [x] certified_baseline: 2026-07-20T17:46:10+09:00
- [x] account_snapshot_freshness: 2026-07-22T11:25:45+09:00
- [x] cash_flow_ledger: 0 declared external flows
- [x] benchmark_download: 4 KOSPI closes
- [x] benchmark_anchor_alignment: certified=2026-07-16, effective=2026-07-20, account baseline unchanged
- [x] scoped_order_execution_data: 9 orders / 16 executions
- [x] paper_ledger_reconstruction: 465 orders; held quantity match 50.00%
- [x] performance_calculation: 3 daily NAV observations

### 주의사항

- 수익률은 인증 기준선 이후 계좌 NAV의 시간가중수익률이며 외부 자금 이동은 cash_flows.json으로 조정합니다.
- 체결 수수료·세금이 0으로 기록된 경우 설정된 KOSPI 비용률로 추정합니다.
- 원장 수준 실현손익은 누락 체결 때문에 부분 추정치이며, 계좌 종점 손익은 브로커 조회값입니다.
- 추세 재무장 후보는 관측 전용이며 주문·목표비중 계산에 연결되지 않습니다.

### 근거자료

- `C:\dev\project\Service_Stock_Analysis\logs\paper\operational_health.jsonl`
- `C:\dev\project\Service_Stock_Analysis\logs\paper\account_snapshots.jsonl`
- `C:\dev\project\Service_Stock_Analysis\reports\promotion\paper\baseline.json`
- `C:\dev\project\Service_Stock_Analysis\reports\promotion\paper\cash_flows.json`
- `Yahoo Finance ^KS11 via data loader`
- `PostgreSQL orders + executions (strategy/venue/account scoped)`
- `PostgreSQL full PAPER/legacy order ledger + broker dashboard endpoint`
- `C:\dev\project\Service_Stock_Analysis\logs\paper\shadow_reentry_state.json`
- `C:\dev\project\Service_Stock_Analysis\reports\analysis\paper_reentry_experiments\pass_only\metrics.json`
