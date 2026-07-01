# `analyze all` 투자 종목 선정 프로세스

`python -m apps.worker analyze all` 명령이 투자 종목을 최대 10개 선정하는 전체 흐름을 설명한다.

**최종 목표**: KOSPI LARGE 기업 **최대 10개** (최대 5개 산업 × 산업별 최대 2개) 선정

---

## 전체 흐름 요약

```
25개 WICS 산업 (전체 지원)
  └─ 산업별 FA 스코어 모델 적용 (GENERAL_V1 / FINANCIAL_V1 / BIOTECH_V1)
      └─ 17개 매크로 시그널 방향 × 매크로-산업 기여도 × FA 개선도 × 유동성으로 채점
          └─ UP 수혜 5개(up_benefit_score) + DOWN 헤지 3개(down_hedge_score) → 8개 후보풀
              └─ 후보풀 내 sector_score 정렬 → 5개 산업 선정
                  └─ 산업별 LARGE 기업 FA 랭킹 → 각 최대 2개 선택
                      └─ 최종 최대 10개 종목
```

---

## 산업별 FA 스코어 모델

WICS 25개 전체 산업을 지원하며, 산업 특성에 따라 3가지 모델을 적용한다.
코호트는 `fiscal_quarter + score_model_code` 조합으로 분리되어 모델 간 비교가 발생하지 않는다.

### GENERAL_V1 — 일반 제조·서비스 (20개 산업)

G1010·G1510·G2010·G2020·G2030·G2510·G2520·G2530·G2550·G2560·G3010·G3020·G3030·G3510·G4510·G4520·G4530·G5010·G5020·G5510

| 축 | 지표 (가중치) | 만점 |
|----|--------------|------|
| **Level** | 영업이익률(10), ROE(10), 부채비율(7.5), 유동비율(7.5), OCF/매출(7.5), OCF/순이익(3.75), FCF(3.75), PER(5), PBR(5) | 60점 |
| **Change** | 매출성장률YoY(10), 영업이익성장률(8), 영업이익률변화(6), 영업현금흐름변화(6) | 30점 |
| **Risk** | 순이익(+)·OCF(−)(−3), 부채비율 급등>50%(−3), 매출↑+이익↓+OCF↓(−3) | 10점 |

### FINANCIAL_V1 — 금융 (4개 산업)

G4010 은행 · G4020 보험 · G4030 증권 · G4040 다각화금융

부채비율·유동비율은 금융사 특성상 의미가 없어 제외하고, ROE·ROA 비중을 높인다.

| 축 | 지표 (가중치) | 만점 |
|----|--------------|------|
| **Level** | ROE(20), ROA(15), 영업이익률(12.5), PBR(7.5), PER(5) | 60점 |
| **Change** | 매출성장률YoY(12), 영업이익성장률(12), 영업이익률변화(6) | 30점 |
| **Risk** | 순손실(−5), 영업적자(−3), 매출↑+이익↓+OCF↓(−3) | 10점 |

> GENERAL_V1 대비 제외: 부채비율, 유동비율, OCF/매출, OCF/순이익, FCF
> OCF 패널티 제거: 금융사 OCF에는 고객 자금 이동이 포함되어 음수가 정상

### BIOTECH_V1 — 제약·바이오 (1개 산업)

G3520 제약·바이오·생명과학

R&D 단계 기업은 매출 없음·영업손실이 정상이므로 수익성 대신 **생존력(유동성) + 손실 축소 궤적** 중심으로 평가한다.

| 축 | 지표 (가중치) | 만점 |
|----|--------------|------|
| **Level** | 유동비율(20), 부채비율(15), ROE(10), ROA(10), PBR(5) | 60점 |
| **Change** | 영업이익률변화YoY(12), 매출성장률YoY(10), 영업현금흐름변화(8) | 30점 |
| **Risk** | 유동비율<1.0(−5), 부채비율 급등>50%(−3), 매출↓+OCF↓(−3) | 10점 |

> GENERAL_V1 대비 제외: 영업이익률, OCF/매출, OCF/순이익, FCF, PER, 영업이익성장률
> 영업이익성장률 제외: 영업손실 기업끼리의 증감률은 방향이 역전되어 왜곡 발생

---

## STEP 0. 실행 준비 (`prepare_run`)

### Readiness 검사

