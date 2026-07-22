import datetime
import json
import sys
from contextlib import contextmanager
from pathlib import Path

import pytest
import requests

from core.broker.kis_api import (
    BrokerResponseError,
    KisBroker,
    normalize_symbol,
    redact_sensitive_text,
)
from core.broker.simulation import LocalSimulationBroker
from core.execution.trader import LiveTrader
from core.utils.telegram_bot import TelegramBot
from run_live_trader import main as trader_main
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


def test_cli_rejects_live_dry_run_before_broker_initialization(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["run_live_trader.py", "--live", "--dry-run"])
    monkeypatch.setattr(
        "run_live_trader.LiveTrader",
        lambda *args, **kwargs: pytest.fail("broker must not initialize"),
    )

    with pytest.raises(SystemExit) as caught:
        trader_main()

    assert caught.value.code == 2


def test_cli_rejects_conflicting_one_shot_actions(monkeypatch):
    monkeypatch.setattr(
        sys,
        "argv",
        ["run_live_trader.py", "--mock", "--snapshot-only", "--liquidate"],
    )

    with pytest.raises(SystemExit) as caught:
        trader_main()

    assert caught.value.code == 2


def test_direct_live_trading_requires_complete_paper_system_before_broker(
    monkeypatch,
):
    monkeypatch.setattr(sys, "argv", ["run_live_trader.py", "--live"])
    monkeypatch.setattr(
        "run_live_trader._assert_real_system_ready",
        lambda: (_ for _ in ()).throw(PermissionError("PAPER incomplete")),
    )
    monkeypatch.setattr(
        "run_live_trader.LiveTrader",
        lambda *args, **kwargs: pytest.fail("broker must not initialize"),
    )

    with pytest.raises(PermissionError, match="PAPER incomplete"):
        trader_main()


def test_live_snapshot_and_emergency_liquidation_keep_separate_safety_paths(
    monkeypatch,
):
    source = Path("run_live_trader.py").read_text(encoding="utf-8")
    assert "args.live and not args.snapshot_only and not args.liquidate" in source


def test_live_scheduler_requires_full_system_gate_before_legacy_kpi_gate():
    batch = Path("run_scheduler.bat").read_text(encoding="utf-8")
    completion = (
        "core.analytics.system_readiness --require-complete "
        "--for-real-activation"
    )
    legacy = "core.analytics.trading_kpis --target REAL"
    assert completion in batch
    assert batch.index(completion) < batch.index(legacy)


def test_mock_mode_is_safe_default_even_with_real_marker(monkeypatch):
    _credential_env(monkeypatch)
    monkeypatch.setenv("KIS_ENV", "real")
    monkeypatch.setenv("ALLOW_LIVE_ORDER", "false")
    monkeypatch.setattr("core.broker.kis_api.mojito.KoreaInvestment", DummyKoreaInvestment)
    assert KisBroker().is_mock is True


def test_kis_error_redaction_removes_account_and_credentials():
    message = (
        "500 for https://example.test/orders?CANO=12345678&ACNT_PRDT_CD=01&"
        "appKey=secret-key&authorization=secret-token"
    )

    redacted = redact_sensitive_text(message)

    assert "12345678" not in redacted
    assert "secret-key" not in redacted
    assert "secret-token" not in redacted
    assert "CANO=***" in redacted


def test_kis_safe_error_message_masks_instance_secrets():
    broker = object.__new__(KisBroker)
    broker.key = "app-key"
    broker.secret = "app-secret"
    broker.broker = type("Client", (), {
        "access_token": "access-token",
        "acc_no_prefix": "12345678",
    })()

    message = broker._safe_error_message(
        RuntimeError("app-key app-secret access-token 12345678-01")
    )

    assert message == "*** *** *** ***-01"


