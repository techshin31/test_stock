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
├── rotation.py                 ← 분기 종목 교체 관리 (vbt 없음, backtest·trading 공유)
│                                  RotationPlan, RotationManager
│                                  build_rotated_size_df()   — portfolio.build_size_df() + rotation 후처리
│                                  apply_rotation_to_signal() — trading 전용 단일 신호 후처리
├── portfolio.py                ← 포트폴리오 자금 배분 (vbt 없음, backtest·trading 공유)
│                                  build_size_df()  — 종목별 신호 집계 + 3단계 자금 배분
│                                  add_cash_etf()   — 잔여 현금 → 단기채 ETF
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
│   ├── engine.py               ← run_walk_forward(), run_bh_portfolio()
│   │                              rotation_plans 파라미터로 분기 종목 교체 시뮬레이션 지원
│   ├── metrics.py              ← calc_metrics(), build_metrics_table()
│   └── plots/performance.py, strategy.py, optimizer.py
└── trading/                    ← 자동매매 (vbt 없음, 브로커 서버)
    ├── data.py
    ├── signal.py               ← get_today_signal() — rotation_state_path 파라미터로
    │                              rotation_state.json 읽어 매수 신호 차단·강제 청산 적용
    ├── optimizer.py
    └── executor.py
```

### 호출 계층

```
backtest/engine.py              trading/signal.py
       │                                │
       └──────────┬─────────────────────┘
                  │
          rotation.build_rotated_size_df()   또는   rotation.apply_rotation_to_signal()
                  │                                           │
          portfolio.build_size_df()              profiles.get_signal()
```

### 분기 종목 교체 전략 — 파일별 역할

| 파일 | 역할 |
|------|------|
| `rotation.py` | 편출 종목 sell_only 등록, 강제 청산일 관리, 후처리 적용 |
| `portfolio.py` | 순수 자금 배분 (rotation 개념 없음, 변경 없음) |
| `backtest/engine.py` | `rotation_plans` 수신 → 윈도우마다 plan 적용, active_names 산출 |
| `trading/signal.py` | `rotation_state.json` 읽기 → 오늘 신호에 rotation 후처리 |

#### rotation 사용 예시

```python
# backtest — rotation_plans 전달
from stock_system.rotation import RotationPlan

plans = [
    RotationPlan("2023-01-02", exit_stocks=["삼성전자"], entry_stocks=["SK하이닉스"]),
    RotationPlan("2023-04-03", exit_stocks=["NAVER"],    entry_stocks=[]),
]
pf, wf_info = run_walk_forward(profile, close_df, high_df, low_df,
                                rotation_plans=plans, ...)

# trading — 분기 검토 후 1회 실행
from stock_system.rotation import RotationManager, RotationPlan

manager = RotationManager()
manager.apply_plan(RotationPlan("2024-01-02", exit_stocks=["삼성전자"]))
manager.to_json("rotation_state.json")

# trading — 매일 실행
signal = get_today_signal(params_path="best_params.json",
                          rotation_state_path="rotation_state.json")
```

---

## 백테스트 코드 검증 계획

### 검증 기준

- **설계 명세**: `obsidian/투자성향/위험중립형_전략.md`
- **검증 범위**: backtest 전용 (trading 제외)
- **검증 순서**: 전략 실행 흐름 순서 (하위 레이어 → 상위 레이어)

```
[1] 지표 계산         indicators/
 ↓
[2] 국면 판별         strategies/regime.py
 ↓
[3] 신호 생성         profiles/neutral.py
 ↓
[4] 자금 배분         portfolio.py
 ↓
[5] 포트폴리오 실행   backtest/engine.py  ← _run_portfolio_backtest()
 ↑
[6] WF 최적화         backtest/engine.py  ← _walk_forward_portfolio()
 ↓
[7] 분기 종목 교체    rotation.py + backtest/engine.py
 ↓
