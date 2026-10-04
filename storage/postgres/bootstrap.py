"""Initialize an empty application database without overwriting existing data."""
from __future__ import annotations

import json
import re

import psycopg

from storage.postgres.migrate import (
    MIGRATION_ADVISORY_LOCK_ID, MIGRATION_START_VERSION, SCHEMA_DIR,
    _connection_uri, apply_migrations,
)


class IncompleteDatabaseError(RuntimeError):
    pass


def initial_schema_files():
    return [
        path for path in sorted(SCHEMA_DIR.glob("[0-9][0-9]_*.sql"))
        if int(path.name[:2]) < MIGRATION_START_VERSION
    ]


def required_tables() -> set[str]:
    return {
        name
        for path in initial_schema_files()
        for name in re.findall(
            r"^CREATE TABLE(?: IF NOT EXISTS)?\s+([a-z_]+)",
            path.read_text(encoding="utf-8"), re.MULTILINE,
        )
    }


def initialize_empty_database(conn) -> list[str]:
    """Apply all base schemas/seeds in one transaction; refuse partial schemas."""
    conn.execute("SELECT pg_advisory_lock(%s)", (MIGRATION_ADVISORY_LOCK_ID,))
    try:
        tables = {
            row[0] for row in conn.execute(
                "SELECT tablename FROM pg_tables WHERE schemaname = 'public'"
            ).fetchall()
        }
        expected = required_tables()
        if not expected:
            raise IncompleteDatabaseError("No initial schema tables were found")
        if expected <= tables:
            return []
        if tables:
            raise IncompleteDatabaseError(
                "Database is nonempty but incomplete; initialization refused. "
                "Missing tables: " + ", ".join(sorted(expected - tables))
            )
        files = initial_schema_files()
        with conn.transaction():
            for path in files:
                conn.execute(path.read_text(encoding="utf-8"))
        return [path.name for path in files]
    finally:
        conn.execute("SELECT pg_advisory_unlock(%s)", (MIGRATION_ADVISORY_LOCK_ID,))


def main() -> int:
    from apps.backtester.config import load_env

    load_env()
    try:
        with psycopg.connect(_connection_uri(), autocommit=True) as conn:
            initialized = initialize_empty_database(conn)
        migrated = apply_migrations()
    except IncompleteDatabaseError as exc:
        print(json.dumps({"ok": False, "reason": str(exc)}))
        return 2
    except (psycopg.Error, OSError, ValueError) as exc:
        # Connection exceptions may contain authentication information.
        print(json.dumps({"ok": False, "error_type": type(exc).__name__}))
        return 1
    print(json.dumps({"ok": True, "initialized": initialized, "migrated": migrated}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
