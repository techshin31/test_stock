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
├── strategies/                 ← 지표 조합 + 매매 규칙 (vbt 없음)
│   ├── regime.py               ← calc_regime() — 4국면 판별
│   └── partial.py              ← make_signals() — 분할 매수/매도
├── profiles/                   ← 성향별 파라미터 + get_signal() (vbt 없음)
│   ├── base.py, neutral.py, aggressive.py
│   └── __init__.py             ← get_profile("neutral") 팩토리
├── backtest/                   ← vbt 의존 (개발 머신 전용)
│   ├── portfolio.py            ← run_walk_forward(), run_bh_portfolio()
│   ├── metrics.py              ← calc_metrics(), build_metrics_table()
│   └── plots/performance.py, strategy.py, optimizer.py
└── trading/                    ← 자동매매 (vbt 없음, 브로커 서버)
    ├── data.py, signal.py, optimizer.py, executor.py
```

### 계층별 의존성

| 계층 | vbt | 역할 |
|------|-----|------|
| `indicators/` | ✗ | 지표 계산. 순수 pandas |
| `strategies/` | ✗ | 지표 조합 + 복합 매매 규칙 |
| `profiles/` | ✗ | 성향별 파라미터 상수 + `get_signal()` |
| `backtest/` | ✓ | vbt.Portfolio로 과거 시뮬레이션 |
| `trading/signal.py` | ✗ | best_params.json → 오늘 신호 생성 |
| `trading/optimizer.py` | ✓ | 3개월마다 WF → best_params.json 저장 |

`profiles/`는 `backtest/`를 import하지 않는다.

---

## obsidian/ — 전략 설계 문서 (코드와 불일치 시 obsidian이 정답)

| obsidian 문서 | Python 구현 |
|--------------|------------|
| `투자성향/위험중립형_전략.md` | `profiles/neutral.py` + `strategies/partial.py` + `strategies/regime.py` |
| `투자성향/적극투자형_전략.md` | `profiles/aggressive.py` + `strategies/partial.py` + `strategies/regime.py` |
| `매매원칙/분할매수매도_원칙.md` | `strategies/partial.py` |
| `최적화/Walk_Forward_최적화.md` | `backtest/portfolio.py` + `trading/optimizer.py` |
| `성과지표/*.md` | `backtest/metrics.py` |

---

## 단계별 검증 계획

의존성 방향(아래 → 위)대로 진행한다. 각 단계 [FAIL] 0개 확인 후 다음 단계로 이동.

### 검증 원칙

- 합성 데이터(`pd.bdate_range`, 300~500일)로 먼저 검증 — yfinance는 5단계에서만 사용
- vbt import는 4단계 이전에 하지 않는다
- [FAIL] 발생 시 해당 파일만 수정 후 해당 단계 전체 재실행

---

### 1단계 — `indicators/` (vbt 없음)

#### 검증 항목

| 함수 | 확인 포인트 |
|------|------------|
| `calc_ma(close, window)` | 처음 `window-1`개 NaN / 이후 rolling mean 일치 |
| `calc_macd(close, 12, 26, 9)` | 반환 3개(line, signal, hist) / `hist == line - signal` |
| `calc_rsi(close, 14)` | 유효값 0~100 범위 / 처음 14개 NaN |
| `calc_bollinger(close, 20, 2)` | `upper >= mid >= lower` (유효 구간 전체) |
| `calc_atr(high, low, close, 14)` | 유효값 > 0 |
| `calc_obv(close, volume)` | 상승일 OBV 증가 / 하락일 감소 |
| `calc_adx(high, low, close, 14)` | 컬럼 `{ADX, plus_di, minus_di}` / ADX 0~100 범위 |

#### 정리 항목

- 각 함수 내 불필요한 중간 변수 제거 (결과를 한 번만 쓰는 임시 변수)
- 함수 동작이 함수명·파라미터명으로 자명한 경우 주석 제거
- `calc_adx`: `mask_plus`, `mask_minus` 변수명이 역할을 충분히 설명하는지 확인. 아니라면 이름 개선

---

### 2단계 — `strategies/` (indicators 사용)

#### 검증 항목 — `calc_regime()`

| 확인 포인트 | 기댓값 |
|------------|--------|
| 4국면만 등장 | `regime.unique()` ⊆ `{SIDEWAYS, UPTREND, DOWNTREND, TRANSITION}` |
| 우선순위 — SIDEWAYS | ADX < `adx_sideways` 날은 UPTREND·DOWNTREND 불가 |
| 우선순위 — DOWNTREND 최우선 | DOWNTREND 마스크 True인 날 regime == "DOWNTREND" 100% |
| TRANSITION = 나머지 | 4국면 합이 전체 날짜 수와 일치 |
| masks dict 키 | `{UPTREND, DOWNTREND, SIDEWAYS, TRANSITION, ma_s, ma_m, ma_l, adx}` 모두 존재 |
| KOSPI 필터 off | `kospi=None` 시 결과 변화 없음 |
| KOSPI 필터 on — UPTREND 차단 | KOSPI < MA120 날은 UPTREND == False |
| KOSPI 필터 on — DOWNTREND 강제 | KOSPI < MA120 날은 DOWNTREND == True |
| KOSPI 필터 후 TRANSITION 재계산 | `TRANSITION == ~SIDEWAYS & ~UPTREND & ~DOWNTREND` |

#### 검증 항목 — `make_signals()`

| 확인 포인트 | 기댓값 |
|------------|--------|
| `entry1` — 전환 첫날만 | `entry1[t]` → `UPTREND[t-1] == False` |
| `entry2` — entry1 이후만 | `entry2[t]` → 최근 `recent_window`일 내 `entry1` 존재 |
| `entry1 & entry2` 동시 없음 | `(entry1 & entry2).any() == False` |
| DOWNTREND → `size = 0.0` | DOWNTREND 날 size_series 전부 0.0 |
| ATR stop → `size = 0.0` 최우선 | ATR stop 발동 시 매수 신호 동시 발생해도 size == 0.0 |
| `size_series` 값 범위 | NaN / 0.0 / `{0.1, 0.3, 0.4, 0.7}` 외 값 없음 |
| 반환 4개 | `entries, exits, size_series, detail` |
| `detail` 키 | `{regime, masks, entry1, entry2, entry_range, transition_from_up, dead_cross, bb_exit_sideways, atr_stop}` |

#### 정리 항목

- `regime.py`: 모듈 docstring의 "우선순위" 설명이 코드와 일치하는지 확인, 불일치 수정
- `partial.py`: `bb_entry`, `bb_exit` 변수 중 `SIDEWAYS` 조건 없이 단독으로 쓰이는 곳이 없으면 인라인 처리 검토
- `partial.py`: `has_position` 변수 — rolling max 방식이 의도와 맞는지 주석 없이 변수명만으로 이해 가능한지 확인. 불명확하면 변수명 개선
- `partial.py`: `transition_from_up` 계산 블록 — 3줄 조건식이 단순화 가능하면 정리

---

### 3단계 — `profiles/` (strategies 지연 import)

#### 검증 항목

| 확인 포인트 | 기댓값 |
|------------|--------|
| `get_profile("neutral")` | 모듈 객체 반환, 예외 없음 |
| `get_profile("aggressive")` | 모듈 객체 반환, 예외 없음 |
| `get_profile("unknown")` | `ValueError` 발생 |
| `neutral` 상수 목록 | `ADX_THRESHOLD, ADX_SIDEWAYS, ENTRY1_SIZE, ENTRY2_SIZE, ENTRY_RANGE_SIZE, EXIT1_SIZE, EXIT2_SIZE, RECENT_WINDOW, MOMENTUM_WINDOW, MIN_MOMENTUM, ATR_PERIOD, ATR_MULTIPLIER, KOSPI_MA, CASH_RETURN, FEES, SLIPPAGE, WF_TRAIN_MONTHS, WF_TEST_MONTHS, ADX_PARAM_GRID, METRICS_TARGET, METRICS_ALERT` 전부 존재 |
| `aggressive` 상수 목록 | neutral과 동일한 키 목록 전부 존재 |
| `neutral.get_signal(close_df, ...)` | 합성 150일 데이터로 호출 → `dict` 반환, 값이 NaN 또는 float |
| `aggressive.get_signal(close_df, ...)` | 동일 |
| 순환 import 없음 | `from stock_system.profiles import get_profile` 단독 import 성공 |

#### 정리 항목

- `neutral.py`, `aggressive.py`: `from .base import ... # noqa: F401` — 실제 해당 파일에서 직접 참조하지 않는 상수가 있으면 `__init__.py` 경유 re-export로 이동 검토
- `neutral.py` `get_signal()` docstring: 파라미터·반환값 설명이 실제 동작과 일치하는지 확인
- `base.py`: `ADX_PARAM_GRID` 값이 `neutral.py`·`aggressive.py`에서 override 없이 그대로 쓰이는지 확인. override가 없으면 각 profile에 별도 정의 불필요

---

### 4단계 — `backtest/` (vbt 의존)

합성 멀티종목 DataFrame(3종목, 500일)으로 검증. yfinance 불필요.

#### 검증 항목 — `build_size_df()`

| 확인 포인트 | 기댓값 |
|------------|--------|
| 반환 shape | `size_df.shape == (n_days, n_stocks)` |
| 값 범위 | NaN / 0.0 / 양수만 존재, 음수 없음 |
| `min_momentum > 0` 적용 | 모멘텀 음수 종목의 매수 size → NaN으로 필터링 |
| `signal_info` 키 | 종목별 `{진입 횟수, 1차 익절, 2차 청산}` |

#### 검증 항목 — `run_bh_portfolio()`

| 확인 포인트 | 기댓값 |
|------------|--------|
| 반환 타입 | `vbt.Portfolio` 인스턴스 |
| 첫날 이후 포지션 존재 | `pf.value().iloc[1:]`이 초기 자본과 다름 |

#### 검증 항목 — `calc_metrics()`

| 확인 포인트 | 기댓값 |
|------------|--------|
| 절대 지표 5개 | `{cagr, mdd, mdd_duration, calmar, sortino}` 모두 존재 |
| `benchmark_series=None` | 상대 지표 키 없음 |
| `benchmark_series` 전달 | 상대 지표 6개 추가 `{alpha, beta, mdd_reduction, calmar_improvement, info_ratio, win_rate}` |
| `mdd <= 0` | 드로다운은 음수 또는 0 |
| `0 <= win_rate <= 1` | 승률 범위 |

#### 검증 항목 — `build_metrics_table()`

| 확인 포인트 | 기댓값 |
|------------|--------|
| 반환 타입 | `pd.DataFrame` |
| 컬럼 포함 여부 | `B&H, 목표, 경보선, 상태` 컬럼 존재 |
| 상태값 범위 | `{✓, ⚠, ✗, —}` 외 없음 |
| profile 이름 자동 추출 | 전략값 컬럼명에 `"neutral"` 또는 `"aggressive"` 포함 |

#### 검증 항목 — `run_walk_forward()` (E2E)

| 확인 포인트 | 기댓값 |
|------------|--------|
| 반환 `(pf, wf_info)` | `pf`: vbt.Portfolio / `wf_info`: dict |
| `wf_info["windows"]` 원소 키 | `{train_start, train_end, test_start, test_end, best_params, best_score}` |
| `wf_info["n_windows"] > 0` | WF 창 최소 1개 이상 |
| `best_params` 키 | `{adx_threshold, adx_sideways}` |
| OOS 구간 연속성 | windows의 test 구간이 겹치지 않고 연속 |

#### 정리 항목

- `portfolio.py`: `_score_equity()` — `metric` 분기가 3개뿐이므로 dict dispatch나 match-case로 단순화 검토
- `portfolio.py`: `_walk_forward_portfolio()` 내 `scan_rows` 수집 블록 — 디버깅 외 용도가 없으면 제거 검토
- `metrics.py`: `_calc_mdd_duration_months()` 내 for-loop — pandas `groupby` 또는 누적합으로 대체 가능한지 확인
- `metrics.py`: `build_metrics_table()` 내 `_f()` 중첩 함수 — `try/except` 범위가 과도하게 넓으면 축소
- `plots/`: 각 plot 함수 파라미터 중 실제로 사용되지 않는 파라미터가 있으면 제거
