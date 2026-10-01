"""Explicit PostgreSQL integration checks; use an ephemeral test database.

Run with QUANTPILOT_RUN_DB_INTEGRATION=1 python -m pytest integration.
The configured DB role must be allowed to create and drop test databases.
"""
import os
import uuid

import psycopg
from psycopg import sql
import pytest

from api import main as dashboard_api
from storage.postgres import migrate

pytestmark = pytest.mark.skipif(
    os.getenv('QUANTPILOT_RUN_DB_INTEGRATION') != '1',
    reason='Requires explicit opt-in and a local PostgreSQL test server',
)


@pytest.fixture(scope='module')
def database():
    # Create only a uniquely named database owned by this test run. Never clear
    # the configured application DB or reuse it for integration test writes.
    database_name = 'quantpilot_test_' + uuid.uuid4().hex
    with psycopg.connect(migrate._connection_uri(), autocommit=True) as admin:
        admin.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(database_name)))
        try:
            with pytest.MonkeyPatch.context() as monkeypatch:
                monkeypatch.setenv('POSTGRES_DB', database_name)
                with psycopg.connect(migrate._connection_uri(), autocommit=True) as conn:
                    for path in sorted(migrate.SCHEMA_DIR.glob('[0-9][0-9]_*.sql')):
                        if int(path.name[:2]) < 8:
                            conn.execute(path.read_text(encoding='utf-8'))
                yield database_name
        finally:
            admin.execute(sql.SQL('DROP DATABASE {}').format(sql.Identifier(database_name)))


def test_fresh_schema_migrations_and_api_readiness(database, monkeypatch):
    applied = migrate.apply_migrations()
    assert applied == ['08', '09']
    assert migrate.apply_migrations() == []
    assert dashboard_api.get_service_health() == {'status': 'ok', 'database': 'ready'}
    with psycopg.connect(migrate._connection_uri()) as conn:
        assert conn.execute('SELECT count(*) FROM schema_migrations').fetchone()[0] == 2
        assert conn.execute('SELECT count(*) FROM codes').fetchone()[0] > 0


def test_real_connection_preserves_special_character_password(database, monkeypatch):
    role_name = 'connection_test_' + uuid.uuid4().hex
    # A synthetic password used exclusively for the temporary test role.
    password = "test@:/?# spaces 'quotes' \\ slash"
    with psycopg.connect(migrate._connection_uri(), autocommit=True) as admin:
        admin.execute(sql.SQL('CREATE ROLE {} LOGIN PASSWORD {}').format(sql.Identifier(role_name), sql.Literal(password)))
        try:
            with monkeypatch.context() as patch:
                patch.setenv('POSTGRES_USER', role_name)
                patch.setenv('POSTGRES_PASSWORD', password)
                with psycopg.connect(migrate._connection_uri()) as conn:
                    assert conn.execute('SELECT current_user').fetchone()[0] == role_name
        finally:
            admin.execute(sql.SQL('DROP ROLE {}').format(sql.Identifier(role_name)))
