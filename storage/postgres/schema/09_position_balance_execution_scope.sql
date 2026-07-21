-- Isolate mutable account state by strategy, execution venue, and masked account.
-- Legacy rows remain UNKNOWN because their original account scope is not safe to infer.

ALTER TABLE positions
    ADD COLUMN IF NOT EXISTS execution_venue_code VARCHAR(20) NOT NULL DEFAULT 'UNKNOWN';
ALTER TABLE positions
    ADD COLUMN IF NOT EXISTS account_scope VARCHAR(100) NOT NULL DEFAULT 'UNKNOWN';

ALTER TABLE balance_history
    ADD COLUMN IF NOT EXISTS execution_venue_code VARCHAR(20) NOT NULL DEFAULT 'UNKNOWN';
ALTER TABLE balance_history
    ADD COLUMN IF NOT EXISTS account_scope VARCHAR(100) NOT NULL DEFAULT 'UNKNOWN';

ALTER TABLE positions
    DROP CONSTRAINT IF EXISTS positions_strategy_id_symbol_instrument_type_code_key;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'positions'::regclass
          AND conname = 'positions_execution_scope_key'
    ) THEN
        ALTER TABLE positions
            ADD CONSTRAINT positions_execution_scope_key UNIQUE (
                strategy_id,
                symbol,
                instrument_type_code,
                execution_venue_code,
                account_scope
            );
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_positions_execution_scope
    ON positions(execution_venue_code, account_scope, strategy_id, symbol);
CREATE INDEX IF NOT EXISTS idx_balance_history_execution_scope
    ON balance_history(execution_venue_code, account_scope, recorded_at);

COMMENT ON COLUMN positions.execution_venue_code IS
    'Execution environment: DRY_RUN/SIMULATE/PAPER/REAL';
COMMENT ON COLUMN positions.account_scope IS
    'Masked account identifier; never store the raw account number here';
COMMENT ON COLUMN balance_history.execution_venue_code IS
    'Execution environment: DRY_RUN/SIMULATE/PAPER/REAL';
COMMENT ON COLUMN balance_history.account_scope IS
    'Masked account identifier; never store the raw account number here';
