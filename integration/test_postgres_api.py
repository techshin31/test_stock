"""Explicit PostgreSQL integration checks; use an ephemeral test database.

Run with QUANTPILOT_RUN_DB_INTEGRATION=1 python -m pytest integration.
The configured DB role must be allowed to create and drop test databases.
"""
import os
import uuid
from contextlib import contextmanager
from datetime import date

import psycopg
from psycopg import sql
from psycopg.rows import dict_row
import pytest

from api import main as dashboard_api
from storage.postgres import migrate
from apps.worker.analyzer.config import load_config
from apps.worker.analyzer.pipeline import build_request, prepare_run
from storage.postgres.repositories.fa_analysis_repo import update_analysis_run_status
from storage.postgres.repositories.macro_signal_repo import upsert_macro_signals
from storage.postgres.repositories.readiness_repo import fetch_macro_signal_coverage, fetch_finance_industry_coverage
from storage.postgres.repositories.analysis_input_repo import fetch_analysis_source_fingerprints
from storage.postgres.repositories.company_repo import upsert_companies
from storage.postgres.repositories.financial_repo import upsert_financial_statements
from storage.postgres.repositories.dart_event_repo import upsert_dart_events
from storage.postgres.repositories.wics_repo import upsert_wics_companies
from storage.postgres.repositories.wics_industry_repo import (
    fetch_wics_industry_prices, upsert_wics_constituent_prices, upsert_wics_industry_prices,
)

pytestmark = pytest.mark.skipif(
    os.getenv('QUANTPILOT_RUN_DB_INTEGRATION') != '1',
    reason='Requires explicit opt-in and a local PostgreSQL test server',
)


@contextmanager
def _empty_verification_database():
    from psycopg.conninfo import conninfo_to_dict, make_conninfo

    params = conninfo_to_dict(migrate._connection_uri())
    name = "quantpilot_bootstrap_" + uuid.uuid4().hex
    with psycopg.connect(**params, autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
        try:
            uri = make_conninfo(**{**params, "dbname": name})
            with psycopg.connect(uri, autocommit=True) as conn:
                yield conn, uri
        finally:
            admin.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(name)))


def test_bootstrap_fresh_database_and_read_only_doctor(database, monkeypatch):
    from apps.system import diagnostics
    from storage.postgres.bootstrap import initialize_empty_database, required_tables
    from psycopg.conninfo import conninfo_to_dict

    with _empty_verification_database() as (conn, uri):
        applied = initialize_empty_database(conn)
        assert "01_codes_schema.sql" in applied
        assert conn.execute("SELECT COUNT(*) FROM strategies").fetchone()[0] == 2
        monkeypatch.setattr(migrate, "_connection_uri", lambda: uri)
        assert migrate.apply_migrations() == ["08", "09"]
        assert initialize_empty_database(conn) == []
        assert migrate.apply_migrations() == []
        params = conninfo_to_dict(uri)
        monkeypatch.setattr(diagnostics, "load_env", lambda: None)
        monkeypatch.setattr(diagnostics, "build_db_config", lambda: {
            "host": params["host"], "port": params["port"], "user": params["user"],
            "password": params["password"], "database": params["dbname"],
        })
        report = diagnostics.diagnose(date(2026, 10, 2))
        assert report["development_ready"] is True
        assert report["data_ready"] is False
        assert report["database"]["migration_versions"] == ["08", "09"]
        assert report["orders_enabled"] is False
        assert report["broker_authentication"] == "NOT_TESTED"
        assert conn.execute("SELECT COUNT(*) FROM fa_analysis_runs").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0] == 0
        assert len(required_tables()) >= 20


def test_bootstrap_refuses_nonempty_incomplete_schema(database):
    from storage.postgres.bootstrap import IncompleteDatabaseError, initialize_empty_database

    with _empty_verification_database() as (conn, _):
        conn.execute("CREATE TABLE keep_me (value INTEGER)")
        conn.execute("INSERT INTO keep_me VALUES (42)")
        with pytest.raises(IncompleteDatabaseError, match="nonempty but incomplete"):
            initialize_empty_database(conn)
        assert conn.execute("SELECT value FROM keep_me").fetchone() == (42,)
        assert conn.execute("SELECT tablename FROM pg_tables WHERE schemaname='public'").fetchall() == [("keep_me",)]


def test_bootstrap_initial_schema_failure_rolls_back_every_file(database, monkeypatch, tmp_path):
    from storage.postgres import bootstrap

    first = tmp_path / "01_valid.sql"
    first.write_text("CREATE TABLE rollback_fixture (value INTEGER); INSERT INTO rollback_fixture VALUES (1);")
    second = tmp_path / "02_invalid.sql"
    second.write_text("INVALID SQL;")
    monkeypatch.setattr(bootstrap, "initial_schema_files", lambda: [first, second])
    with _empty_verification_database() as (conn, _):
        with pytest.raises(psycopg.errors.SyntaxError):
            bootstrap.initialize_empty_database(conn)
        assert conn.execute("SELECT tablename FROM pg_tables WHERE schemaname='public'").fetchall() == []


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


