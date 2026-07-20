-- Scope operational order/execution metrics by strategy, venue, account and date.
-- Existing rows remain UNKNOWN because their original venue/account cannot be
-- reconstructed safely from the hashed idempotency key.
ALTER TABLE orders
    ADD COLUMN IF NOT EXISTS execution_venue_code VARCHAR(20) NOT NULL DEFAULT 'UNKNOWN';

ALTER TABLE orders
    ADD COLUMN IF NOT EXISTS account_scope VARCHAR(100) NOT NULL DEFAULT 'UNKNOWN';

CREATE INDEX IF NOT EXISTS idx_orders_execution_scope
    ON orders(execution_venue_code, account_scope, created_at);

COMMENT ON COLUMN orders.execution_venue_code IS
    'Execution environment: DRY_RUN/SIMULATE/PAPER/REAL';
COMMENT ON COLUMN orders.account_scope IS
    'Masked account identifier; never store the raw account number here';
