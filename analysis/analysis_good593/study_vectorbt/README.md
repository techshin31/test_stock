# vectorbt 백테스팅 학습 커리큘럼

## 환경 설정

### 버전 요구사항

| 항목 | 권장 버전 | 비고 |
|------|-----------|------|
| Python | **3.10.x** | 3.11도 동작하나 numba 경고 발생 가능 |
| vectorbt | 0.26.2 | PyPI 최신 안정 버전 |
| pandas | **1.5.3** | 2.0+ 는 vectorbt와 API 비호환 |
| numpy | 1.24.4 | numba 0.58.x 호환 범위 |

### 가상환경 생성 및 패키지 설치

```powershell
# 1. 가상환경 생성
#    Python 3.10 이 기본이 아닌 경우: py -3.10 -m venv .venv
python -m venv .venv

# 2. 가상환경 활성화 (Windows)
.venv\Scripts\activate

# 3. pip 최신화
python -m pip install --upgrade pip

# 4. 패키지 설치
pip install -r requirements.txt

# 5. Jupyter 커널 등록 (노트북에서 이 환경을 선택할 수 있게 됨)
python -m ipykernel install --user --name vectorbt-study --display-name "Python (vectorbt)"

# 6. Jupyter 실행
jupyter notebook
```

> **설치 확인**: 아래 명령어로 주요 패키지가 정상 설치됐는지 확인하세요.
> ```powershell
> python -c "import vectorbt as vbt; import pandas as pd; print(vbt.__version__, pd.__version__)"
> ```
> 출력 예시: `0.26.2  1.5.3`

### 디렉토리 구조

```
study_vectorbt/
├── requirements.txt             ← 패키지 버전 고정 파일
├── 02_vectorbt_핵심개념.ipynb   ← 2단계 강의 노트북
├── 03_전략_구현.ipynb            ← 3단계 강의 노트북
├── 04_성과분석_최적화.ipynb      ← 4단계 강의 노트북
├── 05_실전_확장.ipynb            ← 5단계 강의 노트북
├── strategies/
│   ├── golden_cross.py          ← 골든크로스 전략 모듈
│   ├── rsi_strategy.py          ← RSI 전략 모듈
│   └── macd_strategy.py         ← MACD 전략 모듈
└── utils/
    └── data_loader.py           ← 데이터 로딩 공통 함수
```

---

## 1단계 · 기초 준비 (약 1~2일)

사전 지식과 환경을 세팅하는 단계예요.

- Python 기본 문법 확인
- `pandas`, `numpy` 기본 사용법 익히기
- vectorbt 설치: `pip install vectorbt`
- `yfinance` 등으로 주가 데이터 불러오기

```python
import vectorbt as vbt
import yfinance as yf

# 데이터 받아오기 예시
df = yf.download("AAPL", start="2020-01-01", end="2024-01-01")
close = df["Close"]
```

---

## 2단계 · vectorbt 핵심 개념 (약 3~5일)

vectorbt의 기본 작동 방식을 이해하는 단계예요.

- `Portfolio.from_signals()` 사용법
- 롱/숏 시그널을 True/False 배열로 표현하기
- 수수료(fees), 슬리피지(slippage) 설정
- 수익률 기본 계산

```python
entries = close < close.shift(1)  # 예시: 전날보다 낮으면 매수
exits   = close > close.shift(1)  # 예시: 전날보다 높으면 매도

pf = vbt.Portfolio.from_signals(close, entries, exits, fees=0.001)
print(pf.total_return())
```

---

## 3단계 · 전략 구현 (약 1~2주)

실제 매매 전략을 코드로 만들어보는 단계예요.

- 이동평균 골든크로스 전략
- RSI, MACD 등 기술 지표 활용
- `ta` 또는 `pandas-ta` 라이브러리 연동
- 진입/청산 조건을 시그널 배열로 변환하기

```python
# 골든크로스 예시
fast = close.rolling(20).mean()
slow = close.rolling(60).mean()

entries = (fast > slow) & (fast.shift(1) <= slow.shift(1))
exits   = (fast < slow) & (fast.shift(1) >= slow.shift(1))

pf = vbt.Portfolio.from_signals(close, entries, exits, fees=0.001)
```

---

## 4단계 · 성과 분석 & 최적화 (약 1~2주)

전략의 성과를 분석하고 파라미터를 최적화하는 단계예요.

- `pf.stats()` — 샤프비율, 최대낙폭(MDD), 승률 등 한 번에 확인
- `pf.plot()` — 자산 곡선, 드로우다운 시각화
- 파라미터 그리드 서치 (여러 조합 한꺼번에 테스트)
- 과최적화(오버피팅) 주의
- in-sample / out-of-sample 분리 검증

```python
# 성과 분석
pf.stats()

# 파라미터 최적화 예시 (fast/slow 조합 탐색)
fast_windows = [10, 20, 30]
slow_windows = [60, 120]

for fw in fast_windows:
    for sw in slow_windows:
        fast = close.rolling(fw).mean()
        slow = close.rolling(sw).mean()
        entries = (fast > slow) & (fast.shift(1) <= slow.shift(1))
        exits   = (fast < slow) & (fast.shift(1) >= slow.shift(1))
        pf = vbt.Portfolio.from_signals(close, entries, exits)
        print(f"fast={fw}, slow={sw}, 수익률={pf.total_return():.2%}")
```

> ⚠️ 파라미터를 너무 최적화하면 과거 데이터에만 잘 맞는 전략이 될 수 있어요. 반드시 학습 기간과 검증 기간을 분리해서 테스트하세요.

---

## 5단계 · 실전 확장 (약 2~4주+)

실전에 가까운 고급 기능을 익히는 단계예요.

- 멀티 자산 동시 백테스팅
- 포트폴리오 비중 최적화 (Kelly, 마코위츠 등)
- 실시간 데이터 연동 개념 이해
- 나만의 전략 라이브러리 구축

```python
# 멀티 자산 예시
tickers = ["AAPL", "MSFT", "GOOGL"]
data = yf.download(tickers, start="2020-01-01", end="2024-01-01")
close = data["Close"]

# 각 자산에 동일한 전략 적용
fast = close.rolling(20).mean()
slow = close.rolling(60).mean()

entries = fast > slow
exits   = fast < slow

pf = vbt.Portfolio.from_signals(close, entries, exits, fees=0.001)
pf.stats()
```

---

## 참고 자료

| 자료 | 링크 |
|------|------|
| 공식 문서 | https://vectorbt.dev |
| GitHub | https://github.com/polakowo/vectorbt |
| yfinance | https://pypi.org/project/yfinance/ |
| pandas-ta | https://github.com/twopirllc/pandas-ta |

---

> 💡 **학습 팁**: 단순한 전략(이동평균 크로스)부터 완전히 이해한 뒤 복잡한 전략으로 넘어가는 게 훨씬 효과적이에요.