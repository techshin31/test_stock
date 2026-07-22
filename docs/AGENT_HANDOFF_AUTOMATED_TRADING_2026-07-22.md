# PAPER 자동매매 시스템 작업 인수인계

작성 시각: 2026-07-22 KST  
프로젝트: `C:\dev\project\Service_Stock_Analysis`  
작업 목표: PAPER 자동매매 시스템을 안전하게 완성하고 장기 운영 증거를 누적한다. REAL 실행은 별도 사용자 승인 전까지 금지한다.

## 가장 먼저 읽을 결론

- 현재 PAPER 런타임은 안전하다. 준비도는 안전검사 **12/12**, 완료 근거 **10/14**다.
- 전체 시스템은 아직 완료가 아니다. 남은 장기 증거는 BUY 5/30, SELL 4/30, shadow 1/10세션, PAPER 1/60세션, FINAL·READY 일일 보고서 1/60건이다.
- 기존 PAPER scheduler PID 2644는 계속 실행 중이다. 절대 임의로 중지하거나 재시작하지 않는다.
- 숨김 supervisor PID 7004가 기존 scheduler PID 2644에 무중단 연결돼 있다.
- DRY_RUN 및 REAL scheduler는 실행 중이지 않다. `KIS_ENV`와 `ALLOW_LIVE_ORDER`도 설정돼 있지 않다.
- 마지막 EOD 연속성 패치는 코드에 적용됐고 대상 테스트 59개가 통과했다. 그러나 아래의 `BLOCKED EOD exit 0` 문제를 아직 마무리하지 못했다.
- 최신 EOD 변경 이후 전체 테스트는 아직 다시 실행하지 않았다. 그 이전 전체 회귀 결과는 246 passed다.

## 절대 지켜야 할 안전 조건

1. `--live`를 실행하지 않는다.
2. `KIS_ENV=real`을 설정하지 않는다.
3. `ALLOW_LIVE_ORDER=true`로 변경하지 않는다.
4. 현재 PAPER scheduler 및 하위 프로세스를 중지하거나 재시작하지 않는다.
5. 현재 supervisor를 중복 실행하지 않는다.
6. 기준선, 원본 주문 DB, 브로커 계좌를 분석 편의를 위해 수정하지 않는다.
7. 전략 후보 `R_TREND_REARM`, `C_CAP10`, `C_CAP08`을 표본 충족 전에 실제 주문 규칙에 연결하지 않는다.
8. 작업 트리가 매우 dirty하다. 사용자의 기존 변경을 보존하고 관련 파일만 최소 수정한다. `git reset --hard`, `git checkout --`, 광범위 삭제를 사용하지 않는다.

## 현재 실행 프로세스

| 역할 | 프로세스 체인 | 상태 |
|---|---|---|
| PAPER scheduler | 20452 → 24712 → **2644** | 실행 중, mode PAPER |
| scheduler supervisor | 22548 → 13252 → **7004** | PID 2644에 연결됨 |
| DRY_RUN scheduler | 없음 | 정상 |
| REAL scheduler | 없음 | 정상 |

잠금 및 연결 근거:

- `logs/scheduler.instance.lock.json`: pid 2644, mode PAPER, label scheduler
- `logs/scheduler.supervisor.instance.lock.json`: pid 7004, mode PAPER, label scheduler-supervisor
- `logs/paper/scheduler_supervisor.jsonl`: `ATTACHED_TO_EXISTING`, `pid=2644`

현재 실행 중인 scheduler는 supervisor/EOD 백필 코드 수정 전에 로드된 프로세스다. 새 코드는 현재 프로세스에 핫리로드되지 않는다. 그래도 오늘의 정상 EOD 생성은 기존 코드가 수행한다. 향후 scheduler가 비정상 종료되면 supervisor가 수정된 코드로 PAPER scheduler를 복구한다.

## 현재 수익 및 원장 결과

| 항목 | 결과 |
|---|---:|
| 시작 기준자산 | 500,000,000원 |
| 현재 PAPER 총평가액 | 471,978,629원 |
| 5억원 대비 손익 | -28,021,371원 |
| 5억원 대비 수익률 | -5.6043% |
| 2026-07-20 인증 기준선 이후 손익 | +8,953,039원 |
| 인증 기준선 이후 수익률 | +1.9336% |
| 전체 주문 이벤트 | 547건 |
| 실제 체결 이벤트 | 201건 |
| 현재 보유수량 일치 | 4/4, 100% |
| 전체 종목 수량 일치 | 23/23, 100% |
| 5억원 직접 재생 현금 잔차 | 391,449원, 0.0783% |
| 명시 허용한도 | 500,000원, 0.10% |

핵심 판단:

