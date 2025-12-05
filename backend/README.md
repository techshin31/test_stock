# FastAPI API 서버 + LLM 에이전트
│   ├── app/
│   │   ├── api/                      # REST API 라우트
│   │   ├── core/                     # 설정, 보안, DB 연결
│   │   ├── models/                   # DB 모델
│   │   ├── services/                 # 도메인 서비스 (예측, 분석 등)
│   │   ├── agents/                   # LangGraph / LLM Agents
│   │   ├── workflows/                # LangGraph 워크플로우 (AI 전용)
│   │   ├── repositories/             # DB CRUD 계층
│   │   ├── schemas/                  # Pydantic
│   │   └── utils/                    # 헬퍼 함수
│   │
│   ├── tests/                        # 백엔드 테스트
│   ├── scripts/                      # DB 마이그레이션, 유틸 스크립트
│   └── requirements.txt

