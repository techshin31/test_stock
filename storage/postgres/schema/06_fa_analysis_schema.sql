-- ============================================================
-- Analyzer FA analysis schema
-- company_quarter_fa, fa_analysis_runs, fa_*_results, and universe publication lineage
-- Run after 04_trader_schema.sql and 05_market_data_schema.sql.
-- ============================================================

CREATE TABLE IF NOT EXISTS company_quarter_fa (
    id                           BIGSERIAL PRIMARY KEY,
    stock_code                   VARCHAR(10) NOT NULL REFERENCES companies(stock_code),
    source_rcept_no              VARCHAR(20) NOT NULL REFERENCES dart_events(rcept_no),
    fiscal_year                  SMALLINT NOT NULL,
    fiscal_quarter               VARCHAR(10) NOT NULL,
    reprt_code                   VARCHAR(10) NOT NULL,
    fs_div                       VARCHAR(5) NOT NULL,
    period_end                   DATE NOT NULL,
    available_date               DATE NOT NULL,
    model_version                VARCHAR(50) NOT NULL,
    revenue                      NUMERIC(20, 0),
    operating_income             NUMERIC(20, 0),
    net_income                   NUMERIC(20, 0),
    total_assets                 NUMERIC(20, 0),
    total_liabilities            NUMERIC(20, 0),
    total_equity                 NUMERIC(20, 0),
    current_assets               NUMERIC(20, 0),
    current_liabilities          NUMERIC(20, 0),
    operating_cashflow           NUMERIC(20, 0),
    capex                        NUMERIC(20, 0),
    fcf                          NUMERIC(20, 0),
    market_cap                   NUMERIC(20, 0),
    market_data_date             DATE,
    operating_margin             NUMERIC(12, 8),
    roe                          NUMERIC(12, 8),
    roa                          NUMERIC(12, 8),
    debt_ratio                   NUMERIC(12, 8),
    current_ratio                NUMERIC(12, 8),
    ocf_to_revenue               NUMERIC(12, 8),
    ocf_to_net_income            NUMERIC(12, 8),
    revenue_growth_yoy           NUMERIC(12, 8),
    operating_income_growth_yoy  NUMERIC(12, 8),
    operating_margin_change_yoy  NUMERIC(12, 8),
    operating_cashflow_change_yoy NUMERIC(12, 8),
    per_proxy                    NUMERIC(16, 8),
    pbr_proxy                    NUMERIC(16, 8),
    level_score                  NUMERIC(8, 4) NOT NULL,
    change_score                 NUMERIC(8, 4) NOT NULL,
    risk_penalty                 NUMERIC(8, 4) NOT NULL,
    risk_score                   NUMERIC(8, 4) NOT NULL,
    fa_score                     NUMERIC(8, 4) NOT NULL,
    level_confidence             NUMERIC(8, 6) NOT NULL,
    change_confidence            NUMERIC(8, 6) NOT NULL,
    score_confidence             NUMERIC(8, 6) NOT NULL,
    score_model_code             VARCHAR(50) NOT NULL,
    is_eligible                  BOOLEAN NOT NULL,
    excluded_reason_code         VARCHAR(50),
    score_detail                 JSONB NOT NULL DEFAULT '{}'::jsonb,
    calculated_at                TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_company_quarter_fa
        UNIQUE (stock_code, source_rcept_no, fs_div, model_version),
    CONSTRAINT ck_company_quarter_fa_scores CHECK (
        level_score BETWEEN 0 AND 60 AND change_score BETWEEN 0 AND 30
        AND risk_penalty BETWEEN 0 AND 10 AND risk_score BETWEEN 0 AND 10
        AND fa_score BETWEEN 0 AND 100
    ),
    CONSTRAINT ck_company_quarter_fa_confidence CHECK (
        level_confidence BETWEEN 0 AND 1
        AND change_confidence BETWEEN 0 AND 1
        AND score_confidence BETWEEN 0 AND 1
    )
);

CREATE INDEX IF NOT EXISTS idx_company_quarter_fa_stock_available
    ON company_quarter_fa(stock_code, available_date DESC);
CREATE INDEX IF NOT EXISTS idx_company_quarter_fa_quarter_model
    ON company_quarter_fa(fiscal_quarter, model_version);
CREATE INDEX IF NOT EXISTS idx_company_quarter_fa_eligible_confidence
    ON company_quarter_fa(is_eligible, score_confidence);