class RepositoryDB:
    """Use one real connection in the temporary database, without a singleton."""
    def __init__(self, conn):
        self.conn = conn

    def fetch_one(self, query, params=None):
        return self.conn.execute(query, params).fetchone()

    def fetch_all(self, query, params=None):
        return self.conn.execute(query, params).fetchall()

    def execute(self, query, params=None):
        return self.conn.execute(query, params).rowcount

    def execute_many(self, query, params_list):
        with self.conn.cursor() as cursor:
            cursor.executemany(query, params_list)

    @contextmanager
    def transaction(self):
        with self.conn.transaction():
            yield self.conn


@pytest.mark.parametrize('change', ['backfill', 'correction', 'deletion', 'revision', 'future', 'recollection'])
def test_analysis_cache_tracks_as_of_content_not_only_latest_dates(database, change):
    cutoff = date(2026, 5, 31)
    request = build_request(target='all', analysis_month='2026-06', cutoff_date=cutoff, effective_date='2026-06-01')
    config = load_config('risk_neutral')
    with psycopg.connect(migrate._connection_uri(), autocommit=True, row_factory=dict_row) as conn:
        # Each case rolls back its fixture data and analysis rows.
        with conn.transaction(force_rollback=True):
            db = RepositoryDB(conn)
            record = {
                'signal_name_code': 'VIX', 'category_code': 'RISK',
                'observation_date': date(2026, 5, 28), 'available_date': date(2026, 5, 29),
                'value': 20, 'frequency_code': 'DAILY', 'source_code': 'YAHOO',
                'source_value_key': '^VIX', 'revision_no': 0,
            }
            older = {**record, 'observation_date': date(2026, 5, 27), 'available_date': date(2026, 5, 28), 'value': 18}
            upsert_macro_signals(db, [record, older])
            first = prepare_run(db, request, config)
            update_analysis_run_status(db, first.run_id, 'WARNING')
            cached = prepare_run(db, request, config)
            assert cached.run_id == first.run_id
            assert not cached.created
            coverage = fetch_macro_signal_coverage(db, cutoff)

            if change == 'backfill':
                upsert_macro_signals(db, [{**older, 'observation_date': date(2026, 5, 26)}])
            elif change == 'correction':
                upsert_macro_signals(db, [{**older, 'value': 19}])
            elif change == 'deletion':
                db.execute('DELETE FROM macro_signals WHERE observation_date = %s', (older['observation_date'],))
            elif change == 'revision':
                upsert_macro_signals(db, [{**older, 'value': 19, 'revision_no': 1, 'available_date': date(2026, 5, 29)}])
            elif change == 'future':
                upsert_macro_signals(db, [{**older, 'observation_date': date(2026, 5, 30), 'available_date': date(2026, 6, 1)}])
            else:
                upsert_macro_signals(db, [older])
                db.execute("UPDATE macro_signals SET collected_at = collected_at + INTERVAL '1 hour'")

            assert fetch_macro_signal_coverage(db, cutoff) == coverage
            after = prepare_run(db, request, config)
            if change in {'future', 'recollection'}:
                assert not after.created
                assert after.run_id == first.run_id
            else:
                assert after.created
                assert after.run_id != first.run_id
                assert after.input_hash != first.input_hash


