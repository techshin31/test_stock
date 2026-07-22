# PAPER 자동매매 잔여 작업 일괄 전달서

기준 시각: 2026-07-22 14:46 KST  
프로젝트: `C:\dev\project\Service_Stock_Analysis`

## 판정

코드 수정과 새 scheduler 런타임 적용은 완료됐다. 지금 남은 것은 다음 세 묶음뿐이다.

1. 2026-07-22 실제 장 마감 EOD 통합 증거 확인
2. dirty worktree의 자동매매 변경 전달 manifest 작성
3. 실제 체결·shadow·60세션 장기 증거 누적과 재평가

전체 시스템은 아직 완료가 아니다. 현재 직접 재감사 결과:

- `paper_runtime_safe=true`
- 안전검사 12/12
- 완료 근거 10/14
- `full_system_complete=false`
- `real_execution_authorized=false`
- BUY 5/30
- SELL 4/30
- shadow 1/10
- PAPER 완료 세션 1/60
- FINAL·READY 일일 보고서 1/60

## 이미 완료됐으므로 다시 하지 말 것

- PAPER/REAL EOD가 FINAL·READY가 아니면 daily 진단을 저장하고 exit 2 처리
- BLOCKED EOD를 대시보드 CURRENT로 오판하지 않도록 FINAL+READY 검증
- 과거 백필이 canonical latest와 real_readiness를 과거로 되돌리지 않게 처리
- 누락 PAPER EOD 세션 탐지와 5분 제한 재시도
- EOD stdout/stderr redaction 및 상태 JSON 기록 구현
- bounded scheduler supervisor 구현
- 새 scheduler 런타임 적용
- 5억원 주문·손익 원장 복원
- 주문결과 리플레이와 체결 스트레스 실험
- 한글 종목명 주표기
- REAL 사전 게이트 차단

검증 완료 상태:

```text
255 pytest passed
compileall passed
dashboard lint passed
dashboard build passed
uv lock --check passed
git diff --check passed
```

## 현재 런타임

2026-07-22 14:42 KST에 새 코드로 PAPER 런타임이 적용됐다.

| 역할 | PID | 모드/상태 |
|---|---:|---|
| supervisor lock owner | 23448 | PAPER, managed child launch |
| scheduler lock owner | 20796 | PAPER |
| DRY_RUN scheduler | 없음 | 정상 |
| REAL scheduler | 없음 | 정상 |

최근 operational log:

- 상태 NORMAL
- 시장데이터 52/52 최신
- 보유 위험점검 4/4
- 당일 execution ledger READY
- 미종결 주문 0
- last_error 없음

현재 `logs/paper/eod_report_status.json`이 없는 것은 15:30 이전이라 아직 실패로 판정하지 않는다. 현재 프로세스를 다시 재시작하지 않는다.

## P0: 오늘 실제 EOD 통합 증거 확인

### 실행 시점

2026-07-22 15:40 KST 이후 확인한다. scheduler가 15:30부터 생성하고 실패하면 5분 간격으로 재시도할 시간을 준다.

### 필수 확인

1. `logs/paper/eod_report_status.json` 존재
2. `mode=PAPER`, `report_date=2026-07-22`, `status=READY`, `return_code=0`
3. `reports/promotion/paper/daily/2026-07-22.json` 존재
4. daily JSON이 `FINAL`·`READY`, 운영률 네 항목 1.0, 미종결 주문 0
5. `reports/promotion/paper/latest.json`의 날짜가 2026-07-22
6. `reports/analysis/automated_trading_system_readiness.json` 재생성
7. `reports/analysis/paper_system_report/latest.json` 재생성
8. 날짜별 정식 분석 아티팩트 생성
9. scheduler와 supervisor가 계속 PAPER로 살아 있음
10. DRY_RUN/REAL 프로세스 0, REAL 환경변수 unset

### 실패 시 처리

- 전략·위험한도·주문 규칙을 바꾸지 않는다.
- `eod_report_status.json`의 redacted tail과 `logs/paper/scheduler.log`를 확인한다.
- BLOCKED daily 보고서는 진단 증거로 보존한다.
- scheduler가 해당 날짜를 성공 처리하지 않고 5분 뒤 재시도하는지 확인한다.
- 실패 원인만 수정하고 PAPER scheduler를 반복 재시작하지 않는다.
- FINAL+READY가 될 때까지 전체 완료를 주장하지 않는다.

### 완료 증거

다음을 기술 보고서와 이 문서에 추가한다.

- 실제 EOD 완료 시각
- status JSON 결과
- daily/latest/report artifact 날짜
- 재시도 발생 여부
- 최신 준비도 숫자
- scheduler/supervisor PID와 모드

## P1: 변경 전달 manifest 작성

현재 worktree에는 사용자 변경, 자동매매 소스, 테스트, 생성 보고서가 함께 있다. 전체를 일괄 커밋하거나 되돌리면 안 된다.

`docs/AUTOMATED_TRADING_CHANGE_MANIFEST_2026-07-22.md`를 만들고 다음으로 분류한다.

