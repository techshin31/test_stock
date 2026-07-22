# FA 배분 통합 역사 리플레이 리포트

- 기간: 2023-05-31 ~ 2026-07-09
- 월별 FA 리플레이: 39개

- 리플레이 상태: {'WARNING': 32, 'PASS': 6, 'PUBLISHED': 1}

| 방식 | 누적수익률 | CAGR | 변동성 | Sharpe | MDD | 일평균 회전율 | 누적 비용률 |
|---|---:|---:|---:|---:|---:|---:|---:|
| 동일 비중 | 56.34% | 16.04% | 24.43% | 0.732 | -25.63% | 7.124% | 10.98% |
| FA 직접 비례 | 57.88% | 16.42% | 24.42% | 0.745 | -24.87% | 7.146% | 11.01% |
| FA 초과점수 비례 | 65.92% | 18.36% | 25.29% | 0.793 | -23.27% | 7.423% | 11.45% |

## 결론

통합 리플레이 기준 Sharpe 최상 방식은 **FA 초과점수 비례**입니다.
초기 데이터 구간의 WARNING 비중이 높으므로 운영 배분 공식 변경 전 PASS 구간 단독 결과도 함께 확인해야 합니다.

## 한계
- Historical replay runs are research PASS/WARNING records, not retroactively PUBLISHED production records.
- Execution uses daily closes and proportional weights rather than share-level fills.
