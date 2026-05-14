# Walk-Forward 최적화

> 분류: 최적화 기법 | 관련: [[최적화/Grid_Search_최적화]] · [[투자성향/위험중립형_전략]]
> 성과 기준: [[성과지표/샤프비율]] · [[성과지표/Calmar비율]]

---

## 개념

그리드 서치로 찾은 최적 파라미터는 **과거 데이터에만 잘 맞는 과최적화(Overfitting)** 위험이 있다.
Walk-Forward는 이를 방지하기 위해 학습과 검증을 시간 순서대로 분리한다.

```
[학습 구간] → 최적 파라미터 탐색
                    ↓
            [검증 구간] → 해당 파라미터로 실전 시뮬레이션
                                ↓
                        [다음 학습 구간] → 재최적화
                                            ↓
                                    [다음 검증 구간] → ...
```

미래 데이터를 학습에 사용하지 않으므로 룩어헤드 바이어스가 없다.

---

## 구조 및 파라미터

| 파라미터 | 기본값 | 의미 |
|----------|--------|------|
| `train_months` | 12개월 | 최적 파라미터 탐색 구간 |
| `test_months` | 6개월 | 검증(실전 적용) 구간 |
| `warmup_days` | 150일 | 검증 시작 전 지표 안정화 버퍼 (MA120 기준) |
| `metric` | `sharpe_ratio` | 최적화 기준 지표 |

**Warmup 버퍼가 필요한 이유:**
MA120은 120거래일 데이터가 쌓여야 정상 계산된다.
검증 구간 시작 시점에 지표가 비어있으면 신호 자체가 생성되지 않으므로,
검증 시작일 이전 1.5 × warmup_days 구간을 버퍼로 포함해 백테스트한 뒤 검증 구간 구간만 추출한다.

**학습 구간에서 유효한 score가 없을 때:**
하락장 등 거래가 전혀 발생하지 않는 구간에서는 Sharpe가 정의되지 않는다.
이 경우 직전 윈도우의 최적 파라미터를 재사용한다.

---

## 최적화 대상

```python
param_grid = {"adx_threshold": [15, 20, 25, 30]}
```

`adx_threshold`를 최적화 대상으로 선택한 이유:
- MA 기간(20/60/120)은 추세의 시간 단위를 정의 → 전략 철학이므로 고정
- `adx_threshold`는 "얼마나 강한 추세에서만 진입할 것인가"를 결정 → 시장 환경에 따라 달라짐

---

## 자산 곡선 연결 방식

검증 구간별 자산 곡선을 **연속으로 이어붙여** 전체 Walk-Forward 성과를 계산한다.

```python
# 각 검증 구간을 직전 구간의 마지막 자산가치에서 시작하도록 정규화
normalized  = tv / tv.iloc[0] * multiplier
multiplier  = normalized.iloc[-1]
```

---

## 장점 / 단점

| | 내용 |
|---|---|
| **장점** | 미래 데이터 미사용 → 실전에 가장 가까운 검증 방식 |
| **장점** | 시장 환경 변화에 따라 파라미터가 자동으로 재조정됨 |
| **장점** | 과최적화된 그리드 서치 결과보다 신뢰도 높음 |
| **단점** | 학습 구간이 짧으면 노이즈에 민감한 파라미터가 선택됨 |
| **단점** | 구간 수가 적으면(데이터 부족) 통계적 의미가 약해짐 |
| **단점** | 학습→검증 전환 시점에 파라미터가 갑자기 바뀌어 수익률 불연속 발생 가능 |

---

## 이 시스템에서의 역할

**08번 노트북** — MA정렬 + ADX 4국면 전략의 `adx_threshold` 최적화

```python
from vbt_backtest.optimizer import walk_forward
from vbt_backtest.strategies.combined.ma_regime_strategy import run_backtest

result = walk_forward(
    close, run_backtest,
    param_grid={"adx_threshold": [15, 20, 25, 30]},
    train_months=12,
    test_months=6,
    high=high, low=low,
)
```

→ 관련 구현: `vbt_backtest/optimizer.py::walk_forward()`
