# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Environment

```bash
# Python 3.10.x 권장 (vectorbt 0.26.2 공식 지원)
python -m venv .venv
.venv\Scripts\activate          # Windows
pip install -r requirements.txt
```

**버전 고정 이유:** vectorbt 0.26.2는 pandas 1.5.3 + numpy 1.23.5 + numba 0.56.4 조합에서만 안정 동작. pandas 2.0+, numpy 1.24+, Python 3.11+ 에서는 vectorbt 내부 API 비호환 경고 또는 오류 발생. `requirements.txt`의 버전을 임의로 올리지 말 것.

---

## 목표 시스템 구조

이 프로젝트는 두 시스템을 구현한다.

- **백테스팅 시스템** — 투자성향별 전략을 과거 데이터로 검증
- **자동매매 시스템** — 검증된 전략을 실전에 그대로 적용

두 시스템은 `indicators/`, `strategies/`, `profiles/`를 공유한다. 전략 로직을 수정하면 백테스팅과 자동매매에 동시에 반영된다.

```
[공유 계층]  indicators / strategies / profiles
                    ↓                       ↓
[시스템 계층]    backtest/              trading/
               vbt.Portfolio         오늘 주문 dict
```

### 투자성향 → 백테스팅 → 자동매매 흐름

투자성향별로 백테스팅을 통해 전략을 검증하고, 검증된 그대로 자동매매에 적용한다.
`get_profile()` 한 줄만 바꾸면 성향 전환이 된다.

```python
from stock_system.profiles import get_profile
from stock_system.backtest.portfolio import run_walk_forward

profile = get_profile("neutral")    # 또는 "aggressive"

# 1. 백테스팅 — 전략 검증 (vbt 필요)
pf, wf_info = run_walk_forward(profile, close_df, high_df, low_df, volume_df, ...)

# 2. 자동매매 — 검증된 전략 그대로 적용 (vbt 불필요)
# get_signal은 MA120 계산을 위해 최소 150일 이상의 과거 데이터가 필요하다
signal = profile.get_signal(close_df[-200:], high_df[-200:], low_df[-200:], kospi=kospi[-200:])
# → {'삼성전자': 0.35, 'SK하이닉스': 0.28, ...}  오늘 목표 비중 dict
```

`make_signals()`는 두 시스템에서 동일한 함수를 호출한다. 차이는 출력을 어떻게 쓰느냐뿐이다.

```python
# backtest/portfolio.py 내부 — build_size_df()가 종목별로 호출
_, _, size_series, _ = make_signals(close_s, high_s, low_s, **profile_params)
# → 전체 기간 size_series → vbt.Portfolio.from_orders()

# profiles/neutral.py: get_signal() 내부
_, _, size_series, _ = make_signals(close_s, high_s, low_s, **profile_params)
today_size = size_series.iloc[-1]   # 오늘 날짜 값만 추출 → 브로커 주문
```

---

## 목표 패키지 구조

`obsidian/` 폴더 구조와 1:1 대응을 목표로 한다.

