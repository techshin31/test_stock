-- ============================================================
-- Collector source data schema
-- macro, company, DART, WICS, and company risk source tables
-- Run after 01_codes_schema.sql and 02_codes_seed.sql.
-- ============================================================

-- Macro signals
CREATE TABLE IF NOT EXISTS macro_signals (
    id                  BIGSERIAL       PRIMARY KEY,
    signal_name_code    VARCHAR(50)     NOT NULL,
    category_code       VARCHAR(50)     NOT NULL,
    signal_date         DATE            NOT NULL,
    observation_date    DATE            NOT NULL,
    available_date      DATE            NOT NULL,
    value               NUMERIC(18, 6)  NOT NULL,
    frequency_code      VARCHAR(20)     NOT NULL DEFAULT 'DAILY',
    source_code         VARCHAR(50)     NOT NULL,
    source_value_key    VARCHAR(100),
    revision_no         SMALLINT        NOT NULL DEFAULT 0,
    collected_at        TIMESTAMPTZ     NOT NULL DEFAULT NOW(),

    CONSTRAINT uq_macro_signals_observation_revision
        UNIQUE (signal_name_code, observation_date, revision_no)
);

-- Existing installations: retain legacy rows and mark their historical
-- availability conservatively as their prior signal date. Phase 3 rejects
-- incomplete legacy coverage before analyzer execution.
ALTER TABLE macro_signals ADD COLUMN IF NOT EXISTS observation_date DATE;
ALTER TABLE macro_signals ADD COLUMN IF NOT EXISTS available_date DATE;
ALTER TABLE macro_signals ADD COLUMN IF NOT EXISTS source_code VARCHAR(50);
ALTER TABLE macro_signals ADD COLUMN IF NOT EXISTS source_value_key VARCHAR(100);
ALTER TABLE macro_signals ADD COLUMN IF NOT EXISTS revision_no SMALLINT DEFAULT 0;

UPDATE macro_signals
SET observation_date = COALESCE(observation_date, signal_date),
    available_date = COALESCE(available_date, signal_date),
    source_code = COALESCE(source_code, 'LEGACY'),
    revision_no = COALESCE(revision_no, 0)
WHERE observation_date IS NULL
   OR available_date IS NULL
   OR source_code IS NULL
   OR revision_no IS NULL;

ALTER TABLE macro_signals ALTER COLUMN observation_date SET NOT NULL;
ALTER TABLE macro_signals ALTER COLUMN available_date SET NOT NULL;
ALTER TABLE macro_signals ALTER COLUMN source_code SET NOT NULL;
ALTER TABLE macro_signals ALTER COLUMN revision_no SET NOT NULL;
ALTER TABLE macro_signals DROP CONSTRAINT IF EXISTS uq_macro_signals_name_date;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'uq_macro_signals_observation_revision'
    ) THEN
        ALTER TABLE macro_signals
            ADD CONSTRAINT uq_macro_signals_observation_revision
            UNIQUE (signal_name_code, observation_date, revision_no);
    END IF;
END $$;

CREATE INDEX idx_macro_signals_signal_name_code ON macro_signals(signal_name_code);
CREATE INDEX idx_macro_signals_category_code    ON macro_signals(category_code);
CREATE INDEX idx_macro_signals_signal_date      ON macro_signals(signal_date);
CREATE INDEX IF NOT EXISTS idx_macro_signals_available_date
    ON macro_signals(signal_name_code, available_date, observation_date);

COMMENT ON TABLE  macro_signals                  IS 'Top-down FA 분석용 글로벌 매크로 시계열 — 원자재·금리·위험지표·FX';
COMMENT ON COLUMN macro_signals.id               IS '시그널 기록 고유 ID';
COMMENT ON COLUMN macro_signals.signal_name_code IS '시그널 이름 코드 (codes.MACRO_SIGNAL_CODE)';
COMMENT ON COLUMN macro_signals.category_code    IS '자산 분류 코드 (codes.MACRO_CATEGORY_CODE)';
COMMENT ON COLUMN macro_signals.signal_date      IS '기준일 (일간: 거래일, 월간: 해당 월 1일)';
COMMENT ON COLUMN macro_signals.observation_date IS '값이 설명하는 관측일 또는 관측월';
COMMENT ON COLUMN macro_signals.available_date   IS '투자자가 해당 revision을 실제 사용할 수 있게 된 날짜';
COMMENT ON COLUMN macro_signals.value            IS '종가 또는 지수값 (CPI는 원본 지수값)';
COMMENT ON COLUMN macro_signals.frequency_code   IS '발표 주기 코드 (codes.FREQUENCY_CODE)';
COMMENT ON COLUMN macro_signals.source_code      IS '원천 코드 (YAHOO/FRED/LEGACY)';
COMMENT ON COLUMN macro_signals.source_value_key IS '원천 티커 또는 시리즈 ID';
COMMENT ON COLUMN macro_signals.revision_no      IS '동일 관측치 수정 순서, 최초값 0';
COMMENT ON COLUMN macro_signals.collected_at     IS '데이터 수집 일시';


