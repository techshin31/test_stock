# 자동매매 변경 전달 Manifest

작성 시각: 2026-07-22 KST  
프로젝트: `C:\dev\project\Service_Stock_Analysis`  
목적: 작업 트리의 변경 사항을 안전하게 보존하고, 사용자 파일과 자동매매 관련 코드를 명확히 분류하여 전달한다.

> [!IMPORTANT]
> **보존 정책**: `git reset --hard`, `git checkout --`, 파일 일괄 삭제, 전체 worktree 일괄 커밋을 수행하지 않는다. 사용자의 기존 변경 및 불명 파일은 원본 그대로 보존한다.

---

## 1. 런타임 종료 및 복구 이력 (2026-07-22 15:05 ~ 15:10 KST)

1. **이전 프로세스 종료 원인**: 에이전트 전용 백그라운드 태스크(`task-180`) 취소 과정에서 하위 스케줄러 PID `20796` 및 수퍼바이저 PID `23448` 프로세스 트리가 함께 종료되었습니다.
2. **Stale Lock 오판 결함 발견 및 수정**:
   - 종료 당시 metadata JSON 파일만 남아있었으나, 기존 `system_readiness.py`가 OS lock 보유 여부 및 PID 생존 여부를 검사하지 않아 `safety 12/12`로 잘못 판정하였습니다.
   - `core/utils/process_lock.py`에 비파괴 OS file lock 및 PID liveness 검사 함수 (`is_process_alive`, `is_process_lock_held`)를 추가하였습니다.
   - `core/analytics/system_readiness.py`에서 stale lock(죽은 PID / 미보유 OS lock) 감지 시 `paper_runtime_safe=False`로 즉시 fail-closed 처리하도록 보완했습니다.
3. **공식 경로 런타임 복구**:
   - `Start-Process cmd.exe -ArgumentList '/d /c "set PATH=%PATH%;C:\Users\Playdata\.local\bin && run_scheduler.bat --paper"' -WindowStyle Hidden` 공식 배치 경로로 복구 가동했습니다.
   - **복구된 수퍼바이저 PID**: **`19512`** (`logs/scheduler.supervisor.instance.lock.json`, 15:09:50 KST 획득)
   - **복구된 스케줄러 PID**: **`21112`** (`logs/scheduler.instance.lock.json`, 15:09:53 KST 획득)
   - **60초 생존 확인**: 가동 60초 경과 후에도 수퍼바이저 PID `19512` 및 스케줄러 PID `21112`가 OS lock을 보유한 채 정상 생존함을 확인했습니다.

---

## 2. 자동매매 핵심 소스 변경

| 파일 경로 | 주요 변경 내용 | Git 상태 | 검증 명령 및 결과 |
|---|---|:---:|---|
| `core/utils/process_lock.py` | 비파괴 OS file lock 보유 및 PID 생존 검사 함수 (`is_process_lock_held`, `is_process_alive`) 추가 | 수정됨 (Tracked) | `uv run pytest tests/test_system_readiness.py` (통과) |
| `core/analytics/system_readiness.py` | stale lock 감지 시 `paper_runtime_safe=False` fail-closed 적용 | 수정됨 (Tracked) | `uv run pytest tests/test_system_readiness.py` (통과) |
| `core/analytics/trading_performance.py` | EOD fail-closed exit 2, daily JSON/MD 작성, KOSPI 보정 | 수정됨 (Tracked) | `uv run pytest tests/test_trading_performance.py` (통과) |
| `api/main.py` | Freshness 판단, 시스템 준비도 노출, 한글 종목명 주표기 | 미추적 (Untracked) | `uv run pytest tests/test_dashboard_api.py` (통과) |
| `scheduler.py` | EOD 백필 날짜 탐지, 5분 재시도, exit code 및 status 기록 | 수정됨 (Tracked) | `uv run pytest -q` (통과) |
| `core/utils/scheduler_supervisor.py` | bounded 수퍼바이저 (최대 5회 재시작, exit 2 미재시도) | 미추적 (Untracked) | `uv run pytest tests/test_scheduler_supervisor.py` (통과) |

---

## 3. 신규 및 보완 테스트

| 파일 경로 | 설명 | Git 상태 | 검증 결과 |
|---|---|:---:|---|
| `tests/test_system_readiness.py` | stale lock 감지(`is_process_lock_held`) 및 fail-closed 검증 테스트 추가 (총 15개) | 수정됨 (Tracked) | **15/15 passed** |
| `tests/test_trading_performance.py` | EOD fail-closed exit 2, daily 진단, 백필 비퇴행 테스트 | 수정됨 (Tracked) | 통과 |
| `tests/test_trading_safety.py` | 주문 안전 수량, KIS API 페이지네이션, 멱등성 테스트 | 수정됨 (Tracked) | 통과 |
| `tests/test_dashboard_api.py` | `_report_freshness` (FINAL+READY 요구), 대시보드 API 테스트 | 미추적 (Untracked) | 통과 |
| `tests/test_scheduler_supervisor.py` | 수퍼바이저 자동 복구 및 exit 2 미재시도 테스트 | 미추적 (Untracked) | 통과 |

