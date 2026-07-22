import datetime as dt

from core.analytics.paper_broker_history import audit_broker_history


class FakeDB:
    def fetch_all(self, query, params):
        return [
            {
                "order_id": "db-fill-price",
                "local_date": "2026-07-03",
                "strategy_name": "risk_neutral",
                "broker_order_id": "0001",
                "symbol": "A.KS",
                "order_side_code": "BUY",
                "order_status_code": "FILLED",
                "qty": 2,
                "filled_qty": 2,
                "avg_fill_price": 0,
            },
            {
                "order_id": "db-false-fill",
                "local_date": "2026-07-03",
                "strategy_name": "risk_neutral",
                "broker_order_id": "0002",
                "symbol": "B.KS",
                "order_side_code": "BUY",
                "order_status_code": "FILLED",
                "qty": 3,
                "filled_qty": 3,
                "avg_fill_price": 100,
            },
        ]


class FakeBroker:
    is_mock = True
    masked_account = "***9904-01"

    def fetch_daily_orders(self, day):
        if day != dt.date(2026, 7, 3):
            return []
        return [
            {
                "odno": "0001", "pdno": "A", "sll_buy_dvsn_cd": "02",
                "ord_qty": "2", "tot_ccld_qty": "2", "rmn_qty": "0",
                "tot_ccld_amt": "202", "avg_prvs": "101", "cncl_yn": "N",
                "ord_tmd": "090000",
            },
            {
                "odno": "0002", "pdno": "B", "sll_buy_dvsn_cd": "02",
                "ord_qty": "3", "tot_ccld_qty": "0", "rmn_qty": "3",
                "tot_ccld_amt": "0", "avg_prvs": "0", "cncl_yn": "N",
                "ord_tmd": "090100",
            },
            {
                "odno": "0003", "pdno": "C", "sll_buy_dvsn_cd": "01",
                "ord_qty": "4", "tot_ccld_qty": "4", "rmn_qty": "0",
                "tot_ccld_amt": "404", "avg_prvs": "101", "cncl_yn": "N",
                "ord_tmd": "090200",
            },
        ]


def test_audit_classifies_fill_backfill_false_fill_and_broker_only_order():
    result = audit_broker_history(
        FakeDB(),
        FakeBroker(),
        start_date=dt.date(2026, 7, 3),
        end_date=dt.date(2026, 7, 3),
    )

    assert len(result["fill_overrides"]) == 1
    assert len(result["broker_filled_rows"]) == 1
    assert result["fill_overrides"][0]["db_order_id"] == "db-fill-price"
    assert len(result["broker_nonfill_overrides"]) == 1
    assert result["broker_nonfill_overrides"][0]["db_order_id"] == "db-false-fill"
    assert len(result["broker_only_rows"]) == 1
    assert result["broker_only_rows"][0]["broker_order_id"] == "0003"
    assert result["unresolved_db_filled_rows"] == []
    assert result["audit_complete"] is True
