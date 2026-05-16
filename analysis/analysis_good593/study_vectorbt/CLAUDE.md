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

## 단계별 검증 계획 — 위험중립형 전략

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
| `calc_bollinger(close, 20, 2)` | `upper >= mid >= lower` (유효 구간 전체) |
| `calc_atr(high, low, close, 14)` | 유효값 > 0 |
| `calc_adx(high, low, close, 14)` | 컬럼 `{ADX, plus_di, minus_di}` / ADX 0~100 범위 |

#### 정리 항목

- `adx.py`: `# +DM과 -DM이 같거나 둘 다 0이면 0` 주석 → `valid_plus_dm`, `valid_minus_dm` 변수명으로 의도 전달됨, 삭제
- `adx.py`: `di_sum`, `dx` → 각각 한 번만 쓰이는 임시 변수, 인라인 처리 검토

---

### 2단계 — `strategies/regime.py`

#### 검증 항목

| 확인 포인트 | 기댓값 |
|------------|--------|
| 4국면만 등장 | `regime.unique()` ⊆ `{SIDEWAYS, UPTREND, DOWNTREND, TRANSITION}` |
| 우선순위 — SIDEWAYS | ADX < `adx_sideways` 날은 UPTREND·DOWNTREND 불가 |
| 우선순위 — DOWNTREND 최우선 | DOWNTREND 마스크 True인 날 regime == "DOWNTREND" 100% |
| TRANSITION = 나머지 | 4국면 합이 전체 날짜 수와 일치 |
| masks dict 키 | `{UPTREND, DOWNTREND, SIDEWAYS, TRANSITION, ma_s, ma_m, ma_l, adx}` 모두 존재 |
| KOSPI 필터 off | `kospi=None` 시 결과 변화 없음 |
| KOSPI 필터 on — UPTREND 차단 | KOSPI < KOSPI_MA(60)인 날은 UPTREND == False |
| KOSPI 필터 후 TRANSITION 재계산 | `TRANSITION == ~SIDEWAYS & ~UPTREND & ~DOWNTREND` |

#### 정리 항목

- L47~49: `# MA20`, `# MA60`, `# MA120` 주석 → `ma_windows` 파라미터 기반이라 고정값처럼 오해 소지, 삭제
- L54: `# ADX 모드: SIDEWAYS → UPTREND → DOWNTREND → TRANSITION` → 모듈 docstring 중복, 삭제
- L59: `# MA+KOSPI 모드: ADX 조건 제외, SIDEWAYS 없음` → 모듈 docstring 중복, 삭제
- L69~70: `# 신규 UPTREND 진입만 차단`, `# 반드시 재계산` → WHY를 설명, 유지

---

### 3단계 — `profiles/neutral.py`

#### 검증 항목 — 상수·팩토리

| 확인 포인트 | 기댓값 |
|------------|--------|
| `get_profile("neutral")` | 모듈 객체 반환, 예외 없음 |
| `get_profile("unknown")` | `ValueError` 발생 |
| `neutral` 상수 목록 | `ADX_THRESHOLD, ADX_SIDEWAYS, ENTRY1_SIZE, ENTRY2_SIZE, ENTRY_RANGE_SIZE, EXIT1_SIZE, EXIT2_SIZE, RECENT_WINDOW, MOMENTUM_WINDOW, MIN_MOMENTUM, ATR_PERIOD, ATR_MULTIPLIER, KOSPI_MA, CASH_RETURN, FEES, SLIPPAGE, WF_TRAIN_MONTHS, WF_TEST_MONTHS, ADX_PARAM_GRID, METRICS_TARGET, METRICS_ALERT` 전부 존재 |
| 순환 import 없음 | `from stock_system.profiles import get_profile` 단독 import 성공 |

#### 검증 항목 — `neutral.make_signals()`