1. 자동매매 핵심 소스 변경
2. 신규 테스트
3. API/대시보드 변경
4. 운영 스크립트
5. 분석 근거 및 생성 보고서
6. 사용자 기존 변경 또는 출처 불명 파일
7. Git 추적 여부
8. 각 파일의 검증 명령과 결과

manifest에는 삭제·되돌림·커밋을 수행하지 않았음을 명시한다. Git 커밋이 필요하면 자동매매 관련 파일 목록을 사용자에게 먼저 제시하고 별도 승인을 받는다.

## P2: 장기 증거 자동 누적

### 매 거래일

- PAPER scheduler 및 supervisor 생존 확인
- 데이터 신선도와 보유 위험점검 100%
- 미종결 주문 0
- execution ledger 연결률·수량 일치율 100%
- 브로커 감사 미해결 0
- 날짜별 FINAL·READY EOD 보고서 존재
- 시스템 준비도와 정식 분석 리포트 갱신
- shadow가 observe-only인지 확인

### 절대 조작 금지

- 테스트 데이터로 BUY/SELL 표본을 채우지 않는다.
- observed_sessions나 daily report 파일을 수동 생성해 10/60 조건을 채우지 않는다.
- 60일을 달력 일수로 대신 계산하지 않는다.
- R_TREND_REARM을 주문 경로에 연결하지 않는다.
- C_CAP10/C_CAP08을 조기 적용하지 않는다.

### 표본 충족 후

BUY/SELL 각 30건을 충족하면 현행 규칙, C_CAP10, C_CAP08을 이상적 체결·관측 사후평균·Wilson 95% 하한에서 다시 비교한다.

판정 기준:

- 수익률
- 최대낙폭
- 연환산 회전율
- 비용 드래그
- 벤치마크 초과수익
- 체결 시나리오 전체 통과

표본 통과는 전략 자동 적용 권한이 아니다. 별도 사용자 승인이 필요하다.

## 최종 완료 조건

- BUY 30건 이상
- SELL 30건 이상
- shadow 10개 고유 세션 이상
- PAPER 완료 세션 60개 이상
- 해당 세션과 일치하는 FINAL·READY 보고서 60개 이상
- 운영 무결성 목표 통과
- 비용 차감 벤치마크 초과수익 양수
- MDD -15% 이내
- 비용 드래그 1.5% 이하
- 치명 운영사고 0
- 브로커 감사와 주문결과 패리티 유지
- 전체 회귀 테스트 통과

이 조건을 모두 만족해도 REAL은 자동 승인하지 않는다. 사용자의 별도 명시적 승인과 기존 이중 잠금이 필요하다.

## 검증 명령

```powershell
uv run pytest -q
uv run python -m compileall -q scheduler.py core api apps
uv lock --check

Push-Location dashboard
npm run lint
npm run build
Pop-Location

git diff --check
```

프로세스 확인:

```powershell
Get-CimInstance Win32_Process |
  Where-Object { $_.CommandLine -match 'scheduler\.py|scheduler_supervisor' } |
  Select-Object ProcessId,ParentProcessId,CreationDate,Name,CommandLine

Get-Content logs/scheduler.instance.lock.json -Encoding utf8
Get-Content logs/scheduler.supervisor.instance.lock.json -Encoding utf8
Get-Content logs/paper/scheduler_supervisor.jsonl -Encoding utf8 | Select-Object -Last 10
```

## 다른 에이전트에게 그대로 전달할 요청

```text
C:\dev\project\Service_Stock_Analysis에서
docs/REMAINING_WORK_PACKET_2026-07-22.md를 전부 읽고 그 문서의 P0→P1→P2 순서로 작업하라.

완료된 코드 수정을 반복하지 말고, 2026-07-22 15:40 KST 이후 실제 PAPER EOD
통합 증거부터 확인하라. 현재 PAPER scheduler PID 20796과 supervisor PID 23448을
다시 재시작하거나 중지하지 마라. 실패하면 전략을 바꾸지 말고 redacted EOD 상태와
scheduler 로그를 근거로 원인만 수정해 5분 재시도 경로를 검증하라.

그 다음 dirty worktree를 사용자 변경·자동매매 소스·테스트·생성 보고서로 분류한
docs/AUTOMATED_TRADING_CHANGE_MANIFEST_2026-07-22.md를 작성하라. 삭제, reset,
checkout, 전체 일괄 커밋은 금지한다.

BUY/SELL 30건, shadow 10세션, PAPER 60세션, FINAL/READY 60건은 실제 운영으로만
누적하라. 파일 수동 편집이나 테스트 데이터로 채우지 마라. 모든 장기 게이트 전까지
full_system_complete=false와 real_execution_authorized=false를 유지하고 REAL/--live/
KIS_ENV=real/ALLOW_LIVE_ORDER 변경을 금지한다.

각 단계마다 문서에 정의된 완료 증거와 전체 테스트 결과를 보고하라.
```
