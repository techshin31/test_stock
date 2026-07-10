-- ============================================================
-- Common code seed data
-- Run after 01_codes_schema.sql.
-- ============================================================

INSERT INTO code_groups VALUES
    ('ORDER_SIDE_CODE',      '주문 방향',    '매수/매도 구분'),
    ('ORDER_TYPE_CODE',      '주문 유형',    '시장가/지정가 등 주문 방식'),
    ('ORDER_STATUS_CODE',    '주문 상태',    '주문 처리 단계'),
    ('MARKET_TYPE_CODE',     '거래소',       '종목이 상장된 거래소'),
    ('INSTRUMENT_TYPE_CODE', '종목 유형',    '주식/ETF/선물/암호화폐 구분'),
    ('PLAN_STATUS_CODE',       '계획 상태',      '당일 거래 계획의 처리 단계'),
    ('TRADE_REASON_CODE',     '매매 사유',      '거래 계획을 생성한 전략 신호 종류'),
    ('UNIVERSE_STATUS_CODE',  '유니버스 상태',  '투자 대상 종목의 운용 단계')
ON CONFLICT DO NOTHING;

INSERT INTO codes VALUES
    -- 주문 방향
    ('ORDER_SIDE_CODE',      'BUY',       '매수',   NULL,                           1, TRUE),
    ('ORDER_SIDE_CODE',      'SELL',      '매도',   NULL,                           2, TRUE),
    -- 주문 유형
    ('ORDER_TYPE_CODE',      'MARKET',    '시장가', '즉시 체결',                    1, TRUE),
    ('ORDER_TYPE_CODE',      'LIMIT',     '지정가', '희망 가격 지정',               2, TRUE),
    ('ORDER_TYPE_CODE',      'STOP',      '스탑',   '트리거 가격 도달 시 시장가',   3, TRUE),
    ('ORDER_TYPE_CODE',      'STOP_LIMIT','스탑 지정가', '트리거 후 지정가 주문',   4, TRUE),
    -- 주문 상태
    ('ORDER_STATUS_CODE',    'PENDING',   '대기',      '증권사 제출 전',                        1, TRUE),
    ('ORDER_STATUS_CODE',    'SUBMITTED', '제출됨',    '증권사 API 호출 완료 — 접수 확인 전',   2, TRUE),
    ('ORDER_STATUS_CODE',    'ACCEPTED',  '접수됨',    '증권사가 주문번호 발급 및 접수 확인',   3, TRUE),
    ('ORDER_STATUS_CODE',    'PARTIAL',   '부분 체결', '일부 수량만 체결',                      4, TRUE),
    ('ORDER_STATUS_CODE',    'FILLED',    '완전 체결', '전량 체결 완료',                        5, TRUE),
    ('ORDER_STATUS_CODE',    'MODIFIED',  '정정 완료', '주문 정정 처리 완료',                   6, TRUE),
    ('ORDER_STATUS_CODE',    'CANCELLED', '취소',      '주문 취소됨',                           7, TRUE),
    ('ORDER_STATUS_CODE',    'REJECTED',  '거부',      '증권사 주문 거부',                      8, TRUE),
    ('ORDER_STATUS_CODE',    'EXPIRED',   '만료',      '유효시간 초과로 자동 소멸',             9, TRUE),
    -- 거래소
    ('MARKET_TYPE_CODE',     'KOSPI',     'KOSPI',  '한국 유가증권시장',            1, TRUE),
    ('MARKET_TYPE_CODE',     'KOSDAQ',    'KOSDAQ', '한국 코스닥시장',              2, TRUE),
    ('MARKET_TYPE_CODE',     'NASDAQ',    'NASDAQ', '미국 나스닥',                  3, TRUE),
    ('MARKET_TYPE_CODE',     'NYSE',      'NYSE',   '미국 뉴욕증권거래소',          4, TRUE),
    ('MARKET_TYPE_CODE',     'CRYPTO',    '암호화폐 거래소', '업비트, 바이낸스 등', 5, TRUE),
    -- 종목 유형
    ('INSTRUMENT_TYPE_CODE', 'STOCK',     '주식',   NULL,                           1, TRUE),
    ('INSTRUMENT_TYPE_CODE', 'ETF',       'ETF',    '상장지수펀드, 매도 시 거래세 없음', 2, TRUE),
    ('INSTRUMENT_TYPE_CODE', 'FUTURES',   '선물',   '매도 시 거래세 없음',          3, TRUE),
    ('INSTRUMENT_TYPE_CODE', 'CRYPTO',    '암호화폐', NULL,                         4, TRUE),
    -- 계획 상태
    ('PLAN_STATUS_CODE',     'PENDING',   '대기',   '장중 실행 전',                 1, TRUE),
    ('PLAN_STATUS_CODE',     'ORDERED',   '주문됨', '주문 제출 완료',               2, TRUE),
    ('PLAN_STATUS_CODE',     'DONE',      '완료',   '체결 확인됨',                  3, TRUE),
    ('PLAN_STATUS_CODE',     'SKIPPED',   '건너뜀', '조건 미충족으로 미실행',       4, TRUE),
    ('PLAN_STATUS_CODE',     'CANCELLED', '취소',   NULL,                           5, TRUE),
    -- 매매 사유
    -- 유니버스 상태
    ('UNIVERSE_STATUS_CODE', 'ACTIVE',    '정상 매매',   'FA 선정 후 정상 매수·매도 가능',         1, TRUE),
    ('UNIVERSE_STATUS_CODE', 'SELL_ONLY', '매도 전용',   '로테이션 대기 — 신규 매수 금지, 청산만 허용', 2, TRUE),
    ('UNIVERSE_STATUS_CODE', 'REMOVED',   '제거됨',      '청산 완료 후 유니버스에서 제외',          3, TRUE),
    -- 매매 사유
    ('TRADE_REASON_CODE',    'UPTREND_ENTRY1',        '상승장 1차 매수',  '상승장 진입 신호 — 1차 분할매수',         1, TRUE),
    ('TRADE_REASON_CODE',    'UPTREND_ENTRY2',        '상승장 2차 매수',  '상승장 진입 신호 — 2차 분할매수',         2, TRUE),
    ('TRADE_REASON_CODE',    'REBALANCE_SELL',        '리밸런싱 매도',    '목표 비중 초과 종목 비중 조정 매도',       3, TRUE),
    ('TRADE_REASON_CODE',    'DEFENSIVE_ALLOCATION',  '방어자산 배분',    '단기채 ETF 매수 또는 매도로 방어 비중 조정', 4, TRUE),
    ('TRADE_REASON_CODE',    'TRANSITION_EXIT',       '전환장 비중 축소', '상승 → 전환 국면 진입 시 비중 축소',      5, TRUE),
    ('TRADE_REASON_CODE',    'DEADCROSS',             '데드크로스 비중 축소', '데드크로스 발생 시 비중 축소',         6, TRUE),
    ('TRADE_REASON_CODE',    'DOWNTREND',             '하락장 청산',      '하락장 진입 — 전 종목 청산',              7, TRUE),
    ('TRADE_REASON_CODE',    'ATR_STOP',              'ATR 손절',         'ATR 기반 손절 트리거 발동',               8, TRUE),
    ('TRADE_REASON_CODE',    'REBALANCE_BUY',         '리밸런싱 매수',    '목표 비중 미달 종목 비중 조정 매수',       9, TRUE),
    ('TRADE_REASON_CODE',    'NO_SIGNAL',             '무신호',           '오늘 발생한 전략 신호 없음 (목표 비중 없음)', 10, TRUE),
    ('TRADE_REASON_CODE',    'BELOW_MIN_QTY',         '최소수량 미달',    '목표-현재 비중 차이가 최소 주문 수량 미달', 11, TRUE),
    ('TRADE_REASON_CODE',    'SELL_ONLY_BLOCKED',     'SELL_ONLY 매수차단', 'SELL_ONLY 종목의 추가 매수 신호 차단',  12, TRUE)
