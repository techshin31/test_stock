# Grid Search 최적화

> 분류: 최적화 기법 | 관련: [[최적화/Walk_Forward_최적화]] · [[투자성향/위험중립형_전략]]
> 성과 기준: [[성과지표/샤프비율]] · [[성과지표/MDD]] · [[성과지표/승률]]

---

## 개념

파라미터 후보를 **모든 조합으로 전수 탐색**해 가장 좋은 성과를 낸 파라미터를 찾는다.

```
fast_window: [5, 10, 20]
slow_window: [60, 90]
→ 3 × 2 = 6가지 조합을 모두 백테스트 → 최고 Sharpe 파라미터 선택
```

단순하고 직관적이지만, 과거 데이터 전체에 맞춰 최적화하므로
**과최적화(Overfitting) 위험**이 있다.
실전 적용 전 반드시 [[최적화/Walk_Forward_최적화]]로 검증해야 한다.

---

## 계산 방법

```python
import itertools

keys   = list(param_grid.keys())
values = list(param_grid.values())

for combo in itertools.product(*values):
    params = dict(zip(keys, combo))
    pf = strategy_fn(close, **params, fees=fees)
    # total_return, sharpe_ratio, max_drawdown, win_rate, trade_count 기록
```

조합 수 = 각 파라미터 후보 수의 곱
→ 파라미터 수가 늘어날수록 탐색 시간이 지수적으로 증가한다.

---

## 출력 결과

| 컬럼 | 의미 |
|------|------|
| 파라미터 컬럼들 | 해당 조합의 파라미터 값 |
| `total_return` | 전체 수익률 |
| `sharpe_ratio` | 위험 조정 수익률 → [[성과지표/샤프비율]] |
| `max_drawdown` | 최대 낙폭 → [[성과지표/MDD]] |
| `win_rate` | 수익 거래 비율 → [[성과지표/승률]] |
| `trade_count` | 총 거래 횟수 |

결과는 `sharpe_ratio` 내림차순으로 정렬된다.

---

## 장점 / 단점

| | 내용 |
|---|---|
| **장점** | 구현이 단순하고 모든 조합을 빠짐없이 탐색 |
| **장점** | 파라미터 민감도(히트맵 시각화)를 파악하기 쉬움 |
| **단점** | 과거 데이터 전체에 최적화 → 미래 성과 보장 없음 (과최적화) |
| **단점** | 파라미터가 많아질수록 조합 수가 폭발적으로 증가 |
| **단점** | 예외 발생 시 해당 조합을 무시하고 넘어가므로 결과가 일부 누락될 수 있음 |

---

## 이 시스템에서의 역할

Walk-Forward 내부에서 **학습 구간의 최적 파라미터 탐색**에 사용된다.
단독으로 쓰면 과최적화 위험이 있으므로, 반드시 Walk-Forward와 함께 사용한다.

```
Grid Search (학습 구간) → 최적 파라미터 선택
                               ↓
                    Walk-Forward (검증 구간) → 실전 성과 측정
```

→ 관련 구현: `vbt_backtest/optimizer.py::grid_search()`