분석 시작 전 Collector가 다음 데이터를 모두 준비했는지 확인한다.
하나라도 부족하면 즉시 중단(`SourceReadinessError`).

- 17개 매크로 시그널 최신 데이터
- WICS 스냅샷 + 업종 가격 이력 (~3년)
- LARGE 기업 분기 재무제표 커버리지
- `company_risk_states` 계약

### Run 생성 규칙

| 조건 | 동작 |
|------|------|
| 동일 (target + analysis_month + cutoff + input_hash)의 PASS run 존재 | 기존 run 재사용 (`created: false`) |
| 없음 | 신규 run INSERT (`created: true`) |
| `--force` 플래그 | 항상 신규 run 생성 |

1시간 이상 RUNNING 상태인 stale run은 FAIL 처리 후 새 run을 생성한다.

---

## STEP 1. 분기 FA 스코어링 (`refresh_quarterly_scores`)

전 종목의 재무제표를 동일 코호트 내 백분위 점수로 환산한다.
결과는 `company_quarter_fa` 테이블에 UPSERT된다.

### 1-1. 원시 데이터 → 개별 분기 변환

DART 누적 손익 데이터(1Q=1Q, 2Q=1Q+2Q, ...)를 개별 분기 값으로 역산한다.

파생 지표:

| 지표 | 계산식 |
|------|--------|
| `operating_margin` | 영업이익 / 매출 |
| `roe` | 순이익 / 자본 |
| `roa` | 순이익 / 자산 |
| `debt_ratio` | 부채 / 자본 |
| `current_ratio` | 유동자산 / 유동부채 |
| `ocf_to_revenue` | 영업현금흐름 / 매출 |
| `ocf_to_net_income` | 영업현금흐름 / 순이익 |
| `fcf` | 영업현금흐름 − \|CAPEX\| |
| `per_proxy` | 시가총액 / 순이익 |
| `pbr_proxy` | 시가총액 / 자본 |
| YoY 변화 지표 | 전년 동분기 대비 변화율/변화량 |

### 1-2. 모델별 코호트 채점

`score_model_code`로 분리된 코호트 내에서 각 모델의 지표를 백분위로 변환한다.
모델 배정은 WICS 산업 코드로 자동 결정된다 (`score_model_for(industry_code)`).

적용 모델은 위 **"산업별 FA 스코어 모델"** 섹션 참고.

### 1-3. 탈락 기준 (`is_eligible = false`)

| 사유 | 조건 |
|------|------|
| `CAPITAL_IMPAIRMENT` | `total_equity ≤ 0` (자본잠식) |
| `LOW_CONFIDENCE` | `score_confidence < 0.70` |
| `LOW_FA_SCORE` | `fa_score < 50.0` |
| `MAPPING_ERROR` | 알 수 없는 산업 코드 또는 비활성 상태 |

---

## STEP 2. 매크로 분석 (`run_macro_analysis`)

17개 시그널의 방향을 판단하고, 각 산업과의 관계를 계산한다.
결과는 `fa_macro_results` 테이블에 INSERT된다.

### 2-1. 17개 매크로 시그널

| 시그널 | 카테고리 | 주기 | 변환 방식 |
|--------|----------|------|-----------|
| COPPER | COMMODITY | DAILY | MARKET_RETURN |
| GOLD | COMMODITY | DAILY | MARKET_RETURN |
| WTI | COMMODITY | DAILY | MARKET_RETURN |
| TNX | RATES | DAILY | YIELD_CHANGE |
| CPI | RATES | MONTHLY | CPI_YOY_PRESSURE |
| SOX | RISK | DAILY | MARKET_RETURN |
| BDRY | RISK | DAILY | MARKET_RETURN |
| VIX | RISK | DAILY | MARKET_RETURN |
| GPR | RISK | MONTHLY | MARKET_RETURN |
| DXY | FX | DAILY | MARKET_RETURN |
| USDKRW | FX | DAILY | MARKET_RETURN |
| US2Y | RATES | DAILY | YIELD_CHANGE |
| ISM_PMI | MANUFACTURING | MONTHLY | LEVEL |
| SEMIPROD | MANUFACTURING | MONTHLY | YOY_CHANGE |
| GTREND_KPOP | HALLYU | MONTHLY | LEVEL |
| GTREND_KDRAMA | HALLYU | MONTHLY | LEVEL |
| KR_TOURIST | HALLYU | MONTHLY | YOY_CHANGE |

