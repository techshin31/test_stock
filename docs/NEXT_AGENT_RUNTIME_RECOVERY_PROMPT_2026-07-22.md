# 다음 에이전트 작업 프롬프트: PAPER 런타임 복구와 stale-lock 오판 수정

기준 시각: 2026-07-22 15:06 KST  
프로젝트: `C:\dev\project\Service_Stock_Analysis`

## 복사해서 전달할 프롬프트

```text
C:\dev\project\Service_Stock_Analysis에서 PAPER 자동매매 시스템을 즉시 복구하고
런타임 안전 오판을 수정하라.

먼저 다음 문서를 전부 읽어라.

1. docs/NEXT_AGENT_RUNTIME_RECOVERY_PROMPT_2026-07-22.md
2. docs/REMAINING_WORK_PACKET_2026-07-22.md
3. docs/AUTOMATED_TRADING_CHANGE_MANIFEST_2026-07-22.md
4. docs/AGENT_HANDOFF_AUTOMATED_TRADING_2026-07-22.md
5. C:\Users\Playdata\.codex\automations\paper\memory.md

현재 완료 주장을 신뢰하지 말고 아래 직접 관측값에서 시작하라.

- 2026-07-22 15:05 KST 기준 scheduler PID 20796은 종료됨
- supervisor PID 23448도 종료됨
- 관련 scheduler/supervisor 프로세스는 실제로 0개
- logs/scheduler.instance.lock.json과
  logs/scheduler.supervisor.instance.lock.json만 stale 상태로 남아 있음
- dashboard_state와 operational log의 마지막 갱신은 약 15:04
- logs/paper/eod_report_status.json 없음
- reports/promotion/paper/daily/2026-07-22.json 없음
- 그런데 audit_system_readiness는 stale JSON만 믿고 paper_runtime_safe=true,
  safety 12/12를 반환함
- 이 상태는 명백한 런타임 안전 오판임
- 코드 회귀 테스트 255개, dashboard lint/build는 통과하지만 실제 운영은 중단 상태임

[절대 금지]

- --live 실행
- KIS_ENV=real 설정
- ALLOW_LIVE_ORDER=true 설정
- REAL scheduler 시작
- DRY_RUN으로 모드 변경
- 테스트 데이터나 수동 JSON으로 세션/체결 증거 조작
- 전략·위험한도 변경
- git reset --hard, git checkout --, 일괄 삭제
- stale lock JSON을 단순 삭제한 뒤 정상이라고 주장
- 프로세스가 없는데 테스트 통과만으로 완료 선언

[P0-1: PAPER 런타임 즉시 복구]

1. Win32_Process와 Get-Process로 scheduler/supervisor가 실제 0개인지 다시 확인한다.
2. dashboard의 open order가 0이고 최근 execution ledger가 READY인지 확인한다.
3. 현재 프로세스가 0개일 때만 다음 공식 배치 경로를 숨김 창으로 정확히 한 번 시작한다.

   Start-Process를 사용해 cmd.exe /d /c run_scheduler.bat --paper를
   C:\dev\project\Service_Stock_Analysis 작업 디렉터리에서 WindowStyle Hidden으로 실행한다.

4. direct `uv run ...scheduler_supervisor` 임시 실행 대신 run_scheduler.bat 경로를 사용한다.
5. 10초 후 다음을 확인한다.
   - supervisor 프로세스 정확히 1개 체인
   - scheduler 프로세스 정확히 1개 체인
   - scheduler lock 실제 PID가 살아 있음
   - supervisor lock 실제 PID가 살아 있음
   - 두 metadata mode=PAPER
   - scheduler_supervisor.jsonl에 새 SUPERVISOR_STARTED 이벤트
   - dashboard와 operational log가 다시 갱신
   - open order 0
6. 최소 60초 뒤 한 번 더 확인해 에이전트의 실행 셸 종료와 함께 프로세스가 죽지 않는지 증명한다.
7. 중복 프로세스가 생기면 추가 실행하지 말고 원인을 조사한다.

[P0-2: stale lock을 안전으로 오판하는 결함 수정]

현재 `core/analytics/system_readiness.py`는 lock JSON의 pid/mode/label만 검사한다.
실제 프로세스와 OS file lock이 없는 stale metadata도 통과하므로 수정하라.

권장 구현:

1. `core/utils/process_lock.py`에 실제 lock 보유 여부를 비파괴적으로 검사하는
   `is_process_lock_held(path: Path) -> bool`를 추가한다.
2. 파일이 없으면 false다.
3. 파일을 `r+b`로 열고 Windows에서는 msvcrt 비차단 lock, Unix에서는 fcntl
   LOCK_EX|LOCK_NB를 시도한다.
4. lock 시도가 충돌하면 다른 프로세스가 실제 보유 중이므로 true다.
5. lock 획득에 성공하면 즉시 unlock하고 false를 반환한다.
6. metadata 파일을 생성·수정·삭제하지 않는다.
7. 가능하면 metadata PID의 process liveness도 함께 확인한다.
8. `scheduler_instance_scope`는 다음을 모두 요구한다.
   - mode=PAPER
   - label=scheduler
   - 유효한 pid
   - scheduler.instance.lock이 실제 보유 중
   - metadata PID가 실제 생존
9. `scheduler_supervisor_runtime`도 같은 방식으로 supervisor lock과 PID 생존을 요구한다.
10. stale lock일 때 `paper_runtime_safe=false`가 돼야 한다.

테스트 요구사항:

- 실제 ProcessInstanceLock을 획득한 동안 true
- release 후 false
- JSON metadata만 있고 OS lock이 없으면 false
- scheduler stale lock이면 readiness 실패
- supervisor stale lock이면 readiness 실패
- PID가 죽었거나 재사용된 경우 실패
- 정상 PAPER 두 lock은 통과
- REAL mode metadata는 계속 실패

테스트에서 운영 lock을 건드리지 말고 tmp_path를 사용하라. 기존 readiness 테스트에는
lock checker 주입 또는 실제 tmp lock fixture를 사용해 의미를 보존하라.

[P0-3: 2026-07-22 실제 EOD 완료]

현재 시각이 15:40 KST 이전이면 복구된 PAPER 프로세스를 유지한 채 기다린다.
15:40 이후 다음을 확인한다.

1. logs/paper/eod_report_status.json
   - mode=PAPER
   - report_date=2026-07-22
   - status=READY
   - return_code=0
2. reports/promotion/paper/daily/2026-07-22.json
   - report_status=FINAL
   - validation.status=READY
   - 운영률 네 항목 모두 1.0
   - open_order_count=0
3. reports/promotion/paper/latest.json 날짜 2026-07-22
4. automated_trading_system_readiness.json 재생성
5. paper_system_report/latest.json과 daily/2026-07-22.json 재생성
6. ledger, broker audit, parity, execution stress 최신화

실패하면 redacted EOD status와 scheduler.log를 근거로 원인만 수정하고, 5분 재시도가
실제로 발생하는지 확인한다. 전략이나 주문 규칙은 바꾸지 않는다.

[P1: manifest와 보고서 정정]

docs/AUTOMATED_TRADING_CHANGE_MANIFEST_2026-07-22.md에 다음을 반영한다.

- 14:42에 시작한 supervisor/scheduler가 15:05 전에 모두 종료됐던 사실
- stale lock JSON 때문에 readiness가 12/12로 오판한 사실
- 복구한 새 PID, 시작 시각, 60초 생존 확인
- stale-lock 감지 테스트와 전체 테스트 결과
- 실제 7월 22일 EOD 결과

기존 문서의 “런타임 실행 중” 주장을 실제 상태와 일치하도록 고친다.

[P2: 장기 증거]

복구와 EOD가 완료돼도 전체 시스템은 완료가 아니다. 실제 운영으로만 누적한다.

- BUY 최소 30건
- SELL 최소 30건
- shadow 고유 세션 10개
- PAPER 완료 세션 60개
- 같은 날짜 FINAL·READY 보고서 60개

수동 파일 편집이나 테스트 데이터로 채우지 않는다. 표본 충족 전에는
R_TREND_REARM, C_CAP10, C_CAP08을 실제 주문 규칙에 적용하지 않는다.

[최종 검증]

uv run pytest -q
uv run python -m compileall -q scheduler.py core api apps
uv lock --check
dashboard에서 npm run lint 및 npm run build
git diff --check

마지막 보고에는 반드시 포함한다.

1. 종료 원인 또는 확인 가능한 종료 정황
2. 복구한 scheduler/supervisor 실제 PID와 명령행
3. OS lock 실제 보유 검증 결과
4. 60초 이상 생존 증거
5. 최신 dashboard/operational timestamp
6. 7월 22일 EOD 상태와 보고서 경로
7. stale-lock 상태에서 readiness=false 재현 결과
8. 정상 lock 상태에서 readiness safety 결과
9. 전체 테스트 결과
10. 남은 실제 장기 게이트 숫자

프로세스와 OS lock이 실제로 살아 있고 EOD가 FINAL·READY가 되기 전에는 완료라고
말하지 마라. REAL은 계속 금지한다.
```

## 현재 감사 근거

- `Get-Process`에서 PID 20796, 23448, 관련 부모 PID 모두 미존재
- Win32_Process에서 scheduler/supervisor 명령행 0건
- lock metadata JSON은 두 개 모두 존재
- `audit_system_readiness()`는 이 상태에서도 safety 12/12를 잘못 반환
- EOD status 및 2026-07-22 daily report 미존재
- 전체 코드 테스트는 255 passed

따라서 다음 작업의 최우선 목표는 테스트 추가가 아니라 PAPER 런타임 복구와 stale-lock fail-closed 판정이다.
