import datetime as dt

import pytest

from core.analytics.paper_ledger_reconstruction import (
    KST,
    _build_broker_only_ledger,
    _build_order_ledger,
    _minimum_opening_inventory,
)


def test_broker_daily_order_backfill_recovers_missing_fill_price_and_amount():
    source = {
        "companies": [{"stock_code": "005930", "company_name": "삼성전자"}],
        "executions": [],
        "orders": [{
            "id": "order-1",
            "created_at": dt.datetime(
                2026, 7, 9, 9, 0, tzinfo=dt.timezone(dt.timedelta(hours=9))
            ),
            "symbol": "005930",
            "order_side_code": "SELL",
            "qty": 3,
            "price": 0,
            "order_status_code": "FILLED",
            "filled_qty": 3,
            "avg_fill_price": 0,
            "broker_order_id": "0000001234",
            "execution_venue_code": "UNKNOWN",
            "account_scope": "UNKNOWN",
        }],
    }
    backfill = {
        ("2026-07-09", "1234"): {
            "broker_order_id": "0000001234",
            "symbol": "005930",
            "filled_qty": 3,
            "total_fill_amount": 301,
            "avg_fill_price": 100,
        }
    }

    ledger = _build_order_ledger(source, {}, backfill)
    row = ledger.iloc[0]

    assert row["avg_fill_price"] == pytest.approx(301 / 3)
    assert row["fill_amount"] == 301
    assert row["fill_price_available"]
    assert row["fill_source"] == "BROKER_DAILY_ORDER_BACKFILL"


def test_broker_only_fill_is_preserved_as_confirmed_paper_evidence():
    ledger = _build_broker_only_ledger(
        [{
            "date": "2026-07-09",
            "broker_order_id": "0000047428",
            "symbol": "009420",
            "side": "SELL",
            "ordered_qty": 870,
            "filled_qty": 870,
            "total_fill_amount": 49_620_600,
            "avg_fill_price": 57_035,
            "order_time": "145948",
        }],
        {"009420": "한올바이오파마"},
        account_scope="***9904-01",
    )
    row = ledger.iloc[0]

    assert row["order_id"] == "BROKER_ONLY:0000047428"
    assert row["created_at"] == dt.datetime(
        2026, 7, 9, 14, 59, 48, tzinfo=KST
    ).isoformat()
    assert row["filled_qty"] == 870
    assert row["fill_amount"] == 49_620_600
    assert row["fill_source"] == "BROKER_DAILY_ORDER_ONLY"
    assert row["scope_class"] == "CONFIRMED_PAPER_BROKER_ONLY"


def test_minimum_opening_inventory_only_covers_preexisting_sell_quantity():
    import pandas as pd

    orders = pd.DataFrame([
        {
            "order_id": "1",
            "created_at": "2026-07-09T09:00:00+09:00",
            "symbol": "A",
            "side": "SELL",
            "status": "FILLED",
            "filled_qty": 5,
        },
        {
            "order_id": "2",
            "created_at": "2026-07-09T10:00:00+09:00",
            "symbol": "A",
            "side": "BUY",
            "status": "FILLED",
            "filled_qty": 2,
        },
        {
            "order_id": "3",
            "created_at": "2026-07-09T09:00:00+09:00",
            "symbol": "B",
            "side": "BUY",
            "status": "FILLED",
            "filled_qty": 7,
        },
    ])

    assert _minimum_opening_inventory(orders) == {"A": 5.0, "B": 0.0}


def test_broker_nonfill_overrides_false_db_fill_without_mutating_source():
    source = {
        "companies": [{"stock_code": "012510", "company_name": "더존비즈온"}],
        "executions": [{
            "order_id": "order-1",
            "qty": 168,
            "amount": 20_160_000,
            "commission": 0,
            "tax": 0,
            "slippage": 0,
        }],
        "orders": [{
            "id": "order-1",
            "created_at": dt.datetime(2026, 7, 9, 15, 17, 39, tzinfo=KST),
            "symbol": "012510.KS",
            "order_side_code": "BUY",
            "qty": 168,
            "price": 0,
            "order_status_code": "FILLED",
            "filled_qty": 168,
            "avg_fill_price": 120_000,
            "broker_order_id": "0000049114",
            "execution_venue_code": "UNKNOWN",
            "account_scope": "UNKNOWN",
        }],
    }
    override = {
        ("2026-07-09", "49114"): {
            "symbol": "012510",
            "ordered_qty": 168,
            "filled_qty": 0,
        }
    }

    ledger = _build_order_ledger(source, {}, {}, override)
    row = ledger.iloc[0]

    assert row["status"] == "EXPIRED_UNFILLED"
    assert row["filled_qty"] == 0
    assert row["avg_fill_price"] == 0
    assert row["fill_amount"] == 0
    assert row["execution_row_count"] == 0
    assert row["db_original_execution_row_count"] == 1
    assert row["db_original_execution_qty"] == 168
    assert row["broker_status_override"]
    assert row["db_original_status"] == "FILLED"
    assert row["db_original_filled_qty"] == 168
    assert row["fill_source"] == "BROKER_DAILY_ORDER_NO_FILL_OVERRIDE"
    assert source["orders"][0]["order_status_code"] == "FILLED"