CREATE TABLE IF NOT EXISTS fa_analysis_runs (
    id                      BIGSERIAL PRIMARY KEY,
    strategy_id             INT NOT NULL REFERENCES strategies(id),
    analysis_month          DATE NOT NULL,
    cutoff_date             DATE NOT NULL,
    effective_date          DATE NOT NULL,
    run_version             SMALLINT NOT NULL,
    model_version           VARCHAR(50) NOT NULL,
    status_code             VARCHAR(20) NOT NULL DEFAULT 'RUNNING',
    input_hash              VARCHAR(64) NOT NULL,
    selected_industry_count SMALLINT NOT NULL DEFAULT 0,
    selected_company_count  SMALLINT NOT NULL DEFAULT 0,
    validation_summary      JSONB,
    failure_reason          TEXT,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at            TIMESTAMPTZ,
    published_at            TIMESTAMPTZ,
    CONSTRAINT uq_fa_analysis_runs_version
        UNIQUE (strategy_id, analysis_month, run_version),
    CONSTRAINT ck_fa_analysis_runs_month_start
        CHECK (analysis_month = date_trunc('month', analysis_month)::date),
    CONSTRAINT ck_fa_analysis_runs_dates CHECK (cutoff_date <= effective_date),
    CONSTRAINT ck_fa_analysis_runs_status CHECK (
        status_code IN ('RUNNING', 'PASS', 'WARNING', 'FAIL', 'PUBLISHED')
    )
);

CREATE INDEX IF NOT EXISTS idx_fa_analysis_runs_strategy_month
    ON fa_analysis_runs(strategy_id, analysis_month DESC);
CREATE INDEX IF NOT EXISTS idx_fa_analysis_runs_input_hash
    ON fa_analysis_runs(strategy_id, input_hash);

ALTER TABLE fa_analysis_runs
    DROP CONSTRAINT IF EXISTS ck_fa_analysis_runs_dates;
ALTER TABLE fa_analysis_runs
    ADD CONSTRAINT ck_fa_analysis_runs_dates CHECK (cutoff_date <= effective_date);

DROP INDEX IF EXISTS uq_fa_analysis_runs_published_month;
CREATE UNIQUE INDEX IF NOT EXISTS uq_fa_analysis_runs_published_effective_date
    ON fa_analysis_runs(strategy_id, effective_date)
    WHERE status_code = 'PUBLISHED';

CREATE TABLE IF NOT EXISTS fa_macro_results (
    id                    BIGSERIAL PRIMARY KEY,
    run_id                BIGINT NOT NULL REFERENCES fa_analysis_runs(id) ON DELETE CASCADE,
    signal_name_code      VARCHAR(50) NOT NULL,
    last_observation_date DATE NOT NULL,
    last_available_date   DATE NOT NULL,
    direction_code        VARCHAR(20) NOT NULL,
    trend_raw             NUMERIC(12, 6) NOT NULL,
    trend_strength        NUMERIC(8, 6) NOT NULL,
    data_point_count      INT NOT NULL,
    confidence            NUMERIC(8, 6) NOT NULL,
    calculation_detail    JSONB NOT NULL DEFAULT '{}'::jsonb,
    CONSTRAINT uq_fa_macro_results UNIQUE (run_id, signal_name_code),
    CONSTRAINT ck_fa_macro_results_direction CHECK (direction_code IN ('UP', 'DOWN', 'FLAT')),
    CONSTRAINT ck_fa_macro_results_strength CHECK (
        trend_strength BETWEEN 0 AND 1 AND confidence BETWEEN 0 AND 1
    )
);

CREATE INDEX IF NOT EXISTS idx_fa_macro_results_run_direction
    ON fa_macro_results(run_id, direction_code);