- 손실은 단순 원장 오류로 설명되지 않는다.
- 누락된 브로커 체결 5건과 DB에 잘못 FILLED로 저장된 012510 매수 7건을 분석 원장에서 교정했다.
- 종점 보유수량과 현금 패리티는 허용범위 안에서 복원됐다.
- 거래별 실현손익은 과거 executions 누락과 실제 비용 미기록 때문에 저신뢰다.
- 과도한 누적 체결대금과 회전율이 손실 및 비용 드래그의 주요 의심 요인이다.

## 완료된 구현

### 1. 종목명 주표기 복구

- 대시보드와 분석 리포트는 한글 종목명을 주표기로 사용하고 코드를 보조 표기로 사용한다.
- API는 로컬 PostgreSQL `companies` 테이블의 종목명을 읽되 DB 장애 시 계좌 모니터링을 계속 제공한다.

주요 파일:

- `api/main.py`
- `dashboard/src/App.jsx`
- `reports/analysis/build_paper_ledger_reentry_artifact.py`

### 2. 5억원 주문·손익 원장 복원

- KIS PAPER 일별 주문의 전체 연속 페이지를 감사한다.
- 날짜와 브로커 주문번호로 DB 주문을 대사한다.
- 원본 DB를 변경하지 않고 분석 레이어에서 잘못된 체결을 `EXPIRED_UNFILLED`로 보정한다.
- 관측된 체결·부분체결·거절·취소 이벤트만 재생한다.

주요 파일 및 근거:

- `core/analytics/paper_broker_history.py`
- `core/analytics/paper_ledger_reconstruction.py`
- `apps/backtester/paper_order_result_replay.py`
- `reports/analysis/paper_broker_history/latest.json`
- `reports/analysis/paper_ledger_latest/summary.json`
- `reports/analysis/paper_order_result_replay/latest/summary.json`

### 3. 재진입 및 위험한도 실험

- `R_TREND_REARM`을 주문 경로와 분리된 observe-only shadow로 구현했다.
- 이상적 체결, 관측 체결 사후평균, Wilson 95% 하한 시나리오로 스트레스 실험한다.
- `R_TREND_REARM`은 Wilson 하한에서 실패하므로 운영 반영 금지다.
- `C_CAP10`, `C_CAP08`은 세 시나리오를 통과했지만 BUY/SELL 표본이 작아 비상 위험후보로만 보존한다.

주요 파일 및 근거:

- `core/analytics/paper_shadow_reentry.py`
- `apps/backtester/paper_strategy_experiments.py`
- `apps/backtester/paper_execution_stress.py`
- `reports/analysis/paper_execution_stress/latest/summary.json`
- `logs/paper/shadow_reentry_state.json`

### 4. 일일 보고서와 정식 분석 리포트

- EOD 보고서는 FINAL·READY뿐 아니라 데이터 신선도, 위험점검, 주문 대사, 운영 무결성 100%와 미종결 주문 0건을 요구한다.
- `reports/promotion/paper/daily/YYYY-MM-DD.json|md`를 날짜별로 저장한다.
- `reports/promotion/paper/latest.json`을 최신 정식 보고서로 사용한다.
- 정식 분석 아티팩트는 `reports/analysis/paper_system_report/latest.json`과 날짜별 스냅샷으로 원자적 갱신한다.
- EOD 후 준비도 또는 정식 아티팩트 갱신 실패는 작업 실패로 전파한다.

### 5. 전체 시스템 준비도

- `core.analytics.system_readiness`가 런타임 안전과 장기 완료 근거를 분리한다.
- 현재 결과는 `paper_runtime_safe=true`, `full_system_complete=false`, `real_execution_authorized=false`다.
- 완료된 operational session 날짜와 같은 날짜의 FINAL·READY 보고서를 교차 검증한다.
- REAL 배치 및 직접 주문 경로는 전체 PAPER 완료 전에 fail-closed한다.

주요 근거:

- `reports/analysis/automated_trading_system_readiness.json`
- `docs/AUTOMATED_TRADING_COMPLETION_MATRIX.md`
- `reports/analysis/PAPER_EXECUTION_EVIDENCE_REPORT_2026-07-22.md`

### 6. scheduler 자동복구

- `run_scheduler.bat`는 PAPER/DRY_RUN/SIMULATE를 bounded supervisor로 실행한다.
- 비정상 종료는 최대 5회, 기본 30초 간격으로 복구한다.
- 안전거부 exit 2는 재시도하지 않는다.
- REAL은 어떤 exit code에서도 자동복구하지 않는다.
- 브로커를 로드하지 않는 무주문 자기진단은 exit `[1, 0]`, 최종 0을 증명했다.
- 현재 실행 중인 PID 2644에는 별도 supervisor를 무중단 연결했다.

주요 파일 및 근거:

- `core/utils/scheduler_supervisor.py`
- `run_scheduler.bat`
- `reports/analysis/scheduler_recovery_evidence.json`
- `logs/paper/scheduler_supervisor.jsonl`

