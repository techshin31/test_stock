-- ============================================================
-- User schema
-- users, user_broker_credentials
-- Run after 02_codes_seed.sql and before 04_trader_schema.sql.
-- ============================================================

CREATE TABLE users (
    id              SERIAL          PRIMARY KEY,
    email           VARCHAR(255)    NOT NULL UNIQUE,
    display_name    VARCHAR(100),
    is_active       BOOLEAN         NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE  users              IS '트레이딩 시스템 사용자';
COMMENT ON COLUMN users.id           IS '사용자 고유 ID';
COMMENT ON COLUMN users.email        IS '사용자 이메일 (로그인 식별자)';
COMMENT ON COLUMN users.display_name IS '표시 이름';
COMMENT ON COLUMN users.is_active    IS '활성 사용자 여부';
COMMENT ON COLUMN users.created_at   IS '가입 일시';


-- ============================================================
-- 2. 증권사 API 자격증명 (user_broker_credentials)
-- ============================================================
CREATE TABLE user_broker_credentials (
    id               SERIAL          PRIMARY KEY,
    user_id          INT             NOT NULL REFERENCES users(id),
    broker_code      VARCHAR(50)     NOT NULL,
    account_number   VARCHAR(50)     NOT NULL,
    api_key          TEXT            NOT NULL,
    api_secret       TEXT            NOT NULL,
    environment_code VARCHAR(20)     NOT NULL DEFAULT 'PAPER',
    extra            JSONB           NOT NULL DEFAULT '{}'::jsonb,
    is_active        BOOLEAN         NOT NULL DEFAULT TRUE,
    created_at       TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    updated_at       TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    UNIQUE (user_id, broker_code, account_number, environment_code),
    CONSTRAINT ck_user_broker_credentials_env
        CHECK (environment_code IN ('REAL', 'PAPER'))
);

CREATE INDEX idx_user_broker_credentials_user_id ON user_broker_credentials(user_id);

COMMENT ON TABLE  user_broker_credentials                  IS '유저별 증권사 API 자격증명 — api_key/api_secret은 앱 레이어에서 AES 암호화 후 저장';
COMMENT ON COLUMN user_broker_credentials.id               IS '자격증명 고유 ID';
COMMENT ON COLUMN user_broker_credentials.user_id          IS '소유 사용자 ID';
COMMENT ON COLUMN user_broker_credentials.broker_code      IS '증권사 코드 (예: KIS, EBEST)';
COMMENT ON COLUMN user_broker_credentials.account_number   IS '증권 계좌번호';
COMMENT ON COLUMN user_broker_credentials.api_key          IS '증권사 API 키 (Fernet 암호화)';
COMMENT ON COLUMN user_broker_credentials.api_secret       IS '증권사 API 시크릿 (Fernet 암호화)';
COMMENT ON COLUMN user_broker_credentials.environment_code IS '거래 환경 — REAL: 실계좌 / PAPER: 모의투자';
COMMENT ON COLUMN user_broker_credentials.extra            IS '증권사별 추가 인증 정보 (예: KIS의 account_product_code) — 제공자가 바뀌어도 스키마 변경 없이 확장 가능';
COMMENT ON COLUMN user_broker_credentials.is_active        IS '활성 자격증명 여부';
COMMENT ON COLUMN user_broker_credentials.created_at       IS '등록 일시';
COMMENT ON COLUMN user_broker_credentials.updated_at       IS '최종 수정 일시';

CREATE TRIGGER trg_user_broker_credentials_updated_at
    BEFORE UPDATE ON user_broker_credentials
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();