ON CONFLICT DO NOTHING;

INSERT INTO code_groups VALUES
    ('MACRO_SIGNAL_CODE',   '매크로 시그널', '글로벌 매크로 시그널 종류'),
    ('MACRO_CATEGORY_CODE', '매크로 분류',   '매크로 시그널의 자산 분류'),
    ('MACRO_SOURCE_CODE',   '매크로 소스',   '매크로 시그널 원천 데이터 출처'),
    ('FREQUENCY_CODE',      '발표 주기',     '시계열 데이터의 발표/수집 주기')
ON CONFLICT DO NOTHING;

INSERT INTO codes VALUES
    -- 매크로 시그널 (description에 원천 티커 기재)
    ('MACRO_SIGNAL_CODE', 'COPPER', '구리 선물',              'HG=F',          1, TRUE),
    ('MACRO_SIGNAL_CODE', 'GOLD',   '금 선물',                'GC=F',          2, TRUE),
    ('MACRO_SIGNAL_CODE', 'WTI',    'WTI 원유 선물',          'CL=F',          3, TRUE),
    ('MACRO_SIGNAL_CODE', 'TNX',    '미국 10년 국채금리',      '^TNX',          4, TRUE),
    ('MACRO_SIGNAL_CODE', 'CPI',    '미국 소비자물가지수',     'FRED CPIAUCSL', 5, TRUE),
    ('MACRO_SIGNAL_CODE', 'SOX',    '필라델피아 반도체 지수',  '^SOX',          6, TRUE),
    ('MACRO_SIGNAL_CODE', 'BDRY',   '건화물 운임 ETF (BDI 대체)', 'BDRY',        7, TRUE),
    ('MACRO_SIGNAL_CODE', 'DXY',    '달러 인덱스 선물',        'DX=F',          8, TRUE),
    ('MACRO_SIGNAL_CODE', 'VIX',           '시장 공포지수',                   '^VIX',             9,  TRUE),
    ('MACRO_SIGNAL_CODE', 'USDKRW',        '원/달러 환율',                    'KRW=X',            10, TRUE),
    ('MACRO_SIGNAL_CODE', 'US2Y',          '미국 2년물 국채금리',             '^IRX',             11, TRUE),
    ('MACRO_SIGNAL_CODE', 'GPR',           '지정학적 리스크 지수',            'GPR_MONTHLY',      12, TRUE),
    ('MACRO_SIGNAL_CODE', 'ISM_PMI',       'ISM 제조업 PMI (50 기준선)',      'NAPMPMI',          13, TRUE),
    ('MACRO_SIGNAL_CODE', 'US_MFG_IP',     '미국 제조업 산업생산지수',        'IPMAN',            13, TRUE),
    ('MACRO_SIGNAL_CODE', 'SEMIPROD',      '반도체 및 전자부품 산업생산지수', 'IPGMFGS',          14, TRUE),
    ('MACRO_SIGNAL_CODE', 'GTREND_KPOP',   'Google Trends K-pop 글로벌 검색', 'K-pop',            15, TRUE),
    ('MACRO_SIGNAL_CODE', 'GTREND_KDRAMA', 'Google Trends Korean drama 검색', 'Korean drama',     16, TRUE),
    ('MACRO_SIGNAL_CODE', 'KR_TOURIST',    '외국인 관광객 월별 입국자 수',    'inbnd_touris_num', 17, TRUE),
    -- 매크로 분류
    ('MACRO_CATEGORY_CODE', 'COMMODITY', '원자재',         NULL, 1, TRUE),
    ('MACRO_CATEGORY_CODE', 'RATES',     '금리/인플레이션', NULL, 2, TRUE),
    ('MACRO_CATEGORY_CODE', 'RISK',      '위험 지표',      NULL, 3, TRUE),
    ('MACRO_CATEGORY_CODE', 'FX',        '외환',           NULL, 4, TRUE),
    ('MACRO_CATEGORY_CODE', 'MANUFACTURING', '제조업 지표', NULL, 5, TRUE),
    ('MACRO_CATEGORY_CODE', 'HALLYU',        '한류 지표',   NULL, 6, TRUE),
    -- 매크로 소스
    ('MACRO_SOURCE_CODE', 'YAHOO',   'Yahoo Finance (yfinance)',       NULL, 1, TRUE),
    ('MACRO_SOURCE_CODE', 'FRED',    'Federal Reserve Economic Data',  NULL, 2, TRUE),
    ('MACRO_SOURCE_CODE', 'GPR',     'Caldara & Iacoviello GPR Index', NULL, 3, TRUE),
    ('MACRO_SOURCE_CODE', 'GTRENDS', 'Google Trends (pytrends)',       NULL, 4, TRUE),
    ('MACRO_SOURCE_CODE', 'KTO',     '한국관광공사 공공데이터포털 API', NULL, 5, TRUE),
    -- 발표 주기
    ('FREQUENCY_CODE', 'DAILY',   '일간', NULL, 1, TRUE),
    ('FREQUENCY_CODE', 'MONTHLY', '월간', NULL, 2, TRUE)
