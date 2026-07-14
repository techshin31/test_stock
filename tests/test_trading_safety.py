import datetime
from contextlib import contextmanager

import pytest

from core.broker.kis_api import BrokerResponseError, KisBroker, normalize_symbol
from core.broker.simulation import LocalSimulationBroker
from core.execution.trader import LiveTrader
from scheduler import is_trading_day
import scheduler
from storage.postgres.repositories.order_repo import DuplicateOrderError, create_order


class DummyKoreaInvestment:
    def __init__(self, **kwargs):
        self.mock = kwargs["mock"]


def _credential_env(monkeypatch):
    monkeypatch.setenv("KIS_APP_KEY", "key")
    monkeypatch.setenv("KIS_APP_SECRET", "secret")
    monkeypatch.setenv("KIS_DOMESTIC_STOCK_ACCOUNT_NO", "12345678")
    monkeypatch.setenv("KIS_DOMESTIC_STOCK_ACCOUNT_PRODUCT_CODE", "01")


def test_live_broker_requires_both_environment_gates(monkeypatch):
    _credential_env(monkeypatch)
    monkeypatch.setattr("core.broker.kis_api.mojito.KoreaInvestment", DummyKoreaInvestment)

    monkeypatch.setenv("KIS_ENV", "paper")
    monkeypatch.setenv("ALLOW_LIVE_ORDER", "true")
    with pytest.raises(PermissionError, match="KIS_ENV=real"):
        KisBroker(mock=False)

    monkeypatch.setenv("KIS_ENV", "real")
    monkeypatch.setenv("ALLOW_LIVE_ORDER", "false")
    with pytest.raises(PermissionError, match="실주문이 잠겨"):
        KisBroker(mock=False)

    monkeypatch.setenv("ALLOW_LIVE_ORDER", "true")
    broker = KisBroker(mock=False)
    assert broker.is_mock is False
    assert broker.masked_account == "***5678-01"


def test_mock_mode_is_safe_default_even_with_real_marker(monkeypatch):
    _credential_env(monkeypatch)
    monkeypatch.setenv("KIS_ENV", "real")
    monkeypatch.setenv("ALLOW_LIVE_ORDER", "false")
    monkeypatch.setattr("core.broker.kis_api.mojito.KoreaInvestment", DummyKoreaInvestment)
    assert KisBroker().is_mock is True


def test_balance_failure_is_not_converted_to_empty_account():
    wrapper = object.__new__(KisBroker)
    wrapper._fetch_balance_page = lambda *_: {
        "rt_cd": "0", "output1": [], "output2": [], "tr_cont": ""
    }
    with pytest.raises(BrokerResponseError, match="계좌 요약이 비어"):
        wrapper.get_balance()


def test_safe_kis_reads_retry_transient_server_error(monkeypatch):
    wrapper = object.__new__(KisBroker)
    wrapper.get_retry_attempts = 3
    wrapper.retry_backoff_seconds = 0
    wrapper._rate_limit = lambda: None
    calls = []

    class Response:
        headers = {}

        def __init__(self, status_code):
            self.status_code = status_code

        def raise_for_status(self):
            if self.status_code >= 400:
                raise AssertionError("non-retryable response unexpectedly returned")

    monkeypatch.setattr(
        "core.broker.kis_api.requests.request",
        lambda *a, **k: calls.append(True) or Response(500 if len(calls) == 1 else 200),
    )
    monkeypatch.setattr("core.broker.kis_api.time.sleep", lambda *_: None)

    assert wrapper._safe_request("GET", "https://example.invalid").status_code == 200
    assert len(calls) == 2


def _bare_trader(broker):
    trader = object.__new__(LiveTrader)
    trader.broker = broker
    trader.db = object()
    trader.strategy_name = "aggressive"
    trader.max_price_deviation = 0.02
    trader.buy_cash_buffer = 1.03
    trader.max_order_attempts = 2
    trader.fill_poll_attempts = 1
    trader.fill_poll_interval = 0
    return trader


class SafeBroker:
    is_mock = True

    def __init__(self, price=100.0):
        self.price = price
        self.place_calls = 0

    def get_balance(self):
        return {
            "cash": 1_000_000,
            "today_cash": 1_000_000,
            "total_asset": 1_000_000,
            "positions": {"005930.KS": {"qty": 10}},
        }

    def get_current_price(self, ticker):
        return self.price

    def place_market_buy(self, ticker, qty):
        self.place_calls += 1
        return {"rt_cd": "0", "output": {"ODNO": "0001"}}

    def place_market_sell(self, ticker, qty):
        self.place_calls += 1
        return {"rt_cd": "0", "output": {"ODNO": "0001"}}

    def get_order_status(self, order_id):
        return {
            "status": "ACCEPTED", "filled_qty": 0, "remaining_qty": 1,
            "avg_fill_price": 0, "total_fill_amount": 0, "raw": {},
        }


