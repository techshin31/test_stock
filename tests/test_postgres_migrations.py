from storage.postgres.migrate import MIGRATION_ADVISORY_LOCK_ID, discover_migrations
from storage.postgres.migrate import SCHEMA_DIR
from storage.postgres import migrate
from psycopg.conninfo import conninfo_to_dict
import pytest


@pytest.mark.parametrize("password", ["pass@host:/?#", "spaces and 'quotes' \\ slash"])
def test_migration_connection_preserves_special_characters(monkeypatch, password):
    monkeypatch.setattr(migrate, "load_dotenv", lambda **kwargs: None)
    monkeypatch.setenv("POSTGRES_HOST", "127.0.0.1")
    monkeypatch.setenv("POSTGRES_PORT", "5433")
    monkeypatch.setenv("POSTGRES_USER", "admin")
    monkeypatch.setenv("POSTGRES_DB", "quantpilot_db")
    monkeypatch.setenv("POSTGRES_PASSWORD", password)

    params = conninfo_to_dict(migrate._connection_uri())

    assert params["password"] == password
    assert params["host"] == "127.0.0.1"
    assert params["port"] == "5433"
    assert params["dbname"] == "quantpilot_db"


def test_migration_rejects_missing_password(monkeypatch):
    monkeypatch.setattr(migrate, "load_dotenv", lambda **kwargs: None)
    monkeypatch.delenv("POSTGRES_PASSWORD", raising=False)
    with pytest.raises(ValueError, match="POSTGRES_PASSWORD is required"):
        migrate._connection_uri()


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
