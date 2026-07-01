from apps.worker.analyzer.operations import _average_turnover, audit_operational_state


class FakeDB:
    def __init__(self, one_rows, all_rows):
        self.one_rows = list(one_rows)
        self.all_rows = list(all_rows)

    def fetch_one(self, query, params=None):
        self.last_query = query
        return self.one_rows.pop(0)

    def fetch_all(self, query, params=None):
        return self.all_rows.pop(0)


def test_operational_audit_passes_without_point_in_time_or_publish_mismatch():
    db = FakeDB(
        [
            {"macro_late": 0, "company_late": 0, "stale_running": 0},
            {"mismatch_count": 0, "published_count": 2},
        ],
        [[
            {"run_id": 1, "stock_code": "A"},
            {"run_id": 1, "stock_code": "B"},
            {"run_id": 2, "stock_code": "B"},
            {"run_id": 2, "stock_code": "C"},
        ]],
    )
    report = audit_operational_state(db)
    assert report.status == "PASS"
    assert report.average_monthly_turnover == 0.5


def test_operational_audit_fails_stale_or_point_in_time_state():
    db = FakeDB(
        [
            {"macro_late": 1, "company_late": 0, "stale_running": 1},
            {"mismatch_count": 0, "published_count": 0},
        ],
        [[]],
    )
    report = audit_operational_state(db)
    assert report.status == "FAIL"
    assert report.macro_point_in_time_violations == 1
    assert report.stale_running_count == 1


def test_operational_audit_uses_run_created_at_for_stale_detection():
    db = FakeDB(
        [
            {"macro_late": 0, "company_late": 0, "stale_running": 0},
            {"mismatch_count": 0, "published_count": 0},
        ],
        [[]],
    )
    queries = []
    original_fetch_one = db.fetch_one

    def capture(query, params=None):
        queries.append(query)
        return original_fetch_one(query, params)

    db.fetch_one = capture
    audit_operational_state(db)
    assert "created_at" in queries[0]
    assert "started_at" not in queries[0]


def test_turnover_requires_two_published_runs():
    assert _average_turnover([{"run_id": 1, "stock_code": "A"}]) is None
