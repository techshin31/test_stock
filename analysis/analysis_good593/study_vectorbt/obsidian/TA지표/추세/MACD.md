# MACD (Moving Average Convergence Divergence)

> 분류: 추세 지표 | 관련 전략: [[투자성향/위험중립형_전략]]

---

## 개념

단기 EMA에서 장기 EMA를 뺀 값이다.
두 이동평균의 **수렴(좁아짐)과 발산(벌어짐)**으로 추세 방향과 강도를 동시에 파악한다.

```
MACD선    = EMA(12) - EMA(26)      ← 빠른 선
시그널선   = MACD선의 EMA(9)        ← 느린 선 (MACD의 평균)
히스토그램 = MACD선 - 시그널선      ← 두 선의 차이
```

---

## 계산 방법

```python
ema_fast    = close.ewm(span=12, adjust=False).mean()
ema_slow    = close.ewm(span=26, adjust=False).mean()
macd_line   = ema_fast - ema_slow
signal_line = macd_line.ewm(span=9, adjust=False).mean()
histogram   = macd_line - signal_line
```

---

## 매매 신호

| 신호 | 조건 | 의미 |
|------|------|------|
| 매수 | MACD선이 시그널선을 **상향** 돌파 | 단기 모멘텀이 장기보다 강해짐 |
| 매도 | MACD선이 시그널선을 **하향** 돌파 | 단기 모멘텀이 장기보다 약해짐 |

```python
entries = (macd > signal) & (macd.shift(1) <= signal.shift(1))
exits   = (macd < signal) & (macd.shift(1) >= signal.shift(1))
```

---

## 장점 / 단점

| | 내용 |
|---|------|
| **장점** | 추세 방향과 강도를 하나의 지표로 파악 가능 |
| **장점** | 히스토그램으로 모멘텀 변화를 시각적으로 확인 |
| **장점** | MA보다 빠르게 반응 (EMA 기반) |
| **단점** | 후행성 존재 — EMA 평균의 평균이라 신호가 늦음 |
| **단점** | 횡보장에서 잦은 교차 → 오신호 반복 |
| **단점** | 파라미터(12/26/9)가 고정적 — 시장 상황에 따라 최적값이 다름 |

---

## 이 시스템에서의 역할

현재 메인 전략(위험중립형·적극투자형)에서 **직접 사용하지 않는다.**

MA + ADX 조합이 국면 판별과 추세 확인을 이미 담당하고 있어,
MACD를 추가하면 신호가 중복되고 복잡도만 증가한다.

보조 지표로 구현되어 있으며, 향후 전략 고도화 시 활용 가능하다.
