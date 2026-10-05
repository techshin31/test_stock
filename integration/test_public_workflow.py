"""Real PostgreSQL and fixed public-source FA → publication → local fills → restart."""
import gzip
import hashlib
import json
import os
from datetime import date, datetime
from pathlib import Path

import pandas as pd
from psycopg import sql
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
import pytest

from integration.test_postgres_api import _empty_verification_database, RepositoryDB
from storage.postgres import migrate
from storage.postgres.bootstrap import initialize_empty_database
from apps.system import workflow
from apps.worker import __main__ as worker
from apps.worker.collector.monitor import health_path
from core.execution import trader as runtime
from core.broker.simulation import LocalSimulationBroker
from core.utils.io import write_json

pytestmark = pytest.mark.skipif(os.getenv("QUANTPILOT_RUN_DB_INTEGRATION") != "1", reason="Requires isolated local PostgreSQL")
FIXTURES = Path(__file__).parent / "fixtures"


class BorrowedDatabase(RepositoryDB):
    def close(self):
        pass


@pytest.mark.parametrize("paper_policy", [False, True])
def test_public_inputs_complete_workflow_and_restart(monkeypatch, tmp_path, paper_policy):
    from apps.backtester.config import load_env
    load_env()
    raw = gzip.decompress((FIXTURES / "workflow-public-sample.json.gz").read_bytes())
    assert hashlib.sha256(raw).hexdigest() == "76f45da8a95602c9ac08aef2fef4798de2cadeb84145bd3bb149ea64338791fd"
    sample = json.loads(raw)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("COLLECTION_HEALTH_DIR", str(tmp_path / "collection"))
    monkeypatch.setenv("SIM_ACCOUNT_PATH", str(tmp_path / "simulation.json"))
    monkeypatch.setenv("SIM_INITIAL_CASH", "10000000")
    monkeypatch.setenv("VALIDATION_STRATEGY_POLICY", "paper" if paper_policy else "")
    # This stock-only sample deliberately excludes the independently tested hedge.
    monkeypatch.setenv("PAPER_INVERSE_HEDGE_ENABLED", "false")
    monkeypatch.setattr(workflow, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(workflow, "now_kst", lambda: datetime(2026, 10, 5, 12, tzinfo=workflow.KST))
    monkeypatch.setattr(runtime, "_today_kst", lambda: date(2026, 10, 6))
    monkeypatch.setattr(runtime, "_now_kst", lambda: datetime(2026, 10, 6, 10, tzinfo=workflow.KST))
    def forbidden(*args, **kwargs):
        raise AssertionError("External broker/network forbidden in fixed-source workflow")
    monkeypatch.setattr(runtime, "KisBroker", forbidden)
    import requests
    monkeypatch.setattr(requests.sessions.Session, "request", forbidden)
    quotes = {ticker: pd.DataFrame(record["values"], columns=record["columns"], index=pd.to_datetime(record["dates"]))
              for ticker, record in sample["quotes"].items()}
    def prices(tickers, start, end, **kwargs):
        return {ticker: quotes[ticker].loc[(quotes[ticker].index >= pd.Timestamp(start)) & (quotes[ticker].index < pd.Timestamp(end))].copy()
                for ticker in tickers}
    monkeypatch.setattr(runtime, "download_multiple_stocks", prices)
    index = pd.Series(sample["index"]["values"], index=pd.to_datetime(sample["index"]["dates"]))
    monkeypatch.setattr(runtime, "download_kospi_index", lambda start, end: index.loc[start:end])
    with _empty_verification_database() as (conn, uri):
        initialize_empty_database(conn)
        monkeypatch.setattr(migrate, "_connection_uri", lambda: uri)
        migrate.apply_migrations()
        conn.row_factory = dict_row
        db = BorrowedDatabase(conn)
        from psycopg.conninfo import conninfo_to_dict
        params = conninfo_to_dict(uri)
        monkeypatch.setenv("POSTGRES_DB", params["dbname"])
        for table, rows in sample["tables"].items():
            if not rows:
                continue
            columns = list(rows[0])
            query = sql.SQL("INSERT INTO {} ({}) VALUES ({})").format(
                sql.Identifier(table), sql.SQL(",").join(map(sql.Identifier, columns)),
                sql.SQL(",").join(sql.Placeholder() for _ in columns))
            with conn.cursor() as cursor:
                cursor.executemany(query, [tuple(Jsonb(row[c]) if isinstance(row[c], (list, dict)) else row[c] for c in columns) for row in rows])
            if "id" in columns:
                sequence = conn.execute("SELECT pg_get_serial_sequence(%s,'id') AS name", (table,)).fetchone()["name"]
                if sequence:
                    conn.execute(sql.SQL("SELECT setval(%s,(SELECT max(id) FROM {}))").format(sql.Identifier(table)), (sequence,))
        evidence = json.loads((FIXTURES / "collection-public-sample.json").read_text())
        write_json(health_path(db), {**evidence, "checked_at": "2026-10-05T12:00:00+09:00"})
        monkeypatch.setattr(worker, "_init", lambda: (None, db))
        monkeypatch.setattr(runtime, "PostgreDB", lambda config: db)
        prepared = workflow.prepare(effective_date=date(2026, 10, 6), output=tmp_path / "preparation.json")
        assert prepared["status"] == "PASS"
        assert prepared["publication"]["active_count"] > 0
        repeated = workflow.prepare(effective_date=date(2026, 10, 6), output=tmp_path / "repeated.json")
        assert repeated["run_id"] == prepared["run_id"]
        assert repeated["publication"]["already_published"]
        trader = runtime.LiveTrader(simulate=True)
        candidates = trader.run_premarket_batch()
        assert candidates
        orders = trader.run_daily_batch()
        assert orders
        fills = trader._execute_orders(orders)
        assert fills and all(f["status"] == "FILLED" for f in fills)
        balance = trader.broker.get_balance()
        trader.broker = LocalSimulationBroker()
        retry = trader._execute_orders(orders)
        assert trader.broker.get_balance() == balance
        assert [f["broker_order_id"] for f in retry] == [f["broker_order_id"] for f in fills]
        assert trader.strategy_policy.status == ("PAPER_POLICY_VALIDATION" if paper_policy else "UNCHANGED")
        assert conn.execute("SELECT count(*) AS n FROM orders WHERE execution_venue_code IN ('REAL','PAPER')").fetchone()["n"] == 0
        print(json.dumps({"public_workflow": "PASS", "paper_policy": paper_policy,
                          "published": prepared["publication"]["active_count"], "premarket_candidates": len(candidates),
                          "local_fills": len(fills), "restart_idempotency": "PASS", "external_orders": 0}))
