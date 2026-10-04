# 실제 FA/TA 백테스트 및 재무 데이터 검증 — 2026-10-03

> 이 문서는 커밋 a077b9a 시점의 기준 결과다. 이후 개별 종목에도 검증된 8분기 조건을 적용했다. 새 선정 기준과 재백테스트는 [재무 이력 미달 종목 제외 검증](FA_FINANCIAL_HISTORY_EXCLUSION_2026-10-03.md)을 참고한다.


실제 공시 재무와 가격으로 **2025-10-01~2026-10-02, 243거래일** FA/TA 백테스트를 완료했다. 수익률 **+32.42%**, 최대 낙폭 **-33.93%**이며 같은 기간 KOSPI **+102.66%**보다 낮다. 성과 수치는 연구용 과거 재구성 결과다. 실제 과거 발행 또는 실거래 실적이 아니다.

## 데이터 보충 결과

| 자료 | 적재·검증 결과 |
|---|---:|
| 공식 DART 연결재무 | 135기업, 1,850접수번호, 237,042행 |
| 결산기간 | 2023-09-30~2026-06-30 |
| 실제 공시 가용일 | 2023-11-09~2026-09-30 |
| WICS 원본 구성 이력 | 125시점, 282,067행, 2022-09-23~2026-10-01 |
| 구성종목 실제 종가 | 726,839행, 2022-09-01~2026-10-02 |
| 파생 업종 가격 | 19,125행 |
| 기존 실제 매크로 자료 | 7,788행 |
| 연구 DB 분기 FA 관측 | 1,850행; 정정 포함, 고유 분기 수와 구분 |
| 공시·기업·기간 계보 위반 | 0건 |

2026-09-30 기준 지원 업종의 KOSPI 대형주 중 **86/89기업(96.6%)**이 검증된 8개 결산분기를 충족한다. 정정 공시가 분기 수를 늘리지 않도록 결산연도·보고서 종류로 구분했다. 2026-10-02 입력 준비도는 PASS다. 기본 위험 공시 수집과 실거래 준비도까지 통과했다는 의미는 아니다.

카카오뱅크(323410)는 해당 원본에서 CFS 재무가 없고, 맥쿼리인프라(088980)는 해당 공개 XBRL 검색에서 정기 재무 결과가 없다. 삼일전기(062040)는 2026-09-30에 사용 가능한 CFS 결산분기가 5개다. 원본 부재·회계 형식·이력 길이를 임의의 값으로 채우지 않았다. 8분기는 전체 입력 준비도 조건이며 현재 개별 종목 선정의 하드 필터는 아니다. 삼일전기를 포함한 종목은 실제 확보된 분기의 점수·신뢰도 조건으로 선정될 수 있다.

## 수집 경로와 검증

한국어 Open DART API의 프록시 Envoy 502는 여전히 별도 문제다. 프록시 내부 upstream 설정·로그를 확인할 도구가 없어 근본 원인 해결을 주장하지 않는다. 대신 **공식 공개 원본 XBRL**로 필요한 재무 수집을 완료했다.

1. `https://engopendart.fss.or.kr/cmm/searchCorp.do`에서 종목·기업코드·시장 식별을 검증한다.
2. `/disclosureinfo/fnltt/xbrl/list.do`의 기업별 공시 목록에서 접수번호·실제 공시일·결산기간을 확인한다.
3. `/xbrl/viewer/main.do`의 내부 `xbrlExtSeq`를 얻는다.
4. `/xbrl/download/xbrl/origin.do?xbrlExtSeq=...&rcpNo=...&lang=ko`의 실제 ZIP을 파싱한다.

API 키를 읽거나 보내지 않는 별도 공개 수집기다. 기존 키의 영어 API 사용, TLS 검증 해제, 프록시 우회는 하지 않았다. API 인증·일일 할당량 정상 여부는 이 경로의 성공만으로 확인할 수 없다.

원본의 기업 식별·CFS 축·단일 통화 KRW·정확한 결산기간·기본 재무제표 역할·대차대조표 등식을 검증한다. XML 외부 엔티티·DTD를 허용하지 않는다. `decimals=-6`은 값의 정확도 표기이므로 원화 금액에 다시 백만을 곱하지 않는다. 당분기와 연초 누적을 보존하고 Q4는 FY−Q3로 계산한다. 원본의 한국어 표준 계정명을 사용한다. 비교기간 값을 현재 보고서의 과거 공시값으로 소급하지 않는다.

