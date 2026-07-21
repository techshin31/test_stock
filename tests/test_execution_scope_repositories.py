import datetime as dt

from storage.postgres.repositories.balance_repo import (
    fetch_balance_history,
    insert_balance_history,
)
from storage.postgres.repositories.position_repo import (
    fetch_active_position_symbols,
    upsert_position,
    zero_out_position,
)


class RecordingDB:
    def __init__(self, rows=None):
        self.calls = []
        self.rows = rows or []

    def execute(self, query, params=None):
        self.calls.append((query, params))
        return 1

    def fetch_all(self, query, params=None):
        self.calls.append((query, params))
        return self.rows


def test_position_upsert_is_scoped_by_venue_and_account():
    db = RecordingDB()

    upsert_position(
        db,
        "aggressive",
        "005930",
        {"qty": 10, "avg_cost": 70_000},
        execution_venue_code="PAPER",
        account_scope="***9904-01",
    )

    query, params = db.calls[0]
    assert "execution_venue_code, account_scope" in query
    assert "ON CONFLICT" in query
    assert params[3:5] == ("PAPER", "***9904-01")


def test_position_reads_and_zeroing_are_scoped():
    db = RecordingDB([{"symbol": "005930"}])

    assert fetch_active_position_symbols(
        db,
        "aggressive",
        execution_venue_code="PAPER",
        account_scope="***9904-01",
    ) == ["005930"]
    zero_out_position(
        db,
        "aggressive",
        "005930",
        execution_venue_code="PAPER",
        account_scope="***9904-01",
    )

    assert db.calls[0][1] == ("aggressive", "PAPER", "***9904-01")
    assert db.calls[1][1] == (
        "aggressive", "005930", "PAPER", "***9904-01"
    )


def test_balance_history_write_and_read_are_scoped():
    db = RecordingDB()
    now = dt.datetime(2026, 7, 21, 9, 30, tzinfo=dt.timezone.utc)

    insert_balance_history(
        db,
        "aggressive",
        {"cash": 10, "stock_value": 20, "total_value": 30, "date": now},
        execution_venue_code="PAPER",
        account_scope="***9904-01",
    )
    fetch_balance_history(
        db,
        "aggressive",
        start_date=dt.date(2026, 7, 21),
        end_date=dt.date(2026, 7, 21),
        execution_venue_code="PAPER",
        account_scope="***9904-01",
    )

    assert db.calls[0][1][:2] == ("PAPER", "***9904-01")
    assert db.calls[1][1][:3] == (
        "aggressive", "PAPER", "***9904-01"
    )
