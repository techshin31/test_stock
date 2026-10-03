import copy
import datetime as dt
import json
import sys
from types import SimpleNamespace

import pytest

from apps.system.__main__ import main as system_main
from apps.system.local_check import run_local_check
from core.broker.simulation import LocalSimulationBroker
from core.execution.trader import LiveTrader
import run_live_trader


@pytest.mark.parametrize("simulated", [True, False])
def test_direct_dry_run_never_queries_or_submits_to_broker(simulated):
    class ForbiddenBroker:
        is_simulated = simulated

        def __getattr__(self, name):
            pytest.fail("DRY_RUN accessed broker: " + name)

    trader = object.__new__(LiveTrader)
    trader.execution_venue = "DRY_RUN"
    trader.broker = ForbiddenBroker()
    orders = [{"type": "BUY", "ticker": "005930.KS", "qty": 1, "reason": "test"}]
    before = copy.deepcopy(orders)
    assert trader._execute_orders(orders) == [{**orders[0], "status": "DRY_RUN", "filled_qty": 0}]
    assert orders == before


@pytest.mark.parametrize("flags,dry_run,submitted", [([], True, False), (["--mock"], False, True)])
def test_cli_requires_explicit_broker_orders_and_opt_in_notifications(monkeypatch, flags, dry_run, submitted):
    captured = {}

    class Trader:
        broker = SimpleNamespace(is_mock=True, masked_account="TEST")

        def __init__(self, **kwargs):
            captured.update(kwargs)

        def run_daily_batch(self):
            return [{"type": "BUY", "ticker": "TEST", "qty": 1, "reason": "fixture"}]

        def _execute_orders(self, orders):
            captured["submitted"] = True
            return [{**orders[0], "status": "FILLED"}]

        def update_intraday_dashboard(self, results):
            pass

        def append_trade_history(self, results):
            captured["history"] = True

    monkeypatch.setattr(sys, "argv", ["run_live_trader.py", *flags])
    monkeypatch.setattr(run_live_trader, "LiveTrader", Trader)
    monkeypatch.setattr(run_live_trader, "configure_logging", lambda mode: None)
    monkeypatch.setattr(run_live_trader, "ProcessInstanceLock", lambda *a, **k: SimpleNamespace(acquire=lambda: None, release=lambda: None))
    monkeypatch.setattr(run_live_trader, "TelegramBot", lambda: pytest.fail("notification client initialized"))
    run_live_trader.main()
    assert captured["dry_run"] == dry_run
    assert bool(captured.get("submitted")) == submitted
    assert bool(captured.get("history")) == submitted


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -1, 0, True, None])
def test_invalid_simulation_quote_does_not_change_account(tmp_path, value):
    path = tmp_path / "account.json"
    broker = LocalSimulationBroker(path)
    broker.set_market_price("005930", 100)
    before = path.read_bytes()
    with pytest.raises(ValueError):
        broker.set_market_price("005930", value)
    assert path.read_bytes() == before
    assert broker.get_current_price("005930") == 100


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -1, 0, 1.5, True, None])
def test_invalid_simulation_quantity_is_not_truncated(tmp_path, value):
    path = tmp_path / "account.json"
    broker = LocalSimulationBroker(path)
    broker.set_market_price("005930", 100)
    before = path.read_bytes()
    with pytest.raises(ValueError):
        broker.place_market_buy("005930", value)
    assert path.read_bytes() == before


@pytest.mark.parametrize("field,value", [("qty", 1.5), ("qty", None), ("qty", True), ("type", "INVALID"), ("expected_price", float("nan"))])
def test_invalid_simulation_order_is_rejected_without_changing_holdings(tmp_path, field, value):
    path = tmp_path / "account.json"
    broker = LocalSimulationBroker(path)
    broker.set_market_price("005930", 100)
    broker.place_market_buy("005930", 2)
    trader = object.__new__(LiveTrader)
    trader.execution_venue = "SIMULATE"
    trader.broker = broker
    order = {"type": "BUY", "ticker": "005930", "qty": 1, "expected_price": 200, "reason": "fixture", field: value}
    before = path.read_bytes()
    result = trader._execute_orders([order])
    assert result[0]["status"] == "REJECTED"
    assert path.read_bytes() == before