ON CONFLICT DO NOTHING;

INSERT INTO code_groups VALUES
    ('COMPANY_STATUS_CODE', '기업 상태', 'KRX 상장 상태 — ACTIVE/SUSPENDED/DELISTED')
ON CONFLICT DO NOTHING;

INSERT INTO codes VALUES
    ('COMPANY_STATUS_CODE', 'ACTIVE',    '정상 상장', 'KRX에 정상 상장·거래 중',        1, TRUE),
    ('COMPANY_STATUS_CODE', 'SUSPENDED', '거래 정지', '관리종목 또는 거래정지 상태',     2, TRUE),
    ('COMPANY_STATUS_CODE', 'DELISTED',  '상장 폐지', 'KRX에서 퇴출된 종목',            3, TRUE)
ON CONFLICT DO NOTHING;

INSERT INTO code_groups VALUES
    ('DART_EVENT_CATEGORY_CODE', 'DART 이벤트 분류', '배당·자사주·증자 등 이벤트 대분류'),
    ('DART_EVENT_SUBTYPE_CODE',  'DART 이벤트 세부', '이벤트 세부 유형')
ON CONFLICT DO NOTHING;

INSERT INTO codes VALUES
    -- 이벤트 대분류
    ('DART_EVENT_CATEGORY_CODE', 'SHAREHOLDER_RETURN', '주주환원',   NULL, 1, TRUE),
    ('DART_EVENT_CATEGORY_CODE', 'CAPITAL_CHANGE',     '자본변동',   NULL, 2, TRUE),
    ('DART_EVENT_CATEGORY_CODE', 'PIPELINE_EVENT',     '파이프라인', NULL, 3, TRUE),
    ('DART_EVENT_CATEGORY_CODE', 'BUSINESS_EVENT',     '사업이벤트', NULL, 4, TRUE),
    ('DART_EVENT_CATEGORY_CODE', 'REGULAR_REPORT',     '정기공시',   NULL, 5, TRUE),
    -- 이벤트 세부유형 (B타입 — 주요사항보고서)
    ('DART_EVENT_SUBTYPE_CODE', 'CASH_DIVIDEND',            '현금배당',        NULL, 1,  TRUE),
    ('DART_EVENT_SUBTYPE_CODE', 'BUYBACK',                  '자사주매입',      NULL, 2,  TRUE),
    ('DART_EVENT_SUBTYPE_CODE', 'TREASURY_DISPOSAL',        '자사주처분',      NULL, 3,  TRUE),
    ('DART_EVENT_SUBTYPE_CODE', 'SHARE_CANCELLATION',       '주식소각',        NULL, 4,  TRUE),
    ('DART_EVENT_SUBTYPE_CODE', 'PAID_IN_CAPITAL_INCREASE', '유상증자',        NULL, 5,  TRUE),
    ('DART_EVENT_SUBTYPE_CODE', 'BONUS_ISSUE',              '무상증자',        NULL, 6,  TRUE),
    ('DART_EVENT_SUBTYPE_CODE', 'CONVERTIBLE_BOND',         '전환사채',        NULL, 7,  TRUE),
    ('DART_EVENT_SUBTYPE_CODE', 'BOND_WITH_WARRANT',        '신주인수권부사채', NULL, 8,  TRUE),
    ('DART_EVENT_SUBTYPE_CODE', 'EXCHANGE_BOND',            '교환사채',        NULL, 9,  TRUE),
    ('DART_EVENT_SUBTYPE_CODE', 'CLINICAL_TRIAL',           '임상시험',        NULL, 10, TRUE),
    ('DART_EVENT_SUBTYPE_CODE', 'APPROVAL',                 '품목허가',        NULL, 11, TRUE),
    ('DART_EVENT_SUBTYPE_CODE', 'TECHNOLOGY_TRANSFER',      '기술이전',        NULL, 12, TRUE),
    ('DART_EVENT_SUBTYPE_CODE', 'MAJOR_CONTRACT',           '대형계약',        NULL, 13, TRUE),
    ('DART_EVENT_SUBTYPE_CODE', 'INVESTMENT_DECISION',      '투자결정',        NULL, 14, TRUE),
    -- 이벤트 세부유형 (A타입 — 정기공시)
    ('DART_EVENT_SUBTYPE_CODE', 'ANNUAL_REPORT',      '사업보고서',  NULL, 15, TRUE),
    ('DART_EVENT_SUBTYPE_CODE', 'SEMI_ANNUAL_REPORT', '반기보고서',  NULL, 16, TRUE),
    ('DART_EVENT_SUBTYPE_CODE', 'Q1_REPORT',          '1분기보고서', NULL, 17, TRUE),
    ('DART_EVENT_SUBTYPE_CODE', 'Q3_REPORT',          '3분기보고서', NULL, 18, TRUE)
