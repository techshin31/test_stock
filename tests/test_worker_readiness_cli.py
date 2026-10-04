import json
from datetime import date
from types import SimpleNamespace

import pytest

import apps.worker.__main__ as worker
from apps.worker.collector import readiness


@pytest.mark.parametrize('status', ['PASS', 'WARNING', 'FAIL'])
@pytest.mark.parametrize('strict', [False, True])
def test_readiness_command_prints_report_and_enforces_requested_gate(monkeypatch, capsys, status, strict):
    db = SimpleNamespace(closed=False)
    db.close = lambda: setattr(db, 'closed', True)
    monkeypatch.setattr(worker, '_init', lambda: (None, db))
    monkeypatch.setattr(worker, '_parse_args', lambda: SimpleNamespace(
        category='readiness', cutoff=date(2026, 10, 2), require_ready=strict,
    ))
    calls = []
    report = SimpleNamespace(status=status, to_dict=lambda: {'status': status, 'cutoff_date': '2026-10-02'})
    monkeypatch.setattr(readiness, 'run', lambda current_db, cutoff: calls.append((current_db, cutoff)) or report)

    def unexpected(*args):
        pytest.fail('A read-only readiness check dispatched collection or analysis')

    monkeypatch.setattr(worker, 'run_collect', unexpected)
    monkeypatch.setattr(worker, 'run_analyze', unexpected)
    if strict and status != 'PASS':
        with pytest.raises(SystemExit) as caught:
            worker.main()
        assert caught.value.code == 2
    else:
        worker.main()
    assert db.closed
    assert calls == [(db, date(2026, 10, 2))]
    assert json.loads(capsys.readouterr().out)['status'] == status


def test_readiness_defaults_to_exchange_date_and_closes_db_on_error(monkeypatch):
    db = SimpleNamespace(closed=False)
    db.close = lambda: setattr(db, 'closed', True)
    monkeypatch.setattr(worker, '_init', lambda: (None, db))
    monkeypatch.setattr(worker, '_today_kst', lambda: date(2026, 10, 3))

    def fail(current_db, cutoff):
        assert cutoff == date(2026, 10, 3)
        raise RuntimeError('test database unavailable')

    monkeypatch.setattr(readiness, 'run', fail)
    with pytest.raises(RuntimeError):
        worker.run_readiness(SimpleNamespace(cutoff=None, require_ready=True))
    assert db.closed


def test_readiness_rejects_invalid_date_before_initialization(monkeypatch):
    monkeypatch.setattr('sys.argv', ['worker', 'readiness', '--cutoff', 'not-a-date', '--require-ready'])

    def unexpected():
        pytest.fail('Invalid CLI input opened a database connection')

    monkeypatch.setattr(worker, '_init', unexpected)
    with pytest.raises(SystemExit) as caught:
        worker.main()
    assert caught.value.code == 2