@pytest.mark.parametrize('source', ['wics_companies', 'wics_industry_prices', 'wics_constituent_prices', 'financial_statements', 'companies'])
def test_analysis_cache_tracks_corrections_in_other_source_tables(database, source):
    cutoff = date(2026, 5, 31)
    config = load_config('risk_neutral')
    request = build_request(target='all', analysis_month='2026-06', cutoff_date=cutoff, effective_date='2026-06-01')
    with psycopg.connect(migrate._connection_uri(), autocommit=True, row_factory=dict_row) as conn:
        with conn.transaction(force_rollback=True):
            db = RepositoryDB(conn)
            upsert_companies(db, [{'stock_code': '005930', 'corp_code': '00126380', 'company_name': 'test', 'market_type_code': 'KOSPI'}])
            upsert_wics_companies(db, [{'stock_code': '005930', 'base_date': cutoff, 'sector_code': 'G45', 'industry_code': 'G4530', 'mkt_val': 100000, 'company_size_code': 'LARGE'}])
            upsert_wics_industry_prices(db, [{'industry_code': 'G4530', 'price_date': cutoff, 'index_value': 1000, 'source_code': 'WISEINDEX'}])
            upsert_wics_constituent_prices(db, [{'stock_code': '005930', 'price_date': cutoff, 'close': 70000}])
            upsert_financial_statements(db, [{
                'stock_code': '005930', 'corp_code': '00126380', 'bsns_year': 2026,
                'fs_div': 'CFS', 'sj_div': 'IS', 'account_nm': 'revenue',
                'source_rcept_no': '20260515000001', 'available_date': date(2026, 5, 15),
                'period_end': date(2026, 3, 31), 'thstrm_amount': 1000,
            }])
            first = prepare_run(db, request, config)
            update_analysis_run_status(db, first.run_id, 'WARNING')
            statements = {
                'wics_companies': 'UPDATE wics_companies SET mkt_val = mkt_val + 1',
                'wics_industry_prices': 'UPDATE wics_industry_prices SET index_value = index_value + 1',
                'wics_constituent_prices': 'UPDATE wics_constituent_prices SET close = close + 1',
                'financial_statements': 'UPDATE financial_statements SET thstrm_amount = thstrm_amount + 1',
                'companies': "UPDATE companies SET status_code = 'SUSPENDED'",
            }
            db.execute(statements[source])
            after = prepare_run(db, request, config)
            assert after.created
            assert after.input_hash != first.input_hash


def test_quarterly_score_fingerprints_apply_only_to_reuse_mode(database):
    with psycopg.connect(migrate._connection_uri(), autocommit=True, row_factory=dict_row) as conn:
        with conn.transaction(force_rollback=True):
            db = RepositoryDB(conn)
            kwargs = {'cutoff_date': date(2026, 5, 31), 'model_version': load_config('risk_neutral').model_version}
            upsert_companies(db, [{'stock_code': '005930', 'corp_code': '00126380', 'company_name': 'test'}])
            db.execute("""
                INSERT INTO dart_events (stock_code, corp_code, rcept_no, rcept_dt,
                    report_nm, pblntf_ty, event_category_code, event_subtype_code)
                VALUES ('005930', '00126380', '20260515000001', '2026-05-15',
                    'quarterly report', 'A', 'FINANCIAL', 'QUARTERLY')
            """)
            db.execute("""
                INSERT INTO company_quarter_fa (stock_code, source_rcept_no,
                    fiscal_year, fiscal_quarter, reprt_code, fs_div, period_end,
                    available_date, model_version, level_score, change_score,
                    risk_penalty, risk_score, fa_score, level_confidence,
                    change_confidence, score_confidence, score_model_code, is_eligible)
                VALUES ('005930', '20260515000001', 2026, '2026Q1', '11013', 'CFS',
                    '2026-03-31', '2026-05-15', %s, 40, 20, 0, 10, 70, 1, 1, 1,
                    'GENERAL_V1', TRUE)
            """, (kwargs['model_version'],))
            raw = fetch_analysis_source_fingerprints(db, reuse_quarter_scores=False, **kwargs)
            reused = fetch_analysis_source_fingerprints(db, reuse_quarter_scores=True, **kwargs)
            assert reused['company_quarter_fa']['row_count'] == 1
            db.execute('UPDATE company_quarter_fa SET level_score = 50, fa_score = 80')
            assert fetch_analysis_source_fingerprints(db, reuse_quarter_scores=False, **kwargs) == raw
            corrected = fetch_analysis_source_fingerprints(db, reuse_quarter_scores=True, **kwargs)
            assert corrected != reused
            db.execute("UPDATE company_quarter_fa SET calculated_at = calculated_at + INTERVAL '1 hour'")
            assert fetch_analysis_source_fingerprints(db, reuse_quarter_scores=True, **kwargs) == corrected
            other_model = fetch_analysis_source_fingerprints(db, reuse_quarter_scores=True, cutoff_date=kwargs['cutoff_date'], model_version='other-model')
            assert other_model['company_quarter_fa']['row_count'] == 0


def test_price_source_tie_break_changes_invalidate_analysis_cache(database):
    cutoff = date(2026, 5, 31)
    config = load_config('risk_neutral')
    request = build_request(target='all', analysis_month='2026-06', cutoff_date=cutoff, effective_date='2026-06-01')
    with psycopg.connect(migrate._connection_uri(), autocommit=True, row_factory=dict_row) as conn:
        with conn.transaction(force_rollback=True):
            db = RepositoryDB(conn)
            upsert_wics_industry_prices(db, [
                {'industry_code': 'G4530', 'price_date': cutoff, 'index_value': value,
                 'source_code': 'DERIVED', 'method_version': version}
                for value, version in [(1000, 'v1'), (2000, 'v2')]
            ])
            db.execute("UPDATE wics_industry_prices SET collected_at = '2026-06-01' WHERE method_version = 'v1'")
            db.execute("UPDATE wics_industry_prices SET collected_at = '2026-06-02' WHERE method_version = 'v2'")
            assert fetch_wics_industry_prices(db, cutoff)[0]['index_value'] == 2000
            first = prepare_run(db, request, config)
            update_analysis_run_status(db, first.run_id, 'WARNING')
            db.execute("UPDATE wics_industry_prices SET collected_at = '2026-06-03' WHERE method_version = 'v1'")
            assert fetch_wics_industry_prices(db, cutoff)[0]['index_value'] == 1000
            after = prepare_run(db, request, config)
            assert after.created
            assert after.input_hash != first.input_hash


