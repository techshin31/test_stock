# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Environment

```bash
# Python 3.10.x 권장 (vectorbt 0.26.2 공식 지원)
python -m venv .venv
.venv\Scripts\activate          # Windows
pip install -r requirements.txt
```

**버전 고정 이유:** vectorbt 0.26.2는 pandas 1.5.3 + numpy 1.23.5 + numba 0.56.4 조합에서만 안정 동작. `requirements.txt`의 버전을 임의로 올리지 말 것.

---

## 패키지 구조

```
stock_system/
├── config.py                   ← 종목·지수·ETF 설정 (유일한 수정 포인트)
├── indicators/                 ← 순수 pandas 지표 계산 (vbt 없음)
│   ├── trend/ma.py, macd.py
│   ├── momentum/rsi.py
│   ├── volatility/bollinger.py, atr.py
│   ├── volume/obv.py
│   └── trend_strength/adx.py
├── strategies/                 ← 재사용 가능한 지표 조합 유틸 (vbt 없음)
│   └── regime.py               ← calc_regime() — 4국면 판별
├── profiles/                   ← 성향별 전략 구현 (vbt 없음)
│   ├── base.py                 ← 공통 상수 (FEES, SLIPPAGE, WF_*, ADX_PARAM_GRID)
│   ├── neutral.py              ← 위험중립형: 상수 + make_signals() + get_signal()
│   ├── aggressive.py           ← 적극투자형: 상수만 (make_signals() 미구현)
│   └── __init__.py             ← get_profile("neutral") 팩토리
├── backtest/                   ← vbt 의존 (개발 머신 전용)
│   ├── portfolio.py            ← run_walk_forward(), run_bh_portfolio()
│   ├── metrics.py              ← calc_metrics(), build_metrics_table()
│   └── plots/performance.py, strategy.py, optimizer.py
└── trading/                    ← 자동매매 (vbt 없음, 브로커 서버)
    ├── data.py, signal.py, optimizer.py, executor.py
```

---

## 추가 개발 건

### [TODO] `build_size_df()` 자본배분 로직 개선

**파일:** `stock_system/backtest/portfolio.py`

#### 문제: 현재 코드의 동작

```python
# 현재 (portfolio.py:96-102)
mom_weight = momentum_df.where(valid_entry).div(mom_sum, axis=0)  # 합계 = 1.0
size_df[valid_entry] = (size_raw * mom_weight)[valid_entry]
```

`size_raw`(신호 비중)와 `mom_weight`(모멘텀 비율)를 곱하면 결과가 **가중 평균**이 됩니다.

```
A(entry2=0.7, 모멘텀60%) + B(entry1=0.4, 모멘텀40%) 동시 발생
→ A: 0.7 × 0.6 = 0.42,  B: 0.4 × 0.4 = 0.16,  합계: 0.58
→ ETF: 0.42  ← 의도보다 과다 (entry2 신호임에도 42% 방치)
```

같은 날 여러 종목이 서로 다른 신호(entry1/entry2)를 내면, 주식 합계가 `max(size_raw)`보다 낮아지고
단기채 ETF에 의도치 않게 많은 현금이 묶입니다.

#### 설계 원칙

| 조건 | 주식 배분 | 단기채 ETF |
|------|----------|-----------|
| 신호 없음 | 0% | **1.0** (전액 ETF) |
| 신호 합계 ≤ 100% | 각 종목 `size_raw` 그대로 | **나머지** (1 - 합계) |
| 신호 합계 > 100% | 신호강도 × 모멘텀 비율로 **100%** 배분 | **NaN** (기존 포지션 유지) |

> **ETF NaN 처리 근거:** `targetpercent` 모드에서 NaN은 "주문 없음 → 기존 포지션 유지"를 의미합니다.
> 주식이 100%를 차지하면 ETF를 명시적으로 0.0으로 청산할 필요 없이, 다음 신호 사이클에서
> 자연스럽게 정리됩니다. 강제 청산은 불필요한 매매 비용을 유발하므로 NaN이 올바른 처리입니다.

#### 수정 내용: `build_size_df()` (portfolio.py:93-103)

```python
# ── 기존 코드 ──────────────────────────────────────────────────────────────────
entry_mask  = size_raw > 0
valid_entry = entry_mask & (momentum_df >= min_momentum)

mom_valid  = momentum_df.where(valid_entry)
mom_sum    = mom_valid.sum(axis=1).replace(0, np.nan)
mom_weight = mom_valid.div(mom_sum, axis=0)

size_df = size_raw.copy()
size_df[entry_mask & ~valid_entry] = np.nan
size_df[valid_entry] = (size_raw * mom_weight)[valid_entry]

# ── 수정 코드 ──────────────────────────────────────────────────────────────────
entry_mask  = size_raw > 0
valid_entry = entry_mask & (momentum_df >= min_momentum)

# 각 종목이 원하는 총 비중 합계
desired       = size_raw.where(valid_entry, 0)
total_desired = desired.sum(axis=1)

# 현금 부족 시: 신호강도 × 모멘텀 결합 가중치
combined     = (size_raw * momentum_df).where(valid_entry)
combined_sum = combined.sum(axis=1).replace(0, np.nan)
weight       = combined.div(combined_sum, axis=0)   # 합계 = 1.0

size_df = size_raw.copy()
size_df[entry_mask & ~valid_entry] = np.nan

sufficient   = (total_desired > 0) & (total_desired <= 1.0)
insufficient = total_desired > 1.0

# Case 2: 현금 충분 → 각자 size_raw 그대로
size_df[valid_entry & sufficient.values[:, None]]   = size_raw[valid_entry & sufficient.values[:, None]]

# Case 3: 현금 부족 → 신호강도×모멘텀 비율로 100% 배분
size_df[valid_entry & insufficient.values[:, None]] = weight[valid_entry & insufficient.values[:, None]]
```

#### 검증 항목

| 시나리오 | 기댓값 |
|---------|--------|
| 신호 없음 | `size_df` 전부 NaN → `add_cash_etf()` 에서 ETF = 1.0 |
| A(entry2=0.7) 단독 | A = 0.70, ETF = 0.30 |
| A(entry1=0.4) + B(entry1=0.4) | A = 0.40, B = 0.40, ETF = 0.20 |
| A(entry2=0.7) + B(entry1=0.4), 합=1.1 | 합계 = 1.0, ETF = NaN(기존 유지) |
| A(entry2=0.7) + B(entry2=0.7), 합=1.4 | 합계 = 1.0, ETF = NaN(기존 유지) |
| A(entry2=0.7, 모멘텀↑) + B(entry1=0.4, 모멘텀↓), 합=1.1 | A > B (신호강도+모멘텀 모두 반영) |
