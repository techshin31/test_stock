from datetime import date
from pathlib import Path

from apps.worker.company_risk import (
    POLICY_VERSION,
    derive_company_risk_states,
)
from core.trade import execution
from storage.postgres.repositories.company_risk_repo import (
    fetch_active_company_risk_states,
    upsert_company_risk_states,
)


ROOT = Path(__file__).resolve().parents[1]


class FakeDB:
    def __init__(self, rows=None):
        self.rows = rows or []
        self.calls = []

    def execute_many(self, query, params):
        self.calls.append((query, params))

    def fetch_all(self, query, params=None):
        self.calls.append((query, params))
        return self.rows


def _event(event_id, stock_code, subtype, rcept_dt):
    return {
        "id": event_id, "stock_code": stock_code,
        "event_subtype_code": subtype, "rcept_dt": rcept_dt,
        "rcept_no": f"R{event_id}", "report_nm": subtype,
    }


def test_risk_policy_versions_each_dilution_event_for_as_of_replay():
    rows = derive_company_risk_states(
        [
            _event(1, "A", "PAID_IN_CAPITAL_INCREASE", date(2025, 1, 1)),
            _event(2, "A", "CASH_DIVIDEND", date(2026, 5, 20)),
            _event(3, "A", "CONVERTIBLE_BOND", date(2026, 5, 1)),
            _event(4, "A", "BOND_WITH_WARRANT", date(2026, 5, 15)),
        ],
        date(2026, 5, 31),
    )
    assert [row["source_dart_event_id"] for row in rows] == [1, 3, 4]
    assert rows[-1]["risk_action_code"] == "BLOCK_BUY"
    assert rows[-1]["expires_at"] == date(2026, 8, 13)
    assert rows[-1]["policy_version"] == POLICY_VERSION


def test_risk_repository_protects_manual_override_and_filters_as_of_date():
    db = FakeDB()
    upsert_company_risk_states(db, [{
        "stock_code": "A", "risk_action_code": "BLOCK_BUY",
        "reason_code": "CONVERTIBLE_BOND", "source_dart_event_id": 3,
        "effective_date": date(2026, 5, 1), "expires_at": date(2026, 7, 30),
        "policy_version": POLICY_VERSION,
    }])
    assert "source_dart_event_id, policy_version" in db.calls[0][0]

    fetch_active_company_risk_states(db, date(2026, 5, 31), ["A"])
    query, params = db.calls[1]
    assert "DISTINCT ON (stock_code)" in query
    assert "expires_at >= %s" in query
    assert params == (date(2026, 5, 31), date(2026, 5, 31), ["A"], ["BLOCK_BUY", "SELL_ONLY"])


def test_company_risk_schema_has_source_fk_and_manual_override():
    schema = (ROOT / "storage/postgres/schema/05_market_data_schema.sql").read_text(encoding="utf-8")
    assert "CREATE TABLE IF NOT EXISTS company_risk_states" in schema
    assert "id                    BIGSERIAL PRIMARY KEY" in schema
    assert "source_dart_event_id  BIGINT REFERENCES dart_events(id)" in schema
    assert "is_manual_override" in schema


def test_executor_blocks_buy_before_requesting_buyable_quantity(monkeypatch):
    monkeypatch.setattr(execution, "fetch_trade_plan_progress", lambda *args: {"filled_qty": 0})
    monkeypatch.setattr(execution, "sync_open_orders_for_plan", lambda *args: False)
    monkeypatch.setattr(execution, "is_company_buy_blocked", lambda *args: True)
    blocked = []
    monkeypatch.setattr(
        execution, "mark_trade_plan_company_risk_blocked",
        lambda db, plan_id: blocked.append(plan_id),
    )
    monkeypatch.setattr(
        execution, "_get_buyable_qty",
        lambda *args: (_ for _ in ()).throw(AssertionError("must not query buyable qty")),
    )
    result = execution.execute_plan_with_orderbook_slicing(
        object(), object(), {
            "id": 11, "symbol": "005930", "order_side_code": "BUY",
            "planned_qty": 10, "plan_date": date(2026, 5, 31),
        }
    )
    assert result.executable_qty == 0
    assert blocked == [11]
