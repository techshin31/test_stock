from datetime import date

import pandas as pd

from apps.trader.planner import _through_signal_date
from core.utils.trading_calendar import previous_krx_trading_day
from storage.postgres.repositories.universe_repo import (
    mark_empty_sell_only_removed,
    sync_positions_to_universe,
)


class FakeDB:
    def __init__(self, one_rows=None, all_rows=None):
        self.one_rows = list(one_rows or [])
        self.all_rows = list(all_rows or [])
        self.calls = []

    def fetch_one(self, query, params=None):
        self.calls.append(("one", query, params))
        return self.one_rows.pop(0) if self.one_rows else None

    def fetch_all(self, query, params=None):
        self.calls.append(("all", query, params))
        return self.all_rows.pop(0) if self.all_rows else []


def test_signal_date_is_previous_completed_krx_session():
    assert previous_krx_trading_day(date(2026, 6, 1)) == date(2026, 5, 29)
    frame = pd.DataFrame(
        {"close": [100, 101]},
        index=pd.to_datetime(["2026-05-29", "2026-06-01"]),
    )
    filtered = _through_signal_date(frame, date(2026, 5, 29))
    assert filtered.index.max().date() == date(2026, 5, 29)


def test_scheduler_uses_krx_holiday_calendar(monkeypatch):
    from apps.trader import scheduler

    monkeypatch.delenv("TRADER_SKIP_WAIT", raising=False)
    monkeypatch.setattr(
        scheduler, "now_kst",
        lambda: pd.Timestamp("2026-01-01 08:00", tz="Asia/Seoul").to_pydatetime(),
    )
    assert not scheduler.is_trading_day()


def test_expired_sell_only_or_removed_holding_is_reregistered():
    db = FakeDB(
        one_rows=[
            {"id": 1},
            {"symbol": "005930"},
        ],
        all_rows=[[]],
    )
    registered = sync_positions_to_universe(
        db, "risk_neutral",
        [{"symbol": "005930", "market_type_code": "KOSPI"}],
        date(2026, 6, 1),
    )
    assert registered == ["005930"]
    upsert_query = db.calls[-1][1]
    assert "WHERE universe.universe_status_code = 'ACTIVE'" not in upsert_query
    assert "entry_date = EXCLUDED.entry_date" in upsert_query


def test_removed_transition_uses_synchronized_zero_position_guard():
    db = FakeDB(all_rows=[[{"symbol": "005930"}]])
    assert mark_empty_sell_only_removed(db, "risk_neutral") == ["005930"]
    query = db.calls[0][1]
    assert "universe_status_code = 'SELL_ONLY'" in query
    assert "p.qty > 0" in query