```
stock_system/
│
├── config.py                   ← ★ 종목·지수·ETF 설정 (유일한 수정 포인트)
│
├── indicators/                 ← obsidian: TA지표/
│   ├── trend/                  ← 추세/
│   │   ├── ma.py               ← MA_이동평균.md
│   │   └── macd.py             ← MACD.md
│   ├── momentum/               ← 모멘텀/
│   │   └── rsi.py              ← RSI.md
│   ├── volatility/             ← 변동성/
│   │   ├── bollinger.py        ← 볼린저밴드.md
│   │   └── atr.py              ← ATR_평균진폭.md
│   ├── volume/                 ← 거래량/
│   │   └── obv.py              ← OBV_거래량지표.md
│   └── trend_strength/         ← 추세강도/
│       └── adx.py              ← ADX_추세강도.md
│
├── strategies/                 ← obsidian: 매매원칙/
│   ├── regime.py               ← 위험중립형_전략.md "시장 국면 판별" → calc_regime()
│   ├── partial.py              ← 분할매수매도_원칙.md → make_signals()
│   └── inverse_etf.py          ← 인버스ETF_매매원칙.md (추후 추가)
│
├── profiles/                   ← obsidian: 투자성향/
│   ├── base.py                 ← 공통 상수 (FEES, SLIPPAGE, WF_TRAIN_MONTHS, WF_TEST_MONTHS, ADX_PARAM_GRID)
│   ├── neutral.py              ← 위험중립형_전략.md → 파라미터 상수 + get_signal()
│   ├── aggressive.py           ← 적극투자형_전략.md → 파라미터 상수 + get_signal()
│   └── __init__.py             ← get_profile("neutral") 팩토리
│
├── backtest/                   ← 백테스팅 시스템 (vbt 의존)
│   ├── portfolio.py            ← run_walk_forward(profile,...), build_size_df,
│   │                              add_cash_etf, run_bh_portfolio, _walk_forward_portfolio
│   ├── metrics.py              ← obsidian: 성과지표/ — calc_metrics, build_metrics_table
│   └── plots/
│       ├── performance.py      ← 자산곡선, MDD, 기여도, 분산효과, 연도별 수익률
│       ├── strategy.py         ← plot_regime() 국면 시각화
│       └── optimizer.py        ← plot_walkforward_portfolio_comparison()
│
└── trading/                    ← 자동매매 시스템
    ├── data.py                 ← 시장 데이터 수집
    ├── optimizer.py            ← 주기적 WF 실행 → best_params.json 저장
    │                              ※ WF 실행 시 vbt 필요. 개발 머신에서 3개월마다 실행
    ├── signal.py               ← best_params.json 로드 → profile.get_signal() 호출 → 주문 dict
    │                              ※ vbt 불필요. 브로커 서버에서 매일 실행
    └── executor.py             ← 주문 실행 (브로커 API 연동)
```

### 계층별 의존성 원칙

| 계층 | vbt 의존 | 실행 환경 | 역할 |
|------|---------|---------|------|
| `indicators/` | ✗ | 공통 | 지표 계산 + 기본 신호. 순수 pandas |
| `strategies/` | ✗ | 공통 | 지표 조합 + 복합 매매 규칙. 순수 pandas |
| `profiles/` | ✗ | 공통 | 성향별 파라미터 상수 + `get_signal()` |
| `backtest/` | ✓ | 개발 머신 | vbt.Portfolio로 과거 시뮬레이션 |
| `trading/optimizer.py` | ✓ | 개발 머신 | 3개월마다 WF → best_params.json 저장 |
| `trading/signal.py` | ✗ | 브로커 서버 | best_params.json 읽어 오늘 신호 생성 |
| `trading/executor.py` | ✗ | 브로커 서버 | 주문 실행 |

`profiles/`는 `backtest/`를 import하지 않는다. `run_walk_forward()`는 `backtest/portfolio.py`에 위치하며 `profile`을 인자로 받아 파라미터를 꺼내 쓴다.

### 신호 생성 흐름

```
strategies/regime.py: calc_regime(close, high, low, kospi, kospi_ma)
  → 4국면 판별: SIDEWAYS → UPTREND → DOWNTREND → TRANSITION (우선순위 순)
  → KOSPI < MA120 → DOWNTREND 강제 분류 (기존 포지션 전량 청산 트리거)

strategies/partial.py: make_signals(close, high, low, ...)
  → size_series (targetpercent): NaN=유지, 0.0=전량청산, 양수=목표비중
  → ATR stop-loss: size_series 마지막 할당 → 모든 신호 최우선 덮어씀
```

### Walk-Forward 흐름

