from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo
import os

import psycopg
from psycopg.rows import dict_row

from apps.backtester.config import build_db_config, load_env
from apps.worker.collector.readiness import run as check_data
from storage.postgres.bootstrap import required_tables


class ReadOnlyDatabase:
    def __init__(self, conn):
        self.conn = conn

    def fetch_one(self, query, params=None):
        return self.conn.execute(query, params).fetchone()

    def fetch_all(self, query, params=None):
        return self.conn.execute(query, params).fetchall()


def diagnose(cutoff=None) -> dict:
    """Inspect development prerequisites; never initialize a broker or write DB data."""
    load_env()
    now = datetime.now(ZoneInfo("Asia/Seoul"))
    cutoff = cutoff or now.date()
    names = (
        "POSTGRES_HOST", "POSTGRES_USER", "POSTGRES_PASSWORD", "POSTGRES_DB",
        "KIS_APP_KEY", "KIS_APP_SECRET",
        "KIS_DOMESTIC_STOCK_ACCOUNT_NO", "KIS_DOMESTIC_STOCK_ACCOUNT_PRODUCT_CODE",
    )
    report = {
        "checked_at": now.isoformat(), "cutoff_date": cutoff.isoformat(),
        "credential_presence": {name: bool(os.getenv(name)) for name in names},
        "database": {"status": "BLOCKED"},
        "development_ready": False, "data_ready": False,
        "broker_authentication": "NOT_TESTED", "operational_readiness": "NOT_ASSESSED",
        "orders_enabled": False,
    }
    if not all(report["credential_presence"][name] for name in names[:4]):
        report["database"]["reason"] = "MISSING_CONFIGURATION"
        return report
    try:
        config = build_db_config()
        with psycopg.connect(
            host=config["host"], port=config["port"], user=config["user"],
            password=config["password"], dbname=config["database"],
            connect_timeout=5, row_factory=dict_row,
        ) as conn:
            conn.execute("SET TRANSACTION READ ONLY")
            tables = {row["tablename"] for row in conn.execute(
                "SELECT tablename FROM pg_tables WHERE schemaname = 'public'"
            ).fetchall()}
            missing = sorted(required_tables() - tables)
            report["database"] = {
                "status": "PASS" if not missing else "BLOCKED", "missing_tables": missing,
            }
            if missing:
                return report
            versions = []
            if "schema_migrations" in tables:
                versions = [row["version"] for row in conn.execute(
                    "SELECT version FROM schema_migrations ORDER BY version"
                ).fetchall()]
            report["database"]["migration_versions"] = versions
            if not {"08", "09"} <= set(versions):
                report["database"].update(status="BLOCKED", reason="MIGRATIONS_REQUIRED")
                return report
            report["development_ready"] = True
            readiness = check_data(ReadOnlyDatabase(conn), cutoff).to_dict()
            report["data_readiness"] = readiness
            report["data_ready"] = readiness["status"] == "PASS"
    except (psycopg.Error, ValueError, OSError) as exc:
        report["database"] = {"status": "BLOCKED", "error_type": type(exc).__name__}
        report["development_ready"] = False
    return report
