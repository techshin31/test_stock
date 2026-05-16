# Calmar개선 · Calmar 개선율 (vs 벤치마크)

> 분류: 성과지표 | 관련: [[성과지표/Calmar비율]] · [[성과지표/MDD감소율]] · [[성과지표/Alpha]]

---

## 개념

전략의 Calmar 비율이 벤치마크 대비 **얼마나 향상됐는지**를 절대 차이로 나타낸다.
수익과 손실 효율을 동시에 개선했는지 확인하는 종합 지표다.

```
Calmar개선 = 전략 Calmar − 벤치마크 Calmar

전략 Calmar 0.6, KOSPI Calmar 0.3 → 개선 = +0.3  (우수)
전략 Calmar 0.3, KOSPI Calmar 0.3 → 개선 = 0.0   (동일)
전략 Calmar 0.2, KOSPI Calmar 0.3 → 개선 = −0.1  (악화)
```

---

## 계산 방법

```python
# stock_system/backtest/metrics/calc.py
eq_calmar = eq_cagr / abs(eq_mdd) if eq_mdd < 0 else np.nan
bm_calmar = bm_cagr / abs(bm_mdd) if bm_mdd < 0 else np.nan
calmar_improvement = (
    eq_calmar - bm_calmar
    if not (np.isnan(eq_calmar) or np.isnan(bm_calmar))
    else np.nan
)
```

---

## 해석 기준

| Calmar개선 | 의미 |
|-----------|------|
| > +0.3 | 우수한 효율 개선 |
| +0.1 ~ +0.3 | 유의미한 개선 |
| 0 ~ +0.1 | 소폭 개선 |
| < 0 | 벤치마크보다 효율이 낮음 → 전략의 복잡성 정당화 불가 |

---

## 장점 / 단점

| | 내용 |
|---|---|
| **장점** | CAGR 향상과 MDD 감소를 동시에 반영하는 종합 효율 지표 |
| **장점** | Alpha(수익)와 MDD감소율(손실)을 Calmar 하나로 압축해 비교 |
| **단단점** | 벤치마크 Calmar가 극단값(매우 높거나 낮을 때) 해석 주의 필요 |

---

## 투자성향별 적용

| 성향 | 기준선 | 기준 | 비고 |
|------|--------|------|------|
| **위험중립형** | KOSPI | **+0.1 목표 / 0.0 경보** | CAGR은 낮아도 MDD를 크게 줄이면 개선 가능 |
| **적극투자형** | B&H | **+0.3 목표 / +0.1 경보** | B&H보다 수익↑ + MDD↓ 모두 달성해야 의미 있음 |

---

## 이 시스템에서의 역할

`stock_system/backtest/metrics/calc.py::calc_metrics()`에서 KOSPI 대비 상대 지표로 산출된다.
위험중립형에서는 KOSPI 대비, 적극투자형에서는 B&H 대비로 해석 기준이 달라진다.