```
IS 12개월: ADX 파라미터 그리드서치 (Calmar 기준, 12조합)
OOS  3개월: 최적 파라미터 적용 → size_df 생성
슬라이딩 반복 → OOS 구간 이어붙여 단일 vbt.Portfolio 반환
```

- `backtest/portfolio.py: run_walk_forward(profile, ...)` — 전체 기간 WF 백테스팅 (성과 검증용)
- `trading/optimizer.py` — 현재 시점 WF (실전 파라미터 갱신, best_params.json 저장)
- 내부 신호 생성 로직은 동일하며 반환값과 실행 주기만 다르다

---

## obsidian/ — 전략 설계 문서

`obsidian/` 폴더가 Python 구현의 설계 원본이다. Obsidian 문서와 코드 간 불일치가 있으면 **obsidian 문서를 정답**으로 간주한다.

| obsidian 문서 | Python 구현 |
|--------------|------------|
| `투자성향/위험중립형_전략.md` | `profiles/neutral.py` + `strategies/partial.py` + `strategies/regime.py` |
| `투자성향/적극투자형_전략.md` | `profiles/aggressive.py` + `strategies/partial.py` + `strategies/regime.py` |
| `매매원칙/분할매수매도_원칙.md` | `strategies/partial.py` |
| `매매원칙/인버스ETF_매매원칙.md` | `strategies/inverse_etf.py` (추후) |
| `최적화/Walk_Forward_최적화.md` | `backtest/portfolio.py` + `trading/optimizer.py` |
| `성과지표/*.md` | `backtest/metrics.py` |

---

## 구현 가이드

### 사전 작업

`vbt_backtest/` 폴더와 `*.ipynb` 파일은 전부 삭제한다. `stock_system/` 패키지를 새로 생성한다.

---

### `config.py` — 종목 설정 (유일한 수정 포인트)

투자 대상 종목, 시장 지수, 현금 ETF를 한 곳에서 관리한다.
종목 수는 유동적이다 — dict에 줄을 추가/삭제하면 전략·백테스팅·트레이딩 모두 자동 반영된다.

```python
# stock_system/config.py

# ── 투자 대상 종목 ─────────────────────────────────────────────────────────────
# 종목명(표시용): 티커 코드 형태로 자유롭게 추가/삭제
TICKERS = {
    "삼성전자":      "005930.KS",
    "SK하이닉스":    "000660.KS",
    "NAVER":         "035420.KS",
    "카카오":        "035720.KS",
    "LG에너지솔루션": "373220.KS",
}

# ── 시장 기준 지수 (KOSPI 필터용) ─────────────────────────────────────────────
KOSPI_TICKER = "^KS11"

# ── 현금 대체 ETF (유휴 현금 → 단기채 자동 투자) ──────────────────────────────
CASH_ETF_TICKER = "153130.KS"   # KODEX 단기채권
CASH_ETF_NAME   = "단기채"
```

`trading/data.py`와 백테스팅 진입점에서 이 파일을 import한다.

```python
from stock_system.config import TICKERS, KOSPI_TICKER, CASH_ETF_TICKER, CASH_ETF_NAME
```

### 구현 순서

의존성 방향에 따라 아래 순서로 구현한다.

```
1단계: indicators/   (외부 의존성 없음)
2단계: strategies/   (indicators/ 사용)
3단계: profiles/     (strategies/ 지연 import)
4단계: backtest/     (vbt + strategies/ + profiles/ 사용)
5단계: trading/      (profiles/ + backtest/ 선택적 사용)
```

---

### 1단계: `indicators/`

순수 pandas/numpy 계산. 각 파일은 지표 계산 함수만 포함하며 매매 신호를 생성하지 않는다.

