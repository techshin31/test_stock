# FA 배분 통합 역사 리플레이 리포트

- 기간: 2026-01-30 ~ 2026-07-09
- 월별 FA 리플레이: 7개

- 리플레이 상태: {'PASS': 6, 'PUBLISHED': 1}

| 방식 | 누적수익률 | CAGR | 변동성 | Sharpe | MDD | 일평균 회전율 | 누적 비용률 |
|---|---:|---:|---:|---:|---:|---:|---:|
| 동일 비중 | 14.17% | 36.62% | 46.31% | 0.907 | -21.50% | 10.439% | 2.21% |
| FA 직접 비례 | 15.49% | 40.39% | 46.01% | 0.969 | -20.30% | 10.176% | 2.15% |
| FA 초과점수 비례 | 21.11% | 57.01% | 45.76% | 1.216 | -16.99% | 9.525% | 2.01% |

## 결론

통합 리플레이 기준 Sharpe 최상 방식은 **FA 초과점수 비례**입니다.
초기 데이터 구간의 WARNING 비중이 높으므로 운영 배분 공식 변경 전 PASS 구간 단독 결과도 함께 확인해야 합니다.

## 한계
- Historical replay runs are research PASS/WARNING records, not retroactively PUBLISHED production records.
- Execution uses daily closes and proportional weights rather than share-level fills.
