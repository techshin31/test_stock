# 자동매매 주문·손익 진단 — source notes

- Snapshot: 2026-07-20 11:57 KST
- Audience: product stakeholders
- Delivery mode: MCP app report
- Primary question: 오늘 주문 0건과 최근 손익 부진이 전략 관망인지 운영 결함인지 구분한다.
- Baselines: 오늘 첫 DRY_RUN 총자산, 2026-07-13 첫 PAPER 계좌 관측, 8% trailing-stop rule.

## Source inventory

- `logs/dry_run/dashboard_state.json`: 오늘 누적 주문, 운영 상태, 누적 슬리피지.
- `logs/dry_run/decision_state.json`: 최신 6개 포지션의 `DATA_UNAVAILABLE_HOLD` 판정.
- `logs/fa_candidates.json`: 2026-07-17 신호일 기준 후보 0종목.
- `logs/dry_run/account_history.csv`, `logs/paper/account_history.csv`: 최근 계좌 총자산 관측.
- KIS mock balance read at 2026-07-20 11:57 KST: 비식별 포지션 평가손익.
- `core/utils/trading_calendar.py`: XKRX 세션 판정.
- `core/execution/trader.py`, `core/strategy/fa_ta_momentum.py`: stale filter와 위험청산 우선순위.
- `reports/fa_weighting_replay_pass_only/metrics.json`: PASS/PUBLISHED 연구 리플레이.
- Official holiday evidence: https://usa.mofa.go.kr/us-newyork-ko/brd/m_4237/view.do?seq=1348072
- KRX holiday rule: https://global.krx.co.kr/contents/GLB/06/0606/0606030101/GLB0606030101T3.jsp

## Chart map

| Section | Question | Family/type | Fields | Supported claim | Palette |
|---|---|---|---|---|---|
| Recent performance | 오늘 총자산은 장중 어떻게 움직였나? | Trend / line | timestamp, total_asset | 11:57 총자산은 첫 관측보다 낮다 | single-root blue |
| Position concentration | 평가손익은 어디에 집중됐나? | Comparison / horizontal bar | ticker, unrealized_pnl | 삼성전자와 383220 손실이 483650 이익을 초과한다 | diverging around zero |

## QA and caveats

- Notebook executed top-to-bottom successfully with the project Python 3.10 environment.
- Intraday chart has 12 ordered observations; position chart has 6 comparable categories.
- PAPER and DRY_RUN history are the same mock account but different execution modes, so the combined 7/13–7/20 return is a short operational observation, not an audited strategy return.
- Replay data is not production-equivalent because it assumes daily-close proportional fills and contains only one PUBLISHED run.
