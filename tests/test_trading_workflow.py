from datetime import date, datetime
import json
from types import SimpleNamespace

import pytest

from apps.system import workflow as wf
from core.utils.io import write_json


@pytest.fixture
def workflow(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(wf, 'PROJECT_ROOT', tmp_path)
    monkeypatch.setattr(wf, 'now_kst', lambda: datetime(2026, 10, 6, 10, tzinfo=wf.KST))
    return tmp_path


@pytest.fixture
def dependencies(workflow, monkeypatch):
    from apps.worker.analyzer import pipeline, universe_job, operations
    from apps.worker.collector import readiness
    calls = []
    db = SimpleNamespace(fetch_one=lambda *a: {'status_code': 'PASS'}, close=lambda: calls.append('close'))
    monkeypatch.setattr('apps.worker.__main__._init', lambda: (None, db))
    monkeypatch.setattr(readiness, 'run', lambda *a: SimpleNamespace(to_dict=lambda: {'status': 'PASS'}))
    monkeypatch.setattr('apps.worker.collector.monitor.collection_health', lambda *a, **k: {'status': 'PASS'})
    monkeypatch.setattr(pipeline, 'run', lambda *a, **k: (calls.append('analyze') or SimpleNamespace(run_id=7, model_version='FA_V1_1')))
    monkeypatch.setattr(universe_job, 'publish', lambda *a, **k: (calls.append('publish') or SimpleNamespace(run_id=7, active_symbols=('005930',), already_published=False)))
    monkeypatch.setattr(operations, 'audit_operational_state', lambda *a: SimpleNamespace(to_dict=lambda: {'status': 'PASS'}))
    return db, calls


def test_prepare_preserves_analysis_lineage(dependencies):
    _, calls = dependencies
    result = wf.prepare(effective_date=date(2026, 10, 6))
    assert result['status'] == 'PASS'
    assert result['cutoff_date'] == date(2026, 10, 2)
    assert result['orders_submitted'] is False
    assert calls == ['analyze', 'publish', 'close']


@pytest.mark.parametrize('failure', ['readiness', 'analysis', 'dependency'])
def test_prepare_failure_never_publishes_or_leaves_old_success(dependencies, monkeypatch, failure):
    db, calls = dependencies
    output = wf.PROJECT_ROOT / 'report.json'
    write_json(output, {'status': 'PASS'})
    if failure == 'readiness':
        monkeypatch.setattr('apps.worker.collector.readiness.run', lambda *a: SimpleNamespace(to_dict=lambda: {'status': 'FAIL'}))
    elif failure == 'analysis':
        db.fetch_one = lambda *a: {'status_code': 'WARNING'}
    else:
        def error(*a):
            raise RuntimeError('secret-password-do-not-print')
        monkeypatch.setattr('apps.worker.collector.readiness.run', error)
    with pytest.raises(wf.WorkflowBlocked):
        wf.prepare(effective_date=date(2026, 10, 6), output=output)
    assert 'publish' not in calls
    saved = output.read_text()
    assert json.loads(saved)['status'] == 'BLOCKED'
    assert 'secret-password' not in saved
    assert calls[-1] == 'close'


@pytest.mark.parametrize('session', [date(2026, 10, 2), date(2026, 10, 5), date(2026, 10, 7)])
def test_prepare_rejects_past_holiday_or_incomplete_cutoff(workflow, session):
    with pytest.raises(wf.WorkflowBlocked, match='COMPLETED_INPUTS'):
        wf.prepare(effective_date=session)


@pytest.mark.parametrize('reason,accepted', [('XBRL_CFS_BALANCE_MISSING', True), ('HTTP_502', False)])
def test_partial_collection_accepts_only_documented_original_gaps(dependencies, monkeypatch, reason, accepted):
    def collect(args):
        write_json(wf.PROJECT_ROOT / 'logs/system/preparation-collection.json', {
            'status': 'PARTIAL', 'risk_disclosure_coverage': 'POLICY_SCOPE_ONLY',
            'finance': {'failures': [{'reason': reason}]}})
        return 2
    monkeypatch.setattr(wf, 'run_process', collect)
    if accepted:
        assert wf.prepare(effective_date=date(2026, 10, 6), collect=True)['status'] == 'PASS'
    else:
        with pytest.raises(wf.WorkflowBlocked, match='COLLECTION_FAILED'):
            wf.prepare(effective_date=date(2026, 10, 6), collect=True)


def test_old_collection_report_cannot_mask_child_failure(dependencies, monkeypatch):
    path = wf.PROJECT_ROOT / 'logs/system/preparation-collection.json'
    write_json(path, {'status': 'PARTIAL', 'risk_disclosure_coverage': 'POLICY_SCOPE_ONLY'})
    monkeypatch.setattr(wf, 'run_process', lambda *a: 2)
    with pytest.raises(wf.WorkflowBlocked, match='COLLECTION_FAILED'):
        wf.prepare(effective_date=date(2026, 10, 6), collect=True)
    assert not path.exists()


@pytest.mark.parametrize('moment', [(2026, 10, 4, 10), (2026, 10, 5, 10), (2026, 10, 6, 16)])
def test_closed_session_does_not_initialize_dependencies(workflow, monkeypatch, moment):
    monkeypatch.setattr(wf, 'now_kst', lambda: datetime(*moment, tzinfo=wf.KST))
    monkeypatch.setattr(wf, 'prepare', lambda **k: pytest.fail('closed session prepared'))
    monkeypatch.setattr(wf, 'run_process', lambda *a: pytest.fail('closed session broker'))
    assert wf.run_cycle()['status'] == 'WAITING'


@pytest.mark.parametrize('mode,flag', [('dry-run', '--dry-run'), ('simulate', '--simulate'), ('paper', '--mock')])
def test_cycle_orders_phases_and_collects_only_once_per_session(workflow, monkeypatch, mode, flag):
    phases, collected = [], []
    monkeypatch.setattr(wf, 'prepare', lambda **k: (collected.append(k['collect']) or {'status': 'PASS'}))
    def child(args):
        phases.append(args[1:])
        write_json(workflow / 'logs' / wf.MODES[mode].lower() / 'dashboard_state.json',
                   {'operational_status': 'NORMAL', 'execution_mode': wf.MODES[mode]})
        return 0
    monkeypatch.setattr(wf, 'run_process', child)
    assert wf.run_cycle(mode=mode, collect=True)['status'] == 'PASS'
    assert wf.run_cycle(mode=mode, collect=True)['status'] == 'PASS'
    assert collected == [True, False]
    assert phases == [[flag, '--premarket'], [flag]] * 2


def test_cycle_stops_after_failed_premarket(workflow, monkeypatch):
    monkeypatch.setattr(wf, 'prepare', lambda **k: {'status': 'PASS'})
    phases = []
    monkeypatch.setattr(wf, 'run_process', lambda args: (phases.append(args) or 1))
    with pytest.raises(wf.WorkflowBlocked, match='PREMARKET_EXIT_1'):
        wf.run_cycle()
    assert len(phases) == 2
    assert phases[-1][-1] == '--risk-only'
    assert json.loads((workflow / 'logs/system/dry-run/cycle.json').read_text())['status'] == 'BLOCKED'


def test_degraded_trader_is_not_reported_as_success(workflow, monkeypatch):
    monkeypatch.setattr(wf, 'prepare', lambda **k: {'status': 'PASS'})
    def child(*a):
        write_json(workflow / 'logs/dry_run/dashboard_state.json',
                   {'operational_status': 'DEGRADED_DATA_STALE', 'execution_mode': 'DRY_RUN'})
        return 0
    monkeypatch.setattr(wf, 'run_process', child)
    with pytest.raises(wf.WorkflowBlocked, match='TRADER_REQUIRES_ATTENTION'):
        wf.run_cycle()


def test_stale_success_report_cannot_mask_missing_trader_output(workflow, monkeypatch):
    monkeypatch.setattr(wf, 'prepare', lambda **k: {'status': 'PASS'})
    monkeypatch.setattr(wf, 'run_process', lambda *a: 0)
    write_json(workflow / 'logs/dry_run/dashboard_state.json',
               {'operational_status': 'NORMAL', 'execution_mode': 'DRY_RUN'})
    with pytest.raises(wf.WorkflowBlocked, match='TRADER_EVIDENCE_NOT_UPDATED'):
        wf.run_cycle()


def test_concurrent_cycle_and_real_mode_are_rejected(workflow):
    from core.utils.process_lock import ProcessAlreadyRunning
    with wf.locked(workflow / 'logs/system/cycle.lock', 'DRY_RUN'):
        with pytest.raises(ProcessAlreadyRunning):
            wf.run_cycle()
    with pytest.raises(ValueError):
        wf.run_cycle(mode='real')


def test_dry_run_initialization_never_constructs_kis_or_simulation(workflow, monkeypatch):
    from core.execution.trader import LiveTrader
    from core.broker.dry_run import DryRunBroker
    monkeypatch.setenv('POSTGRES_PASSWORD', 'test-only')
    monkeypatch.setattr('core.execution.trader.PostgreDB', lambda *a: object())
    monkeypatch.setattr('core.execution.trader.KisBroker', lambda **k: pytest.fail('KIS initialized'))
    monkeypatch.setattr('core.execution.trader.LocalSimulationBroker', lambda: pytest.fail('simulation initialized'))
    trader = LiveTrader(dry_run=True, simulate=True, mock=False)
    assert isinstance(trader.broker, DryRunBroker)
    assert trader.execution_venue == 'DRY_RUN'
    assert trader.broker.get_balance()['account_source'] == 'HYPOTHETICAL'
    with pytest.raises(PermissionError):
        trader.broker.place_market_buy('005930', 1)
    assert trader.broker.fetch_daily_orders() == []


@pytest.mark.parametrize('cash', ['nan', 'inf', '-1', '0'])
def test_dry_run_rejects_invalid_hypothetical_cash(cash):
    from core.broker.dry_run import DryRunBroker
    with pytest.raises(ValueError):
        DryRunBroker(cash)


def test_paper_check_never_constructs_real_broker_or_submits_orders(monkeypatch):
    from apps.system.paper import inspect_paper
    for key in ('KIS_APP_KEY', 'KIS_APP_SECRET', 'KIS_DOMESTIC_STOCK_ACCOUNT_NO'):
        monkeypatch.setenv(key, 'test-only')
    monkeypatch.setenv('KIS_ENV', 'paper')
    calls = []
    def broker(*, mock):
        calls.append(mock)
        return SimpleNamespace(get_balance=lambda: {'positions': {}})
    monkeypatch.setattr('core.broker.kis_api.KisBroker', broker)
    assert inspect_paper()['status'] == 'PASS'
    assert calls == [True]
    monkeypatch.setenv('KIS_ENV', 'real')
    assert inspect_paper()['reason'] == 'PAPER_ENV_REQUIRED'
    assert calls == [True]


def test_paper_check_redacts_dependency_errors(monkeypatch):
    from apps.system.paper import inspect_paper
    for key in ('KIS_APP_KEY', 'KIS_APP_SECRET', 'KIS_DOMESTIC_STOCK_ACCOUNT_NO'):
        monkeypatch.setenv(key, 'test-only')
    monkeypatch.setenv('KIS_ENV', 'paper')
    def error(**kw):
        raise RuntimeError('private-account-token')
    monkeypatch.setattr('core.broker.kis_api.KisBroker', error)
    result = inspect_paper()
    assert result['status'] == 'BLOCKED'
    assert 'private-account' not in json.dumps(result)
