from datetime import date

import pytest

from apps.backtester.universe import build_fa_published_universe


class FakeDB:
    def __init__(self, rows):
        self.rows = rows

    def fetch_all(self, query, params=None):
        assert "status_code = 'PUBLISHED'" in query
        return self.rows


def _rows(effective_date, symbols, cutoff=date(2026, 5, 31)):
    return [
        {
            "run_id": effective_date.month, "cutoff_date": cutoff,
            "effective_date": effective_date, "stock_code": symbol,
            "latest_available_date": cutoff,
        }
        for symbol in symbols
    ]


def test_published_fa_history_builds_deterministic_rotation_plans():
    june = ["000001", "000002", "000003", "000004", "000005", "000006"]
    july = ["000002", "000003", "000004", "000005", "000006", "000007"]
    initial, plans, tickers = build_fa_published_universe(
        FakeDB(_rows(date(2026, 6, 1), june) + _rows(date(2026, 7, 1), july, date(2026, 6, 30))),
        "risk_neutral", date(2026, 6, 1), date(2026, 7, 31),
    )
    assert initial == june
    assert len(plans) == 1
    assert plans[0].exits == ["000001"]
    assert plans[0].entries == ["000007"]
    assert tickers == set(june + ["000007"])


def test_published_fa_history_rejects_lookahead_input():
    rows = _rows(date(2026, 6, 1), [f"{index:06d}" for index in range(6)])
    rows[0]["latest_available_date"] = date(2026, 6, 1)
    with pytest.raises(ValueError, match="point-in-time"):
        build_fa_published_universe(
            FakeDB(rows), "risk_neutral", date(2026, 6, 1), date(2026, 6, 30)
        )


def test_published_fa_history_rejects_more_than_ten_companies():
    rows = _rows(date(2026, 6, 1), [f"{index:06d}" for index in range(11)])
    with pytest.raises(ValueError, match="exceeds 10"):
        build_fa_published_universe(
            FakeDB(rows), "risk_neutral", date(2026, 6, 1), date(2026, 6, 30)
        )