### 2-2. 방향 판단 (UP / DOWN / FLAT)

변환 타입에 따라 계산 방식이 다르다.

**DAILY 시그널 (MARKET_RETURN / YIELD_CHANGE)**

3개 윈도우에서 변화량을 변동성으로 정규화 후 가중 합산한다.

```
trend_raw = Σ (정규화_변화량 × 가중치)

윈도우별 가중치:
  20일  → 0.2 (단기)
  60일  → 0.3 (중기)
  120일 → 0.5 (장기)
```

**MONTHLY 시그널 (GPR — MARKET_RETURN)**

```
윈도우별 가중치:
  3개월  → 0.2
  6개월  → 0.3
  12개월 → 0.5
```

**CPI_YOY_PRESSURE / YOY_CHANGE 시그널**

월간 YoY 변화율을 먼저 계산한 뒤, 그 변화량(가속도)을 정규화한다.

```
trend_raw = normalized[3] × 0.4 + normalized[6] × 0.6

윈도우: 3개월, 6개월
최소 19개 월간 관측치 필요
```

**ISM_PMI (LEVEL 방식)**

```
trend_raw = (latest - 50.0) / 2.0

방향 판단:
  latest > 52.0  →  UP
  latest < 48.0  →  DOWN
  그 외          →  FLAT
```

**공통 방향 판단 (ISM_PMI 제외)**

```
trend_raw ≥  0.5  →  UP
trend_raw ≤ -0.5  →  DOWN
그 외             →  FLAT
```

### 2-3. 매크로-산업 관계 계산

25개 전체 산업 × 17개 시그널의 모든 조합에 대해 계산한다.

- 주간/월간 수익률 시계열로 상관계수·베타·부호 안정성 산출
- `relationship_confidence = sample_confidence × correlation_confidence × sign_stability`
- 조건(`minimum_abs_correlation ≥ 0.15`, `relationship_confidence ≥ 0.50`) 미충족 시 비적격
- 적격 관계에서 `contribution` 점수 산출 → 섹터 분석의 입력값

```
contribution = direction_sign × correlation × trend_strength × confidence × (1/17)
```

---

## STEP 3. 섹터 분석 (`run_sector_analysis`)

25개 전체 산업 각각에 점수를 매기고 최종 3개를 선정한다.
결과는 `fa_sector_results` 테이블에 INSERT된다.

### 3-1. 산업별 종합 점수 계산

```
sector_score = macro_fit  × 0.45
             + fa_breadth × 0.35
             + liquidity  × 0.20
             − risk_penalty
```

| 축 | 구성 |
|----|------|
| **macro_fit (45%)** | 매크로 contribution 합산 → −1~1 범위 클램핑 → 0~100점 변환 |
| **fa_breadth (35%)** | 중간 FA점수 백분위(40%) + 개선율(35%) + 신뢰도(25%) |
| **liquidity (20%)** | 거래대금 백분위(60%) + eligible LARGE 기업 수 / 2개 기준(40%) |

**카테고리별 기여도 상한선**: 각 매크로 카테고리(COMMODITY, RATES, RISK, FX, MANUFACTURING, HALLYU)의 기여도 절대값 합계는 최대 0.30으로 제한된다. 초과분은 잘라낸다.

**risk_penalty 항목**:

| 조건 | 감점 |
|------|------|
| 종목 커버리지 < 80% | −10점 |
| 관계 신뢰도 < 50% | −5점 |
| 구성 종목 < 3개 | −5점 |
| 시가총액 집중도 > 50% 초과분 | 최대 −10점 |

### 3-2. 후보풀 8개 구성

UP 수혜 풀과 DOWN 헤지 풀로 나눠 8개 산업을 `is_candidate = true`로 표시한다.
이 후보풀이 최종 5개 선정의 **1차 대상**이 된다.

| 풀 | 기준 | 개수 |
|----|------|------|
| **UP 풀** | `up_benefit_score` 내림차순 | 5개 (`candidate_up_count`) |
| **DOWN 풀** | `down_hedge_score` 내림차순 (UP 풀 중복 제외) | 3개 (`candidate_down_count`) |
| **FALLBACK** | 8개 미충족 시 `sector_score` 기준으로 채움 | 부족분 |