ON CONFLICT DO NOTHING;

INSERT INTO code_groups VALUES
    ('WICS_SECTOR_CODE',   'WICS 대분류', 'WICS 섹터 분류 (Sector, G + 2자리)'),
    ('WICS_INDUSTRY_CODE', 'WICS 중분류', 'WICS 산업군 분류 (Industry Group, G + 4자리)'),
    ('COMPANY_SIZE_CODE',  '종목 규모',   'KRX 시가총액 기준 종목 규모 (대형주/중형주/소형주)')
ON CONFLICT DO NOTHING;

INSERT INTO codes VALUES
    -- WICS 대분류 (Sector) — 10개 섹터
    ('WICS_SECTOR_CODE', 'G10', '에너지',             NULL, 1,  TRUE),
    ('WICS_SECTOR_CODE', 'G15', '소재',               NULL, 2,  TRUE),
    ('WICS_SECTOR_CODE', 'G20', '산업재',             NULL, 3,  TRUE),
    ('WICS_SECTOR_CODE', 'G25', '경기소비재',         NULL, 4,  TRUE),
    ('WICS_SECTOR_CODE', 'G30', '필수소비재',         NULL, 5,  TRUE),
    ('WICS_SECTOR_CODE', 'G35', '건강관리',           NULL, 6,  TRUE),
    ('WICS_SECTOR_CODE', 'G40', '금융',               NULL, 7,  TRUE),
    ('WICS_SECTOR_CODE', 'G45', 'IT',                 NULL, 8,  TRUE),
    ('WICS_SECTOR_CODE', 'G50', '커뮤니케이션서비스', NULL, 9,  TRUE),
    ('WICS_SECTOR_CODE', 'G55', '유틸리티',           NULL, 10, TRUE),
    -- WICS 중분류 (Industry Group) — G + 4자리
    ('WICS_INDUSTRY_CODE', 'G1010', '에너지',                    NULL, 1,  TRUE),
    ('WICS_INDUSTRY_CODE', 'G1510', '소재',                      NULL, 2,  TRUE),
    ('WICS_INDUSTRY_CODE', 'G2010', '자본재',                    NULL, 3,  TRUE),
    ('WICS_INDUSTRY_CODE', 'G2020', '상업서비스와공급품',        NULL, 4,  TRUE),
    ('WICS_INDUSTRY_CODE', 'G2030', '운송',                      NULL, 5,  TRUE),
    ('WICS_INDUSTRY_CODE', 'G2510', '자동차와부품',              NULL, 6,  TRUE),
    ('WICS_INDUSTRY_CODE', 'G2520', '내구소비재와의류',          NULL, 7,  TRUE),
    ('WICS_INDUSTRY_CODE', 'G2530', '호텔레스토랑레저',          NULL, 8,  TRUE),
    ('WICS_INDUSTRY_CODE', 'G2550', '소매(유통)',                NULL, 9,  TRUE),
    ('WICS_INDUSTRY_CODE', 'G2560', '소비자서비스',              NULL, 10, TRUE),
    ('WICS_INDUSTRY_CODE', 'G3010', '식품과기본식료품소매',      NULL, 11, TRUE),
    ('WICS_INDUSTRY_CODE', 'G3020', '식품음료담배',              NULL, 12, TRUE),
    ('WICS_INDUSTRY_CODE', 'G3030', '가정용품과개인용품',        NULL, 13, TRUE),
    ('WICS_INDUSTRY_CODE', 'G3510', '건강관리장비와서비스',      NULL, 14, TRUE),
    ('WICS_INDUSTRY_CODE', 'G3520', '제약과생물공학',            NULL, 15, TRUE),
    ('WICS_INDUSTRY_CODE', 'G4010', '은행',                      NULL, 16, TRUE),
    ('WICS_INDUSTRY_CODE', 'G4020', '다각화된금융',              NULL, 17, TRUE),
    ('WICS_INDUSTRY_CODE', 'G4030', '보험',                      NULL, 18, TRUE),
    ('WICS_INDUSTRY_CODE', 'G4040', '부동산',                    NULL, 19, TRUE),
    ('WICS_INDUSTRY_CODE', 'G4510', '소프트웨어와서비스',        NULL, 20, TRUE),
    ('WICS_INDUSTRY_CODE', 'G4520', '기술하드웨어와장비',        NULL, 21, TRUE),
    ('WICS_INDUSTRY_CODE', 'G4530', '반도체와반도체장비',        NULL, 22, TRUE),
    ('WICS_INDUSTRY_CODE', 'G5010', '미디어와엔터테인먼트',      NULL, 23, TRUE),
    ('WICS_INDUSTRY_CODE', 'G5020', '전기통신서비스',            NULL, 24, TRUE),
    ('WICS_INDUSTRY_CODE', 'G5510', '유틸리티',                  NULL, 25, TRUE)
