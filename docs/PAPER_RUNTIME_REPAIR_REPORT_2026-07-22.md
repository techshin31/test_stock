# PAPER 런타임 복구 결과 보고서

- 검증 시각: 2026-07-22 16:14 KST
- 범위: Docker PAPER scheduler, EOD 보고서, readiness, 대시보드 손익 표시
- 안전 범위: `KIS_ENV=paper`, `ALLOW_LIVE_ORDER=false`, REAL 실행 권한 없음

## 결론

자동 EOD의 Docker 의존성 누락과 보고서 상태 모순을 복구했습니다. 새 PAPER 컨테이너는 EOD 실패 상태를 자동 감지해 2026-07-22 보고서를 다시 생성했고, 최종 상태는 `READY`/return code 0입니다. 컨테이너 내부와 Windows 호스트의 readiness는 모두 PAPER safety 12/12로 일치합니다.

## 해결한 결함

1. `/app/data` 누락으로 발생한 `No module named 'data'` EOD 실패
2. FINAL/READY 파일이 자동 EOD 실패 상태를 가리던 API 우선순위
3. 유효한 일일 파일이 있으면 FAILED EOD를 재시도하지 않던 scheduler 조건
4. Docker PID를 Windows PID로 검사하던 readiness namespace 불일치
5. position 객체를 문자열로 join하던 scheduler 콘솔 오류
6. 인증 기준선 이후 `+0.73%`를 전체 누적수익률처럼 표시하던 대시보드 표현
7. 중요 사고가 있어도 최신 EOD 운영 증거가 통과하던 completion gate

## 현재 계좌 및 증거

| 항목 | 결과 |
|---|---:|
| 총 평가자산 | 466,399,046원 |
| 5억원 대비 손익 | -33,600,954원 |
| 5억원 대비 수익률 | -6.7202% |
| 2026-07-20 인증 기준선 이후 | +0.7286% |
| 같은 기간 KOSPI | +4.3189% |
| 초과수익률 | -3.5903%p |
| EOD | READY / return code 0 |
| PAPER 안전성 | 12/12 |
| REAL 실행 권한 | false |

## 아직 통과하지 못한 운영 증거

- 중요 상태 에피소드 9건: ORDER_RECONCILIATION, ENTRY_CIRCUIT_BREAKER, AMBIGUOUS_RESULT_SAME_DAY 주문 억제 포함
- BUY/SELL 실행 표본 각 5/30
- shadow 관찰 1/10 세션
- PAPER 완료 세션 2/60
- FINAL/READY 일일 리포트 2/60
- execution stress 전체 시나리오 미통과

이 항목들은 임의 생성하거나 과거 데이터를 조작해서 채우지 않습니다. PAPER 운영을 유지하면서 실제 거래일과 실제 주문 결과로만 누적해야 합니다.

## 검증 명령

```powershell
uv run pytest -q -p no:cacheprovider
npm run lint
npm run build
uv lock --check
docker compose config --quiet
docker compose ps
```

결과: pytest 266개 통과, dashboard lint/build 통과, lock/compose 검증 통과, PAPER trader/API/dashboard/PostgreSQL 실행 중.