CREATE TABLE IF NOT EXISTS fa_sector_results (
    id                         BIGSERIAL PRIMARY KEY,
    run_id                     BIGINT NOT NULL REFERENCES fa_analysis_runs(id) ON DELETE CASCADE,
    sector_code                VARCHAR(10) NOT NULL,
    industry_code              VARCHAR(10) NOT NULL,
    up_benefit_score           NUMERIC(8, 4),
    down_hedge_score           NUMERIC(8, 4),
    macro_fit_score            NUMERIC(8, 4),
    company_fa_breadth_score   NUMERIC(8, 4),
    liquidity_capacity_score   NUMERIC(8, 4),
    sector_risk_penalty        NUMERIC(8, 4),
    cohort_quality_penalty     NUMERIC(8, 4),
    sector_score               NUMERIC(8, 4),
    candidate_source_code      VARCHAR(30),
    candidate_rank             SMALLINT,
    final_rank                 SMALLINT,
    is_candidate               BOOLEAN NOT NULL DEFAULT FALSE,
    is_selected                BOOLEAN NOT NULL DEFAULT FALSE,
    eligible_large_count       SMALLINT NOT NULL DEFAULT 0,
    company_coverage_rate      NUMERIC(8, 6),
    relationship_confidence    NUMERIC(8, 6),
    macro_contributions        JSONB NOT NULL DEFAULT '[]'::jsonb,
    reason_code                VARCHAR(50),
    reason                     TEXT,
    CONSTRAINT uq_fa_sector_results UNIQUE (run_id, industry_code)
);

CREATE INDEX IF NOT EXISTS idx_fa_sector_results_candidate_score
    ON fa_sector_results(run_id, is_candidate, sector_score DESC);
CREATE INDEX IF NOT EXISTS idx_fa_sector_results_selected
    ON fa_sector_results(run_id, is_selected);

ALTER TABLE fa_sector_results
    ADD COLUMN IF NOT EXISTS cohort_quality_penalty NUMERIC(8, 4);

CREATE TABLE IF NOT EXISTS fa_company_results (
    id                          BIGSERIAL PRIMARY KEY,
    run_id                      BIGINT NOT NULL REFERENCES fa_analysis_runs(id) ON DELETE CASCADE,
    sector_result_id            BIGINT NOT NULL REFERENCES fa_sector_results(id) ON DELETE CASCADE,
    stock_code                  VARCHAR(10) NOT NULL REFERENCES companies(stock_code),
    company_quarter_fa_id       BIGINT REFERENCES company_quarter_fa(id),
    sector_code                 VARCHAR(10) NOT NULL,
    industry_code               VARCHAR(10) NOT NULL,
    company_size_code           VARCHAR(10),
    fa_score                    NUMERIC(8, 4),
    score_confidence            NUMERIC(8, 6),
    latest_available_date       DATE,
    latest_trd_amt              NUMERIC(20, 0),
    industry_rank               SMALLINT,
    is_eligible                 BOOLEAN NOT NULL DEFAULT FALSE,
    is_selected                 BOOLEAN NOT NULL DEFAULT FALSE,
    exclusion_reason_code       VARCHAR(50),
    reason                      TEXT,
    selection_detail            JSONB NOT NULL DEFAULT '{}'::jsonb,
    CONSTRAINT uq_fa_company_results UNIQUE (run_id, stock_code),
    CONSTRAINT ck_fa_company_selected_eligible CHECK (NOT is_selected OR is_eligible)
);

CREATE INDEX IF NOT EXISTS idx_fa_company_results_industry_rank
    ON fa_company_results(run_id, industry_code, industry_rank);
CREATE INDEX IF NOT EXISTS idx_fa_company_results_selected
    ON fa_company_results(run_id, is_selected);

ALTER TABLE universe
    ADD COLUMN IF NOT EXISTS source_fa_company_result_id BIGINT;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'fk_universe_source_fa_company_result'
    ) THEN
        ALTER TABLE universe
            ADD CONSTRAINT fk_universe_source_fa_company_result
            FOREIGN KEY (source_fa_company_result_id)
            REFERENCES fa_company_results(id);
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_universe_source_fa_company_result
    ON universe(source_fa_company_result_id);

COMMENT ON TABLE company_quarter_fa IS '시점 안전 분기 기업 FA 원장';
COMMENT ON TABLE fa_analysis_runs IS '월간 FA 분석 실행 헤더와 발행 단위';
COMMENT ON TABLE fa_macro_results IS '실행별 매크로 방향 결과';
COMMENT ON TABLE fa_sector_results IS '실행별 전체 WICS 중분류 평가 결과';
COMMENT ON TABLE fa_company_results IS '실행별 기업 평가와 최종 선정 결과';

