-- ============================================================
-- Trader operational schema
-- strategies, universe, trade_plans, orders, executions, positions, balance_history
-- Run after 03_user_schema.sql.
-- ============================================================

CREATE TABLE strategies (
    id              SERIAL          PRIMARY KEY,
    user_id         INT             NOT NULL REFERENCES users(id),
    name            VARCHAR(100)    NOT NULL,
    description     TEXT,
    params          JSONB,
    is_active       BOOLEAN         NOT NULL DEFAULT FALSE,
    created_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    UNIQUE (user_id, name)
);

COMMENT ON TABLE  strategies             IS '트레이딩 전략 목록 및 파라미터 관리';
COMMENT ON COLUMN strategies.id          IS '전략 고유 ID';
COMMENT ON COLUMN strategies.user_id     IS '전략 소유 사용자 ID';
COMMENT ON COLUMN strategies.name        IS '전략 이름 (유저 내 고유, 예: ADX_TREND_V1)';
COMMENT ON COLUMN strategies.description IS '전략 설명';
COMMENT ON COLUMN strategies.params      IS 'ADX period, threshold 등 전략별 파라미터 JSON';
COMMENT ON COLUMN strategies.is_active   IS '현재 실행 중인 전략 여부';
COMMENT ON COLUMN strategies.created_at  IS '생성 일시';
COMMENT ON COLUMN strategies.updated_at  IS '최종 수정 일시';


-- ============================================================
-- 2. 투자 유니버스 (universe) — FA 분석으로 선정된 투자 대상 종목
-- ============================================================
CREATE TABLE universe (
    id                   SERIAL          PRIMARY KEY,
    strategy_id          INT             NOT NULL REFERENCES strategies(id),
    symbol               VARCHAR(20)     NOT NULL,
    market_type_code     VARCHAR(50)     NOT NULL,
    instrument_type_code VARCHAR(50)     NOT NULL DEFAULT 'STOCK',
    universe_status_code VARCHAR(50)     NOT NULL DEFAULT 'ACTIVE',
    fa_score             NUMERIC(8, 4),
    entry_date           DATE            NOT NULL,
    exit_deadline        DATE,
    created_at           TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    updated_at           TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    UNIQUE (strategy_id, symbol)
);

CREATE INDEX idx_universe_strategy_id         ON universe(strategy_id);
CREATE INDEX idx_universe_universe_status_code ON universe(universe_status_code);

COMMENT ON TABLE  universe                        IS 'FA 분석으로 선정된 투자 대상 종목 풀 — 전략별 유니버스 관리';
COMMENT ON COLUMN universe.id                     IS '유니버스 항목 고유 ID';
COMMENT ON COLUMN universe.strategy_id            IS '유니버스를 소유한 전략 ID';
COMMENT ON COLUMN universe.symbol                 IS '종목 코드';
COMMENT ON COLUMN universe.market_type_code       IS '상장 거래소 (codes.MARKET_TYPE)';
COMMENT ON COLUMN universe.instrument_type_code   IS '종목 유형 (codes.INSTRUMENT_TYPE)';
COMMENT ON COLUMN universe.universe_status_code   IS '운용 상태 — ACTIVE: 정상 매매 / SELL_ONLY: 청산 대기 / REMOVED: 제거됨';
COMMENT ON COLUMN universe.fa_score               IS 'FA 분석 점수 (높을수록 우선 편입, NULL 허용)';
COMMENT ON COLUMN universe.entry_date             IS '유니버스 편입 날짜';
COMMENT ON COLUMN universe.exit_deadline          IS 'SELL_ONLY 전환 후 강제 청산 마감일';
COMMENT ON COLUMN universe.created_at             IS '최초 편입 일시';
COMMENT ON COLUMN universe.updated_at             IS '최종 수정 일시';

CREATE TRIGGER trg_universe_updated_at
    BEFORE UPDATE ON universe
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();