[8] 성과 지표         metrics/calc.py · metrics/report.py
```

---

### Step 1 — 지표 계산 (`indicators/`)

| 파일 | 검증 항목 | 확인 포인트 |
|------|---------|-----------|
| `trend/ma.py` | MA20, MA60, MA120 | `close.rolling(N).mean()` 값 일치, NaN 구간 정확성 |
| `trend_strength/adx.py` | ADX, +DI, -DI | ADX 범위 0~100, 추세 강할 때 ADX 상승 방향성 |
| `volatility/bollinger.py` | 상단·중간·하단 밴드 | 중간=MA20, 상단>중간>하단, 밴드폭 양수 |
| `volatility/atr.py` | ATR (period=14) | ATR > 0, 변동성 큰 날 ATR 증가 방향성 |

```python
# MA NaN 구간
ma20 = calc_ma(close, 20)
assert ma20.isna().sum() == 19              # 첫 19일 NaN

# ADX 범위
adx_df = calc_adx(high, low, close, 14)
assert (adx_df["ADX"].dropna().between(0, 100)).all()

# Bollinger 구조
upper, mid, lower = calc_bollinger(close, 20, 2.0)
assert (upper > mid).all() and (mid > lower).all()

# ATR 양수
atr = calc_atr(high, low, close, 14)
assert (atr.dropna() > 0).all()
```

---

### Step 2 — 시장 국면 판별 (`strategies/regime.py`)

**2-1. 4국면 상호 배타성 — 하루에 정확히 1개 국면**

```python
regime, masks, _ = calc_regime(close, high, low, use_adx_mode=True)

overlap = (masks["UPTREND"].astype(int) + masks["DOWNTREND"].astype(int)
           + masks["SIDEWAYS"].astype(int) + masks["TRANSITION"].astype(int))
assert (overlap == 1).all()
```

**2-2. ADX 모드 — 국면별 조건**

| 국면 | 조건 | 검증 포인트 |
|------|------|-----------|
| SIDEWAYS | ADX < adx_sideways | SIDEWAYS 날 ADX 전부 < adx_sideways |
| DOWNTREND | MA역배열 + ADX > threshold | MA20<MA60<MA120 & ADX>threshold 동시 충족 |
| UPTREND | MA정배열 + ADX > threshold + KOSPI>MA60 | 세 조건 동시 충족 |
| TRANSITION | 나머지 | 위 3가지 모두 False |

**2-3. 판별 우선순위 — SIDEWAYS가 DOWNTREND보다 먼저 확정**

```python
# MA역배열 + ADX < adx_sideways → SIDEWAYS여야 함 (DOWNTREND 아님)
sideways_days = masks["SIDEWAYS"]
assert masks["DOWNTREND"][sideways_days].sum() == 0
assert masks["UPTREND"][sideways_days].sum() == 0
```

**2-4. MA+KOSPI 모드 — SIDEWAYS 미존재**

```python
_, masks_ma, _ = calc_regime(..., use_adx_mode=False)
assert masks_ma["SIDEWAYS"].sum() == 0    # MA+KOSPI 모드: SIDEWAYS 없음
```

**2-5. KOSPI_MA60 필터 — UPTREND 차단 (neutral.py에서 kospi_ma=60 전달)**

```python
_, masks, _ = calc_regime(..., kospi=kospi_series, kospi_ma=60)
# KOSPI < KOSPI_MA60인 날: MA정배열 + ADX 충족해도 UPTREND 차단
assert masks["UPTREND"][kospi_below_ma60_day] == False
assert masks["TRANSITION"][kospi_below_ma60_day] == True
```

---

### Step 3 — 매수/매도 신호 생성 (`profiles/neutral.py`)

**3-1. 매수 신호 3종 — 발생 조건과 size 값**

```python
entries, exits, size_series, detail = make_signals(close, high, low, ...)

assert (size_series[detail["entry1"]]      == 0.4).all()   # UPTREND 첫날 → 40%
assert (size_series[detail["entry2"]]      == 0.7).all()   # 60거래일 이내 + MA20 상향 → 70%
assert (size_series[detail["entry_range"]] == 0.3).all()   # SIDEWAYS + BB하단 돌파 → 30%
assert (detail["entry1"] & detail["entry2"]).sum() == 0    # 동시 발생 불가
```

**3-2. entry2 — entry1 후 60거래일 이내만 발생**

```python
for d in detail["entry2"][detail["entry2"]].index:
    window = detail["entry1"].loc[:d].iloc[-60:]
    assert window.any(), f"{d}: entry1 없는데 entry2 발생"
