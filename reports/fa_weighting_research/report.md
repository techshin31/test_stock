# FA 비중 배분 비교 연구 리포트

Generated: 2026-07-13T11:17:35

## 성과 비교

| 배분 방식 | 개월 | 누적수익률 | CAGR | 변동성 | Sharpe | MDD | 월평균 회전율 | 누적 비용률 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 동일 비중 | 38 | 134.89% | 30.95% | 21.44% | 1.371 | -13.03% | 37.89% | 2.87% |
| FA 점수 직접 비례 | 38 | 133.54% | 30.72% | 21.41% | 1.365 | -12.96% | 38.01% | 2.88% |
| FA 50점 초과분 비례 | 38 | 130.13% | 30.11% | 21.37% | 1.345 | -12.87% | 38.38% | 2.91% |

## 결론 및 권고

이 배분 방식 단독 비교에서 무위험수익률 0 기준 Sharpe가 가장 높은 방식은 **동일 비중**입니다.
FA 직접 비례 방식은 동일 비중보다 누적수익률과 Sharpe가 소폭 낮았습니다. 현재 결과만으로 FA 비례 배분을 최종 운영안으로 확정하지 않는 것이 좋습니다.
향후 PUBLISHED FA 발행 이력이 충분히 쌓이면 실제 섹터 선택과 TA 진입 시점을 함께 재현해 다시 검증해야 합니다.

## 방법론과 한계

- monthly point-in-time latest eligible FA scores; top 10 by FA score
- FA 점수 기간: 2023-05-02 ~ 2026-07-02
- 가격 기간: 2023-01-02 ~ 2026-07-09
- Only two PUBLISHED aggressive FA runs exist, so historical candidates are reconstructed from point-in-time quarterly FA scores.
- Sector selection and live TA entry timing are not replayed; this isolates allocation-method effects.
- Monthly close-to-close returns and approximate transaction costs are used.