def test_telegram_uses_timeout_and_masks_token_on_failure(monkeypatch, capsys):
    bot = object.__new__(TelegramBot)
    bot.token = "sensitive-bot-token"
    bot.chat_id = "chat-id"
    captured = {}

    def fail(url, **kwargs):
        captured.update({"url": url, **kwargs})
        raise RuntimeError(f"failed at {url}")

    monkeypatch.setattr("core.utils.telegram_bot.requests.post", fail)

    bot.send_message("test")

    output = capsys.readouterr().out
    assert captured["timeout"] == 10
    assert "sensitive-bot-token" not in output
    assert "/bot***/sendMessage" in output


def test_daily_order_http_error_does_not_chain_raw_account_details():
    broker = object.__new__(KisBroker)
    broker.key = "app-key"
    broker.secret = "app-secret"
    broker.is_mock = True
    broker.broker = type("Client", (), {
        "base_url": "https://example.test",
        "access_token": "access-token",
        "acc_no_prefix": "12345678",
        "acc_no_postfix": "01",
    })()

    def fail_request(*args, **kwargs):
        response = requests.Response()
        response.status_code = 500
        response.url = "https://example.test/orders?CANO=12345678&ACNT_PRDT_CD=01"
        raise requests.HTTPError(
            f"500 Server Error for url: {response.url}", response=response
        )

    broker._safe_request = fail_request

    with pytest.raises(BrokerResponseError) as caught:
        broker.fetch_daily_orders(datetime.date(2026, 7, 21))

    assert "12345678" not in str(caught.value)
    assert "CANO=***" in str(caught.value)
    assert caught.value.__cause__ is None


def test_daily_order_query_follows_mock_f_continuation_pages():
    broker = object.__new__(KisBroker)
    broker.key = "app-key"
    broker.secret = "app-secret"
    broker.is_mock = True
    broker.broker = type("Client", (), {
        "base_url": "https://example.test",
        "access_token": "access-token",
        "acc_no_prefix": "12345678",
        "acc_no_postfix": "01",
    })()
    calls = []

    class Response:
        def __init__(self, payload, continuation):
            self._payload = payload
            self.headers = {"tr_cont": continuation}

        def json(self):
            return self._payload

    responses = [
        Response(
            {
                "rt_cd": "0",
                "output1": [{"odno": "1"}],
                "ctx_area_fk100": "next-fk",
                "ctx_area_nk100": "next-nk",
            },
            "F",
        ),
        Response({"rt_cd": "0", "output1": [{"odno": "2"}]}, ""),
    ]

    def request(*args, **kwargs):
        calls.append({
            "headers": dict(kwargs["headers"]),
            "params": dict(kwargs["params"]),
        })
        return responses.pop(0)

    broker._safe_request = request

    rows = broker.fetch_daily_orders(datetime.date(2026, 7, 9))

    assert [row["odno"] for row in rows] == ["1", "2"]
    assert calls[1]["headers"]["tr_cont"] == "N"
    assert calls[1]["params"]["CTX_AREA_FK100"] == "next-fk"
    assert calls[1]["params"]["CTX_AREA_NK100"] == "next-nk"


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
    masked_account = "***1234-01"

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


def test_scheduler_dry_run_premarket_keeps_dry_run_scope(monkeypatch):
    captured = {}
    monkeypatch.setattr(
        scheduler.subprocess,
        "run",
        lambda cmd, **kwargs: captured.update(cmd=cmd) or type(
            "R", (), {"returncode": 0}
        )(),
    )

    scheduler.run_command(mode="premarket", live=False, dry_run=True)

    assert captured["cmd"][-2:] == ["--dry-run", "--premarket"]


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


def test_scheduler_treats_busy_trader_cycle_as_safe_skip(monkeypatch):
    monkeypatch.setattr(
        scheduler.subprocess,
        "run",
        lambda *args, **kwargs: type("R", (), {"returncode": 2})(),
    )

    assert scheduler.run_command(mode="intraday", dry_run=False) is False


def test_scheduler_labels_candidate_suppression_separately_from_global_pause():
    assert scheduler.operational_status_label("ORDER_SUPPRESSION") == (
        "후보별 주문 안전차단 (ORDER_SUPPRESSION)"
    )
    assert scheduler.operational_status_label("ORDER_RECONCILIATION") == (
        "미정산 주문 정산 중·전체 신규주문 일시정지 (ORDER_RECONCILIATION)"
    )
    assert scheduler.SUPPRESSION_REASON_LABELS["AMBIGUOUS_RESULT_SAME_DAY"] == (
        "브로커 응답 불확실·당일 재시도 금지"
    )