| 파일 | 핵심 함수 |
|------|---------|
| `trend/ma.py` | `calc_ma(close, window)` |
| `trend/macd.py` | `calc_macd(close, fast, slow, signal)` |
| `momentum/rsi.py` | `calc_rsi(close, window)` |
| `volatility/bollinger.py` | `calc_bollinger(close, window, num_std)` → upper, mid, lower |
| `volatility/atr.py` | `calc_atr(high, low, close, period)` |
| `volume/obv.py` | `calc_obv(close, volume)` |
| `trend_strength/adx.py` | `calc_adx(high, low, close, window)` → DataFrame(ADX, plus_di, minus_di) |

---

### 2단계: `strategies/`

#### `strategies/regime.py` — `calc_regime()`

KOSPI 통합 후 **SIDEWAYS와 TRANSITION을 반드시 재계산**해야 `masks` dict가 일관성을 유지한다.

```python
def calc_regime(
    close, high, low,
    ma_windows=(20, 60, 120),
    adx_window=14,
    adx_threshold=25.0,
    adx_sideways=20.0,
    kospi=None,
    kospi_ma=120,
):
    ma_s = close.rolling(ma_windows[0]).mean()
    ma_m = close.rolling(ma_windows[1]).mean()
    ma_l = close.rolling(ma_windows[2]).mean()
    adx_df = calc_adx(high, low, close, adx_window)
    adx    = adx_df["ADX"]

    # 우선순위: SIDEWAYS → UPTREND → DOWNTREND → TRANSITION
    SIDEWAYS   = adx < adx_sideways
    UPTREND    = (ma_s > ma_m) & (ma_m > ma_l) & (adx > adx_threshold) & ~SIDEWAYS
    DOWNTREND  = (ma_s < ma_m) & (ma_m < ma_l) & (adx > adx_threshold) & ~SIDEWAYS
    TRANSITION = ~SIDEWAYS & ~UPTREND & ~DOWNTREND

    if kospi is not None:
        kospi_aligned = kospi.reindex(close.index, method="ffill")
        kospi_below   = kospi_aligned < kospi_aligned.rolling(kospi_ma).mean()
        UPTREND    = UPTREND   & ~kospi_below
        DOWNTREND  = DOWNTREND | kospi_below
        SIDEWAYS   = SIDEWAYS  & ~kospi_below       # KOSPI 하락 시 SIDEWAYS도 DOWNTREND로 전환
        TRANSITION = ~SIDEWAYS & ~UPTREND & ~DOWNTREND  # 반드시 재계산

    regime = pd.Series(REGIME_TRANSITION, index=close.index)
    regime[SIDEWAYS]   = REGIME_SIDEWAYS
    regime[UPTREND]    = REGIME_UPTREND
    regime[DOWNTREND]  = REGIME_DOWNTREND   # 마지막 할당 → KOSPI 하락 시 최우선

    masks = {
        "UPTREND": UPTREND, "DOWNTREND": DOWNTREND,
        "SIDEWAYS": SIDEWAYS, "TRANSITION": TRANSITION,
        "ma_s": ma_s, "ma_m": ma_m, "ma_l": ma_l, "adx": adx,
    }
    return regime, masks, adx_df
```

#### `strategies/partial.py` — `make_signals()`

**주의사항 2가지 (obsidian 기준):**

- **1차 진입**: 골든크로스가 아닌 비UPTREND → UPTREND **전환 첫날**.
  UPTREND 분류 시점에는 이미 골든크로스가 지나간 경우가 대부분이라 진입 기회가 극도로 제한된다.
- **2차 진입**: 저가가 MA20 터치 후 회복이 아닌, **종가가 MA20 위에서 유지**됨을 확인하는 것.

```python
# 1차: 비UPTREND → UPTREND 전환 첫날
entry1 = UPTREND & ~UPTREND.shift(1).fillna(False)

# 2차: UPTREND 유지 + 종가가 MA20 위에서 유지 확인
ma20_support = close > ma_s
has_position = entry1.rolling(recent_window, min_periods=1).max().astype(bool)
entry2 = ma20_support & UPTREND & has_position & ~entry1
```

