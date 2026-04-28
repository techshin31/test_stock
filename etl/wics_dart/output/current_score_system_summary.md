# 현재 구현된 FA 점수체계 요약

## 1. 현재 실제 계산 방식

현재 점수는 [build_sector_rankings.py](/C:/dev/Service_Stock_Analysis/etl/wics_dart/build_sector_rankings.py:1)를 기준으로 계산된다.

점수 계산 단위:

- 같은 `연도`
- 같은 `WICS 대분류`
- 같은 섹터 내부에서 `상대평가`

즉 절대값 기준 점수가 아니라, 동일 섹터 내 percentile rank 기반 점수다.

## 2. 현재 사용 중인 입력 지표

| 평가영역 | 사용 지표 | 해석 |
|---|---|---|
| 성장성 | `revenue_growth_yoy` | 전년 대비 매출 성장률이 높을수록 우수 |
| 수익성 | `operating_margin`, `roe` | 영업이익률과 ROE가 높을수록 우수 |
| 안정성 | `debt_ratio`, `current_ratio` | 부채비율은 낮을수록, 유동비율은 높을수록 우수 |
| 현금흐름 | `ocf_to_revenue` | 영업현금흐름/매출 비율이 높을수록 우수 |
| 주주환원 | `shareholder_return_raw` | 배당, 자사주 취득, 소각은 가점, 자기주식 처분은 감점 |
| 파이프라인/이벤트 | `pipeline_event_raw` | 임상, 허가, 기술수출 공시가 많을수록 우수 |
| 재무생존성 | `equity_ratio`, `current_ratio`, `capital_support_raw`, `financing_cash_flow` | 자본여력, 유동성, 자금조달 여력을 함께 평가 |
| 비용통제 | `operating_margin`, `ocf_to_revenue` | 적자기업 기준 비용 효율이 좋을수록 우수 |
| 매출발생력 | `revenue`, `major_contract_raw` | 실제 매출 및 계약 발생 기반으로 평가 |

## 3. 점수 계산식

각 지표는 같은 연도·같은 섹터 그룹 안에서 percentile로 환산된다.

| 점수명 | 계산식 |
|---|---|
| `growth_score` | `revenue_growth_yoy_percentile` |
| `profitability_score` | `mean(operating_margin_percentile, roe_percentile)` |
| `stability_score` | `mean(debt_ratio_percentile, current_ratio_percentile)` |
| `cashflow_score` | `ocf_to_revenue_percentile` |
| `shareholder_return_score` | `shareholder_return_raw_percentile` |
| `pipeline_event_score` | `pipeline_event_raw_percentile` |
| `survival_score` | `mean(equity_ratio_percentile, current_ratio_percentile, capital_support_raw_percentile, financing_cash_flow_percentile)` |
| `cost_control_score` | `mean(operating_margin_percentile, ocf_to_revenue_percentile)` |
| `revenue_generation_score` | `mean(revenue_percentile, major_contract_raw_percentile)` |

## 4. 업종별 종합점수 구성

| score_model | 종합점수 구성 |
|---|---|
| `금융` | 수익성 30, 안정성 30, 성장성 10, 주주환원 10 |
| `유틸리티` | 현금흐름 30, 안정성 30, 수익성 20, 주주환원 20 |
| `커뮤니케이션서비스` | 수익성 25, 현금흐름 25, 성장성 20, 안정성 15, 주주환원 15 |
| `에너지` | 현금흐름 25, 수익성 25, 안정성 25, 주주환원 10 |
| `건강관리_profit` | 성장성 25, 수익성 25, 현금흐름 20, 안정성 20 |
| `건강관리_loss` | 재무생존성 40, 파이프라인/이벤트 25, 비용통제 20, 매출발생력 15 |
| `fallback` | 성장성, 수익성, 안정성 동일가중 평균 |

요약 수식:

```text
overall_score
= weighted_mean(업종별로 정의된 서브스코어들)
```

현재 연결되지 않은 지표는 제외하고, 남은 지표만 기준으로 가중 평균을 재정규화한다.

## 5. 점수 구간 해석

| 구간 | 의미 |
|---|---|
| `0.8 이상` | `top_20%` |
| `0.6 이상 0.8 미만` | `top_40%` |
| `0.4 이상 0.6 미만` | `middle` |
| `0.2 이상 0.4 미만` | `bottom_40%` |
| `0.2 미만` | `bottom_20%` |

## 6. 현재 연결된 참조 데이터

| 평가항목 | 지금 보는 파일 | 주요 컬럼 |
|---|---|---|
| 수익성 | [company_reference_bundle_latest.csv](/C:/dev/Service_Stock_Analysis/etl/wics_dart/output/company_reference_bundle_latest.csv) | `revenue`, `operating_income`, `net_income`, `operating_margin`, `roe` |
| 성장성 | [company_reference_bundle_latest.csv](/C:/dev/Service_Stock_Analysis/etl/wics_dart/output/company_reference_bundle_latest.csv) | `revenue_prev`, `revenue_growth_yoy`, `operating_income_growth_yoy`, `net_income_growth_yoy` |
| 재무안정성 | [company_reference_bundle_latest.csv](/C:/dev/Service_Stock_Analysis/etl/wics_dart/output/company_reference_bundle_latest.csv) | `total_assets`, `total_liabilities`, `total_equity`, `debt_ratio`, `current_ratio` |
| 현금흐름 | [company_reference_bundle_latest.csv](/C:/dev/Service_Stock_Analysis/etl/wics_dart/output/company_reference_bundle_latest.csv) | `operating_cash_flow`, `investing_cash_flow`, `financing_cash_flow`, `ocf_to_revenue` |
| 밸류에이션 일부 | [company_reference_bundle_latest.csv](/C:/dev/Service_Stock_Analysis/etl/wics_dart/output/company_reference_bundle_latest.csv) | `market_cap_wics_raw`, `trading_value_wics_raw`, `shares_outstanding`, `snapshot_date` |
| 주주환원 | [dart_reference_events_20210101_20260424.csv](/C:/dev/Service_Stock_Analysis/etl/company/data/dart_reference_events_20210101_20260424.csv) | `event_category='shareholder_return'` |
| 파이프라인/이벤트 | [dart_reference_events_20210101_20260424.csv](/C:/dev/Service_Stock_Analysis/etl/company/data/dart_reference_events_20210101_20260424.csv) | `event_category='pipeline_event'` |

## 7. 설계안과 현재 구현의 차이

현재 구현은 설계안의 업종별 가중치를 반영하고 있다.

다만 아래 항목은 아직 완전하지 않다.

- 밸류에이션: 주가/PER/PBR/EV-EBITDA 전체가 연결된 상태는 아님
- 비용통제: 판관비·연구개발비 세부 계정은 아직 마스터에 미반영
- 매출발생력: 사업보고서 기반 세부 매출구분은 아직 미반영

즉 현재는 `업종별 가중치 모델`이 구현되어 있지만, 일부 항목은 프록시 지표 또는 부분 데이터 기반으로 계산 중이다.
