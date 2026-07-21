from storage.postgres.migrate import MIGRATION_ADVISORY_LOCK_ID, discover_migrations
from storage.postgres.migrate import SCHEMA_DIR


def test_runtime_migrations_are_ordered_and_checksummed():
    migrations = discover_migrations()

    assert [migration.version for migration in migrations] == ["08", "09"]
    assert migrations[0].path.name == "08_order_execution_scope.sql"
    assert migrations[1].path.name == "09_position_balance_execution_scope.sql"
    assert all(len(migration.checksum) == 64 for migration in migrations)
    assert isinstance(MIGRATION_ADVISORY_LOCK_ID, int)


def test_fresh_schema_and_runtime_migration_share_position_constraint_name():
    fresh_schema = (SCHEMA_DIR / "04_trader_schema.sql").read_text(encoding="utf-8")
    migration = (SCHEMA_DIR / "09_position_balance_execution_scope.sql").read_text(
        encoding="utf-8"
    )

    assert "CONSTRAINT positions_execution_scope_key UNIQUE" in fresh_schema
    assert "conname = 'positions_execution_scope_key'" in migration