## 방금 적용했지만 최종 완료되지 않은 EOD 연속성 작업

다음 변경은 현재 작업 트리에 적용돼 있다.

1. `scheduler.pending_paper_eod_report_date()`가 operational log의 완료 세션과 유효한 일일 보고서를 비교해 가장 오래된 누락 날짜를 반환한다.
2. `scheduler.due_end_of_day_report_date()`가 PAPER 누락 보고서를 다음 날이나 휴장일에도 찾을 수 있게 했다.
3. `should_attempt_daily_report()`를 고쳐 과거 날짜 백필 실패 시 10초 무한 재시도 대신 5분 제한을 유지한다.
4. `run_end_of_day_report()`가 stdout/stderr를 폐기하지 않고 `logs/<mode>/eod_report_status.json`에 READY/FAILED, return code, redacted tail을 기록한다.
5. API overview가 `eod_report_status`를 노출하고 해당 날짜 실패를 리포트 freshness FAILED로 표시할 준비를 했다.
6. `_publish_latest_if_not_older()`를 추가해 과거 날짜 백필이 canonical `latest.json`을 과거로 되돌리지 못하게 했다.

이 변경 이후 확인한 결과:

```text
59 passed
tests/test_trading_safety.py
tests/test_trading_performance.py
tests/test_dashboard_api.py
compileall 성공
git diff --check 오류 없음
```

## 다음 에이전트가 가장 먼저 마무리할 항목

### P0. BLOCKED EOD가 성공으로 종료되는 문제

현재 `core/analytics/trading_performance.py::main()`은 `write_end_of_day_report()`가 반환한 보고서의 `validation.status`가 `BLOCKED`여도 예외가 없으면 exit 0을 반환한다.

결과:

- scheduler는 subprocess exit 0을 보고 `report_run_date`를 완료 처리한다.
- 생성된 daily JSON이 BLOCKED라서 누락 탐지에는 계속 잡히지만, 같은 scheduler 프로세스에서는 `completed_date == report_date` 때문에 재시도하지 않을 수 있다.

권장 수정:

1. `write_end_of_day_report()`는 진단용 daily JSON/Markdown을 먼저 저장한다.
2. PAPER/REAL에서 `report_status != FINAL` 또는 `validation.status != READY`면 저장 후 `RuntimeError`를 발생시킨다.
3. DRY_RUN의 `NOT_APPLICABLE` 규칙은 기존 정책을 유지한다.
4. CLI가 exit 2를 반환하는지 테스트한다.
5. scheduler가 해당 날짜를 완료 처리하지 않고 5분 뒤 재시도하는지 테스트한다.

추천 조건:

```python
if mode.upper() in {"PAPER", "REAL"} and (
    report.get("report_status") != "FINAL"
    or (report.get("validation") or {}).get("status") != "READY"
):
    errors = (report.get("validation") or {}).get("errors") or []
    raise RuntimeError("EOD report is not FINAL/READY: " + "; ".join(errors))
```

발생 위치는 daily/markdown 저장과 필요한 진단 아티팩트 저장 이후가 좋다. 단, BLOCKED 보고서가 `real_readiness.json`을 정상 준비 상태처럼 덮지 않도록 조건을 확인해야 한다.

### P0. freshness가 날짜만 보고 CURRENT로 표시하는 문제

`api/main.py::_report_freshness()`는 최신 날짜가 expected 이상이면 validation 상태와 무관하게 CURRENT를 먼저 선택한다.

권장 수정:

- `latest.report_status == FINAL`
- `latest.validation.status == READY`
- 위 두 조건을 모두 만족할 때만 CURRENT
- 같은 날짜의 보고서가 BLOCKED이고 `eod_report_status.status == FAILED`이면 FAILED
- BLOCKED인데 상태파일이 없어도 INVALID 또는 FAILED 메시지를 반환

이 변경에 대한 API 테스트를 추가한다.

### P1. historical backfill 비퇴행 통합 테스트

현재 `_publish_latest_if_not_older()` 단위 테스트만 있다. 다음 통합 케이스를 추가한다.

1. canonical latest = 2026-07-22 READY
2. 누락 daily = 2026-07-21
3. 7월 21일 백필 실행
4. `daily/2026-07-21.json`은 생성됨
5. `latest.json`은 계속 2026-07-22
6. `real_readiness.json`도 7월 22일 근거에서 과거로 되돌아가지 않음
7. 전체 system readiness는 daily coverage 증가를 반영함

### P1. 전체 회귀 및 프런트 빌드

마무리 후 반드시 실행한다.

```powershell
uv run pytest -q
uv run python -m compileall -q scheduler.py core api apps
Push-Location dashboard
npm run lint
npm run build
Pop-Location
git diff --check
```

