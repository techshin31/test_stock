# API 없이 실행하는 공식 재무·희석 위험 수집

기업 수집은 공식 공개 자료만 사용한다. 인증 DART API 경로는 제거했다. 이제 일반
`collect company`와 `collect all`이 API 키 없이 원본 XBRL과 주요사항 공시를 수집한다.
한국어 API의 502를 해결했다고 주장하지 않으며, 해당 API를 호출하지 않고 작업을
진행하는 공식 자료 경로다. 출처 선택 옵션과 앱의 DART API 키 설정도 제거했다.

## 실제 수집 검증

2026-10-04 기준, 2025-07-01~2026-10-04의 공개 자료를 조회했다.

| 항목 | 검증 결과 |
|---|---:|
| 현재 LARGE 기업 식별 | 100개 |
| 금융 수집 대상 KOSPI | 88개 (다른 시장 12개 제외) |
| 기존 검증된 재무 접수번호 재사용 | 475개 |
| 원본 재무 행 | 237,042행 보존 |
| 공개 KOSPI 희석 위험 공시 | 231건 |
| 과거·현재 LARGE 범위 | 132종목 |
| 대상 기업 위험 공시·상태 저장 | 각 18건 |
| 재무 계보 위반 | 0건 |
| 운영 주문·유니버스·PUBLISHED 분석 | 각각 0건 |

현재 LARGE 재무 수집은 일부 원본 부재·검증 실패 때문에 **PARTIAL(종료 코드 2)**이다.
누락된 접수번호를 정상 수집으로 표시하지 않는다. 원본 12개 항목은 연결 재무 부재 6건,
충돌하는 중복 팩트 5건, 적격 공개 재무 공시 없음 1건으로 제외됐다. 카카오뱅크와
맥쿼리인프라의 원본 한계, 일부 은행·보험 정정본의 모호한 팩트는 임의로 채우지 않는다.
개별 종목은 기존의 검증된 8분기·점수·신뢰도 조건을 통과해야 한다.
현재 시점의 전체 Collector 입력 준비도는 PASS이며, 이는 모든 개별 원본의 수집 완료나
실운용 승인을 뜻하지 않는다.

## 출처와 정책

- 재무: `engopendart.fss.or.kr`의 기업 조회 → 원본 XBRL 목록 → 뷰어 내부 번호 → 원본 ZIP.
  기존 CFS 기업·기간·통화·원본 공시일·기본 제표·대차대조표 등식 검증을 유지한다.
  기존 거래정지·상장 상태를 공개 검색 화면의 ACTIVE 기본값으로 덮어쓰지 않는다.
- 위험: `/disclosureinfo/mainMatter/list.do`의 구조화된 공개 주요사항 화면.
  유상증자 11306(102건), 유무상증자 11308(0건), 전환사채 11324(82건),
  신주인수권부사채 11325(2건), 교환사채 11326(45건)을 검증했다.
- 원본의 기업코드·접수번호·공시일·공시 종류·전체 페이지 수를 대조한다.
  HTTP 200 오류 화면은 ‘공시 없음’으로 취급하지 않는다. 모든 종류·페이지가 완료된 후
  대상 종목의 이벤트를 저장한다. 원본 응답 캐시와 페이지별 SHA256을 보존한다.
- 위험 대상은 요청 기간 내 WICS 규모 조건을 충족했던 종목의 합집합이다. 현재 규모만
  조회해 과거 LARGE 종목의 위험 공시를 누락하지 않는다. 일일 수집은 최소 90일을
  다시 조회해 기존 차단 정책의 기간을 확보한다.
- 위험 상태는 기존 `dart-dilution-v1.0.0`의 90일 매수 차단 정책이다.
  수집 범위는 **POLICY_SCOPE_ONLY**다. 다른 종류의 위험 공시, 정정·철회에 따른
  자동 차단 해제, 전체 역사 공시 피드의 완전성을 검증한 것은 아니다.

공개 수집기는 API 키를 요청에 포함하지 않는다. 기존 키의 대상 호스트 변경,
프록시 우회, TLS 검증 해제를 하지 않았다. 영어 DART의 자발적 영문 공시만으로
한국어 원본 전체를 대체하지 않으며, 위 공개 정형 자료의 식별자와 원본 ZIP을 사용한다.

## 실행 및 증거

```bash
cd /workspace/test_stock
export QUANTPILOT_ENV_FILE=/workspace/test_stock/.env
.venv/bin/python -m apps.worker collect company \
  --company-size LARGE \
  --start 2025-07-01 --end 2026-10-04 --years 2025 2026 \
  --public-cache-dir /workspace/cloud-setup/fa-data-recovery/cache \
  --company-report /workspace/cloud-setup/api-alternative-20261004/company-collection.json \
  --no-progress
```

API 연결 때문에 전체 수집이 멈추는 문제는 이 경로로 피할 수 있다. 부분 완료는 2,
전송·검증 실패로 실행이 중단되면 1을 반환한다. 수집 결과 JSON에 출처·기간·대상·실패
사유를 남긴다. 데이터 준비도 및 분석 결과는 별도로 확인한다.

