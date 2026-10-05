"""Exercise pg_dump/pg_restore against new, disposable PostgreSQL databases."""
import os
from pathlib import Path
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict
import pytest

from apps.backtester.config import load_env
from apps.system import recovery
from integration.test_postgres_api import _empty_verification_database

pytestmark = pytest.mark.skipif(os.getenv("QUANTPILOT_RUN_DB_INTEGRATION") != "1", reason="Requires local PostgreSQL")


def test_backup_restore_verifies_content_and_refuses_existing_database(monkeypatch, tmp_path):
    load_env()
    cache = tmp_path / "public-cache"
    cache.mkdir()
    (cache / "quote.csv").write_text("date,close\n2026-10-02,100\n")
    (cache / ".env").write_text("DO_NOT_ARCHIVE=test-only\n")
    with _empty_verification_database() as (conn, uri):
        params = conninfo_to_dict(uri)
        config = {"host": params["host"], "port": params["port"], "user": params["user"],
                  "password": params["password"], "database": params["dbname"]}
        monkeypatch.setattr(recovery, "build_db_config", lambda: config)
        conn.execute("CREATE TABLE recovery_example (id INTEGER PRIMARY KEY, value TEXT)")
        conn.execute("INSERT INTO recovery_example VALUES (1, 'original'), (2, '한글 원본')")
        conn.execute("CREATE TABLE user_broker_credentials (api_secret TEXT)")
        conn.execute("INSERT INTO user_broker_credentials VALUES ('synthetic-test-secret')")
        directory = tmp_path / "backup"
        assert recovery.backup(directory, cache)["counts_stable"]
        restored = recovery.restore(directory)
        name = restored["database"]
        try:
            assert restored["row_counts"] == {"recovery_example": 2, "user_broker_credentials": 0}
            assert conn.execute("SELECT value FROM recovery_example ORDER BY id").fetchall() == [("original",), ("한글 원본",)]
            import psycopg
            with psycopg.connect(**recovery.parameters(config, name)) as copy:
                assert copy.execute("SELECT value FROM recovery_example ORDER BY id").fetchall() == [("original",), ("한글 원본",)]
            source = Path(restored["source_directory"])
            assert (source / "quote.csv").read_bytes() == (cache / "quote.csv").read_bytes()
            assert not (source / ".env").exists()
            with pytest.raises(ValueError, match="ALREADY_EXISTS"):
                recovery.restore(directory, name)
            with pytest.raises(ValueError, match="ISOLATED"):
                recovery.restore(directory, config["database"])
        finally:
            with recovery.psycopg.connect(**recovery.parameters(config, "postgres"), autocommit=True) as admin:
                admin.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(name)))
