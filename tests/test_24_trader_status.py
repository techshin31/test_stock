from datetime import date
from types import SimpleNamespace

from apps.trader import __main__ as trader_main
from apps.trader.monitor import ServiceStatus, fetch_status, print_status
from core.trade.gate import check_daily_loss_limit


class FakeDB:
    def close(self):
        self.closed = True


def test_status_prints_plan_state_breakdown(capsys):
    status = ServiceStatus(
        strategy_name="risk_neutral",
        plan_date=date(2026, 6, 29),
        total_plans=15,
        done_plans=5,
        skipped_plans=10,
        pending_plans=0,
        total_filled_qty=502,
        daily_net=-7175582,
    )

    print_status(status)

    out = capsys.readouterr().out
    assert "계획 15개" in out
    assert "DONE 5개" in out
    assert "SKIPPED 10개" in out
    assert "PENDING/ORDERED 0개" in out


def test_fetch_status_maps_skipped_plan_count(monkeypatch):
    monkeypatch.setattr(
        "apps.trader.monitor.fetch_daily_plan_counts",
        lambda *args: {"total": 15, "done": 5, "skipped": 10, "pending": 0},
    )
    monkeypatch.setattr(
        "apps.trader.monitor.fetch_daily_execution_summary",
        lambda *args: {"total_filled_qty": 502, "daily_net": -7175582},
    )

    status = fetch_status(FakeDB(), "risk_neutral", date(2026, 6, 29))

    assert status.total_plans == 15
    assert status.done_plans == 5
    assert status.skipped_plans == 10
    assert status.pending_plans == 0


def test_daily_loss_limit_ratio_uses_previous_total_assets(monkeypatch):
    monkeypatch.setattr("core.trade.gate.fetch_latest_total_value", lambda *args: 1_000_000)

    allowed = check_daily_loss_limit(FakeDB(), "risk_neutral", 0.10, 900_000)
    blocked = check_daily_loss_limit(FakeDB(), "risk_neutral", 0.10, 899_999)

    assert allowed.allowed is True
    assert "한도: -100,000원 (전일자산의 10.0%)" in allowed.reason
    assert blocked.allowed is False
    assert "일일 손실 한도 초과" in blocked.reason
    assert "한도: -100,000원 (전일자산의 10.0%)" in blocked.reason


def test_daily_loss_limit_fixed_won_amount_still_supported(monkeypatch):
    monkeypatch.setattr("core.trade.gate.fetch_latest_total_value", lambda *args: 1_000_000)

    status = check_daily_loss_limit(FakeDB(), "risk_neutral", 500_000, 499_999)

    assert status.allowed is False
    assert "한도: -500,000원 (고정 원화)" in status.reason


def test_executor_exits_after_cycle_when_no_pending_or_ordered_plans(monkeypatch, capsys):
    db = FakeDB()
    cfg = SimpleNamespace(
        strategy_name="risk_neutral",
        daily_loss_limit=0.10,
        cycle_interval_sec=60,
    )
    status = ServiceStatus(
        strategy_name="risk_neutral",
        plan_date=date(2026, 6, 29),
        total_plans=15,
        done_plans=5,
        skipped_plans=10,
        pending_plans=0,
    )
    calls = []

    monkeypatch.setattr(trader_main, "_init", lambda: (cfg, db, object()))
    monkeypatch.setattr("apps.trader.scheduler.is_trading_day", lambda: True)
    monkeypatch.setattr("apps.trader.scheduler.wait_until", lambda *args: None)
    monkeypatch.setattr("apps.trader.scheduler.is_market_hours", lambda: True)
    monkeypatch.setattr("apps.trader.planner.has_executable_plans", lambda *args: True)
    monkeypatch.setattr("apps.trader.runner.run_one_cycle", lambda *args, **kwargs: calls.append("cycle"))
    monkeypatch.setattr("apps.trader.monitor.fetch_status", lambda *args: status)

    trader_main.run_executor()

    out = capsys.readouterr().out
    assert calls == ["cycle"]
    assert "PENDING/ORDERED 계획이 0개입니다. 장중 루프를 조기 종료합니다." in out
    assert db.closed is True


def test_reconciler_skips_1540_wait_when_all_plans_are_closed(monkeypatch, capsys):
    db = FakeDB()
    cfg = SimpleNamespace(strategy_name="risk_neutral")
    status = ServiceStatus(
        strategy_name="risk_neutral",
        plan_date=date(2026, 6, 29),
        total_plans=15,
        done_plans=5,
        skipped_plans=10,
        pending_plans=0,
    )
    waits = []
    reconciles = []
    snapshots = []

    monkeypatch.setattr(trader_main, "_init", lambda: (cfg, db, object()))
    monkeypatch.setattr("apps.trader.monitor.fetch_status", lambda *args: status)
    monkeypatch.setattr("apps.trader.scheduler.wait_until", lambda *args: waits.append(args))
    monkeypatch.setattr("apps.trader.audit.log_eod", lambda *args, **kwargs: None)
    monkeypatch.setattr("apps.trader.audit.log_error", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        "core.trade.reconcile.reconcile_orders_from_broker_history",
        lambda *args, **kwargs: reconciles.append(args) or SimpleNamespace(
            broker_rows=0,
            managed_orders=0,
            inserted_executions=0,
            updated_orders=0,
        ),
    )
    monkeypatch.setattr(
        "apps.trader.planner.pre_market_sync",
        lambda *args, **kwargs: {
            "output2": [{"tot_evlu_amt": "1000000", "prvs_rcdl_excc_amt": "400000"}],
        },
    )
    monkeypatch.setattr("storage.postgres.repositories.universe_repo.mark_empty_sell_only_removed", lambda *args: [])
    monkeypatch.setattr("storage.postgres.repositories.balance_repo.fetch_balance_history", lambda *args, **kwargs: [])
    monkeypatch.setattr(
        "storage.postgres.repositories.balance_repo.insert_balance_history",
        lambda *args, **kwargs: snapshots.append(kwargs["snapshot"]),
    )

    trader_main.run_reconciler()

    out = capsys.readouterr().out
    assert waits == []
    assert len(reconciles) == 1
    assert snapshots[0]["total_value"] == 1000000
    assert "PENDING/ORDERED 계획이 0개입니다. 15:40 대기를 건너뜁니다." in out
    assert db.closed is True