| 확인 포인트 | 기댓값 |
|------------|--------|
| `entry1` — 전환 첫날만 | `entry1[t]` → `UPTREND[t-1] == False` |
| `entry2` — entry1 이후만 | `entry2[t]` → 최근 `RECENT_WINDOW`(60)일 내 `entry1` 존재 |
| `entry1 & entry2` 동시 없음 | `(entry1 & entry2).any() == False` |
| DOWNTREND → `size = 0.0` | DOWNTREND 날 size_series 전부 0.0 |
| ATR stop → `size = 0.0` 최우선 | ATR stop 발동 시 매수 신호 동시 발생해도 size == 0.0 |
| `size_series` 값 범위 | NaN / 0.0 / `{0.1, 0.3, 0.4, 0.7}` 외 값 없음 |
| 반환 4개 | `entries, exits, size_series, detail` |
| `detail` 키 | `{regime, masks, adx_df, entry1, entry2, entry_range, transition_from_up, dead_cross, bb_exit_sideways, atr_stop}` |

#### 검증 항목 — `neutral.get_signal()`

| 확인 포인트 | 기댓값 |
|------------|--------|
| 합성 150일 데이터로 호출 | `dict` 반환, 값이 NaN 또는 float |
| `use_adx_mode=False` 전달 | 예외 없이 동작, 결과 dict 반환 |

#### 정리 항목

- `make_signals()` docstring: 매수/매도 단계 설명이 함수 내 섹션 주석으로 이미 전달됨 → docstring 간소화 또는 삭제 검토
- `ma20_support` 변수: 한 번만 사용 → 인라인 처리 검토: `(close > ma_s) & UPTREND & had_entry1_recently & ~entry1`
- `had_entry1_recently` 변수: 한 번만 사용이지만 이름이 의도를 명확히 설명 → 유지
- `base.py`: `ADX_PARAM_GRID`가 neutral에서 override 없이 그대로 쓰이면 neutral에 별도 정의 불필요

---

### 4단계 — `backtest/` (vbt 의존)

합성 멀티종목 DataFrame(3종목, 500일)으로 검증. yfinance 불필요.

#### 검증 항목 — `build_size_df(profile, ...)`

| 확인 포인트 | 기댓값 |
|------------|--------|
| 호출 형태 | `build_size_df(neutral, close_df, high_df, low_df, volume_df)` — `profile` 첫 인수 |
| 반환 shape | `size_df.shape == (n_days, n_stocks)` |
| 값 범위 | NaN / 0.0 / 양수만 존재, 음수 없음 |
| `min_momentum > 0` 적용 | 모멘텀 음수 종목의 매수 size → NaN으로 필터링 |
| 모멘텀 윈도우 | `profile.MOMENTUM_WINDOW` 사용 — UPTREND=126, TRANSITION=63, SIDEWAYS=21 |
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
| profile 이름 자동 추출 | 전략값 컬럼명에 `"neutral"` 포함 |

#### 검증 항목 — `run_walk_forward()` (E2E)

| 확인 포인트 | 기댓값 |
|------------|--------|
| 반환 `(pf, wf_info)` | `pf`: vbt.Portfolio / `wf_info`: dict |
| `wf_info["windows"]` 원소 키 | `{train_start, train_end, test_start, test_end, best_params, best_score, use_adx_mode, scan}` |
| `wf_info["n_windows"] > 0` | WF 창 최소 1개 이상 |
| `best_params` 키 | `{adx_threshold, adx_sideways}` |
| `use_adx_mode` 타입 | `bool` |
| OOS 구간 연속성 | windows의 test 구간이 겹치지 않고 연속 |

#### 정리 항목 — `portfolio.py`

- `build_size_df()`: `volume_df` 파라미터 미사용 → 제거, `_walk_forward_portfolio()` 내 `tr_vol = volume_df[train_mask]` 라인도 함께 제거
- `_score_equity()`: if 분기 3개 → dict dispatch로 단순화
- `windows["scan"]`: 그리드 서치 전체 결과 저장 → 실전 서비스 불필요 시 제거 검토

#### 정리 항목 — `metrics.py`

- `n_y` 변수명 → 의미 불명확, `n_years_bm`으로 개선
- `ir` 변수명 → `info_ratio`로 개선
- `_f()` 중첩 함수: `except Exception` → `except (TypeError, ValueError)`로 범위 축소
- `# 승률: 월별 수익률 기준` 주석 → `win_rate` 변수명으로 명확, 삭제
- `# 지표별 표시 포맷 + 높을수록 좋은지 여부` 주석 → META dict 내용으로 명확, 삭제
