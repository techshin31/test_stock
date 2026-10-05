"""Keep order-submission tests independent of the wall clock and host controls."""
from datetime import datetime
import pytest


@pytest.fixture(autouse=True)
def deterministic_submission_session(monkeypatch, tmp_path):
    from core.execution import session_guard
    monkeypatch.setattr(session_guard, 'now_kst', lambda: datetime(2026, 10, 6, 10, tzinfo=session_guard.KST))
    monkeypatch.setenv('TRADING_CONTROL_PATH', str(tmp_path / 'trading-control.json'))
