# 검증된 재무 8분기 미달 종목 제외 및 재백테스트

재무 이력이 부족한 종목을 선정 대상에서 제외하도록 수정했다. 원본 재무 237,042행과 공시 1,850건은 보존했다. 2025-10-01~2026-10-02의 재백테스트에서 전체 등장 종목은 76개에서 75개로 줄었으며 수익률 **+32.42%**, 최대 낙폭 **-33.93%**, 거래 원장 **71건**은 이전 결과와 정확히 같다. 삼일전기의 기존 실제 매수 비중이 0이었고, 다른 월별 제외도 거래 원장을 바꾸지 않았다. 이는 입력 자격을 바로잡는 변경이며 성과 개선을 입증하는 변경은 아니다.

## 선정 기준

- 기준일 이전에 공개된 연결재무(CFS)의 검증된 분기가 최소 8개여야 한다.
- 같은 사업연도·보고서 종류의 정정 공시는 하나의 분기로 센다. 기준일에 보이는 최신 정정본이 불완전하면 그 분기는 인정하지 않는다.
- BS, IS/CIS, CF가 같은 접수번호에 있어야 하며, 기업코드·공시일·기간을 원본 공시와 대조한다. 미래 공개 자료, OFS, LEGACY 또는 계보가 확인되지 않은 자료는 포함하지 않는다.
- 전체 준비도와 개별 선정이 동일한 SQL 정의를 사용한다. 개별 분기 수를 확인할 수 없으면 0으로 처리해 제외한다.
- 이력 미달 FA 점수는 업종 품질·적격 대형주 수에도 기여하지 않는다. 구성종목 전체는 커버리지 분모에 남긴다.
- `INSUFFICIENT_FINANCIAL_HISTORY`와 확보 분기 수·요구 분기 수·기준일을 기록한다. 선택되지 않은 업종에 속한 미달 종목도 분석의 `validation_summary.financial_history_exclusions`에 남긴다.

`FaV1Config.minimum_financial_quarters`의 기본값은 8이고 8 미만 설정은 거부한다. 새 필드가 분석 설정 fingerprint에 포함돼 이전 분석 캐시를 재사용하지 않는다. 점수 산식의 `topdown-fa-v1.1.0` 버전은 유지하며, 월별 입력 해시와 결과를 새로 생성했다.

## 실제 선정 변화

| 적용 월 | 종목 | 기준일 당시 확보 분기 | 변경 |
|---|---|---:|---|
| 2026-01 | HD현대마린솔루션(443060) | 6 | 49 → 48종목 |
| 2026-05 | HD현대마린솔루션(443060) | 7 | 44 → 43종목 |
| 2026-07 | 삼일전기(062040) | 4 | 48 → 47종목 |
| 2026-09 | 삼일전기(062040) | 5 | 46 → 45종목 |
| 2026-10 | 삼일전기(062040) | 5 | 46 → 45종목 |

HD현대마린솔루션은 8분기를 확보한 다른 월에는 선정될 수 있다. 카카오뱅크(323410, CFS 부재)와 맥쿼리인프라(088980, 해당 공개 원본 없음)는 기존에도 선정되지 않았고 계속 제외된다. 2026-09-30 현재 원천 8분기 충족률은 여전히 86/89(96.6%)다. 미달 종목을 분모에서 지워 100%로 표시하지 않는다.

## 검증 및 재현

별도 연구 DB `quantpilot_fa_research_20261003_b6e70713`에 주 DB 원천을 읽기 전용 REPEATABLE READ 트랜잭션으로 복제했다. 이전 연구 DB와 결과는 보존했다. 13개월 선정 원장 전체에서 기준일·시행일·분기 수·최신 점수 연결을 다시 조회해 위반 0건을 확인했다. 운영 유니버스·주문·PUBLISHED 분석은 0이다.

가격은 이전 실행의 원본 CSV를 재사용했다. 전체 고정 입력 묶음 SHA256은 `1c0c71035ee58338a9feb1faa92c7b10526f621409a00a1c508446ea3ce44405`이며, 새 실행은 이 묶음 중 선정된 75종목을 사용한다. 재실행의 자산곡선·비중·거래 원장을 완전 일치로 검증했다. 이전 실행과도 자산곡선·거래 원장·공통 종목의 비중이 정확히 같고, 제거된 삼일전기 열은 전 기간 0이었다.

- Python 테스트 557개 통과.
- 실제 PostgreSQL 테스트 31개 통과. 정상 8분기, 동일 분기 정정, OFS, 불완전 최신 정정, 미래 정정, 잘못된 공시일, 원본 공시 없음, CIS, LEGACY, 미래 기간 등을 확인했다.
- 원본과 실패 사유를 보존하고, 미래 공시를 과거 시점의 분기 수로 사용하지 않는다.

새 증거 경로: `/workspace/cloud-setup/fa-strict-history`.

- `research-snapshot.json`, `research-analysis.json`: 복제와 월별 분석
- `exclusion-validation.json`: 월별 제외 사유·확보 분기 수·원천 보존 검증
- `before-after-comparison.json`: 이전 결과와 실제 비교
- `backtest/metrics.json`, `backtest/report.md`, `backtest/figures`: 재백테스트 결과
- `equity-curve.csv`, `weights.csv`, `trade-ledger.csv`: 계산 원장
- `backtest-reproducibility.json`: 같은 입력의 별도 프로세스 재실행

고정 가격은 `/workspace/cloud-setup/fa-data-recovery/backtest-inputs`에 보존돼 있다. 원본을 다시 내려받으면 공급자의 응답이 달라질 수 있다. 연구 결과를 반복하려면 해당 폴더와 연구 DB를 보존하고 아래 헬퍼를 사용한다.

```bash
cd /workspace/test_stock
export QUANTPILOT_ENV_FILE=/workspace/test_stock/.env
export PYTHONPATH=/workspace/test_stock
export XDG_CACHE_HOME=/workspace/.cache
export MPLCONFIGDIR=/workspace/.cache/matplotlib NUMBA_CACHE_DIR=/workspace/.cache/numba
.venv/bin/python /workspace/cloud-setup/fa-strict-history/validate_exclusions.py
.venv/bin/python /workspace/cloud-setup/fa-strict-history/verify_reproducibility.py
```

이는 연구용 재구성이다. 이전 보고서의 초기 11개월 가격 이력 WARNING, 현재 식별정보에 따른 생존 편향, 위험 공시 미수집, 미검증 매크로 최초 발표 빈티지, 배치와 실제 주문 위험 평가의 차이는 남아 있다. KOSPI +102.66% 대비 수익률 열위도 그대로다. 한국어 API의 Envoy 502 근본 원인 역시 이 변경으로 해결됐다고 판단하지 않는다.