COMMENT ON COLUMN company_quarter_fa.id IS '분기 기업 FA 원장 고유 ID';
COMMENT ON COLUMN company_quarter_fa.stock_code IS '평가 대상 종목코드';
COMMENT ON COLUMN company_quarter_fa.source_rcept_no IS 'FA 계산에 사용한 DART 정기보고서 접수번호';
COMMENT ON COLUMN company_quarter_fa.fiscal_year IS '보고서 기준 사업연도';
COMMENT ON COLUMN company_quarter_fa.fiscal_quarter IS '보고서 기준 분기 코드';
COMMENT ON COLUMN company_quarter_fa.reprt_code IS 'DART 보고서 코드';
COMMENT ON COLUMN company_quarter_fa.fs_div IS '재무제표 구분 (CFS=연결, OFS=별도)';
COMMENT ON COLUMN company_quarter_fa.period_end IS '보고 대상 기간 종료일';
COMMENT ON COLUMN company_quarter_fa.available_date IS '해당 분기 FA 값을 분석에 사용할 수 있게 된 날짜';
COMMENT ON COLUMN company_quarter_fa.model_version IS '분기 FA 산출 모델 버전';
COMMENT ON COLUMN company_quarter_fa.fa_score IS '최종 기업 FA 점수';
COMMENT ON COLUMN company_quarter_fa.is_eligible IS '기업 선정 하드 필터 통과 여부';
COMMENT ON COLUMN company_quarter_fa.excluded_reason_code IS '하드 필터 제외 사유 코드';
COMMENT ON COLUMN company_quarter_fa.score_detail IS '점수 산출 세부 내역 JSON';
COMMENT ON COLUMN company_quarter_fa.calculated_at IS '분기 기업 FA 계산 일시';

COMMENT ON COLUMN fa_analysis_runs.id IS 'FA 분석 실행 고유 ID';
COMMENT ON COLUMN fa_analysis_runs.strategy_id IS '분석 결과를 발행할 전략 ID';
COMMENT ON COLUMN fa_analysis_runs.analysis_month IS '분석 대상 월의 1일';
COMMENT ON COLUMN fa_analysis_runs.cutoff_date IS '분석에 사용할 수 있는 데이터의 기준 마감일';
COMMENT ON COLUMN fa_analysis_runs.effective_date IS '발행된 universe가 trader에 적용될 거래일';
COMMENT ON COLUMN fa_analysis_runs.run_version IS '동일 전략·분석월 내 실행 버전';
COMMENT ON COLUMN fa_analysis_runs.model_version IS '월간 FA 분석 모델 버전';
COMMENT ON COLUMN fa_analysis_runs.status_code IS '실행 상태 (RUNNING/PASS/WARNING/FAIL/PUBLISHED)';
COMMENT ON COLUMN fa_analysis_runs.input_hash IS '입력 데이터와 설정의 재사용 판정 해시';
COMMENT ON COLUMN fa_analysis_runs.created_at IS '분석 실행 생성 일시';
COMMENT ON COLUMN fa_analysis_runs.completed_at IS '분석 실행 완료 일시';
COMMENT ON COLUMN fa_analysis_runs.published_at IS '운영 universe 발행 완료 일시';

COMMENT ON COLUMN fa_macro_results.run_id IS '소속 FA 분석 실행 ID';
COMMENT ON COLUMN fa_macro_results.signal_name_code IS '매크로 시그널 코드';
COMMENT ON COLUMN fa_macro_results.direction_code IS '매크로 방향 (UP/DOWN/FLAT)';

COMMENT ON COLUMN fa_sector_results.run_id IS '소속 FA 분석 실행 ID';
COMMENT ON COLUMN fa_sector_results.industry_code IS 'WICS 중분류 코드';
COMMENT ON COLUMN fa_sector_results.sector_score IS '최종 업종 점수';
COMMENT ON COLUMN fa_sector_results.cohort_quality_penalty IS '코호트 중간 FA 점수 미달에 따른 추가 리스크 패널티';
COMMENT ON COLUMN fa_sector_results.is_selected IS '최종 업종 선정 여부';

COMMENT ON COLUMN fa_company_results.run_id IS '소속 FA 분석 실행 ID';
COMMENT ON COLUMN fa_company_results.stock_code IS '평가 대상 종목코드';
COMMENT ON COLUMN fa_company_results.is_selected IS '최종 기업 선정 여부';

COMMENT ON COLUMN universe.source_fa_company_result_id IS '현재 유니버스 선정 근거 FA 기업 결과 ID';
