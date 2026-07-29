import json
from datetime import date, datetime, timedelta, timezone

from core.analytics.trading_kpis import (
    PromotionPolicy,
    TradingKpiSnapshot,
    evaluate_promotion_gate,
    extract_critical_incidents,
    main,
    promotion_snapshot_from_operational_log,
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


def test_order_suppression_counts_as_critical_incident(tmp_path):
    log_path = tmp_path / "health.jsonl"
    log_path.write_text(
        json.dumps({
            "timestamp": "2026-07-20T10:00:00+09:00",
            "operational_status": "ORDER_SUPPRESSION",
            "data_health": {
                "expected_count": 1,
                "fresh_count": 1,
                "risk_checks_total": 1,
                "risk_checks_completed": 1,
            },
            "actual_orders": {},
        }),
        encoding="utf-8",
    )

    snapshot = snapshot_from_operational_log(log_path)

    assert snapshot.critical_incidents == 1


def test_incident_report_includes_sanitized_broker_cause_only(tmp_path):
    log_path = tmp_path / "health.jsonl"
    log_path.write_text(
        json.dumps({
            "timestamp": "2026-07-20T10:00:00+09:00",
            "operational_status": "ORDER_SUPPRESSION",
            "data_health": {
                "order_suppressions": {
                    "total": 1,
                    "by_reason": {"AMBIGUOUS_RESULT_SAME_DAY": 1},
                    "incident_codes": {"BROKER_HTTP_500": 1},
                },
            },
            "actual_orders": {},
        }),
        encoding="utf-8",
    )

    incidents = extract_critical_incidents(log_path)

    assert "BROKER_HTTP_500" in incidents[0]["summary"]
    assert "://" not in incidents[0]["summary"]
    assert "secret" not in incidents[0]["summary"].lower()


def test_incident_report_redacts_raw_broker_transport_error(tmp_path):
    log_path = tmp_path / "health.jsonl"
    log_path.write_text(
        json.dumps({
            "timestamp": "2026-07-20T10:00:00+09:00",
            "operational_status": "ERROR",
            "last_error": (
                "500 Server Error for url: "
                "https://openapivts.koreainvestment.com/order?"
                "CANO=12345678&appkey=secret-value"
            ),
            "actual_orders": {},
        }),
        encoding="utf-8",
    )

    incident = extract_critical_incidents(log_path)[0]

    assert incident["summary"] == "BROKER_HTTP_500"
    assert incident["last_error"] == "BROKER_HTTP_500"
    assert "openapivts" not in json.dumps(incident).lower()
    assert "12345678" not in json.dumps(incident)
    assert "secret-value" not in json.dumps(incident)


def test_repeated_critical_status_counts_incident_episodes(tmp_path):
    log_path = tmp_path / "health.jsonl"
    rows = []
    for minute, status in enumerate([
        "ORDER_SUPPRESSION",
        "ORDER_SUPPRESSION",
        "NORMAL",
        "ORDER_SUPPRESSION",
    ]):
        rows.append(json.dumps({
            "timestamp": f"2026-07-20T10:0{minute}:00+09:00",
            "operational_status": status,
            "data_health": {
                "expected_count": 1,
                "fresh_count": 1,
                "risk_checks_total": 1,
                "risk_checks_completed": 1,
            },
            "actual_orders": {},
        }))
    log_path.write_text("\n".join(rows), encoding="utf-8")

    snapshot = snapshot_from_operational_log(log_path)

    assert snapshot.critical_incidents == 2
    assert snapshot.data_freshness_rate == 1.0
    assert snapshot.risk_check_coverage == 1.0


def test_snapshot_can_be_limited_to_one_operational_day(tmp_path):
    log_path = tmp_path / "health.jsonl"
    rows = [
        {
            "timestamp": "2026-07-21T15:00:00+09:00",
            "operational_status": "NORMAL",
            "data_health": {
                "expected_count": 2,
                "fresh_count": 1,
                "risk_checks_total": 1,
                "risk_checks_completed": 1,
            },
            "actual_orders": {},
        },
        {
            "timestamp": "2026-07-22T15:00:00+09:00",
            "operational_status": "NORMAL",
            "data_health": {
                "expected_count": 2,
                "fresh_count": 2,
                "risk_checks_total": 1,
                "risk_checks_completed": 1,
            },
            "actual_orders": {},
        },
    ]
    log_path.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")

    cumulative = snapshot_from_operational_log(log_path)
    daily = snapshot_from_operational_log(
        log_path,
        start_date=date(2026, 7, 22),
        through_date=date(2026, 7, 22),
    )

    assert cumulative.data_freshness_rate == 0.5
    assert daily.data_freshness_rate == 1.0
    assert daily.observed_trading_days == 1


def test_real_promotion_uses_latest_clean_completed_session_window(tmp_path):
    log_path = tmp_path / "health.jsonl"
    rows = []
    for day, status in [
        ("2026-07-20", "ORDER_SUPPRESSION"),
        ("2026-07-21", "NORMAL"),
        ("2026-07-22", "NORMAL"),
    ]:
        rows.append(json.dumps({
            "timestamp": f"{day}T15:20:00+09:00",
            "operational_status": status,
            "data_health": {
                "expected_count": 1,
                "fresh_count": 1,
                "risk_checks_total": 1,
                "risk_checks_completed": 1,
            },
            "actual_orders": {},
        }))
    log_path.write_text("\n".join(rows), encoding="utf-8")

    snapshot, window = promotion_snapshot_from_operational_log(
        log_path,
        "REAL",
        policy=PromotionPolicy(paper_days=2),
    )

    assert snapshot.observed_trading_days == 2
    assert snapshot.critical_incidents == 0
    assert window.to_dict() == {
        "target_mode": "REAL",
        "required_completed_sessions": 2,
        "available_completed_sessions": 3,
        "selected_completed_sessions": 2,
        "start_date": "2026-07-21",
        "end_date": "2026-07-22",
    }


def test_real_promotion_window_keeps_recent_incident_as_a_blocker(tmp_path):
    log_path = tmp_path / "health.jsonl"
    rows = []
    for day, status in [
        ("2026-07-20", "ORDER_SUPPRESSION"),
        ("2026-07-21", "NORMAL"),
    ]:
        rows.append(json.dumps({
            "timestamp": f"{day}T15:20:00+09:00",
            "operational_status": status,
            "data_health": {
                "expected_count": 1,
                "fresh_count": 1,
                "risk_checks_total": 1,
                "risk_checks_completed": 1,
            },
            "actual_orders": {},
        }))
    log_path.write_text("\n".join(rows), encoding="utf-8")

    snapshot, window = promotion_snapshot_from_operational_log(
        log_path,
        "REAL",
        policy=PromotionPolicy(paper_days=2),
    )

    assert snapshot.critical_incidents == 1
    assert window.start_date == date(2026, 7, 20)


def test_promotion_window_excludes_an_incomplete_current_session(tmp_path):
    log_path = tmp_path / "health.jsonl"
    rows = []
    for timestamp in ["2026-07-28T15:20:00+09:00", "2026-07-29T09:30:00+09:00"]:
        rows.append({
            "timestamp": timestamp,
            "operational_status": "NORMAL",
            "data_health": {
                "expected_count": 1,
                "fresh_count": 1,
                "risk_checks_total": 1,
                "risk_checks_completed": 1,
            },
            "actual_orders": {},
        })
    log_path.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")

    snapshot, window = promotion_snapshot_from_operational_log(
        log_path,
        "REAL",
        policy=PromotionPolicy(paper_days=2),
        as_of=datetime(2026, 7, 29, 9, 31, tzinfo=timezone(timedelta(hours=9))),
    )

    assert snapshot.observed_trading_days == 1
    assert window.end_date == date(2026, 7, 28)


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