현재 환경 증거: `/workspace/cloud-setup/api-alternative-20261004`.
`company-collection.json`, `company-collection-repeat.json`, `policy-source-events.json`, `policy-collection.json`,
`source-qa.json`, 원본 페이지 캐시, `unit-tests.log`, `db-tests.log`를 보존한다.
실제 재무·위험 데이터는 DB에 있고 Git에는 코드·테스트·문서를 반영한다.

## 대체 데이터 반영 후 FA 백테스트

운영 DB를 읽기 전용 스냅샷으로 복사한
`quantpilot_fa_research_20261004_922bd769`에서 13개월의 FA 분석을 다시 만들었다.
18개 위험 상태를 각 분석 시점의 공시일과 차단 기간으로 평가했으며, 최종 선정 종목의
8분기 재무·원본 접수번호·공시일 조건과 활성 위험 제외를 별도로 대조했다. 위반은 0건이다.
전체 기간의 선정 이력이 있는 종목은 75개이고, 월별 분석의 선정 수는 38~49개다.

| 항목 | 결과 |
|---|---:|
| 가격 기반 평가 기간 | 2025-10-01~2026-10-02, 243거래일 |
| 초기 자산 | 10,000,000원 |
| 최종 자산 | 13,241,956.67원 |
| 총수익률 | +32.4196% |
| 최대 낙폭 | -33.9261% |
| Sharpe | 0.7809 |
| 거래 | 71건 |
| 월별 교체 | 12회 |
| 동일 입력 재실행 | 자산 곡선·거래 내역·비중 모두 정확히 일치 |

가격 원본은 기존 실제 CSV를 그대로 사용했고, 묶음 SHA256은
`1c0c71035ee58338a9feb1faa92c7b10526f621409a00a1c508446ea3ce44405`다.
위험 공시를 반영한 뒤에도 표시한 수익률·낙폭·거래 수는 이전 엄격 재무 검증 결과와 같다.
같은 기간 KOSPI 수익률은 +102.6645%로, 이 결과는 전략의 시장 대비 우위를 보여주지 않는다.

앞의 11개월은 전체 수집 대상의 가격 이력 준비도 때문에 WARNING이고 마지막 2개월은
PASS다. 선정 종목의 조건과 백테스트 가격 이력은 통과했으며, 기존의 명시적 연구 모드로
실행했다. 공개 화면의 정정 이력 완전성, 당시 상장 기업 전체의 구성 및 거시 데이터 빈티지
검증이 끝난 것은 아니므로 실운용 승인 결과로 사용하지 않는다.

증거는 `research-validation.json`, `research/backtest/metrics.json`,
`research/backtest/report.md`, `research/backtest-audit.json`,
`research/backtest-reproducibility.json`, `research/equity-curve.csv`,
`research/trade-ledger.csv`, `research/weights.csv`에 보존했다.
API 제거 전 코드 검증은 Python 574개, 실제 PostgreSQL 통합 31개, 브라우저 7개 테스트와
대시보드 lint/build가 통과했다.

## 인증 API 제거

계속된 502 때문에 사용하지 않는 인증 DART 클라이언트와 과거 API 전용 로더를 제거했다.
기업 수집 및 진단은 DART API 키를 읽지 않고, COMPANY_DATA_SOURCE 설정도 사용하지 않는다.
`--company-source`는 제거되어 이전 명령은 오류로 종료하므로 위 새 명령을 사용한다.
공개 원본·위험 공시 수집과 원본 검증은 그대로 유지한다. 기존 DB와 원본 캐시는 삭제하지 않는다.

뉴스 감정 분석의 당일 전체시장 DART API 조회도 제거했다. 뉴스 점수는 네이버 기사로만
계산하고, `naver_news_sentiment_v1_YYYY-MM-DD.json`에 저장해 이전 뉴스·DART 혼합
캐시를 재사용하지 않는다. 공개 공시 기반 희석 위험 차단은 별도로 유지한다.
이 변경 이후 실시간 DART 공시 전체를 뉴스 입력으로 제공하지 않는다.

환경 설정에 남은 DART API 키 바인딩은 앱에서 사용하지 않는다. 이 코드 변경은 외부 키를
폐기하거나 플랫폼의 저장된 비밀값을 삭제하는 작업은 아니다.

제거 후 로컬 검증은 Python 522개와 실제 PostgreSQL 통합 31개가 통과했다.
이전 API 전용 테스트를 제거하고, 남은 환경 설정이 API를 선택할 수 없는지,
제거된 CLI 옵션의 거부, 공개 수집 오류의 종료 코드·DB 종료, 뉴스 캐시 분리를 검증한다.
기존 실제 가격과 연구 DB로 FA 백테스트를 다시 실행해 자산 곡선·비중·거래 내역이
모두 정확히 일치했다. 신규 증거는 `/workspace/cloud-setup/remove-dart-api-20261004`의
`unit-tests.log`, `db-tests.log`, `final-regression-tests.log`,
`backtest-reproducibility.json`에 보존한다.
