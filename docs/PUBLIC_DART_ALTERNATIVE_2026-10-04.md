# API 없이 실행하는 공식 재무·희석 위험 수집

기업 수집의 기본 경로를 인증 DART API에서 공식 공개 자료로 바꿨다. 이제 일반
`collect company`와 `collect all`이 API 키 없이 원본 XBRL과 주요사항 공시를 수집한다.
한국어 API의 502를 해결했다고 주장하지 않으며, 해당 API를 호출하지 않고 작업을
진행하는 별도 경로다. 기존 인증 API는 `--company-source api`로 선택할 수 있다.

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
  --company-source public --company-size LARGE \
  --start 2025-07-01 --end 2026-10-04 --years 2025 2026 \
  --public-cache-dir /workspace/cloud-setup/fa-data-recovery/cache \
  --company-report /workspace/cloud-setup/api-alternative-20261004/company-collection.json \
  --no-progress
```

API 연결 때문에 전체 수집이 멈추는 문제는 이 경로로 피할 수 있다. 부분 완료는 2,
전송·검증 실패로 실행이 중단되면 1을 반환한다. 수집 결과 JSON에 출처·기간·대상·실패
사유를 남긴다. 데이터 준비도 및 분석 결과는 별도로 확인한다.

현재 환경 증거: `/workspace/cloud-setup/api-alternative-20261004`.
`company-collection.json`, `policy-source-events.json`, `policy-collection.json`,
`source-qa.json`, 원본 페이지 캐시, `unit-tests.log`, `db-tests.log`를 보존한다.
실제 재무·위험 데이터는 DB에 있고 Git에는 코드·테스트·문서를 반영한다.