def test_scheduler_eod_report_passes_mode_and_date(tmp_path, monkeypatch):
    captured = {}
    monkeypatch.setattr(scheduler, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        scheduler.subprocess,
        "run",
        lambda cmd, **kwargs: captured.update(cmd=cmd) or type("R", (), {"returncode": 0})(),
    )

    scheduler.run_end_of_day_report(datetime.date(2026, 7, 20), "PAPER")

    assert "core.analytics.trading_performance" in captured["cmd"]
    assert captured["cmd"][-3:] == ["PAPER", "--date", "2026-07-20"]
    status = json.loads(
        (tmp_path / "logs/paper/eod_report_status.json").read_text(encoding="utf-8")
    )
    assert status["status"] == "READY"
    assert status["report_date"] == "2026-07-20"


def test_scheduler_eod_failure_persists_actionable_diagnostic(tmp_path, monkeypatch):
    monkeypatch.setattr(scheduler, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        scheduler.subprocess,
        "run",
        lambda *args, **kwargs: type(
            "R",
            (),
            {"returncode": 1, "stdout": "", "stderr": "trace\nroot cause"},
        )(),
    )

    with pytest.raises(RuntimeError, match="root cause"):
        scheduler.run_end_of_day_report(datetime.date(2026, 7, 21), "PAPER")

    status = json.loads(
        (tmp_path / "logs/paper/eod_report_status.json").read_text(encoding="utf-8")
    )
    assert status["status"] == "FAILED"
    assert status["return_code"] == 1
    assert status["stderr_tail"].endswith("root cause")


def test_scheduler_backfills_oldest_missing_completed_paper_report(tmp_path):
    operational = tmp_path / "logs/paper/operational_health.jsonl"
    operational.parent.mkdir(parents=True, exist_ok=True)
    operational.write_text(
        "\n".join(
            json.dumps(
                {
                    "timestamp": f"{day}T15:20:00+09:00",
                    "operational_status": "NORMAL",
                }
            )
            for day in ("2026-07-20", "2026-07-21")
        )
        + "\n",
        encoding="utf-8",
    )
    daily = tmp_path / "reports/promotion/paper/daily"
    daily.mkdir(parents=True, exist_ok=True)
    (daily / "2026-07-20.json").write_text(
        json.dumps(
            {
                "report_date": "2026-07-20",
                "mode": "PAPER",
                "report_status": "FINAL",
                "validation": {"status": "READY"},
                "operations": {
                    "data_freshness_rate": 1.0,
                    "risk_check_coverage": 1.0,
                    "order_reconciliation_rate": 1.0,
                    "operational_integrity": 1.0,
                },
                "trading": {"open_order_count": 0},
            }
        ),
        encoding="utf-8",
    )
    now = datetime.datetime(2026, 7, 22, 9, 0)

    assert scheduler.pending_paper_eod_report_date(now, tmp_path) == (
        datetime.date(2026, 7, 21)
    )
    assert scheduler.due_end_of_day_report_date(now, "PAPER", tmp_path) == (
        datetime.date(2026, 7, 21)
    )


def test_scheduler_retries_failed_eod_after_bounded_delay():
    report_date = datetime.date(2026, 7, 21)
    first_attempt = datetime.datetime(2026, 7, 21, 15, 30)

    assert scheduler.should_attempt_daily_report(
        None, report_date, None, first_attempt
    ) is True
    assert scheduler.should_attempt_daily_report(
        None,
        report_date,
        first_attempt,
        first_attempt + datetime.timedelta(minutes=4, seconds=59),
    ) is False
    assert scheduler.should_attempt_daily_report(
        None,
        report_date,
        first_attempt,
        first_attempt + datetime.timedelta(minutes=5),
    ) is True
    assert scheduler.should_attempt_daily_report(
        report_date,
        report_date,
        first_attempt,
        first_attempt + datetime.timedelta(minutes=10),
    ) is False