ON CONFLICT DO NOTHING;

INSERT INTO codes VALUES
    ('COMPANY_SIZE_CODE', 'LARGE', '대형주', 'KRX 시가총액 기준 상위 1~100위',    1, TRUE),
    ('COMPANY_SIZE_CODE', 'MID',   '중형주', 'KRX 시가총액 기준 상위 101~300위',  2, TRUE),
    ('COMPANY_SIZE_CODE', 'SMALL', '소형주', 'KRX 시가총액 기준 상위 301위 이하', 3, TRUE)
ON CONFLICT DO NOTHING;

INSERT INTO code_groups VALUES
    ('FA_RUN_STATUS_CODE', 'FA 실행 상태', '월간 FA 분석 실행 상태'),
    ('MACRO_DIRECTION_CODE', '매크로 방향', 'UP/DOWN/FLAT'),
    ('FA_CANDIDATE_SOURCE_CODE', 'FA 후보 출처', '업종 후보 선정 출처'),
    ('FA_SECTOR_REASON_CODE', 'FA 업종 사유', '업종 선정 또는 탈락 사유'),
    ('FA_COMPANY_EXCLUSION_CODE', 'FA 기업 제외 사유', '기업 하드 필터 제외 사유')
ON CONFLICT DO NOTHING;

INSERT INTO codes VALUES
    ('FA_RUN_STATUS_CODE', 'RUNNING', '실행 중', NULL, 1, TRUE),
    ('FA_RUN_STATUS_CODE', 'PASS', '검증 통과', NULL, 2, TRUE),
    ('FA_RUN_STATUS_CODE', 'WARNING', '경고', NULL, 3, TRUE),
    ('FA_RUN_STATUS_CODE', 'FAIL', '실패', NULL, 4, TRUE),
    ('FA_RUN_STATUS_CODE', 'PUBLISHED', '발행 완료', NULL, 5, TRUE),
    ('MACRO_DIRECTION_CODE', 'UP', '상승', NULL, 1, TRUE),
    ('MACRO_DIRECTION_CODE', 'DOWN', '하강', NULL, 2, TRUE),
    ('MACRO_DIRECTION_CODE', 'FLAT', '보합', NULL, 3, TRUE),
    ('FA_CANDIDATE_SOURCE_CODE', 'UP_BENEFIT', '상승 수혜', NULL, 1, TRUE),
    ('FA_CANDIDATE_SOURCE_CODE', 'DOWN_HEDGE', '하강 방어', NULL, 2, TRUE),
    ('FA_CANDIDATE_SOURCE_CODE', 'BOTH', '양쪽 후보', NULL, 3, TRUE),
    ('FA_CANDIDATE_SOURCE_CODE', 'FILL', '보충 후보', NULL, 4, TRUE),
    ('FA_SECTOR_REASON_CODE', 'SELECTED', '선정', NULL, 1, TRUE),
    ('FA_SECTOR_REASON_CODE', 'LOW_SCORE', '점수 미달', NULL, 2, TRUE),
    ('FA_SECTOR_REASON_CODE', 'DUPLICATE_PARENT', '대분류 중복', NULL, 3, TRUE),
    ('FA_SECTOR_REASON_CODE', 'INSUFFICIENT_LARGE', 'LARGE 기업 부족', NULL, 4, TRUE),
    ('FA_SECTOR_REASON_CODE', 'LOW_CONFIDENCE', '신뢰도 미달', NULL, 5, TRUE),
    ('FA_COMPANY_EXCLUSION_CODE', 'NOT_LARGE', 'LARGE 아님', NULL, 1, TRUE),
    ('FA_COMPANY_EXCLUSION_CODE', 'LOW_FA_SCORE', 'FA 점수 미달', NULL, 2, TRUE),
    ('FA_COMPANY_EXCLUSION_CODE', 'LOW_CONFIDENCE', '신뢰도 미달', NULL, 3, TRUE),
    ('FA_COMPANY_EXCLUSION_CODE', 'NO_QUARTER_FA', '분기 FA 없음', NULL, 4, TRUE),
    ('FA_COMPANY_EXCLUSION_CODE', 'CAPITAL_IMPAIRMENT', '자본 잠식', NULL, 5, TRUE),
    ('FA_COMPANY_EXCLUSION_CODE', 'BUY_BLOCKED', '신규 매수 차단', NULL, 6, TRUE),
    ('FA_COMPANY_EXCLUSION_CODE', 'MAPPING_ERROR', '식별자 매핑 오류', NULL, 7, TRUE)
ON CONFLICT DO NOTHING;

INSERT INTO code_groups VALUES
    ('COMPANY_RISK_ACTION_CODE', '기업 위험 조치', '기업별 현재 매매 제한 조치')
ON CONFLICT DO NOTHING;

INSERT INTO codes VALUES
    ('COMPANY_RISK_ACTION_CODE', 'NONE', '제한 없음', NULL, 1, TRUE),
    ('COMPANY_RISK_ACTION_CODE', 'BLOCK_BUY', '신규 매수 차단', NULL, 2, TRUE),
    ('COMPANY_RISK_ACTION_CODE', 'SELL_ONLY', '매도 전용', NULL, 3, TRUE),
    ('TRADE_REASON_CODE', 'COMPANY_RISK_BLOCKED', '기업 위험 매수차단',
     'company_risk_states의 유효한 위험 조치로 매수 계획 차단', 13, TRUE)
ON CONFLICT DO NOTHING;
