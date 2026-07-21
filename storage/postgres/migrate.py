"""Apply forward-only PostgreSQL migrations required by the trading runtime."""
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path

import psycopg
from dotenv import load_dotenv


SCHEMA_DIR = Path(__file__).resolve().parent / "schema"
MIGRATION_START_VERSION = 8
MIGRATION_ADVISORY_LOCK_ID = 728194061


@dataclass(frozen=True)
class Migration:
    version: str
    path: Path
    checksum: str


def discover_migrations(schema_dir: Path = SCHEMA_DIR) -> list[Migration]:
    migrations = []
    for path in sorted(schema_dir.glob("[0-9][0-9]_*.sql")):
        version = path.name.split("_", 1)[0]
        if int(version) < MIGRATION_START_VERSION:
            continue
        checksum = hashlib.sha256(path.read_bytes()).hexdigest()
        migrations.append(Migration(version, path, checksum))
    return migrations


def _connection_uri() -> str:
    load_dotenv(dotenv_path=Path.cwd() / ".env")
    host = os.getenv("POSTGRES_HOST", "localhost")
    port = int(os.getenv("POSTGRES_PORT", "5433"))
    user = os.getenv("POSTGRES_USER", "admin")
    password = os.getenv("POSTGRES_PASSWORD", "")
    database = os.getenv("POSTGRES_DB", "quantpilot_db")
    if not password:
        raise ValueError("POSTGRES_PASSWORD is required to apply database migrations")
    return f"postgresql://{user}:{password}@{host}:{port}/{database}"


def apply_migrations(schema_dir: Path = SCHEMA_DIR) -> list[str]:
    applied_now = []
    with psycopg.connect(_connection_uri(), autocommit=True) as conn:
        conn.execute(
            "SELECT pg_advisory_lock(%s)", (MIGRATION_ADVISORY_LOCK_ID,)
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version VARCHAR(20) PRIMARY KEY,
                filename TEXT NOT NULL,
                checksum VARCHAR(64) NOT NULL,
                applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """
        )
        for migration in discover_migrations(schema_dir):
            row = conn.execute(
                "SELECT filename, checksum FROM schema_migrations WHERE version = %s",
                (migration.version,),
            ).fetchone()
            if row is not None:
                if row[1] != migration.checksum:
                    raise RuntimeError(
                        f"migration {migration.version} checksum changed: "
                        f"recorded={row[1]} current={migration.checksum}"
                    )
                continue
            sql_text = migration.path.read_text(encoding="utf-8")
            with conn.transaction():
                conn.execute(sql_text)
                conn.execute(
                    """
                    INSERT INTO schema_migrations(version, filename, checksum)
                    VALUES (%s, %s, %s)
                    """,
                    (migration.version, migration.path.name, migration.checksum),
                )
            applied_now.append(migration.version)
    return applied_now


def main() -> int:
    applied = apply_migrations()
    print(json.dumps({"ok": True, "applied": applied}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