@pytest.mark.parametrize('case', [
    'complete', 'same_quarter_corrections', 'separate_only_eighth',
    'incomplete_latest', 'future_incomplete_latest', 'wrong_availability',
    'missing_event', 'comprehensive_income', 'legacy', 'unmapped_company',
    'future_eighth', 'future_period',
])
def test_finance_readiness_counts_complete_as_of_quarters(database, case):
    cutoff = date(2026, 5, 31)
    with psycopg.connect(migrate._connection_uri(), autocommit=True, row_factory=dict_row) as conn:
        with conn.transaction(force_rollback=True):
            db = RepositoryDB(conn)
            upsert_companies(db, [{'stock_code': '005930', 'corp_code': '00126380',
                                  'company_name': 'test', 'market_type_code': 'KOSPI'}])
            wics = {'stock_code': '005930', 'base_date': cutoff, 'sector_code': 'G45',
                    'industry_code': 'G4530', 'mkt_val': 100000, 'company_size_code': 'LARGE'}
            upsert_wics_companies(db, [wics])
            quarters = [(2024, '11012', 6, 30), (2024, '11014', 9, 30), (2024, '11011', 12, 31),
                        (2025, '11013', 3, 31), (2025, '11012', 6, 30), (2025, '11014', 9, 30),
                        (2025, '11011', 12, 31), (2026, '11013', 3, 31)]
            records = []
            events = []
            for i, (year, report, month, day) in enumerate(quarters):
                if case == 'same_quarter_corrections':
                    year, report, month, day = quarters[0]
                receipt = f'20260515000{i:03}'
                if case == 'legacy':
                    receipt = f'LEGACY:{i}'
                available = date(2026, 6, 1) if case == 'future_eighth' and i == 7 else date(2026, 5, 15)
                event = {'stock_code': '005930', 'corp_code': '00126380', 'rcept_no': receipt,
                         'rcept_dt': available, 'report_nm': f'test report ({year}.{month:02})',
                         'pblntf_ty': 'A', 'event_category_code': 'REGULAR_REPORT',
                         'event_subtype_code': 'Q1_REPORT'}
                if not (case == 'missing_event' and i == 7):
                    events.append(event)
                for statement in ['BS', 'IS', 'CF']:
                    records.append({
                        'stock_code': '005930', 'corp_code': '00126380', 'bsns_year': year,
                        'reprt_code': report, 'fs_div': 'OFS' if case == 'separate_only_eighth' and i == 7 else 'CFS',
                        'sj_div': 'CIS' if case == 'comprehensive_income' and statement == 'IS' else statement,
                        'account_id': 'test_' + statement, 'account_nm': statement,
                        'source_rcept_no': receipt, 'rcept_dt': available,
                        'available_date': date(2026, 5, 16) if case == 'wrong_availability' and i == 7 else available,
                        'period_start': date(year, 1, 1),
                        'period_end': date(2026, 6, 30) if case == 'future_period' and i == 7 else date(year, month, day),
                        'thstrm_amount': 1000, 'revision_no': i if case == 'same_quarter_corrections' else 0,
                    })
            if case in {'incomplete_latest', 'future_incomplete_latest'}:
                corrected_date = date(2026, 6, 1) if case.startswith('future') else date(2026, 5, 20)
                events.append({**events[-1], 'rcept_no': '20260520000001', 'rcept_dt': corrected_date})
                # Do not combine BS from a correction with IS/CF from an older receipt.
                records.append({**records[-3], 'source_rcept_no': '20260520000001',
                                'rcept_dt': corrected_date, 'available_date': corrected_date, 'revision_no': 1})
            if case == 'unmapped_company':
                upsert_wics_companies(db, [{**wics, 'stock_code': '000660'}])
            upsert_dart_events(db, events)
            upsert_financial_statements(db, records)
            rows = fetch_finance_industry_coverage(db, cutoff)
            eligible = 1 if case in {'complete', 'future_incomplete_latest', 'comprehensive_income', 'unmapped_company'} else 0
            assert rows == [{'industry_code': 'G4530',
                             'large_company_count': 2 if case == 'unmapped_company' else 1,
                             'eligible_company_count': eligible}]