KOSPI 필터는 `calc_regime()` 내부에서 처리되므로 `make_signals()`에 별도 KOSPI 블록을 두지 않는다. `kospi` 파라미터는 `calc_regime()`에 그대로 전달한다.

---

### 3단계: `profiles/`

#### `profiles/base.py`

```python
FEES            = 0.0015
SLIPPAGE        = 0.001
WF_TRAIN_MONTHS = 12
WF_TEST_MONTHS  = 3      # OOS 3개월 → 연 4회 갱신
ADX_PARAM_GRID  = {
    "adx_threshold": [15, 20, 25, 30],
    "adx_sideways":  [10, 15, 20],
}
```

#### `profiles/neutral.py`

```python
from .base import FEES, SLIPPAGE, WF_TRAIN_MONTHS, WF_TEST_MONTHS, ADX_PARAM_GRID  # noqa: F401

ADX_THRESHOLD    = 25.0
ADX_SIDEWAYS     = 20.0
ENTRY1_SIZE      = 0.4
ENTRY2_SIZE      = 0.7
ENTRY_RANGE_SIZE = 0.3
EXIT1_SIZE       = 0.4
EXIT2_SIZE       = 0.1
RECENT_WINDOW    = 60
MOMENTUM_WINDOW  = {"UPTREND": 126, "TRANSITION": 63, "SIDEWAYS": 21}
MIN_MOMENTUM     = 0.0
ATR_PERIOD       = 14
ATR_MULTIPLIER   = 2.0
KOSPI_MA         = 120
CASH_RETURN      = 0.035


def get_signal(close_df, high_df, low_df, kospi=None):
    """오늘의 매매 신호 생성 — 자동매매 시스템 진입점

    Parameters
    ----------
    close_df : DataFrame  최소 150일 이상의 과거 종가 (MA120 warmup 필요)

    Returns
    -------
    dict  종목명 → 오늘 목표 비중 (NaN=유지, 0.0=전량청산, 양수=목표비중)
    """
    from ..strategies.partial import make_signals
    result = {}
    for name in close_df.columns:
        _, _, size_s, _ = make_signals(
            close_df[name], high_df[name], low_df[name],
            adx_threshold=ADX_THRESHOLD,
            adx_sideways=ADX_SIDEWAYS,
            kospi=kospi,
            kospi_ma=KOSPI_MA,
            atr_multiplier=ATR_MULTIPLIER,
            atr_period=ATR_PERIOD,
        )
        result[name] = size_s.iloc[-1]
    return result
```

#### `profiles/aggressive.py`

`neutral.py`와 동일한 구조. 아래 상수가 **모두 정의되어야** `get_signal()`과 `run_walk_forward()`가 오류 없이 동작한다.

```python
from .base import FEES, SLIPPAGE, WF_TRAIN_MONTHS, WF_TEST_MONTHS, ADX_PARAM_GRID  # noqa: F401

ADX_THRESHOLD    = 20.0
ADX_SIDEWAYS     = 15.0
ENTRY1_SIZE      = 0.6
ENTRY2_SIZE      = 0.9
ENTRY_RANGE_SIZE = 0.4
EXIT1_SIZE       = 0.5
EXIT2_SIZE       = 0.2
RECENT_WINDOW    = 40
MOMENTUM_WINDOW  = {"UPTREND": 126, "TRANSITION": 63, "SIDEWAYS": 21}
MIN_MOMENTUM     = 0.05
ATR_PERIOD       = 14
ATR_MULTIPLIER   = 2.5   # 더 민감한 stop-loss
KOSPI_MA         = 120
CASH_RETURN      = 0.035


def get_signal(close_df, high_df, low_df, kospi=None):
    from ..strategies.partial import make_signals
    result = {}
    for name in close_df.columns:
        _, _, size_s, _ = make_signals(
            close_df[name], high_df[name], low_df[name],
            adx_threshold=ADX_THRESHOLD,
            adx_sideways=ADX_SIDEWAYS,
            kospi=kospi,
            kospi_ma=KOSPI_MA,
            atr_multiplier=ATR_MULTIPLIER,
            atr_period=ATR_PERIOD,
        )
        result[name] = size_s.iloc[-1]
    return result
```