```

**3-3. DOWNTREND에서 매수 신호 없음**

```python
down = detail["masks"]["DOWNTREND"]
assert detail["entry1"][down].sum() == 0
assert detail["entry2"][down].sum() == 0
assert detail["entry_range"][down].sum() == 0
```

**3-4. 매도 신호 — size 값과 우선순위**

| 신호 | 조건 | size 기댓값 | 우선순위 |
|------|------|-----------|---------|
| ATR stop | 낙폭 > ATR×2.0 | 0.0 | 최우선 |
| DOWNTREND 진입 | — | 0.0 | 높음 |
| BB 청산 | SIDEWAYS + BB상단 하향돌파 | 0.0 | 높음 |
| 데드크로스 | MA20 < MA60 | 0.1 | 중간 |
| 1차 익절 | UPTREND→TRANSITION 첫날 | 0.4 | 낮음 |

```python
assert (size_series[detail["atr_stop"]]         == 0.0).all()
assert exits[detail["atr_stop"]].all()                         # exits에 포함
assert (size_series[detail["dead_cross"]]        == 0.1).all()
assert (size_series[detail["transition_from_up"]]== 0.4).all()
```

---

### Step 4 — 자금 배분 (`portfolio.py`)

**4-1. `build_size_df()` — 3단계 배분 시나리오**

```python
size_df, _ = build_size_df(profile, close_df, high_df, low_df, ...)

# Case 1: 신호 없음 → 전체 NaN (add_cash_etf에서 ETF 100%)
assert size_df.isna().all(axis=1).sum() > 0

# Case 2: 합계 ≤ 100% → 각자 목표비중 그대로
# A(entry1=0.4) + B(entry1=0.4) → A=0.40, B=0.40
assert abs(size_df.loc[two_entry1_day, "A"] - 0.4) < 1e-6
assert abs(size_df.loc[two_entry1_day, "B"] - 0.4) < 1e-6

# Case 3: 합계 > 100% → score 비례 배분, 합계=1.0
# A(entry2=0.7, 모멘텀60%) + B(entry1=0.4, 모멘텀40%) → A=72.4%, B=27.6%
total = size_df.loc[overflow_day, ["A", "B"]].sum()
assert abs(total - 1.0) < 1e-6
assert size_df.loc[overflow_day, "A"] > size_df.loc[overflow_day, "B"]
```

**4-2. 모멘텀 윈도우 — 국면별 126/63/21일**

```python
assert profile.MOMENTUM_WINDOW == {"UPTREND": 126, "TRANSITION": 63, "SIDEWAYS": 21}
```

**4-3. `add_cash_etf()` — ETF 주차 상세 동작**

```python
size_etf, close_etf, _, _ = add_cash_etf(size_df, close_df, high_df, low_df, etf_price)

assert "단기채" in size_etf.columns                            # ETF 컬럼 추가
assert "단기채" in close_etf.columns
assert size_etf.loc[no_signal_day, "단기채"] == 1.0            # 신호 없음 → ETF 100%
assert abs(size_etf.loc[entry1_day, "단기채"] - 0.6) < 1e-6   # 주식 40% → ETF 60%
assert pd.isna(size_etf.loc[overflow_day, "단기채"])           # 주식 100% → ETF NaN
assert pd.isna(size_etf.loc[tiny_cash_day, "단기채"])          # 잔여 < 1% → ETF NaN
assert abs(size_etf.loc[hold_day, "단기채"] - 0.3) < 1e-6     # ffill: 이전 포지션 반영
```

---

### Step 5 — 포트폴리오 실행 (`backtest/engine.py` → `_run_portfolio_backtest()`)

여러 종목을 동시에 매수/매도하는 포트폴리오 운용 레이어를 검증한다.

**5-1. 다중 종목 동시 매수 — 현금 공유(cash_sharing) 검증**

```python
pf = _run_portfolio_backtest(close_etf, size_etf, fees=0.0015, slippage=0.001)

# 같은 날 A=40%, B=40%, ETF=20% → 총 투자 100%, 현금 초과 없음
orders = pf.orders.records_readable
day_orders = orders[orders["Date"] == multi_signal_day]
total_value = (day_orders["Size"] * day_orders["Price"]).sum()
assert total_value <= pf.init_cash * 1.001
```

**5-2. targetpercent 모드 — NaN/0.0/양수 동작**

```python
# NaN → 주문 없음 (기존 포지션 유지)
assert len(orders[orders["Date"] == nan_signal_day]) == 0