검증한 접수번호와 전체 재무 행을 하나의 트랜잭션으로 저장한다. 실패 응답은 캐시하지 않고 429/502/503/504 및 일시적 전송 오류만 제한적으로 재시도한다. 일부 원본은 연결 정보·중복 팩트·기본 제표 검증을 통과하지 않아 제외했다. WICS 2024-06-14는 033310의 업종 정보가 충돌해 해당 시점 전체를 제외했다.

## 수정한 분석·백테스트 오류

- 누적 흐름이 0일 때 당분기 값으로 대체되던 계산을 수정했다.
- WiseIndex 시가총액의 백만원 단위를 원화 재무와 맞췄다.
- 금융사의 IFRS 영업이익 계정을 지원하고, 비슷한 이름의 소계·모호한 계정을 총액으로 선택하지 않는다.
- 업종 가격 커버리지 분모에 가격 조회 실패 종목도 유지한다.
- 기업 식별 없는 WICS 종목이 결과 원장의 외래키 오류를 일으키지 않도록 제외 사유를 분석 요약에 기록한다.
- OHLCV의 FA 모델 버전을 분석 원장과 일치시킨다.
- 미리 받은 가격 이력을 최소 이력·지표 계산에 사용한다. 첫 편입 전 매매 상태는 만들지 않고, 미래 가격은 최소 이력에 포함하지 않는다.
- 종료일을 포함하도록 가격 요청의 end-exclusive 경계를 처리한다. FA 가격 다운로드 실패·빈 평가기간·부족 이력을 임의로 제외해 성과를 만들지 않는다.
- `fa-reconstructed`는 월별 최신 분석과 빈 선정 월을 보존하며, 모델·기준일을 검증한다. 기본 PASS만 허용한다. WARNING은 연구용 옵션으로만 허용하고 보고서에 명시한다.

## 백테스트 조건과 결과

FA 원천은 `risk_neutral` 월별 분석, 실제 매매 전략은 `fa_ta_momentum`, 점수 버전은 `topdown-fa-v1.1.0`이다. 전월말 공시 기준일 이후 다음 월부터 종목 선정을 적용했다. 13개월 분석에서 매월 39~50기업이 선정됐으며 전체 등장 종목은 76개, 교체 계획은 12건이다.

초기 자본 1천만원, 실제 가격과 거래 비용을 사용했다. 지표용으로 2년 이전부터 데이터를 수집했다. 기본 252일 기준의 실행은 신규 상장 LG CNS(064400)의 최초 편입 당시 이력 부족으로 거부됐다. 이 연구에서는 전략 최장 MA120에 맞춰 **최소 120거래일**을 명시했다. 선택 종목의 실제 조회 실패·최소 이력 제외는 최종 실행에서 0건이다.

| 지표 | 결과 |
|---|---:|
| 최종 평가액 | 13,241,957원 |
| 총 수익률 | +32.42% |
| 최대 낙폭 | -33.93% |
| Sharpe | 0.78 |
| 거래 원장 | 71건 |
| KOSPI 총 수익률 | +102.66% |

입력 가격 CSV와 SHA256을 보존했다. 동일 입력을 별도 프로세스에서 재실행해 **자산곡선·거래 원장·비중의 완전 일치(PASS)**를 확인했다. 증거는 `backtest-reproducibility.json`에 있다. 원본을 다시 조회하면 공급자 보정·응답 상태에 따라 값이 달라질 수 있어 고정 입력을 기준으로 검증한다.

## 연구의 제한과 개선 방향