def test_scheduler_instance_lock_rejects_concurrent_process(tmp_path):
    lock_path = tmp_path / "scheduler.instance.lock"
    first = scheduler.SchedulerInstanceLock(lock_path, "PAPER").acquire()
    try:
        with pytest.raises(scheduler.SchedulerAlreadyRunning):
            scheduler.SchedulerInstanceLock(lock_path, "PAPER").acquire()
    finally:
        first.release()

    replacement = scheduler.SchedulerInstanceLock(lock_path, "DRY_RUN").acquire()
    replacement.release()


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
    trader.strategy_name = "aggressive"
    trader.execution_venue = "PAPER"
    trader.broker = SafeBroker()
    trader.db = type("DB", (), {"fetch_one": lambda *a, **k: {"count": 2}})()

    with pytest.raises(RuntimeError, match="2 open orders"):
        trader._assert_no_unresolved_orders()


def test_unresolved_order_query_is_scoped_to_current_account():
    calls = []

    class DB:
        def fetch_one(self, query, params):
            calls.append((query, params))
            return {"count": 0}

    trader = object.__new__(LiveTrader)
    trader.strategy_name = "aggressive"
    trader.execution_venue = "PAPER"
    trader.broker = SafeBroker()
    trader.db = DB()

    trader._assert_no_unresolved_orders()

    query, params = calls[0]
    assert "execution_venue_code = %s" in query
    assert "account_scope = %s" in query
    assert params == ("aggressive", "PAPER", "***1234-01")


def test_daily_execution_ledger_health_requires_linked_matching_quantities():
    calls = []

    class DB:
        def fetch_one(self, query, params):
            calls.append((query, params))
            return {
                "filled_order_count": 3,
                "execution_linked_order_count": 2,
                "quantity_matched_order_count": 1,
            }

    trader = object.__new__(LiveTrader)
    trader.strategy_name = "aggressive"
    trader.execution_venue = "PAPER"
    trader.broker = SafeBroker()
    trader.db = DB()

    health = trader._daily_execution_ledger_health()

    assert health == {
        "status": "BLOCKED",
        "filled_order_count": 3,
        "execution_linked_order_count": 2,
        "quantity_matched_order_count": 1,
        "missing_execution_order_count": 1,
        "quantity_mismatch_order_count": 2,
        "execution_link_coverage": pytest.approx(2 / 3),
        "quantity_match_rate": pytest.approx(1 / 3),
    }
    query, params = calls[0]
    assert "execution_venue_code = %s" in query
    assert "account_scope = %s" in query
    assert "ABS(COALESCE(x.execution_qty, 0) - f.filled_qty)" in query
    assert params == ("aggressive", "PAPER", "***1234-01")


def test_daily_execution_ledger_health_is_ready_when_no_orders_exist():
    trader = object.__new__(LiveTrader)
    trader.strategy_name = "aggressive"
    trader.execution_venue = "PAPER"
    trader.broker = SafeBroker()
    trader.db = type("DB", (), {"fetch_one": lambda *a, **k: {}})()

    health = trader._daily_execution_ledger_health()

    assert health["status"] == "READY"
    assert health["execution_link_coverage"] == 1.0
    assert health["quantity_match_rate"] == 1.0


def test_open_order_reconciliation_queries_are_scoped():
    calls = []

    class DB:
        def fetch_all(self, query, params):
            calls.append((query, params))
            return []

    broker = SafeBroker()
    broker.is_mock = False
    trader = object.__new__(LiveTrader)
    trader.strategy_name = "aggressive"
    trader.execution_venue = "PAPER"
    trader.broker = broker
    trader.db = DB()

    trader._reconcile_open_orders()

    assert len(calls) == 2
    for query, params in calls:
        assert "execution_venue_code = %s" in query
        assert "account_scope = %s" in query
        assert params == ("aggressive", "PAPER", "***1234-01")


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