# 0.0 → 청산 매도 주문
sell_orders = orders[(orders["Date"] == downtrend_day) & (orders["Side"] == "Sell")]
assert len(sell_orders) > 0

# 양수 → 매수 주문
buy_orders = orders[(orders["Date"] == entry1_day) & (orders["Side"] == "Buy")]
assert len(buy_orders) > 0
```

**5-3. 포트폴리오 기본 건전성**

```python
assert (pf.value() >= 0).all()                                      # 음수 없음
assert abs(pf.value().iloc[1] - pf.init_cash) / pf.init_cash < 0.01  # 첫날 ≈ 초기자금
cash_ratio = pf.cash() / pf.value()
assert cash_ratio.mean() < 0.05                                     # 유휴 현금 < 5%
```

---

### Step 6 — Walk-Forward 최적화 (`backtest/engine.py` → `_walk_forward_portfolio()`)

**6-1. IS 12개월 / OOS 3개월 구간 분리**

```python
pf, wf_info = run_walk_forward(profile, close_df, high_df, low_df, cash_etf=etf)

for w in wf_info["windows"]:
    assert 330 <= (w["train_end"] - w["train_start"]).days <= 400  # IS ≒ 12개월
    assert  55 <= (w["test_end"]  - w["test_start"]).days  <= 100  # OOS ≒ 3개월
```

**6-2. 종목별 독립 그리드 서치 — 12조합**

```python
combos = list(itertools.product(*ADX_PARAM_GRID.values()))
assert len(combos) == 12   # [15,20,25,30] × [10,15,20]

# 종목별 다른 best_params 가능 (독립 평가 설계 의도)
# → params_A != params_B 허용
```

**6-3. IS score 기반 모드 전환**

```python
for w in wf_info["windows"]:
    for name, params in w["per_stock"].items():
        score = params["best_score"]
        mode  = params["use_adx_mode"]
        if np.isfinite(score) and score > 0:
            assert mode is True    # IS score > 0 → ADX 모드
        elif np.isfinite(score) and score <= 0:
            assert mode is False   # IS score ≤ 0 → MA+KOSPI 모드
```

**6-4. IS score 미달 시 fallback — 직전 윈도우 params 보장**

```python
for w in wf_info["windows"]:
    for name, params in w["per_stock"].items():
        assert "best_params"   in params
        assert "adx_threshold" in params["best_params"]
        assert "adx_sideways"  in params["best_params"]
```

**6-5. 과적합 진단 — OOS/IS Calmar 비율 ≥ 0.5 권장**

```python
# wf_info의 IS best_score 와 OOS 실제 Calmar 비교
# OOS_calmar / IS_calmar >= 0.5 이면 과적합 없음으로 판단
```

---

### Step 7 — 분기 종목 교체 (`rotation.py` + `backtest/engine.py`)

**7-1. RotationManager 상태 관리**

```python
mgr = RotationManager()
mgr.apply_plan(RotationPlan("2023-01-05", exit_stocks=["A"], deadline_days=20),
               trading_calendar=calendar)

assert "A" in mgr.get_sell_only()
assert mgr.get_force_close_date("A") == calendar[19]   # 20번째 거래일

mgr.complete_exit("A")
assert "A" not in mgr.get_sell_only()
```

**7-2. sell_only — 매수 신호 차단, 청산 신호(0.0) 유지**

```python
size_rot, _ = build_rotated_size_df(mgr, profile, close_df, high_df, low_df, ...)
deadline = mgr.get_force_close_date("A")
pre_mask = size_rot.index < deadline

assert (size_rot.loc[pre_mask, "A"] > 0).sum() == 0        # 매수 신호 차단

size_base, _ = build_size_df(profile, close_df, high_df, low_df, ...)
zero_days = size_base.loc[pre_mask, "A"] == 0.0
assert (size_rot.loc[pre_mask[zero_days], "A"] == 0.0).all()  # 청산 신호 유지
```

**7-3. force_close — 마감일 이후 첫 거래일 0.0**

```python
post_dates = size_rot.index[size_rot.index >= deadline]
assert size_rot.loc[post_dates[0], "A"] == 0.0
```

**7-4. IS 그리드 서치에서 sell_only 종목 제외**

```python
plans = [RotationPlan("2022-04-01", exit_stocks=["A"])]
_, wf_info = run_walk_forward(..., rotation_plans=plans, ...)

