-- ============================================================
-- Common code tables and database utilities
-- Run before all other schema files.
-- ============================================================

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";


CREATE TABLE IF NOT EXISTS code_groups (
    code_group  VARCHAR(50)     PRIMARY KEY,
    name        VARCHAR(100)    NOT NULL,
    description TEXT
);

COMMENT ON TABLE  code_groups             IS 'ENUM 클래스 정의 — 각 코드 그룹의 메타 정보';
COMMENT ON COLUMN code_groups.code_group  IS '코드 그룹 ID (예: ORDER_SIDE, MARKET_TYPE)';
COMMENT ON COLUMN code_groups.name        IS '코드 그룹 한글명 (예: 주문 방향)';
COMMENT ON COLUMN code_groups.description IS '코드 그룹 설명';


CREATE TABLE IF NOT EXISTS codes (
    code_group  VARCHAR(50)     NOT NULL,
    code        VARCHAR(50)     NOT NULL,
    name        VARCHAR(100)    NOT NULL,
    description TEXT,
    sort_order  INT             NOT NULL DEFAULT 0,
    is_active   BOOLEAN         NOT NULL DEFAULT TRUE,
    PRIMARY KEY (code_group, code)
);

COMMENT ON TABLE  codes            IS 'ENUM 상수 정의 — code_groups 하위 코드값 목록';
COMMENT ON COLUMN codes.code_group IS '소속 코드 그룹 (code_groups.code_group 참조)';
COMMENT ON COLUMN codes.code       IS '코드값 (예: BUY, SELL)';
COMMENT ON COLUMN codes.name       IS '코드 한글명 (예: 매수, 매도)';
COMMENT ON COLUMN codes.description IS '코드 상세 설명';
COMMENT ON COLUMN codes.sort_order IS '정렬 순서';
COMMENT ON COLUMN codes.is_active  IS '사용 여부 (FALSE면 선택 불가)';


-- ============================================================
-- updated_at auto refresh function
-- ============================================================
CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    -- updated_at을 OLD 값으로 정규화한 뒤 실제 데이터 변경 여부 비교
    -- 변경된 컬럼이 있을 때만 updated_at 갱신
    NEW.updated_at = OLD.updated_at;
    IF OLD IS DISTINCT FROM NEW THEN
        NEW.updated_at = NOW();
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
