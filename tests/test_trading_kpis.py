import json
from datetime import date, datetime, timedelta, timezone

from core.analytics.trading_kpis import (
    TradingKpiSnapshot,
    evaluate_promotion_gate,
    main,
    snapshot_from_operational_log,
    validate_paper_readiness_report,
)


def _snapshot(**overrides):
    values = {
        "as_of": date(2026, 7, 20),
        "observed_trading_days": 60,
        "scan_count": 1_000,
        "fresh_scan_count": 1_000,
        "risk_checks_total": 5_000,
        "risk_checks_completed": 5_000,
        "submitted_orders": 20,
        "reconciled_orders": 20,
        "critical_incidents": 0,
        "net_return": 0.05,
        "benchmark_return": 0.02,
        "max_drawdown": -0.08,
        "cost_drag": 0.01,
        "performance_validation_status": "READY",
    }
    values.update(overrides)
    return TradingKpiSnapshot(**values)


def test_dry_run_can_be_ready_for_paper_without_performance_metrics():
    decision = evaluate_promotion_gate(
        _snapshot(
            observed_trading_days=1,
            submitted_orders=0,
            reconciled_orders=0,
            net_return=None,
            benchmark_return=None,
            max_drawdown=None,
            cost_drag=None,
        ),
        "PAPER",
    )
    assert decision.ready is True
    assert decision.manual_approval_required is True


def test_real_gate_blocks_operational_and_performance_failures():
    decision = evaluate_promotion_gate(
        _snapshot(
            fresh_scan_count=990,
            risk_checks_completed=4_999,
            reconciled_orders=19,
            critical_incidents=1,
            net_return=0.01,
            benchmark_return=0.02,
            max_drawdown=-0.20,
            cost_drag=0.02,
        ),
        "REAL",
    )
    assert decision.ready is False
    assert len(decision.blockers) >= 7


def test_real_gate_reports_readiness_but_never_auto_approves_capital():
    decision = evaluate_promotion_gate(_snapshot(), "REAL")
    assert decision.ready is True
    assert decision.manual_approval_required is True
    assert decision.blockers == ()


def test_real_gate_blocks_uncertified_performance_even_when_metrics_pass():
    decision = evaluate_promotion_gate(
        _snapshot(performance_validation_status="BLOCKED"), "REAL"
    )
    assert decision.ready is False
    assert any("performance_validation_status" in row for row in decision.blockers)


def test_operational_log_uses_last_daily_order_state_without_double_counting(tmp_path):
    log_path = tmp_path / "health.jsonl"
    rows = [
        {
            "timestamp": "2026-07-20T09:01:00+09:00",
            "operational_status": "NORMAL",
            "data_health": {
                "expected_count": 2,
                "fresh_count": 2,
                "risk_checks_total": 1,
                "risk_checks_completed": 1,
            },
            "actual_orders": {"buy_filled": 0, "sell_filled": 0, "open": 1, "rejected": 0},
        },
        {
            "timestamp": "2026-07-20T15:20:00+09:00",
            "operational_status": "NORMAL",
            "data_health": {
                "expected_count": 2,
                "fresh_count": 2,
                "risk_checks_total": 1,
                "risk_checks_completed": 1,
            },
            "actual_orders": {"buy_filled": 1, "sell_filled": 0, "open": 0, "rejected": 0},
        },
    ]
    log_path.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")

    snapshot = snapshot_from_operational_log(log_path)

    assert snapshot.observed_trading_days == 1
    assert snapshot.submitted_orders == 1
    assert snapshot.reconciled_orders == 1
    assert snapshot.data_freshness_rate == 1.0
    assert snapshot.risk_check_coverage == 1.0


def test_cli_allows_one_completed_dry_run_day(tmp_path):
    log_path = tmp_path / "health.jsonl"
    log_path.write_text(
        json.dumps({
            "timestamp": "2026-07-20T15:20:00+09:00",
            "operational_status": "NORMAL",
            "data_health": {"expected_count": 1, "fresh_count": 1},
            "actual_orders": {},
        }),
        encoding="utf-8",
    )
    assert main([
        "--target", "PAPER",
        "--operational-log", str(log_path),
    ]) == 0


def test_paper_readiness_requires_final_latest_eod_report():
    kst = timezone(timedelta(hours=9))
    payload = {
        "mode": "DRY_RUN",
        "report_status": "PRELIMINARY_INTRADAY",
        "report_date": "2026-07-20",
        "promotion": {"target_mode": "PAPER", "ready": True},
    }

    blockers = validate_paper_readiness_report(
        payload,
        now=datetime(2026, 7, 21, 8, 40, tzinfo=kst),
    )
    assert blockers == ("DRY_RUN EOD report_status must be FINAL",)

    payload["report_status"] = "FINAL"
    assert validate_paper_readiness_report(
        payload,
        now=datetime(2026, 7, 21, 8, 40, tzinfo=kst),
    ) == ()