for w in wf_info["windows"]:
    if w["train_start"] >= pd.Timestamp("2022-04-01"):
        assert "A" not in w["per_stock"]
        break
```

**7-5. rotation_plans=None — 기존 동작과 동일 (하위 호환)**

```python
pf_base, _ = run_walk_forward(profile, close_df, high_df, low_df, cash_etf=etf)
pf_rot,  _ = run_walk_forward(profile, close_df, high_df, low_df, cash_etf=etf,
                               rotation_plans=None)
pd.testing.assert_series_equal(pf_base.value(), pf_rot.value())
```

---

### Step 8 — 성과 지표 (`metrics/calc.py`, `metrics/report.py`)

**8-1. 11개 지표 전부 계산 확인**

```python
metrics = calc_metrics(pf.value(), benchmark_series=kospi)

required = ["cagr", "mdd", "mdd_duration", "calmar", "sortino",
            "alpha", "beta", "mdd_reduction", "calmar_improvement",
            "info_ratio", "win_rate"]
for key in required:
    assert key in metrics and not np.isnan(metrics[key])
```

**8-2. 설계 명세 목표/경보선 수치 일치**

```python
T, A = profile.METRICS_TARGET, profile.METRICS_ALERT

assert T["cagr"]         == 0.08  and A["cagr"]         == 0.05
assert T["mdd"]          == -0.30 and A["mdd"]          == -0.40
assert T["mdd_duration"] == 24    and A["mdd_duration"] == 36
assert T["calmar"]       == 0.35  and A["calmar"]       == 0.20
assert T["sortino"]      == 0.8   and A["sortino"]      == 0.5
assert T["alpha"]        == 0.02  and A["alpha"]        == 0.0
assert T["beta"]         == 0.8   and A["beta"]         == 1.0
assert T["win_rate"]     == 0.55  and A["win_rate"]     == 0.45
```

**8-3. `build_metrics_table()` — 출력 구조 검증**

```python
table = build_metrics_table(pf.value(), close_df, profile,
                             benchmark_series=kospi, etf_series=etf_price)

# 설계 명세 컬럼 순서: 전략 | 단기채 100% | KOSPI | 목표 | 경보선 | 상태
assert {"단기채 100%", "KOSPI", "목표", "경보선", "상태"}.issubset(table.columns)
assert set(table["상태"].unique()).issubset({"✓", "⚠", "✗", "—"})
```

**8-4. 단기채 대비 우위 판단 흐름**

```python
# 설계 명세 판단 흐름:
# 단기채 CAGR < 전략 CAGR → Alpha 확인 → MDD 확인 → Calmar/Sortino 확인
etf_m   = _calc_equity_metrics(etf_price.reindex(pf.value().index, method="ffill"))
strat_m = calc_metrics(pf.value(), benchmark_series=kospi)
# 전략 CAGR > 단기채 CAGR 이어야 전략 가치 있음
```

---

### 검증 순서 요약

| Step | 대상 | 파일 | 핵심 확인 |
|------|------|------|---------|
| 1 | 지표 계산 | `indicators/` | MA/ADX/BB/ATR 수치 정확성 |
| 2 | 국면 판별 | `strategies/regime.py` | 4국면 조건·우선순위·상호배타성·KOSPI필터 |
| 3 | 신호 생성 | `profiles/neutral.py` | 매수3종·매도5종 size 값·ATR 최우선 |
| 4 | 자금 배분 | `portfolio.py` | 3단계 배분·모멘텀 윈도우·ETF 주차 |
| 5 | 포트폴리오 실행 | `backtest/engine.py` | 다중 종목 동시 매수·cash_sharing·NaN 동작 |
| 6 | WF 최적화 | `backtest/engine.py` | IS/OOS 구간·12조합·모드 전환·fallback |
| 7 | 분기 종목 교체 | `rotation.py` | sell_only·force_close·IS 제외·하위호환 |
| 8 | 성과 지표 | `metrics/` | 11개 지표·목표/경보선 수치·테이블 구조 |
