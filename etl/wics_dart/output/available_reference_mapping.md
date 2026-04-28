# 현재 확보된 FA 참조데이터 연결표

이 문서는 현재 워크스페이스에서 실제로 확보되어 있거나 생성 가능한 참조데이터만 기준으로 정리한다.

## 현재 사용 가능한 파일

- 재무·지표 마스터: `C:\dev\Service_Stock_Analysis\etl\wics_dart\output\company_year_master_2021_2025.csv`
- 최신 참조 번들: `C:\dev\Service_Stock_Analysis\etl\wics_dart\output\company_reference_bundle_latest.csv`
- 최신 시장 스냅샷: `C:\dev\Service_Stock_Analysis\etl\stock\data\market_reference_snapshot_20260327.csv`
- 최신 DART 이벤트 스냅샷: `C:\dev\Service_Stock_Analysis\etl\company\data\dart_reference_events_20210101_20260424.csv`
- 손익계산서 원본: `C:\dev\Service_Stock_Analysis\etl\company\data\income_statement_2025.csv`
- 재무상태표 원본: `C:\dev\Service_Stock_Analysis\etl\company\data\balance_sheet_2025.csv`
- 현금흐름표 원본: `C:\dev\Service_Stock_Analysis\etl\company\data\cash_flow_2025.csv`
- WICS 분류 원본: `C:\dev\Service_Stock_Analysis\etl\wics\data\csv\wics_company_2026.csv`

## 평가항목별 연결

| 평가항목 | 지금 바로 볼 파일 | 바로 확인할 컬럼 | 비고 |
|---|---|---|---|
| 수익성 | `company_reference_bundle_latest.csv` | `revenue`, `operating_income`, `net_income`, `operating_margin`, `roe` | 2025 최신 기준으로 바로 확인 가능 |
| 성장성 | `company_reference_bundle_latest.csv` | `revenue_prev`, `revenue_growth_yoy`, `operating_income_prev`, `operating_income_growth_yoy`, `net_income_prev`, `net_income_growth_yoy` | 전년 대비 추이까지 계산해 둠 |
| 재무안정성 | `company_reference_bundle_latest.csv` | `total_assets`, `total_liabilities`, `total_equity`, `debt_ratio`, `current_ratio` | 부채비율·유동비율 확인 가능 |
| 현금흐름 | `company_reference_bundle_latest.csv` | `operating_cash_flow`, `investing_cash_flow`, `financing_cash_flow`, `ocf_to_revenue` | FCF는 CAPEX 원천을 추가 연결해야 더 정확함 |
| 밸류에이션 | `company_reference_bundle_latest.csv` | `market_cap_wics_raw`, `trading_value_wics_raw`, `shares_outstanding`, `snapshot_date` | 현재는 WICS 로컬 스냅샷 기반. 주가/PER/PBR은 외부 수집 추가 필요 |
| 주주환원 | `dart_reference_events_20210101_20260424.csv` | `event_category='shareholder_return'`, `event_subtype in (cash_dividend, buyback, treasury_disposal, share_cancellation)` | 배당·자사주·소각 공시 확인 가능 |
| 재무생존성 | `company_reference_bundle_latest.csv` | `total_equity`, `operating_cash_flow`, `financing_cash_flow` | 현금및현금성자산/단기금융자산은 원본 현금흐름·재무상태표 계정 추가 추출 필요 |
| 파이프라인/이벤트 | `dart_reference_events_20210101_20260424.csv` | `event_category='pipeline_event'`, `event_subtype in (clinical_trial, approval, technology_transfer)` | 임상·허가·기술수출 이벤트 확인 가능 |
| 비용통제 | `C:\dev\Service_Stock_Analysis\etl\company\data\income_statement_2025.csv` | 원본 계정에서 `판관비`, `연구개발비` 계정 직접 추출 필요 | 아직 마스터에는 미반영 |
| 매출발생력 | `company_reference_bundle_latest.csv` + 사업보고서 원문 | `revenue` + 사업부문/제품 매출 관련 본문 | 세부 매출구성은 사업보고서 본문 확장 필요 |

## 현재 즉시 활용 가능한 핵심 컬럼

- 총 기업 수: `2578`
- 최신 기준연도: `2025`

### 바로 점수화 가능한 항목

- 수익성
- 성장성
- 재무안정성
- 현금흐름
- 일부 밸류에이션(시총/거래대금 기준)

### 아직 추가 수집이 필요한 항목

- 비용통제 세부 계정
- 매출발생력 세부 구분
- 주가/PER/PBR 등 완전한 밸류에이션 지표