def test_db_claim_failure_prevents_broker_order(monkeypatch):
    broker = SafeBroker()
    trader = _bare_trader(broker)
    monkeypatch.setattr(
        "storage.postgres.repositories.order_repo.create_order",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("db down")),
    )
    with pytest.raises(RuntimeError, match="DB 선점 실패"):
        trader._execute_orders([
            {"type": "BUY", "ticker": "005930.KS", "qty": 1,
             "expected_price": 100, "reason": "test", "idempotency_key": "key"}
        ])
    assert broker.place_calls == 0


def test_price_deviation_blocks_order_before_db_claim(monkeypatch):
    broker = SafeBroker(price=110)
    trader = _bare_trader(broker)
    called = []
    monkeypatch.setattr(
        "storage.postgres.repositories.order_repo.create_order",
        lambda *args, **kwargs: called.append(True),
    )
    result = trader._execute_orders([
        {"type": "BUY", "ticker": "005930.KS", "qty": 1,
         "expected_price": 100, "reason": "test", "idempotency_key": "key"}
    ])
    assert result[0]["status"] == "SKIPPED"
    assert not called
    assert broker.place_calls == 0


def test_price_deviation_does_not_block_risk_sell(monkeypatch):
    broker = SafeBroker(price=90)
    trader = _bare_trader(broker)
    monkeypatch.setattr("storage.postgres.repositories.order_repo.create_order", lambda *a, **k: "local-id")
    monkeypatch.setattr("storage.postgres.repositories.order_repo.mark_order_submitted", lambda *a, **k: None)
    monkeypatch.setattr("storage.postgres.repositories.order_repo.attach_broker_order_id", lambda *a, **k: None)
    monkeypatch.setattr("storage.postgres.repositories.order_repo.update_order_status", lambda *a, **k: None)
    trader._record_broker_status = lambda *args: "ACCEPTED"

    result = trader._execute_orders([
        {"type": "SELL", "ticker": "005930.KS", "qty": 1,
         "expected_price": 100, "reason": "MARKET_DOWNTREND", "idempotency_key": "sell-key"}
    ])

    assert result[0]["status"] == "ACCEPTED"
    assert broker.place_calls == 1


def test_broker_acceptance_is_not_treated_as_fill(monkeypatch):
    broker = SafeBroker()
    trader = _bare_trader(broker)
    statuses = []
    monkeypatch.setattr("storage.postgres.repositories.order_repo.create_order", lambda *a, **k: "local-id")
    monkeypatch.setattr("storage.postgres.repositories.order_repo.mark_order_submitted", lambda *a, **k: None)
    monkeypatch.setattr("storage.postgres.repositories.order_repo.attach_broker_order_id", lambda *a, **k: None)
    monkeypatch.setattr("storage.postgres.repositories.order_repo.update_order_status", lambda *a, **k: None)
    trader._record_broker_status = lambda *args: statuses.append(args[-1]["status"]) or "ACCEPTED"

    result = trader._execute_orders([
        {"type": "BUY", "ticker": "005930.KS", "qty": 1,
         "expected_price": 100, "reason": "test", "idempotency_key": "key"}
    ])
    assert result[0]["status"] == "ACCEPTED"
    assert statuses == ["ACCEPTED"]
    assert broker.place_calls == 1


def test_actual_fill_creates_signed_execution(monkeypatch):
    trader = _bare_trader(SafeBroker())
    captured = {}
    monkeypatch.setattr(
        "storage.postgres.repositories.execution_repo.fetch_execution_totals_by_order",
        lambda *a, **k: {"qty": 0.0, "amount": 0.0},
    )
    monkeypatch.setattr(
        "storage.postgres.repositories.execution_repo.insert_execution",
        lambda db, order_id, data: captured.update(data),
    )
    monkeypatch.setattr(
        "storage.postgres.repositories.order_repo.update_order_status",
        lambda *a, **k: None,
    )
    status = {
        "status": "FILLED", "filled_qty": 2, "remaining_qty": 0,
        "avg_fill_price": 101, "total_fill_amount": 202, "raw": {},
    }
    assert trader._record_broker_status(
        "order", "005930.KS", "BUY", 100, "broker", status
    ) == "FILLED"
    assert captured["symbol"] == "005930"
    assert captured["price"] == 101
    assert captured["net_amount"] == -202
    assert captured["slippage"] == 2


def test_symbol_normalization_is_consistent():
    assert normalize_symbol("005930.KS") == "005930"
    assert normalize_symbol("005930") == "005930"