-- ============================================================
-- 3. 거래 계획 (trade_plans) — 새벽에 당일 거래 계획 저장
-- ============================================================
CREATE TABLE trade_plans (
    id              SERIAL          PRIMARY KEY,
    strategy_id     INT             NOT NULL REFERENCES strategies(id),
    plan_date       DATE            NOT NULL,
    symbol          VARCHAR(20)     NOT NULL,
    market_type_code     VARCHAR(50)     NOT NULL,
    instrument_type_code VARCHAR(50)     NOT NULL DEFAULT 'STOCK',
    order_side_code      VARCHAR(50),
    planned_qty     NUMERIC(18, 4),
    planned_price   NUMERIC(18, 4),
    order_type_code      VARCHAR(50)     NOT NULL DEFAULT 'MARKET',
    plan_status_code     VARCHAR(50)     NOT NULL DEFAULT 'PENDING',
    trade_reason_code    VARCHAR(50),
    prev_weight          NUMERIC(8, 6),
    target_weight        NUMERIC(8, 6),
    regime_code          VARCHAR(20),
    price_deviation_limit NUMERIC(8, 6),
    reason               TEXT,
    created_at           TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    updated_at           TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX uq_trade_plans_date_strategy_symbol ON trade_plans(plan_date, strategy_id, symbol);

CREATE INDEX idx_trade_plans_plan_date         ON trade_plans(plan_date);
CREATE INDEX idx_trade_plans_plan_status_code  ON trade_plans(plan_status_code);
CREATE INDEX idx_trade_plans_strategy_id       ON trade_plans(strategy_id);
CREATE INDEX idx_trade_plans_symbol            ON trade_plans(symbol);
CREATE INDEX idx_trade_plans_trade_reason_code ON trade_plans(trade_reason_code);

COMMENT ON TABLE  trade_plans               IS '새벽에 생성되는 당일 거래 계획 — 시스템이 이 테이블을 읽어 장중에 주문 실행';
COMMENT ON COLUMN trade_plans.id            IS '계획 고유 ID';
COMMENT ON COLUMN trade_plans.strategy_id   IS '계획을 생성한 전략 ID';
COMMENT ON COLUMN trade_plans.plan_date     IS '거래 예정일 (당일)';
COMMENT ON COLUMN trade_plans.symbol        IS '종목 코드';
COMMENT ON COLUMN trade_plans.market_type_code   IS '상장 거래소 (codes.MARKET_TYPE)';
COMMENT ON COLUMN trade_plans.instrument_type_code IS '종목 유형 (codes.INSTRUMENT_TYPE)';
COMMENT ON COLUMN trade_plans.order_side_code    IS '매수/매도 (codes.ORDER_SIDE) — NULL이면 오늘 주문 의도 없음 (plan_status_code=SKIPPED)';
COMMENT ON COLUMN trade_plans.planned_qty   IS '계획 수량 — NULL이면 오늘 주문 의도 없음 (plan_status_code=SKIPPED)';
COMMENT ON COLUMN trade_plans.planned_price IS '계획 가격 — NULL이면 시장가 주문';
COMMENT ON COLUMN trade_plans.order_type_code    IS '주문 유형 (codes.ORDER_TYPE)';
COMMENT ON COLUMN trade_plans.plan_status_code   IS '계획 처리 상태 (codes.PLAN_STATUS)';
COMMENT ON COLUMN trade_plans.trade_reason_code  IS '매매 신호 종류 (codes.TRADE_REASON — UPTREND_ENTRY1, REBALANCE_SELL 등)';
COMMENT ON COLUMN trade_plans.prev_weight        IS '계획 시점의 이전 비중 — 소수 형태 (예: 0.100000 = 10%)';
COMMENT ON COLUMN trade_plans.target_weight      IS '계획 시점의 목표 비중 — 소수 형태 (예: 0.150000 = 15%)';
COMMENT ON COLUMN trade_plans.regime_code             IS '계획 생성 시점의 시장 국면 (UPTREND / DOWNTREND / TRANSITION / SIDEWAYS)';
COMMENT ON COLUMN trade_plans.price_deviation_limit   IS '장중 호가 편차 허용 한도 — NULL/0이면 항상 실행, 양수면 편차 초과 시 사이클 스킵';
COMMENT ON COLUMN trade_plans.reason                  IS '추가 설명 (예: ADX=32.5 상향돌파)';
COMMENT ON COLUMN trade_plans.created_at    IS '계획 생성 일시 (새벽 배치 실행 시각)';
COMMENT ON COLUMN trade_plans.updated_at    IS '최종 수정 일시';


-- ============================================================
-- 4. 주문 (orders)
-- ============================================================
CREATE TABLE orders (
    id              UUID            PRIMARY KEY DEFAULT uuid_generate_v4(),
    strategy_id     INT             REFERENCES strategies(id),
    plan_id         INT             REFERENCES trade_plans(id),
    broker_order_id VARCHAR(100),
    symbol          VARCHAR(20)     NOT NULL,
    market_type_code     VARCHAR(50)     NOT NULL,
    instrument_type_code VARCHAR(50)     NOT NULL DEFAULT 'STOCK',
    order_side_code      VARCHAR(50)     NOT NULL,
    order_type_code      VARCHAR(50)     NOT NULL,
    qty             NUMERIC(18, 4)  NOT NULL,
    price           NUMERIC(18, 4),
    stop_price      NUMERIC(18, 4),
    order_status_code    VARCHAR(50)     NOT NULL DEFAULT 'PENDING',
    execution_venue_code VARCHAR(20)     NOT NULL DEFAULT 'UNKNOWN',
    account_scope        VARCHAR(100)    NOT NULL DEFAULT 'UNKNOWN',
    filled_qty      NUMERIC(18, 4)  NOT NULL DEFAULT 0,
    avg_fill_price  NUMERIC(18, 4),
    commission      NUMERIC(18, 4)  NOT NULL DEFAULT 0,
    note            TEXT,
    submitted_at    TIMESTAMPTZ,
    filled_at       TIMESTAMPTZ,
    cancelled_at    TIMESTAMPTZ,
    idempotency_key VARCHAR(255),
    created_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_orders_symbol            ON orders(symbol);
CREATE INDEX idx_orders_order_status_code ON orders(order_status_code);
CREATE INDEX idx_orders_strategy_id       ON orders(strategy_id);
CREATE INDEX idx_orders_plan_id           ON orders(plan_id);
CREATE INDEX idx_orders_created_at        ON orders(created_at);
CREATE INDEX idx_orders_execution_scope   ON orders(execution_venue_code, account_scope, created_at);
CREATE UNIQUE INDEX uq_orders_idempotency_key ON orders(idempotency_key)
    WHERE idempotency_key IS NOT NULL;

COMMENT ON TABLE  orders                  IS '매수/매도 주문 전체 이력';
COMMENT ON COLUMN orders.id               IS '주문 고유 ID (UUID)';
COMMENT ON COLUMN orders.strategy_id      IS '주문을 발생시킨 전략 ID';
COMMENT ON COLUMN orders.plan_id          IS '연결된 거래 계획 ID (trade_plans)';
COMMENT ON COLUMN orders.broker_order_id  IS '증권사에서 발급한 주문 ID';
COMMENT ON COLUMN orders.symbol           IS '종목 코드 (예: 005930=삼성전자, 069500=KODEX200)';
COMMENT ON COLUMN orders.market_type_code      IS '상장 거래소 (codes.MARKET_TYPE)';
COMMENT ON COLUMN orders.instrument_type_code  IS '종목 유형 (codes.INSTRUMENT_TYPE)';
COMMENT ON COLUMN orders.order_side_code       IS '매수/매도 (codes.ORDER_SIDE)';
COMMENT ON COLUMN orders.order_type_code       IS '주문 유형 (codes.ORDER_TYPE)';
COMMENT ON COLUMN orders.qty              IS '주문 수량';
COMMENT ON COLUMN orders.price            IS '지정가 주문 시 희망 가격 (시장가이면 NULL)';
COMMENT ON COLUMN orders.stop_price       IS '스탑 주문 트리거 가격';
COMMENT ON COLUMN orders.order_status_code     IS '주문 상태 (codes.ORDER_STATUS)';
COMMENT ON COLUMN orders.execution_venue_code  IS '실행 환경: DRY_RUN/SIMULATE/PAPER/REAL';
COMMENT ON COLUMN orders.account_scope         IS '원문 계좌번호가 아닌 마스킹된 계좌 식별 범위';
COMMENT ON COLUMN orders.filled_qty       IS '실제 체결된 누적 수량';
COMMENT ON COLUMN orders.avg_fill_price   IS '평균 체결 단가';
COMMENT ON COLUMN orders.commission       IS '총 수수료';
COMMENT ON COLUMN orders.note             IS '비고 (수동 메모 등)';
COMMENT ON COLUMN orders.submitted_at     IS '증권사에 주문 제출된 시각';
COMMENT ON COLUMN orders.filled_at        IS '완전 체결된 시각';
COMMENT ON COLUMN orders.cancelled_at     IS '취소된 시각';
COMMENT ON COLUMN orders.idempotency_key  IS '중복 주문 방지를 위한 거래일·전략·종목·방향 기반 멱등성 키';
COMMENT ON COLUMN orders.created_at       IS '주문 생성 일시';
COMMENT ON COLUMN orders.updated_at       IS '최종 수정 일시';


-- ============================================================
-- 5. 주문 상태 이력 (order_status_history)
-- ============================================================
CREATE TABLE order_status_history (
    id                  UUID            PRIMARY KEY DEFAULT uuid_generate_v4(),
    order_id            UUID            NOT NULL REFERENCES orders(id),
    broker_order_id     VARCHAR(100),
    order_status_code   VARCHAR(50)     NOT NULL,
    event_type          VARCHAR(50)     NOT NULL,
    filled_qty          NUMERIC(18, 4),
    remaining_qty       NUMERIC(18, 4),
    avg_fill_price      NUMERIC(18, 4),
    message             TEXT,
    raw_payload         JSONB,
    created_at          TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_order_status_history_order_id        ON order_status_history(order_id);
CREATE INDEX idx_order_status_history_broker_order_id ON order_status_history(broker_order_id);
CREATE INDEX idx_order_status_history_created_at      ON order_status_history(created_at);

COMMENT ON TABLE  order_status_history                    IS '주문 상태 변화 및 브로커 조회/취소 이벤트 이력';
COMMENT ON COLUMN order_status_history.id                 IS '주문 상태 이력 고유 ID';
COMMENT ON COLUMN order_status_history.order_id           IS '연결된 orders.id';
COMMENT ON COLUMN order_status_history.broker_order_id    IS '증권사 주문번호';
COMMENT ON COLUMN order_status_history.order_status_code  IS '해당 시점의 주문 상태 코드';
COMMENT ON COLUMN order_status_history.event_type         IS '상태 이벤트 유형 (CREATE, ACCEPTED, STATUS_POLL, CANCEL_REQUEST 등)';
COMMENT ON COLUMN order_status_history.filled_qty         IS '해당 시점의 누적 체결 수량';
COMMENT ON COLUMN order_status_history.remaining_qty      IS '해당 시점의 잔량';
COMMENT ON COLUMN order_status_history.avg_fill_price     IS '해당 시점의 평균 체결 단가';
COMMENT ON COLUMN order_status_history.message            IS '상태 변경 또는 오류 설명';
COMMENT ON COLUMN order_status_history.raw_payload        IS '브로커 원문 응답 또는 진단 payload';
COMMENT ON COLUMN order_status_history.created_at         IS '이력 기록 시각';


-- ============================================================
-- 6. 체결 내역 (executions)
-- ============================================================
CREATE TABLE executions (
    id              UUID            PRIMARY KEY DEFAULT uuid_generate_v4(),
    order_id        UUID            NOT NULL REFERENCES orders(id),
    symbol          VARCHAR(20)     NOT NULL,
    market_type_code     VARCHAR(50)     NOT NULL,
    instrument_type_code VARCHAR(50)     NOT NULL DEFAULT 'STOCK',
    order_side_code      VARCHAR(50)     NOT NULL,
    qty             NUMERIC(18, 4)  NOT NULL,
    price           NUMERIC(18, 4)  NOT NULL,
    amount          NUMERIC(18, 4)  NOT NULL,
    commission      NUMERIC(18, 4)  NOT NULL DEFAULT 0,
    tax             NUMERIC(18, 4)  NOT NULL DEFAULT 0,
    slippage        NUMERIC(18, 4)  NOT NULL DEFAULT 0,
    net_amount      NUMERIC(18, 4)  NOT NULL,
    executed_at     TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_executions_order_id    ON executions(order_id);
CREATE INDEX idx_executions_symbol      ON executions(symbol);
CREATE INDEX idx_executions_executed_at ON executions(executed_at);

COMMENT ON TABLE  executions               IS '주문별 실제 체결 내역 (1주문 = N체결 가능)';
COMMENT ON COLUMN executions.id            IS '체결 고유 ID (UUID)';
COMMENT ON COLUMN executions.order_id      IS '연결된 주문 ID';
COMMENT ON COLUMN executions.symbol        IS '종목 코드';
COMMENT ON COLUMN executions.market_type_code   IS '상장 거래소 (codes.MARKET_TYPE)';
COMMENT ON COLUMN executions.instrument_type_code IS '종목 유형 (codes.INSTRUMENT_TYPE)';
COMMENT ON COLUMN executions.order_side_code    IS '매수/매도 (codes.ORDER_SIDE)';
COMMENT ON COLUMN executions.qty           IS '이번 체결 수량';
COMMENT ON COLUMN executions.price         IS '체결 단가';
COMMENT ON COLUMN executions.amount        IS '체결 금액 (qty * price)';
COMMENT ON COLUMN executions.commission    IS '이번 체결 수수료';
COMMENT ON COLUMN executions.tax           IS '증권거래세: 국내 주식 매도 시 0.18~0.20% / ETF·선물·크립토는 0';
COMMENT ON COLUMN executions.slippage      IS '슬리피지 비용 (예상가 대비 실체결가 차이)';
COMMENT ON COLUMN executions.net_amount    IS '실제 정산 금액 — 매수: -(amount + commission), 매도: amount - commission - tax';
COMMENT ON COLUMN executions.executed_at   IS '체결 일시';


-- ============================================================
-- 7. 포지션 (positions) — 현재 보유 종목
-- ============================================================
CREATE TABLE positions (
    id              SERIAL          PRIMARY KEY,
    strategy_id     INT             REFERENCES strategies(id),
    symbol          VARCHAR(20)     NOT NULL,
    market_type_code     VARCHAR(50)     NOT NULL,
    instrument_type_code VARCHAR(50)     NOT NULL DEFAULT 'STOCK',
    qty             NUMERIC(18, 4)  NOT NULL DEFAULT 0,
    avg_cost        NUMERIC(18, 4)  NOT NULL,
    realized_pnl    NUMERIC(18, 4)  NOT NULL DEFAULT 0,
    opened_at       TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    UNIQUE (strategy_id, symbol, instrument_type_code)
);

ALTER TABLE positions DROP CONSTRAINT IF EXISTS ck_positions_normalized_symbol;
ALTER TABLE positions ADD CONSTRAINT ck_positions_normalized_symbol
    CHECK (symbol ~ '^[0-9]{6}$');

CREATE INDEX idx_positions_symbol      ON positions(symbol);
CREATE INDEX idx_positions_strategy_id ON positions(strategy_id);

COMMENT ON TABLE  positions               IS '현재 보유 중인 포지션 (전략 × 종목 × 유형 당 1행)';
COMMENT ON COLUMN positions.id            IS '포지션 고유 ID';
COMMENT ON COLUMN positions.strategy_id   IS '포지션을 보유한 전략 ID';
COMMENT ON COLUMN positions.symbol        IS '종목 코드';
COMMENT ON COLUMN positions.market_type_code   IS '상장 거래소 (codes.MARKET_TYPE)';
COMMENT ON COLUMN positions.instrument_type_code IS '종목 유형 (codes.INSTRUMENT_TYPE)';
COMMENT ON COLUMN positions.qty           IS '현재 보유 수량 (0이면 청산 상태)';
COMMENT ON COLUMN positions.avg_cost      IS '평균 매수 단가 (수수료 포함)';
COMMENT ON COLUMN positions.realized_pnl  IS '누적 실현 손익';
COMMENT ON COLUMN positions.opened_at     IS '포지션 최초 진입 일시';
COMMENT ON COLUMN positions.updated_at    IS '최종 수정 일시';


-- ============================================================
-- 8. 잔고 히스토리 (balance_history)
-- ============================================================
CREATE TABLE balance_history (
    id              SERIAL          PRIMARY KEY,
    strategy_id     INT             REFERENCES strategies(id),
    cash            NUMERIC(18, 4)  NOT NULL,
    stock_value     NUMERIC(18, 4)  NOT NULL,
    total_value     NUMERIC(18, 4)  NOT NULL,
    daily_return    NUMERIC(10, 6),
    recorded_at     TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_balance_history_strategy_id ON balance_history(strategy_id);
CREATE INDEX idx_balance_history_recorded_at ON balance_history(recorded_at);

COMMENT ON TABLE  balance_history              IS '전략별 일별 잔고 스냅샷 (수익률 계산용)';
COMMENT ON COLUMN balance_history.id           IS '잔고 기록 고유 ID';
COMMENT ON COLUMN balance_history.strategy_id  IS '전략 ID';
COMMENT ON COLUMN balance_history.cash         IS '현금 잔고';
COMMENT ON COLUMN balance_history.stock_value  IS '보유 종목 평가금액 합계';
COMMENT ON COLUMN balance_history.total_value  IS '총 자산 (cash + stock_value)';
COMMENT ON COLUMN balance_history.daily_return IS '일간 수익률 — 소수 형태 (예: 0.012 = 1.2%)';
COMMENT ON COLUMN balance_history.recorded_at  IS '기록 일시 (보통 장 마감 후 1회)';


-- ============================================================
-- 9. updated_at 자동 갱신 트리거
-- ============================================================
CREATE TRIGGER trg_strategies_updated_at
    BEFORE UPDATE ON strategies
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TRIGGER trg_trade_plans_updated_at
    BEFORE UPDATE ON trade_plans
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TRIGGER trg_orders_updated_at
    BEFORE UPDATE ON orders
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TRIGGER trg_positions_updated_at
    BEFORE UPDATE ON positions
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();


-- ============================================================
-- 10. Row Level Security — 전략 소유자 격리
-- ============================================================
ALTER TABLE strategies ENABLE ROW LEVEL SECURITY;

CREATE POLICY strategies_user_isolation ON strategies
    USING (user_id = current_setting('app.current_user_id')::INT);

COMMENT ON POLICY strategies_user_isolation ON strategies
    IS '애플리케이션이 SET LOCAL app.current_user_id = <id> 설정 후 쿼리하면 자신의 전략만 접근 가능';