마지막 전체 회귀 기준은 EOD 연속성 변경 전 **246 passed**다. 새 테스트가 추가됐으므로 최종 개수는 그보다 커야 정상이다.

### P1. 현재 런타임 불변 확인

전체 테스트 후 다음을 확인한다.

```powershell
Get-CimInstance Win32_Process |
  Where-Object { $_.CommandLine -match 'scheduler\.py|scheduler_supervisor' } |
  Select-Object ProcessId,ParentProcessId,Name,CommandLine

Get-Content logs/scheduler.instance.lock.json -Encoding utf8
Get-Content logs/scheduler.supervisor.instance.lock.json -Encoding utf8
Get-Content logs/paper/scheduler_supervisor.jsonl -Encoding utf8 | Select-Object -Last 5
```

기대값:

- scheduler lock mode PAPER
- supervisor lock mode PAPER
- supervisor가 scheduler lock PID를 감시
- `--dry-run`, `--live` scheduler 없음
- `KIS_ENV`, `ALLOW_LIVE_ORDER` unset

## 장기 누적 후 수행할 작업

### 체결 표본

- BUY 30건, SELL 30건까지 실제 체결 결과를 누적한다.
- 매 EOD `paper_execution_stress/latest/summary.json`이 최신 ledger 주문 수와 일치하는지 검증한다.
- 표본 충족 후 현행 규칙, C_CAP10, C_CAP08을 세 체결 시나리오에서 다시 비교한다.
- 수익률, MDD, 회전율뿐 아니라 Wilson 하한을 반드시 본다.

### shadow

- `logs/paper/shadow_reentry_state.json`의 unique observed sessions가 10이 될 때까지 누적한다.
- `observe_only=true`, `order_permission=DENIED_BY_DESIGN`을 계속 유지한다.
- shadow 후보가 생겨도 실제 목표비중이나 주문으로 연결하지 않는다.

### 60세션 운영 증거

- completed PAPER sessions 60
- 동일 날짜 FINAL·READY daily reports 60
- 데이터 신선도 99.5% 이상
- 위험점검 100%
- 주문정산 100%
- 치명사고 0
- 비용 드래그 1.5% 이하
- MDD -15% 이내
- 비용 차감 벤치마크 초과수익 양수

모든 조건을 충족해도 REAL은 자동 전환하지 않는다. 사용자의 별도 명시적 승인과 기존 이중 잠금이 필요하다.

## 중요 근거 파일

- `reports/analysis/automated_trading_system_readiness.json`
- `reports/analysis/PAPER_EXECUTION_EVIDENCE_REPORT_2026-07-22.md`
- `reports/analysis/paper_system_report/latest.json`
- `reports/analysis/paper_broker_history/latest.json`
- `reports/analysis/paper_ledger_latest/summary.json`
- `reports/analysis/paper_order_result_replay/latest/summary.json`
- `reports/analysis/paper_execution_stress/latest/summary.json`
- `reports/analysis/scheduler_recovery_evidence.json`
- `reports/promotion/paper/latest.json`
- `reports/promotion/paper/daily/2026-07-21.json`
- `docs/AUTOMATED_TRADING_COMPLETION_MATRIX.md`
- `docs/AUTOMATED_TRADING_SYSTEM_DESIGN.md`
- `C:\Users\Playdata\.codex\automations\paper\memory.md`

## 새 에이전트에게 전달할 시작 문구

```text
C:\dev\project\Service_Stock_Analysis에서 작업을 이어가라.
먼저 docs/AGENT_HANDOFF_AUTOMATED_TRADING_2026-07-22.md와
C:\Users\Playdata\.codex\automations\paper\memory.md를 전부 읽고 현재 파일과
프로세스 상태를 직접 재검증하라. PAPER scheduler PID 2644와 supervisor를 중지하거나
재시작하지 말고 REAL/--live/KIS_ENV=real/ALLOW_LIVE_ORDER 변경을 금지한다.
P0인 BLOCKED EOD exit 0 및 freshness 오판부터 fail-closed로 마무리하고 전체 회귀,
dashboard lint/build, 런타임 불변 검증까지 수행하라. 사용자 변경을 보존하라.
```

## 최종 완료 정의

코드와 테스트만 완성됐다고 전체 시스템 완료로 선언하지 않는다. 다음 두 조건이 모두 필요하다.

1. 현재 구현·안전·관제·복구·일일 보고서 경로가 전체 회귀와 실제 PAPER 런타임 증거로 검증됨
2. BUY/SELL 표본, shadow 10세션, PAPER 60세션, FINAL·READY 60건을 포함한 모든 장기 게이트가 실제로 충족됨

현재는 1번을 마무리하는 단계이며 2번은 실제 거래일 경과가 필요한 진행 중 상태다.