#### `profiles/__init__.py`

```python
from . import base, neutral, aggressive

_REGISTRY = {"neutral": neutral, "aggressive": aggressive}

def get_profile(name: str):
    if name not in _REGISTRY:
        raise ValueError(f"Unknown profile: {name}. Available: {list(_REGISTRY)}")
    return _REGISTRY[name]
```

---

### 4단계: `backtest/`

#### `backtest/portfolio.py` — 핵심 함수 목록

| 함수 | 역할 |
|------|------|
| `build_size_df(close_df, high_df, low_df, volume_df, ...)` | 종목별 신호 생성 + 모멘텀 비례 가중치 |
| `add_cash_etf(size_df, close_df, ..., cash_etf_close)` | 잔여 현금 → 단기채 ETF 비중 추가 |
| `_run_portfolio_backtest(close_df, size_df, fees, slippage)` | vbt.Portfolio.from_orders() 래퍼 (내부용) |
| `run_bh_portfolio(close_df, fees, slippage)` | 균등 비중 Buy & Hold |
| `_walk_forward_portfolio(close_df, ..., param_grid, ...)` | IS/OOS 슬라이딩 WF (내부용) |
| `run_walk_forward(profile, close_df, ...)` | 투자성향 파라미터로 WF 실행 (공개 API) |

`run_walk_forward()`는 profile 모듈에서 파라미터를 꺼내 `_walk_forward_portfolio()`에 주입한다. `min_momentum`도 반드시 profile에서 전달해야 적극투자형의 `MIN_MOMENTUM = 0.05`가 적용된다.

```python
def run_walk_forward(profile, close_df, high_df, low_df, volume_df, **kwargs):
    """투자성향 파라미터로 포트폴리오 Walk-Forward 백테스팅 실행"""
    return _walk_forward_portfolio(
        close_df, high_df, low_df, volume_df,
        param_grid=profile.ADX_PARAM_GRID,
        train_months=profile.WF_TRAIN_MONTHS,
        test_months=profile.WF_TEST_MONTHS,
        fees=profile.FEES,
        slippage=profile.SLIPPAGE,
        min_momentum=profile.MIN_MOMENTUM,
        atr_multiplier=profile.ATR_MULTIPLIER,
        atr_period=profile.ATR_PERIOD,
        metric="calmar_ratio",
        **kwargs,
    )
```

#### `backtest/metrics.py` — `build_metrics_table()`

`profile_name` 파라미터를 받아 레이블에 사용한다. "위험중립형" 하드코딩 없이 성향 이름이 자동 반영된다.

```python
def build_metrics_table(pf, pf_bh, close_df, profile_name="위험중립형", benchmark_series=None):
    ...
    (val_09, f"★ {profile_name} 포트"),
```

#### `backtest/plots/performance.py`

`profile_name: str = "위험중립형"` 파라미터를 다음 함수에 추가한다:
`plot_equity_curves()`, `plot_yearly_returns()`, `plot_mdd_comparison()`

---

### 5단계: `trading/`

| 파일 | 역할 | vbt 필요 | 실행 환경 |
|------|------|---------|---------|
| `data.py` | `config.py`의 TICKERS·KOSPI·ETF 티커로 yfinance 데이터 수집 | ✗ | 공통 |
| `optimizer.py` | WF 실행 → `best_params.json` 저장 | ✓ | 개발 머신 (3개월마다) |
| `signal.py` | `best_params.json` → `profile.get_signal()` → 주문 dict | ✗ | 브로커 서버 (매일) |
| `executor.py` | 브로커 API 주문 실행 | ✗ | 브로커 서버 |