- 초기 11개월은 전체 구성종목의 3년 가격 이력 커버리지 95% 조건 미달로 WARNING이다. 최신 두 월은 PASS다. 경고를 정상 상태로 바꾸거나 운영 발행에 사용하지 않았다.
- 과거 상장·시장·상장폐지 상태를 완전히 복원한 자료가 아니다. 현재 회사 식별정보와 수집 가능한 과거 공시로 재구성해 생존 편향이 남는다.
- 이 공개 수집은 정기 재무만 대상으로 한다. 과거 위험 공시 피드는 미수집이다. 위험 원장이 비어 있다는 사실이 과거 위험이 없었다는 뜻은 아니다.
- 매크로 저장 가용일 조건을 지켰지만 모든 지표의 최초 발표 빈티지를 완전히 검증한 것은 아니다.
- 일부 은행·보험 원본에는 일반기업과 같은 매출 총계가 없다. 원본에 없는 매출을 합성하지 않아 일부 금융 점수는 LOW_CONFIDENCE다. 금융 전용 지표와 개별 8분기 선정 정책은 별도 검토가 필요하다.
- 현재 `make_signals` 기반 배치 시뮬레이션이다. `evaluate_latest`의 증권사 실시간 가격 기반 손절·트레일링 정책을 실거래 수준으로 재현한 검증은 아니다. 배치와 실제 평가의 정합성은 후속 검증 대상이다.
- KOSPI 대비 약 70.25%p 수익률 열위와 약 34% 낙폭을 보인다. 다음 단계는 입력을 고정한 상태에서 손절·전환 국면·현금 비중을 검증하고, 다른 기간으로 검증하는 것이다.

주 DB의 운영 유니버스·주문은 각각 0행이며 운영 PUBLISHED 분석은 0건이다. 별도 연구 DB에서 분석했으며 PAPER/REAL 주문, 스케줄러, 외부 알림은 실행하지 않았다.

## 재현 및 증거

현재 환경의 증거 폴더: `/workspace/cloud-setup/fa-data-recovery`.

- `source-qa.json`: 주 DB 행 수·계보·준비도
- `research-snapshot.json`: 읽기 전용 원천 복제의 DB·행 수
- `research-analysis.json`: 월별 선정·경고·기준일
- `backtest/metrics.json`, `backtest/report.md`, `backtest/figures`: 성과·해석·차트
- `equity-curve.csv`, `weights.csv`, `trade-ledger.csv`: 계산 원장
- `backtest-inputs`, `backtest-reproducibility.json`: 실제 가격 고정 입력·SHA256·재실행 검증
- `fa-data-quality.ipynb`: 실행된 QA 및 다시 실행 가능한 읽기 전용 SQL
- `companies/*.json`, `cache`: 원본 접수번호별 검증·다운로드 캐시
- `unit-tests.log`, `db-tests.log`: Python 552개, 실제 PostgreSQL 31개 통과

공개 재무 수집은 재실행 시 이미 적재한 접수번호를 건너뛴다.

```bash
cd /workspace/test_stock
export QUANTPILOT_ENV_FILE=/workspace/test_stock/.env
.venv/bin/python -m apps.worker.collector.public_finance \
  --start 2023-09-01 --end 2026-10-02 --years 2023 2024 2025 2026 \
  --cache-dir /workspace/cloud-setup/fa-data-recovery/cache \
  --output /workspace/cloud-setup/fa-data-recovery/recollection.json
```

전용 연구 DB의 재구성 CLI는 다음과 같다. 날짜는 다른 기간으로 확장하기 전에 데이터 범위를 다시 확인한다. 이 CLI는 가격을 다시 조회하므로 고정 입력 재현은 증거 폴더의 `run_research_backtest.py` 및 `verify_reproducibility.py`를 사용한다.

```bash
cd /workspace/test_stock
export QUANTPILOT_ENV_FILE=/workspace/test_stock/.env
export XDG_CACHE_HOME=/workspace/.cache MPLCONFIGDIR=/workspace/.cache/matplotlib
export NUMBA_CACHE_DIR=/workspace/.cache/numba
POSTGRES_DB=quantpilot_fa_research_20261003_9bdab5f4 .venv/bin/python -m apps.backtester run \
  --strategy-name fa_ta_momentum --fa-source-strategy risk_neutral \
  --universe-source fa-reconstructed --allow-research-warnings \
  --fa-model-version topdown-fa-v1.1.0 --min-history-days 120 \
  --start 2025-10-01 --end 2026-10-02 \
  --output-dir /workspace/cloud-setup/fa-data-recovery/backtest-cli
```

연구 DB와 원본 캐시는 현재 클라우드 인스턴스의 검증 증거다. 새 작업에서 그대로 복원되는지 검증한 결과는 아니다. 기존 한국어 API 키 바인딩과 네트워크 설정은 보존했다.