def test_duplicate_idempotency_claim_is_rejected_before_submission():
    class NoRowResult:
        def fetchone(self):
            return None

    class FakeConnection:
        def execute(self, *args, **kwargs):
            return NoRowResult()

    class FakeDB:
        def execute(self, *args, **kwargs):
            return 0

        def fetch_one(self, *args, **kwargs):
            return {"id": 1}

        @contextmanager
        def transaction(self):
            yield FakeConnection()

    with pytest.raises(DuplicateOrderError):
        create_order(FakeDB(), {
            "symbol": "005930", "order_side_code": "BUY",
            "strategy_id": 1, "qty": 1, "idempotency_key": "same-key",
        })


def test_scheduler_does_not_trade_on_weekends():
    saturday = datetime.datetime(2026, 7, 11, 10, 0)
    assert is_trading_day(saturday) is False


def test_scheduler_dry_run_adds_no_order_flag(monkeypatch):
    captured = {}
    monkeypatch.setattr(
        scheduler.subprocess,
        "run",
        lambda cmd, **kwargs: captured.update(cmd=cmd) or type("R", (), {"returncode": 0})(),
    )

    scheduler.run_command(mode="intraday", live=False, dry_run=True)

    assert "--mock" in captured["cmd"]
    assert "--dry-run" in captured["cmd"]


def test_scheduler_simulation_uses_local_broker_flag(monkeypatch):
    captured = {}
    monkeypatch.setattr(
        scheduler.subprocess,
        "run",
        lambda cmd, **kwargs: captured.update(cmd=cmd) or type("R", (), {"returncode": 0})(),
    )

    scheduler.run_command(mode="intraday", dry_run=False, simulate=True)

    assert "--simulate" in captured["cmd"]
    assert "--dry-run" not in captured["cmd"]


def test_unknown_order_recovery_requires_one_precise_match():
    local = {
        "symbol": "005930", "order_side_code": "BUY", "qty": 2,
        "created_at": datetime.datetime(2026, 7, 10, 9, 1, 0),
    }
    matching = {
        "odno": "000123", "pdno": "005930", "sll_buy_dvsn_cd": "02",
        "ord_qty": "2", "ord_tmd": "090130",
    }
    wrong_qty = {**matching, "odno": "000124", "ord_qty": "3"}
    assert LiveTrader._match_unknown_broker_order(local, [matching, wrong_qty], set()) == [matching]
    assert LiveTrader._match_unknown_broker_order(local, [matching], {"123"}) == []


def test_unknown_order_reconciliation_waits_for_grace_period():
    trader = object.__new__(LiveTrader)
    trader.unknown_order_grace_seconds = 300
    now = datetime.datetime(2026, 7, 13, 5, 20, tzinfo=datetime.timezone.utc)
    assert trader._unknown_order_grace_elapsed(
        {"created_at": now - datetime.timedelta(seconds=301)}, now
    )
    assert not trader._unknown_order_grace_elapsed(
        {"created_at": now - datetime.timedelta(seconds=299)}, now
    )


def test_unresolved_order_circuit_breaker_blocks_trading():
    trader = object.__new__(LiveTrader)
    trader.db = type("DB", (), {"fetch_one": lambda *a, **k: {"count": 2}})()

    with pytest.raises(RuntimeError, match="2 open orders"):
        trader._assert_no_unresolved_orders()


def test_paper_fill_can_be_inferred_from_balance_change():
    broker = SafeBroker(price=100)
    broker.get_balance = lambda: {
        "positions": {"005930.KS": {"qty": 7}}, "cash": 0
    }
    trader = _bare_trader(broker)

    status = trader._infer_paper_fill_from_balance(
        "005930.KS", "SELL", 3, 100, {"005930.KS": {"qty": 10}}
    )

    assert status["status"] == "FILLED"
    assert status["filled_qty"] == 3
    assert status["raw"]["source"] == "PAPER_BALANCE_FALLBACK"


def test_local_simulation_broker_persists_fills(tmp_path, monkeypatch):
    monkeypatch.setenv("SIM_INITIAL_CASH", "1000000")
    monkeypatch.setenv("SIM_SLIPPAGE_RATE", "0")
    state_path = tmp_path / "sim.json"
    broker = LocalSimulationBroker(state_path)
    broker.set_market_price("005930.KS", 100)

    buy = broker.place_market_buy("005930.KS", 10)
    assert broker.get_order_status(buy["output"]["ODNO"])["status"] == "FILLED"
    assert broker.get_balance()["positions"]["005930.KS"]["qty"] == 10

    restarted = LocalSimulationBroker(state_path)
    restarted.set_market_price("005930.KS", 110)
    restarted.place_market_sell("005930.KS", 4)
    balance = restarted.get_balance()
    assert balance["positions"]["005930.KS"]["qty"] == 6
    assert balance["cash"] > 999000