---

## 4. API 및 대시보드

| 파일 경로 | 설명 | Git 상태 | 검증 명령 및 결과 |
|---|---|:---:|---|
| `api/main.py` | 리포트 Freshness 판단, 시스템 준비도 노출 | 미추적 (Untracked) | `uv run pytest tests/test_dashboard_api.py` (통과) |
| `dashboard/src/App.jsx` | React UI 콘솔 (글래스모피즘, 프로그레스, 마크다운) | 미추적 (Untracked) | `npm run lint` & `npm run build` in dashboard (통과) |
| `dashboard/src/index.css` | 다크 그래디언트 디자인 시스템 CSS | 미추적 (Untracked) | `npm run build` in dashboard (통과) |

---

## 5. scheduler 및 운영 스크립트

| 파일 경로 | 설명 | Git 상태 | 검증 명령 및 결과 |
|---|---|:---:|---|
| `run_scheduler.bat` | PAPER continuation 게이트 및 수퍼바이저 실행 배치 | 수정됨 (Tracked) | 런타임 가동 중 (Supervisor PID 19512 / Scheduler PID 21112) |
| `run_live_trader.py` | 계좌 스냅샷 검증 스크립트 | 수정됨 (Tracked) | `uv run python run_live_trader.py --mock --snapshot-only` (통과) |

---

## 6. 사용자 기존 변경 또는 출처 불명 파일 (원본 보존)

| 파일 경로 | 설명 | Git 상태 | 처분 방침 |
|---|---|:---:|---|
| `.impeccable/`, `DESIGN.md`, `PRODUCT.md` | 사용자 디자인 가이드 문서 | 미추적 (Untracked) | 원본 보존 |
| `all_services.txt`, `service_check.txt`, `tasks.txt` | 사용자 작업 메모 및 서비스 로그 | 미추적 (Untracked) | 원본 보존 |
| `start_dashboard.bat`, `start_dashboard.vbs`, `start_detached.py` | 사용자 대시보드 실행 스크립트 | 미추적 (Untracked) | 원본 보존 |
| `core/signal/news_signal.py`, `core/analytics/sentiment.py` | 뉴스 신호 모듈 | 미추적 (Untracked) | 원본 보존 |
| `core/strategy/aggressive.py` | 사용자 전략 구현 파일 | 수정됨 (Tracked) | 원본 보존 |
| `README.md`, `pyproject.toml`, `uv.lock` | 프로젝트 기본설정 파일 | 수정됨 (Tracked) | 원본 보존 |

---

## 7. 종합 검증 결과

```powershell
uv run pytest -q
# 결과: 전체 pytest 통과

uv run python -m compileall -q scheduler.py core api apps
# 결과: 성공 (오류 0건)

uv lock --check
# 결과: Resolved 178 packages in 1ms

cd dashboard; npm run lint; npm run build
# 결과: oxlint 0 errors, 0 warnings / vite build 성공

git diff --check
# 결과: 줄바꿈/공백 오류 없음 (통과)
```

---

## 8. 최종 준수 선언

- `git reset --hard`, `git checkout --`, 파일 일괄 삭제, 전체 worktree 일괄 커밋을 일체 수행하지 않았습니다.
- 커밋이 필요할 경우 본 manifest의 파일 목록을 사용자에게 제시하고 별도 승인을 받습니다.

---

## 9. 16:14 KST Docker PAPER 런타임 복구 검증

- `Dockerfile.app`에 `/app/data`를 포함해 컨테이너의 KOSPI benchmark loader import 실패를 제거했습니다.
- 스케줄러와 supervisor에 `paper-trader` 실행 namespace 및 5초 heartbeat를 추가했습니다. 컨테이너 내부는 OS PID/lock, Windows 호스트는 30초 이내 heartbeat로 동일한 PAPER 런타임을 검증합니다.
- 기존 `FAILED` EOD 상태가 FINAL/READY 파일에 가려지지 않도록 API 우선순위와 스케줄러 재시도 조건을 수정했습니다.
- 이름이 포함된 position 객체와 기존 ticker 문자열을 모두 출력하도록 스케줄러 콘솔의 position schema 호환성을 보강했습니다.
- 대시보드 핵심 수익률을 인증 기준선 이후 수익률이 아닌 5억원 시작 기준 수익률로 표시하고 두 값을 명시적으로 분리했습니다.
- 2026-07-22 EOD 자동 재시도 결과: `READY`, return code 0, FINAL/READY 일일 리포트 생성 완료.
- 런타임 결과: PAPER safety 12/12, 컨테이너 재시작 0회, 미정산 주문 0건, REAL authorization=false.
- 검증 결과: pytest 266개, dashboard lint/build, `uv lock --check`, `docker compose config --quiet`, `git diff --check` 통과.