- `up_benefit_score`: UP 방향 시그널 중 적격 관계의 `correlation × trend_strength × confidence / 17` 합산
- `down_hedge_score`: DOWN 방향 시그널 중 적격 관계의 `|correlation| × trend_strength × confidence / 17` 합산

### 3-3. 최종 5개 선정

**후보풀 8개**를 `sector_score` 내림차순으로 정렬 후 순서대로 순회한다.

| 탈락 조건 | 사유 코드 |
|-----------|-----------|
| `eligible_large_count < 2` | `INSUFFICIENT_LARGE` |

후보풀에서 5개를 채우지 못하면 나머지 비후보 산업을 `sector_score` 내림차순으로 순회해 FALLBACK 선발한다.
그래도 5개를 채우지 못하면 `sector_selection` 검증 FAIL.

---

## STEP 4. 기업 선정 (`run_company_selection`)

선정된 최대 5개 산업에서 각 최대 2개씩, 총 10개 이하를 선정한다.
결과는 `fa_company_results` 테이블에 INSERT된다.

### 4-1. 하드 필터

| 조건 | 기준 |
|------|------|
| 시장 | KOSPI |
| 규모 | LARGE |
| 상태 | ACTIVE |
| FA 점수 | ≥ 50.0 |
| 점수 신뢰도 | ≥ 0.70 |
| 자본 | `total_equity > 0` |
| 위험 상태 | `company_risk_states`에 없음 (BLOCK_BUY/SELL_ONLY) |

### 4-2. 산업별 랭킹 → 상위 최대 2개 선택

필터 통과 기업을 다음 기준으로 정렬한다 (우선순위 순):

1. `fa_score` 내림차순
2. `score_confidence` 내림차순
3. `latest_trd_amt` (거래대금) 내림차순
4. `stock_code` 오름차순 (동점 처리)

rank 1, 2번까지 **최종 선정** (`is_selected = true`)한다.

---

## STEP 5. 검증 (`validate_run`)

6개 검증 항목을 DB에서 재조회해 계약을 검증한다.
모두 PASS여야 `fa_analysis_runs.status_code = PASS`.

| 항목 | 기준 |
|------|------|
| `macro_results` | 17개 완전, 누락 없음 |
| `macro_point_in_time` | `last_available_date ≤ cutoff_date` |
| `sector_selection` | 선정 5개 이하 |
| `company_selection` | 총 10개 이하, 업종별 2개 이하 |
| `company_contract` | KOSPI·LARGE·ACTIVE, `available_date ≤ cutoff_date` |
| `company_risk` | `effective_date` 기준 매수 차단 없음 |

---

## STEP 6. 발행 (`publish_universe`, `--publish` 전용)

검증 PASS 확인 후 단일 트랜잭션으로 운영 universe를 교체한다.

```
기존 ACTIVE 중 미선정 종목  →  SELL_ONLY + 20거래일 청산 기한
신규 선정 종목(최대 10개)   →  ACTIVE (upsert)
fa_analysis_runs            →  PUBLISHED
```

**발행 가능일**: `effective_date` 당일 또는 그 이전

`effective_date` 당일에는 08:30 KST 이후에도 `--publish`를 실행할 수 있다.
`effective_date`가 지난 뒤에는 `publish effective_date is in the past` 오류로 거부된다.

---

## 관련 DB 테이블

| 테이블 | 작업 | 내용 |
|--------|------|------|
| `fa_analysis_runs` | INSERT / UPDATE | run 생성, 상태 추적 |
| `company_quarter_fa` | UPSERT | 분기 FA 스코어 (모델별 코호트 분리) |
| `fa_macro_results` | INSERT | 매크로 방향 + 산업 관계 |
| `fa_sector_results` | INSERT | 산업 채점·선정 결과 |
| `fa_company_results` | INSERT | 기업 선정 결과 |
| `universe` | UPDATE / UPSERT | 운영 포트폴리오 (`--publish`만) |

---

## 공식 월간 실행 순서

```powershell
python -m apps.worker collect all
python -m apps.worker analyze all                # PASS 여부 확인
python -m apps.worker analyze all --publish      # 운영 universe 확정
python -m apps.trader planner
python -m apps.trader executor
python -m apps.trader reconciler
```

두 번째 `analyze all`은 검증용이고, 세 번째 `analyze all --publish`가 trader 입력인 운영 universe를 확정하는 단계다.
