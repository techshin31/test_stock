# 📌 주식 분석 및 예측 서비스 개발 일정 (Agile Sprint Plan / WBS)

## 📅 전체 개발 전략  
- 스프린트 기간: **2주**
- 전체 기간: **10~14 스프린트 (5~7개월)**
- 목표: 분석 + 예측 + 리포트 + 알림 기능을 가진 투자 인사이트 플랫폼 구축
- 방식: 기능 중심, 점진적 딜리버리(Increments), 백로그 우선순위 기반 진행

---

# 🌀 Sprint 1 — 프로젝트 환경 구축 & 데이터 인프라 셋업
### 🎯 목표
서비스의 기반이 되는 데이터/개발 환경을 세팅한다.

### 📝 Backlog
- Git repo / 브랜치 전략 설정
- FastAPI or Django backend 초기 구조 생성
- React / React Native / Expo 기본 템플릿 설정
- TimescaleDB or PostgreSQL 초기 스키마 설계
- Docker Compose 개발환경 구축
- CI (lint/test/build) 파이프라인 적용

---

# 🌀 Sprint 2 — 종목 기본 정보 API + 데이터 수집 파이프라인 MVP
### 🎯 목표
종목 기본 정보를 제공하고, 가격/메타데이터 수집 자동화를 구축.

### 📝 Backlog
- 거래소 API 연결(과거 OHLCV 수집)
- 종목 메타데이터 DB 저장
- 자동 수집 스케줄러(Airflow/Cron/APS) 도입
- 기본 종목 정보 API 개발
- 결측치 처리/데이터 검증 로직

---

# 🌀 Sprint 3 — 실시간 데이터 스트리밍 & 차트 MVP
### 🎯 목표
실시간 가격 제공 및 차트 화면을 구성한다.

### 📝 Backlog
- WebSocket 기반 실시간 가격 스트림
- Redis Pub/Sub or Kafka 기반 스트리밍 추가
- 차트 UI 연결 (TradingView or lightweight-charts)
- OHLCV API 정교화
- 실시간 지표 계산 (SMA/EMA)

---

# 🌀 Sprint 4 — 기술적 분석 엔진 + 차트 분석 기능 강화
### 🎯 목표
기술적 인디케이터 분석 자동화.

### 📝 Backlog
- 기술적 지표 모듈 개발: MACD, RSI, Bollinger Bands 등
- 지표 시각화(차트 오버레이)
- 백엔드 API(지표 요청)
- 사용자 지표 옵션 UI

---

# 🌀 Sprint 5 — 뉴스 수집 & 감성 분석 + 요약
### 🎯 목표
종목별 뉴스 분석 기반 인사이트 제공.

### 📝 Backlog
- 종목별 뉴스 크롤링/뉴스 API 연동
- 뉴스 감성 분석 모델(Sentiment)
- LLM 기반 뉴스 요약
- 뉴스-종목 매핑 DB 구축
- 뉴스 요약 UI

---

# 🌀 Sprint 6 — LLM 종목 분석 리포트 v1 (LangGraph)
### 🎯 목표
뉴스 + 기술적 분석 + 재무 요인 기반 “종목 리포트” 자동 생성.

### 📝 Backlog
- LangGraph 기반 분석 Agent 설계
  - 뉴스 분석 Agent
  - 기술적 분석 Agent
  - 재무 요약 Agent
- “종목 분석 리포트” 자동 생성 API
- 리포트 UI

---

# 🌀 Sprint 7 — ML 기반 가격 예측 v1
### 🎯 목표
머신러닝 기반 단기 가격 예측 기능 제공.

### 📝 Backlog
- 피처 엔지니어링 파이프라인 구축
- ML 모델(XGBoost, RandomForest) 기반 1일/1시간 예측
- 상승확률(Probability of Rise) 계산
- 모델 성능 검증
- 예측 결과 제공 API

---

# 🌀 Sprint 8 — 딥러닝 모델(LSTM/Transformer) 추가 + 모델 서버 구축
### 🎯 목표
딥러닝 기반 예측 모델을 도입하고 모델 서빙 구조 완성.

### 📝 Backlog
- LSTM 또는 TFT 기반 예측 모델 개발
- 모델 서빙 시스템 구축(ONNX/TorchServe)
- 모델 버전 관리(MLflow)
- 예측 결과 시각화 UI

---

# 🌀 Sprint 9 — 포트폴리오 분석 + 리스크 진단 기능
### 🎯 목표
사용자 보유 종목 분석 기능 추가.

### 📝 Backlog
- 증권사 API 연동(모의연동)
- 포트폴리오 수익률/변동성 계산
- 리스크 지표(VaR, Sharpe 등)
- 종목간 상관관계 분석
- 포트폴리오 분석 UI

---

# 🌀 Sprint 10 — 알림 시스템 MVP
### 🎯 목표
중요 이벤트 기반 알림 제공.

### 📝 Backlog
- 뉴스 이슈 알림
- 급등/급락 알림
- 예측 결과 변화 알림
- Push Noti(Firebase / Expo Push)
- 알림 히스토리 화면

---

# 🌀 Sprint 11 — LLM + ML 결합 기반 고급 분석 (Hybrid AI)
### 🎯 목표
LLM Agent와 예측 모델을 결합한 종합 진단 기능 강화.

### 📝 Backlog
- LangGraph 에이전트 조율(Supervisor)
- 리스크 요인 자동 도출
- 기회/위험 요약 생성
- 자연어 기반 질의응답(“이 종목 왜 올랐어?”)
- 예측 + 뉴스 + 지표 자동 종합 모델

---

# 🌀 Sprint 12 — 고도화 및 최적화
### 🎯 목표
대규모 데이터 처리/성능/UX를 개선하고 출시 준비.

### 📝 Backlog
- DB 인덱스 및 성능 튜닝
- 모델 추론 속도 최적화
- LLM 캐시 적용
- UI/UX 개선
- 최종 QA 및 부하테스트

---

# 🌀 Sprint 13 — 운영 환경 배포 & 시작(Login/회원)
### 🎯 목표
운영 준비 및 인증/보안 체계 완성.

### 📝 Backlog
- Prod 배포 (Docker/K8s)
- OAuth2/JWT 기반 로그인
- 사용자 활동 로그
- 모니터링(Grafana/Loki)
- 운영 문서화

---

# 🌀 Sprint 14 — 정식 런칭 & 피드백 반영
### 🎯 목표
v1 정식 출시 및 사용자 피드백 대응.

### 📝 Backlog
- 초기 사용자 개선 요청 반영
- 버그 수정
- 신규 전략/인사이트 제안 기능 기획
- 다음 iteration 설계

---

# 📌 전체 스프린트 요약 표

| Sprint | 주요 목표 |
|--------|-----------|
| 1 | 환경 구축 |
| 2 | 데이터 수집 |
| 3 | 실시간 시세 & 차트 |
| 4 | 기술적 분석 |
| 5 | 뉴스/감성 분석 |
| 6 | LLM 종목 리포트 |
| 7 | ML 예측 v1 |
| 8 | DL 모델 + 모델 서버 |
| 9 | 포트폴리오 분석 |
| 10 | 알림 시스템 |
| 11 | LLM+ML 결합 |
| 12 | 성능 최적화 |
| 13 | 인증/운영 배포 |
| 14 | 정식 출시 |

