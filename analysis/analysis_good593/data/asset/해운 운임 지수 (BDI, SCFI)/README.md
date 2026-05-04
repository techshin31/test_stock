# 해운 운임 지수 (BDI / SCFI)

## 수집 파일

| 파일명 | 기간 | 행 수 | 소스 |
|--------|------|-------|------|
| `bdry_2021.csv` | 2021-01-04 ~ 2021-12-31 | 252행 | yfinance `BDRY` |
| `bdry_2022.csv` | 2022-01-03 ~ 2022-12-30 | 251행 | yfinance `BDRY` |
| `bdry_2023.csv` | 2023-01-03 ~ 2023-12-29 | 250행 | yfinance `BDRY` |
| `bdry_2024.csv` | 2024-01-02 ~ 2024-12-31 | 252행 | yfinance `BDRY` |
| `bdry_2025.csv` | 2025-01-02 ~ 현재 | 250행+ | yfinance `BDRY` |

> BDI 원지수(`bdi_{year}.csv`) / SCFI(`scfi_{year}.csv`)는 무료 자동화 API 없음  
> → `collect_shipping.py --mode stooq --apikey KEY` 또는 `--mode convert` 로 별도 수집

- **수집 스크립트:** `collect_shipping.py`

## CSV 포맷

```
Date, Open, High, Low, Close, Volume
2024-01-02, 11.40, 11.40, 10.35, 10.62, 485700
```

| 컬럼 | 설명 | 단위 |
|------|------|------|
| `Date` | 거래일 (YYYY-MM-DD, 오름차순) | — |
| `Open` | 시가 | USD/주 (BDRY ETF) |
| `High` | 고가 | USD/주 |
| `Low` | 저가 | USD/주 |
| `Close` | 종가, **소수점 2자리** | USD/주 |
| `Volume` | 거래량 (BDRY 실거래량) | 주 수 |

> BDI·SCFI 원지수 파일의 경우 Volume은 0 고정 (현물 지수 — 직접 거래 불가)

---

## BDI / BDRY의 경제적 의미

### BDI (Baltic Dry Index)
Baltic Dry Index는 철광석·석탄·곡물 등 **건화물(Dry Bulk)** 운반선 운임을 집계한 지수다.  
원자재를 싣는 선박의 용선료이므로, 실물 경제의 수요가 늘면 선박이 부족해져 운임이 오르고,  
수요가 줄면 선박이 남아돌아 운임이 내려간다.  
주식시장보다 수 주~수 개월 앞서 경기 방향을 가리키는 **글로벌 경기 선행 지표**다.

### BDRY ETF (Breakwave Dry Bulk Shipping ETF)
BDRY는 BDI와 연동된 건화물 해운 주요 기업(Star Bulk, Eagle Bulk 등)에 투자하는 ETF다.  
BDI 원지수와 높은 상관관계를 가지면서도 **yfinance로 자동 수집 가능하고 직접 투자가 가능**하다.

### SCFI (Shanghai Containerized Freight Index)
SCFI는 상하이발 컨테이너 운임을 나타낸다. BDI가 원자재 물동량을 반영한다면  
SCFI는 **완제품(소비재·IT 기기) 물동량**을 반영해 소비 경기의 선행 지표로 활용된다.

---

## 해석 방법

### BDI / BDRY 가격 수준별 해석

| BDRY Close | BDI 환산 수준 | 시장 해석 |
|------------|--------------|-----------|
| $15 이상 | BDI 3,000+ | 건화물 수요 매우 강함, 원자재 슈퍼사이클 |
| $8 ~ $15 | BDI 1,500~3,000 | 경기 확장, 원자재 수요 양호 |
| $4 ~ $8 | BDI 700~1,500 | 경기 중립 또는 완만한 둔화 |
| $4 이하 | BDI 700 이하 | 경기 침체 우려, 수요 급감 |

### 가격 방향성별 해석

| 신호 | 해석 |
|------|------|
| BDRY(BDI) MA 상향 | 원자재 물동량 증가 → 글로벌 교역 활성화 |
| BDRY(BDI) MA 하향 | 물동량 감소 → 경기 둔화 선행 |
| BDI + 구리 동반 상승 | 수요·물동량 모두 증가 → 강한 Risk-On |
| BDI + 구리 동반 하락 | 광범위한 수요 위축 → 강한 Risk-Off |
| SCFI 상승 | 완제품 물동량 증가 → 소비재·IT 섹터 수요 강도 확인 |
| SCFI 하락 | 완제품 수요 감소 → 소비 경기 둔화 선행 |

### WICS 섹터별 영향

| 섹터 | 연관성 | 영향 |
|------|--------|------|
| 산업재 | 매우 높음 | 해운·항만 기업 직접 수익성 반영 |
| 소재 | 높음 | 철강·화학 원자재 수출입 물동량 연동 |
| IT | 낮음 (SCFI는 보통) | 컨테이너 물동량 — 전자제품 수출 간접 반영 |
| 소비재 | 낮음 (SCFI는 보통) | 완제품 운임 → 소비재 공급 비용 간접 영향 |

---

## 백테스팅 활용

### 직접 투자 대상 (BDRY)
BDRY ETF는 실제 포지션 진입 가능 — 해운 업황 상승기 직접 투자 피드로 사용

### 신호 생성 조합 (S-2 매크로 국면 전략)

```
[Risk-On 신호]
BDI/BDRY MA 상향 AND 구리 MA 상향 → 산업재·소재 섹터 편입

[Risk-Off 신호]
BDI/BDRY MA 하향 AND 구리 MA 하향 → 금·국채 비중 확대

[IT 섹터 보조 신호]
SCFI 상승 추세 → 소비재·IT 섹터 수요 강도 확인 (SOX와 교차 검증)
```

### 주의사항
- BDI·SCFI 원지수는 현물 지수로 **직접 투자 불가** — 신호 생성 전용
- BDRY ETF는 직접 투자 가능하나 BDI와 괴리 발생 가능 (레버리지 효과, 롤오버 비용)
- 이동평균은 Backtrader `bt.indicators.SMA`로 전략 내부 계산

---

## 데이터 재수집

```bash
pip install -r requirements.txt

# BDRY ETF 자동 수집 (권장)
python "collect_shipping.py" --mode bdry
python "collect_shipping.py" --mode bdry --start-year 2022 --end-year 2023

# BDI 원지수 (stooq.com API key 필요)
# 1) https://stooq.com/q/d/?s=bdi&get_apikey 접속 → CAPTCHA 풀기 → API key 복사
# 2) 실행
python "collect_shipping.py" --mode stooq --apikey YOUR_API_KEY

# 기존 CSV 파일 변환
python "collect_shipping.py" --mode convert
```
