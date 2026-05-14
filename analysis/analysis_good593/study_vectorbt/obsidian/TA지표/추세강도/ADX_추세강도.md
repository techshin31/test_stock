# ADX · 평균 방향성 지수 (Average Directional Index)

> 분류: 추세강도 지표 | 관련 전략: [[투자성향/위험중립형_전략]] · [[투자성향/적극투자형_전략]]
> 관련 지표: [[TA지표/변동성/ATR_평균진폭]] (ADX 계산 과정에서 ATR을 공유)

---

## 개념

추세의 **강도(0~100)**만 측정한다. 방향(상승/하락)은 알려주지 않는다.

```
ADX 0~20   → 추세 없음 (횡보)
ADX 20~25  → 약한 추세
ADX 25 이상 → 추세 확인됨
ADX 40 이상 → 강한 추세
```

ADX 단독으로는 매수·매도를 결정할 수 없다.
반드시 **방향 지표(MA 등)와 함께** 사용해야 한다.

---

## 구성 요소

| 요소 | 의미 |
|------|------|
| **+DI** | 상승 방향 움직임 강도 |
| **-DI** | 하락 방향 움직임 강도 |
| **ADX** | +DI와 -DI의 차이를 평균낸 추세 강도 |

```python
# Wilder's smoothing 방식으로 계산
atr      = tr.ewm(com=window-1, min_periods=window).mean()
plus_di  = 100 * plus_dm.ewm(com=window-1).mean() / atr
minus_di = 100 * minus_dm.ewm(com=window-1).mean() / atr
dx       = 100 * abs(plus_di - minus_di) / (plus_di + minus_di)
adx      = dx.ewm(com=window-1).mean()
```

---

## 장점 / 단점

| | 내용 |
|---|------|
| **장점** | 방향과 무관하게 추세 강도만 측정 → 횡보/추세 구분에 최적 |
| **장점** | MA와 조합하면 횡보장 휩소를 효과적으로 걸러냄 |
| **장점** | 0~100 범위로 수치가 명확해 기준선 설정이 쉬움 |
| **단점** | 후행 지표 — 추세가 시작된 후에야 ADX가 올라감 |
| **단점** | 단독 사용 불가 — 방향 정보가 없음 |
| **단점** | threshold 값(20/25)에 따라 결과가 달라짐 |

---

## 이 시스템에서의 역할

### 위험중립형 전략

MA 3중 정렬만으로는 추세인지 횡보인지 구분이 어렵다.
ADX를 게이트웨이 필터로 추가해 **진짜 추세만** 통과시킨다.

| 용도 | 조건 | 결과 |
|------|------|------|
| 횡보 판별 | ADX < 20 | SIDEWAYS → 볼린저밴드 전략 적용 |
| 추세 확인 | ADX > threshold | MA 정렬 방향에 따라 UPTREND / DOWNTREND 판별 |

```
MA 정렬만 있을 때: 횡보장 휩소 다수 발생
MA 정렬 + ADX > threshold: 진짜 추세에서만 진입 → 휩소 감소
```

**두 threshold 모두 Walk-Forward로 최적화한다**
초기값은 업계 표준(threshold=25, sideways=20)을 사용하지만,
Walk-Forward가 12개월 학습 구간마다 두 값을 동시에 재탐색한다.

```
adx_threshold 탐색 범위: [15, 20, 25, 30]   ← 추세 진입 강도
adx_sideways  탐색 범위: [10, 15, 20]        ← 횡보 판별 기준
조합 수: 4 × 3 = 12가지 / 적용 주기: 6개월
```

→ 상세: [[최적화/Walk_Forward_최적화]]

### 적극투자형 전략

인버스 ETF 진입 시 ADX 기준을 **25 → 30**으로 높인다.
인버스 ETF는 장기 보유 시 복리 손실이 발생하므로, 더 강한 추세에서만 진입한다.

---

## ATR과의 관계

ADX 계산에 사용하는 True Range(TR)가 ATR의 기반이기도 하다.
`adx_strategy.py`의 `calc_atr()` 함수는 ADX 계산과 동일한 Wilder's smoothing을 사용하며,
위험중립형 전략에서 **ATR stop-loss** 트리거로 재사용된다.

→ [[TA지표/변동성/ATR_평균진폭]]