@pytest.mark.parametrize("setting", ["commission_rate", "slippage_rate", "sell_tax_rate"])
@pytest.mark.parametrize("value", [float("nan"), -0.1, 1.0])
def test_invalid_simulation_costs_are_rejected_before_state_creation(tmp_path, setting, value):
    path = tmp_path / "account.json"
    with pytest.raises(ValueError):
        LocalSimulationBroker(path, **{setting: value})
    assert not path.exists()


def test_keyed_fill_survives_restart_without_charging_again(tmp_path):
    path = tmp_path / "account.json"
    broker = LocalSimulationBroker(path)
    broker.set_market_price("005930", 100)
    result = broker.place_market_buy("005930", 5, idempotency_key="same-order")
    before = path.read_bytes()
    restarted = LocalSimulationBroker(path)
    repeated = restarted.place_market_buy("005930.KS", 5, idempotency_key="same-order")
    assert result["output"] == repeated["output"]
    assert path.read_bytes() == before
    assert len(restarted.fetch_daily_orders()) == 1
    with pytest.raises(ValueError, match="conflicts"):
        restarted.place_market_buy("005930", 6, idempotency_key="same-order")
    assert path.read_bytes() == before


def test_failed_account_replace_does_not_commit_an_in_memory_fill(tmp_path, monkeypatch):
    path = tmp_path / "account.json"
    broker = LocalSimulationBroker(path)
    broker.set_market_price("005930", 100)
    before = copy.deepcopy(broker._state)
    content = path.read_bytes()
    monkeypatch.setattr("core.broker.simulation.os.replace", lambda *a: (_ for _ in ()).throw(OSError("disk failure")))
    with pytest.raises(OSError):
        broker.place_market_buy("005930", 5)
    assert broker._state == before
    assert path.read_bytes() == content
    assert LocalSimulationBroker(path).get_balance() == broker.get_balance()


@pytest.mark.parametrize("state", [{"cash": -1, "positions": {}, "orders": {}}, {"cash": float("nan"), "positions": {}, "orders": {}}, {"cash": 100}, []])
def test_invalid_persisted_account_is_preserved_and_rejected(tmp_path, state):
    path = tmp_path / "account.json"
    path.write_text(json.dumps(state))
    before = path.read_bytes()
    with pytest.raises(ValueError, match="state is invalid"):
        LocalSimulationBroker(path)
    assert path.read_bytes() == before


def test_explicit_account_path_never_imports_unrelated_legacy_balance(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    legacy = tmp_path / "logs/sim_account.json"
    legacy.parent.mkdir()
    legacy.write_text(json.dumps({"cash": 12, "positions": {}, "orders": {}}))
    broker = LocalSimulationBroker(tmp_path / "isolated/account.json", initial_cash=1000)
    assert broker.get_balance()["cash"] == 1000
    assert json.loads(legacy.read_text())["cash"] == 12


def test_simulation_order_history_obeys_requested_date(tmp_path):
    broker = LocalSimulationBroker(tmp_path / "account.json")
    broker.set_market_price("005930", 100)
    broker.place_market_buy("005930", 1)
    assert len(broker.fetch_daily_orders()) == 1
    assert broker.fetch_daily_orders(dt.date(2000, 1, 1)) == []


def test_local_check_runs_real_components_without_network_or_database(monkeypatch):
    monkeypatch.setattr("core.broker.kis_api.KisBroker.__init__", lambda *a, **k: pytest.fail("KIS initialized"))
    monkeypatch.setattr("storage.postgres.connection.PostgreDB.__init__", lambda *a, **k: pytest.fail("DB initialized"))
    monkeypatch.setattr("requests.sessions.Session.request", lambda *a, **k: pytest.fail("network request"))
    result = run_local_check()
    assert result["status"] == "PASS"
    assert all(result["checks"].values())
    assert result["input_source"] == "SYNTHETIC_FIXTURE"
    assert result["fa_backtest_validated"] is False
    assert [r["type"] for r in result["simulation_fills"]] == ["BUY", "SELL"]


def test_doctor_cli_does_not_confuse_development_and_data_readiness(monkeypatch, tmp_path):
    monkeypatch.setattr("apps.system.diagnostics.diagnose", lambda cutoff: {"development_ready": True, "data_ready": False})
    assert system_main(["doctor"]) == 0
    output = tmp_path / "readiness.json"
    assert system_main(["doctor", "--require-data", "--output", str(output)]) == 2
    assert json.loads(output.read_text())["data_ready"] is False