-- Company, financial statement, and DART event sources
CREATE TABLE IF NOT EXISTS companies (
    stock_code       VARCHAR(10)   PRIMARY KEY,
    corp_code        VARCHAR(10)   NOT NULL UNIQUE,
    company_name     VARCHAR(200)  NOT NULL,
    market_type_code VARCHAR(50),
    status_code      VARCHAR(20)   NOT NULL DEFAULT 'ACTIVE',
    created_at       TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    updated_at       TIMESTAMPTZ   NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_companies_corp_code   ON companies(corp_code);
CREATE INDEX idx_companies_status_code ON companies(status_code);

COMMENT ON TABLE  companies                  IS '종목코드 ↔ DART 고유번호 ↔ 회사명 매핑 — FA 분석의 허브 테이블';
COMMENT ON COLUMN companies.stock_code       IS '종목코드 6자리 (예: 005930)';
COMMENT ON COLUMN companies.corp_code        IS 'DART 고유번호 8자리';
COMMENT ON COLUMN companies.company_name     IS '회사명 (한글)';
COMMENT ON COLUMN companies.market_type_code IS '상장 거래소 (codes.MARKET_TYPE_CODE)';
COMMENT ON COLUMN companies.status_code      IS '상장 상태 (codes.COMPANY_STATUS_CODE — ACTIVE/SUSPENDED/DELISTED)';
COMMENT ON COLUMN companies.created_at       IS '회사 기본정보 최초 저장 일시';
COMMENT ON COLUMN companies.updated_at       IS '회사 기본정보 최종 수정 일시';

CREATE TRIGGER trg_companies_updated_at
    BEFORE UPDATE ON companies
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();


-- ============================================================
-- 2. 재무제표 원본 (financial_statements) — DART 원본 EAV 구조
-- ============================================================
CREATE TABLE IF NOT EXISTS financial_statements (
    id               BIGSERIAL     PRIMARY KEY,
    stock_code       VARCHAR(10)   NOT NULL REFERENCES companies(stock_code),
    corp_code        VARCHAR(10)   NOT NULL,
    bsns_year        SMALLINT      NOT NULL,
    reprt_code       VARCHAR(10)   NOT NULL DEFAULT '11011',
    fs_div           VARCHAR(5)    NOT NULL,
    sj_div           VARCHAR(5)    NOT NULL,
    account_id       TEXT,
    account_nm       TEXT          NOT NULL,
    source_rcept_no  VARCHAR(20),
    rcept_dt         DATE,
    available_date   DATE,
    period_start     DATE,
    period_end       DATE,
    thstrm_amount    NUMERIC(20, 0),
    frmtrm_amount    NUMERIC(20, 0),
    bfefrmtrm_amount NUMERIC(20, 0),
    thstrm_add_amount NUMERIC(20, 0),
    frmtrm_add_amount NUMERIC(20, 0),
    revision_no      SMALLINT      NOT NULL DEFAULT 0,
    collected_at     TIMESTAMPTZ   NOT NULL DEFAULT NOW()
);

ALTER TABLE financial_statements ADD COLUMN IF NOT EXISTS source_rcept_no VARCHAR(20);
ALTER TABLE financial_statements ADD COLUMN IF NOT EXISTS rcept_dt DATE;
ALTER TABLE financial_statements ADD COLUMN IF NOT EXISTS available_date DATE;
ALTER TABLE financial_statements ADD COLUMN IF NOT EXISTS period_start DATE;
ALTER TABLE financial_statements ADD COLUMN IF NOT EXISTS period_end DATE;
ALTER TABLE financial_statements ADD COLUMN IF NOT EXISTS thstrm_add_amount NUMERIC(20, 0);
ALTER TABLE financial_statements ADD COLUMN IF NOT EXISTS frmtrm_add_amount NUMERIC(20, 0);
ALTER TABLE financial_statements ADD COLUMN IF NOT EXISTS revision_no SMALLINT DEFAULT 0;

UPDATE financial_statements
SET source_rcept_no = COALESCE(
        source_rcept_no,
        'LEGACY:' || SUBSTRING(
            MD5(stock_code || ':' || bsns_year || ':' || reprt_code), 1, 13
        )
    ),
    available_date = COALESCE(available_date, collected_at::date),
    revision_no = COALESCE(revision_no, 0)
WHERE source_rcept_no IS NULL OR available_date IS NULL OR revision_no IS NULL;

ALTER TABLE financial_statements ALTER COLUMN source_rcept_no SET NOT NULL;
ALTER TABLE financial_statements ALTER COLUMN available_date SET NOT NULL;
ALTER TABLE financial_statements ALTER COLUMN revision_no SET NOT NULL;
ALTER TABLE financial_statements DROP CONSTRAINT IF EXISTS uq_financial_statements;

CREATE UNIQUE INDEX IF NOT EXISTS uq_financial_statements_source_version
    ON financial_statements (
        stock_code, source_rcept_no, fs_div, sj_div,
        (COALESCE(account_id, account_nm)), account_nm
    );

CREATE INDEX idx_financial_statements_stock_code ON financial_statements(stock_code);
CREATE INDEX idx_financial_statements_bsns_year  ON financial_statements(bsns_year);
CREATE INDEX idx_financial_statements_sj_div     ON financial_statements(sj_div);
CREATE INDEX idx_financial_statements_account_id ON financial_statements(account_id);
CREATE INDEX IF NOT EXISTS idx_financial_statements_available_date
    ON financial_statements(stock_code, available_date, period_end);
CREATE INDEX IF NOT EXISTS idx_financial_statements_rcept_no
    ON financial_statements(source_rcept_no);

COMMENT ON TABLE  financial_statements                  IS 'DART 재무제표 원본 — EAV 구조 (계정과목별 1행), 보관 및 재계산 기준';
COMMENT ON COLUMN financial_statements.id               IS '재무제표 원본 행 고유 ID';
COMMENT ON COLUMN financial_statements.stock_code       IS '종목코드 (companies.stock_code 참조)';
COMMENT ON COLUMN financial_statements.corp_code        IS 'DART 고유번호';
COMMENT ON COLUMN financial_statements.bsns_year        IS '사업연도';
COMMENT ON COLUMN financial_statements.reprt_code       IS '보고서코드 (11011=사업보고서, 11012=반기, 11013=1분기, 11014=3분기)';
COMMENT ON COLUMN financial_statements.fs_div           IS '재무제표 구분 (CFS=연결, OFS=별도)';
COMMENT ON COLUMN financial_statements.sj_div           IS '재무제표 유형 (BS=재무상태표, IS=손익계산서, CIS=포괄손익, CF=현금흐름표)';
COMMENT ON COLUMN financial_statements.account_id       IS 'DART 계정 ID (예: ifrs_Assets)';
COMMENT ON COLUMN financial_statements.account_nm       IS '계정과목명 (예: 자산총계, 매출액)';
COMMENT ON COLUMN financial_statements.source_rcept_no  IS 'DART 정기보고서 접수번호; LEGACY 접두사는 시점 검증 대상에서 제외';
COMMENT ON COLUMN financial_statements.rcept_dt         IS 'DART 접수일';
COMMENT ON COLUMN financial_statements.available_date   IS '분석에서 해당 보고서를 사용할 수 있게 된 날짜';
COMMENT ON COLUMN financial_statements.period_start     IS '보고 대상 기간 시작일';
COMMENT ON COLUMN financial_statements.period_end       IS '보고 대상 기간 종료일';
COMMENT ON COLUMN financial_statements.thstrm_amount    IS '당기 금액 (원)';
COMMENT ON COLUMN financial_statements.frmtrm_amount    IS '전기 금액 (원)';
COMMENT ON COLUMN financial_statements.bfefrmtrm_amount IS '전전기 금액 (원)';
COMMENT ON COLUMN financial_statements.thstrm_add_amount IS 'DART 당기 누적금액 원본';
COMMENT ON COLUMN financial_statements.frmtrm_add_amount IS 'DART 전기 누적금액 원본';
COMMENT ON COLUMN financial_statements.revision_no      IS '동일 보고기간 정정 순서';
COMMENT ON COLUMN financial_statements.collected_at     IS '재무제표 원본 수집 일시';


-- ============================================================
-- 3. FA 지표 (fa_metrics) — financial_statements에서 계산된 지표
-- ============================================================
CREATE TABLE IF NOT EXISTS fa_metrics (
    id               BIGSERIAL     PRIMARY KEY,
    stock_code       VARCHAR(10)   NOT NULL REFERENCES companies(stock_code),
    bsns_year        SMALLINT      NOT NULL,
    fs_div           VARCHAR(5)    NOT NULL DEFAULT 'CFS',
    fiscal_year_end  DATE,
    roe              NUMERIC(10, 6),
    roa              NUMERIC(10, 6),
    operating_margin NUMERIC(10, 6),
    debt_ratio       NUMERIC(10, 6),
    current_ratio    NUMERIC(10, 6),
    fcf              NUMERIC(20, 0),
    calculated_at    TIMESTAMPTZ   NOT NULL DEFAULT NOW(),

    CONSTRAINT uq_fa_metrics UNIQUE (stock_code, bsns_year, fs_div)
);

CREATE INDEX idx_fa_metrics_stock_code ON fa_metrics(stock_code);
CREATE INDEX idx_fa_metrics_bsns_year  ON fa_metrics(bsns_year);

COMMENT ON TABLE  fa_metrics                  IS 'financial_statements에서 계산된 FA 지표 — universe.fa_score 산출에 직접 사용';
COMMENT ON COLUMN fa_metrics.id               IS 'FA 지표 행 고유 ID';
COMMENT ON COLUMN fa_metrics.stock_code       IS '종목코드';
COMMENT ON COLUMN fa_metrics.bsns_year        IS 'DART 사업연도 레이블 — 회계연도가 끝나는 캘린더 연도 (실제 기간은 fiscal_year_end 참조)';
COMMENT ON COLUMN fa_metrics.fs_div           IS '재무제표 구분 (CFS=연결, OFS=별도)';
COMMENT ON COLUMN fa_metrics.fiscal_year_end  IS '회계연도 종료일 (예: 2025-12-31, 2026-03-31) — 데이터 신선도 판단 기준';
COMMENT ON COLUMN fa_metrics.roe              IS '자기자본이익률 = 당기순이익 / 자본총계';
COMMENT ON COLUMN fa_metrics.roa              IS '총자산이익률 = 당기순이익 / 자산총계';
COMMENT ON COLUMN fa_metrics.operating_margin IS '영업이익률 = 영업이익 / 매출액';
COMMENT ON COLUMN fa_metrics.debt_ratio       IS '부채비율 = 부채총계 / 자본총계';
COMMENT ON COLUMN fa_metrics.current_ratio    IS '유동비율 = 유동자산 / 유동부채';
COMMENT ON COLUMN fa_metrics.fcf              IS '잉여현금흐름 = 영업활동현금흐름 - 자본적지출';
COMMENT ON COLUMN fa_metrics.calculated_at    IS 'FA 지표 계산 일시';

-- 정정공시·모델 버전별 시점 원장. fa_metrics는 최신값 조회용 캐시로 유지한다.
CREATE TABLE IF NOT EXISTS fa_metrics_history (
    id               BIGSERIAL PRIMARY KEY,
    stock_code       VARCHAR(10) NOT NULL REFERENCES companies(stock_code),
    bsns_year        SMALLINT NOT NULL,
    fs_div           VARCHAR(5) NOT NULL DEFAULT 'CFS',
    source_rcept_no  VARCHAR(32) NOT NULL,
    available_date   DATE NOT NULL,
    model_version    VARCHAR(50) NOT NULL,
    fiscal_year_end  DATE,
    roe              NUMERIC(10, 6),
    roa              NUMERIC(10, 6),
    operating_margin NUMERIC(10, 6),
    debt_ratio       NUMERIC(10, 6),
    current_ratio    NUMERIC(10, 6),
    fcf              NUMERIC(20, 0),
    calculated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_fa_metrics_history
        UNIQUE (stock_code, source_rcept_no, fs_div, model_version)
);

CREATE INDEX IF NOT EXISTS idx_fa_metrics_history_asof
    ON fa_metrics_history(stock_code, available_date DESC, model_version);


-- ============================================================
-- 4. DART 공시 이벤트 (dart_events)
-- ============================================================
CREATE TABLE IF NOT EXISTS dart_events (
    id                   BIGSERIAL    PRIMARY KEY,
    stock_code           VARCHAR(10)  NOT NULL REFERENCES companies(stock_code),
    corp_code            VARCHAR(10)  NOT NULL,
    rcept_no             VARCHAR(20)  NOT NULL UNIQUE,
    rcept_dt             DATE         NOT NULL,
    report_nm            TEXT         NOT NULL,
    pblntf_ty            VARCHAR(5)   NOT NULL,
    event_category_code  VARCHAR(50)  NOT NULL,
    event_subtype_code   VARCHAR(50)  NOT NULL,
    flr_nm               VARCHAR(200),
    corp_cls             VARCHAR(10),
    rm                   TEXT,
    collected_at         TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_dart_events_stock_code          ON dart_events(stock_code);
CREATE INDEX idx_dart_events_rcept_dt            ON dart_events(rcept_dt);
CREATE INDEX idx_dart_events_pblntf_ty           ON dart_events(pblntf_ty);
CREATE INDEX idx_dart_events_event_category_code ON dart_events(event_category_code);
CREATE INDEX idx_dart_events_event_subtype_code  ON dart_events(event_subtype_code);

COMMENT ON TABLE  dart_events                      IS 'DART 공시 이벤트 — 정기공시(A)·주요사항보고서(B) FA 관련 이벤트';
COMMENT ON COLUMN dart_events.id                   IS 'DART 공시 이벤트 고유 ID';
COMMENT ON COLUMN dart_events.stock_code           IS '종목코드 (companies.stock_code 참조)';
COMMENT ON COLUMN dart_events.corp_code            IS 'DART 고유번호';
COMMENT ON COLUMN dart_events.rcept_no             IS '접수번호 (DART 고유값, UNIQUE)';
COMMENT ON COLUMN dart_events.rcept_dt             IS '공시일';
COMMENT ON COLUMN dart_events.report_nm            IS '원문 공시명';
COMMENT ON COLUMN dart_events.pblntf_ty            IS '공시 타입 (A=정기공시, B=주요사항보고서)';
COMMENT ON COLUMN dart_events.event_category_code  IS '이벤트 대분류 (codes.DART_EVENT_CATEGORY_CODE)';
COMMENT ON COLUMN dart_events.event_subtype_code   IS '이벤트 세부유형 (codes.DART_EVENT_SUBTYPE_CODE)';
COMMENT ON COLUMN dart_events.flr_nm               IS '공시 제출인명';
COMMENT ON COLUMN dart_events.corp_cls             IS '법인 구분 (Y=유가증권, K=코스닥, N=코넥스, E=기타)';
COMMENT ON COLUMN dart_events.rm                   IS '비고';
COMMENT ON COLUMN dart_events.collected_at         IS 'DART 이벤트 수집 일시';


-- WICS source data
CREATE TABLE IF NOT EXISTS wics_companies (
    id                 BIGSERIAL    PRIMARY KEY,
    stock_code         VARCHAR(10)  NOT NULL,
    base_date          DATE         NOT NULL,
    sector_code        VARCHAR(10)  NOT NULL,
    industry_code      VARCHAR(10)  NOT NULL,
    mkt_val            NUMERIC(20, 0),
    trd_amt            NUMERIC(20, 0),
    sec_rate           NUMERIC(10, 6),
    idx_rate           NUMERIC(10, 6),
    company_size_code  VARCHAR(10),
    collected_at       TIMESTAMPTZ  NOT NULL DEFAULT NOW(),

    CONSTRAINT uq_wics_companies UNIQUE (stock_code, base_date)
);

CREATE INDEX idx_wics_companies_stock_code        ON wics_companies(stock_code);
CREATE INDEX idx_wics_companies_base_date         ON wics_companies(base_date);
CREATE INDEX idx_wics_companies_sector_code       ON wics_companies(sector_code);
CREATE INDEX idx_wics_companies_industry_code     ON wics_companies(industry_code);
CREATE INDEX idx_wics_companies_company_size_code ON wics_companies(company_size_code);

COMMENT ON TABLE  wics_companies                        IS 'WiseIndex WICS 날짜별 구성종목 스냅샷';
COMMENT ON COLUMN wics_companies.id                     IS 'WICS 구성종목 스냅샷 행 고유 ID';
COMMENT ON COLUMN wics_companies.stock_code             IS '종목코드 6자리';
COMMENT ON COLUMN wics_companies.base_date              IS '기준일';
COMMENT ON COLUMN wics_companies.sector_code            IS 'WICS 대분류 코드 (codes.WICS_SECTOR_CODE, 예: G45)';
COMMENT ON COLUMN wics_companies.industry_code          IS 'WICS 중분류 코드 (codes.WICS_INDUSTRY_CODE, 예: G4530)';
COMMENT ON COLUMN wics_companies.mkt_val                IS '시가총액 (원)';
COMMENT ON COLUMN wics_companies.trd_amt                IS '거래대금 (원)';
COMMENT ON COLUMN wics_companies.sec_rate               IS '섹터 내 비중 (소수, 예: 0.152 = 15.2%)';
COMMENT ON COLUMN wics_companies.idx_rate               IS '전체 지수 내 비중 (소수)';
COMMENT ON COLUMN wics_companies.company_size_code      IS '종목 규모 코드 (codes.COMPANY_SIZE_CODE 참조)';
COMMENT ON COLUMN wics_companies.collected_at           IS 'WICS 스냅샷 수집 일시';


-- ============================================================
-- 2. WICS 중분류 가격 원천
-- ============================================================
CREATE TABLE IF NOT EXISTS wics_industry_prices (
    id                    BIGSERIAL       PRIMARY KEY,
    industry_code         VARCHAR(10)     NOT NULL,
    price_date            DATE            NOT NULL,
    index_value           NUMERIC(20, 6)  NOT NULL,
    source_code           VARCHAR(50)     NOT NULL,
    constituent_base_date DATE,
    method_version        VARCHAR(50)     NOT NULL DEFAULT 'OFFICIAL',
    collected_at          TIMESTAMPTZ     NOT NULL DEFAULT NOW(),

    CONSTRAINT uq_wics_industry_prices
        UNIQUE (industry_code, price_date, source_code, method_version)
);

CREATE INDEX IF NOT EXISTS idx_wics_industry_prices_code_date
    ON wics_industry_prices(industry_code, price_date);
CREATE INDEX IF NOT EXISTS idx_wics_industry_prices_date
    ON wics_industry_prices(price_date);

COMMENT ON TABLE wics_industry_prices IS '매크로-업종 관계 계산용 WICS 중분류 지수 원천';
COMMENT ON COLUMN wics_industry_prices.id IS 'WICS 중분류 지수 가격 행 고유 ID';
COMMENT ON COLUMN wics_industry_prices.industry_code IS 'WICS 중분류 코드';
COMMENT ON COLUMN wics_industry_prices.price_date IS '지수 종가 기준일';
COMMENT ON COLUMN wics_industry_prices.index_value IS '공식 또는 재구성 지수값';
COMMENT ON COLUMN wics_industry_prices.source_code IS 'WISEINDEX 또는 DERIVED';
COMMENT ON COLUMN wics_industry_prices.constituent_base_date IS '재구성에 사용한 구성종목 스냅샷 기준일';
COMMENT ON COLUMN wics_industry_prices.method_version IS '공식/재구성 방식 버전';
COMMENT ON COLUMN wics_industry_prices.collected_at IS 'WICS 중분류 지수 가격 수집 또는 재구성 일시';


-- ============================================================
-- 3. WICS 지수 재구성용 종목 가격 원천
-- ============================================================
CREATE TABLE IF NOT EXISTS wics_constituent_prices (
    id            BIGSERIAL       PRIMARY KEY,
    stock_code    VARCHAR(10)     NOT NULL,
    price_date    DATE            NOT NULL,
    close         NUMERIC(20, 6)  NOT NULL,
    source_code   VARCHAR(50)     NOT NULL DEFAULT 'YAHOO',
    collected_at  TIMESTAMPTZ     NOT NULL DEFAULT NOW(),

    CONSTRAINT uq_wics_constituent_prices
        UNIQUE (stock_code, price_date, source_code)
);

CREATE INDEX IF NOT EXISTS idx_wics_constituent_prices_code_date
    ON wics_constituent_prices(stock_code, price_date);
CREATE INDEX IF NOT EXISTS idx_wics_constituent_prices_date
    ON wics_constituent_prices(price_date);

COMMENT ON TABLE wics_constituent_prices IS 'WICS 중분류 지수 재구성용 구성종목 종가 원천';
COMMENT ON COLUMN wics_constituent_prices.id IS 'WICS 구성종목 종가 행 고유 ID';
COMMENT ON COLUMN wics_constituent_prices.stock_code IS 'WICS 구성종목 코드';
COMMENT ON COLUMN wics_constituent_prices.price_date IS '종가 거래일';
COMMENT ON COLUMN wics_constituent_prices.close IS '가격 공급자 조정 종가';
COMMENT ON COLUMN wics_constituent_prices.source_code IS '가격 원천 코드';
COMMENT ON COLUMN wics_constituent_prices.collected_at IS '구성종목 종가 수집 일시';


-- Company risk states
CREATE TABLE IF NOT EXISTS company_risk_states (
    id                    BIGSERIAL PRIMARY KEY,
    stock_code            VARCHAR(10) NOT NULL REFERENCES companies(stock_code),
    risk_action_code      VARCHAR(20) NOT NULL DEFAULT 'NONE',
    reason_code           VARCHAR(50),
    source_dart_event_id  BIGINT REFERENCES dart_events(id) ON DELETE SET NULL,
    effective_date        DATE NOT NULL,
    expires_at            DATE,
    policy_version        VARCHAR(50) NOT NULL,
    is_manual_override    BOOLEAN NOT NULL DEFAULT FALSE,
    detail                JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT ck_company_risk_action
        CHECK (risk_action_code IN ('NONE', 'BLOCK_BUY', 'SELL_ONLY')),
    CONSTRAINT ck_company_risk_dates
        CHECK (expires_at IS NULL OR expires_at >= effective_date)
);

-- Migrate the short-lived single-row draft without discarding any rows.
ALTER TABLE company_risk_states ADD COLUMN IF NOT EXISTS id BIGSERIAL;
DO $$
DECLARE
    primary_key_column TEXT;
BEGIN
    SELECT a.attname INTO primary_key_column
    FROM pg_constraint c
    JOIN pg_attribute a
      ON a.attrelid = c.conrelid AND a.attnum = ANY(c.conkey)
    WHERE c.conrelid = 'company_risk_states'::regclass
      AND c.contype = 'p'
    LIMIT 1;

    IF primary_key_column = 'stock_code' THEN
        ALTER TABLE company_risk_states DROP CONSTRAINT company_risk_states_pkey;
        ALTER TABLE company_risk_states ADD PRIMARY KEY (id);
    END IF;
END $$;

CREATE UNIQUE INDEX IF NOT EXISTS uq_company_risk_states_event_policy
    ON company_risk_states(stock_code, source_dart_event_id, policy_version);

CREATE INDEX IF NOT EXISTS idx_company_risk_states_active
    ON company_risk_states(risk_action_code, effective_date, expires_at);
CREATE INDEX IF NOT EXISTS idx_company_risk_states_source_event
    ON company_risk_states(source_dart_event_id);

COMMENT ON TABLE company_risk_states IS 'DART 공시 정책에서 파생된 기업별 기간형 매매 위험 상태';
COMMENT ON COLUMN company_risk_states.id IS '기업 위험 상태 고유 ID';
COMMENT ON COLUMN company_risk_states.stock_code IS '위험 상태 대상 종목코드';
COMMENT ON COLUMN company_risk_states.risk_action_code IS 'NONE/BLOCK_BUY/SELL_ONLY';
COMMENT ON COLUMN company_risk_states.reason_code IS '상태를 발생시킨 정책 또는 DART 이벤트 세부 코드';
COMMENT ON COLUMN company_risk_states.source_dart_event_id IS '자동 상태의 근거 DART 이벤트';
COMMENT ON COLUMN company_risk_states.effective_date IS '위험 상태 적용 시작일';
COMMENT ON COLUMN company_risk_states.expires_at IS 'NULL이면 별도 해제 전까지 유효';
COMMENT ON COLUMN company_risk_states.policy_version IS '위험 상태 산출 정책 버전';
COMMENT ON COLUMN company_risk_states.is_manual_override IS 'TRUE이면 자동 갱신과 만료 처리에서 보호';
COMMENT ON COLUMN company_risk_states.detail IS '위험 상태 산출 근거와 추가 메타데이터';
COMMENT ON COLUMN company_risk_states.created_at IS '위험 상태 최초 저장 일시';
COMMENT ON COLUMN company_risk_states.updated_at IS '위험 상태 최종 수정 일시';
