import datetime as dt
import json

import pandas as pd
import pytest

from core.analytics.trading_performance import (
    BASELINE_CONFIRMATION,
    build_end_of_day_report,
    calculate_performance,
    check_baseline,
    initialize_baseline,
    load_account_snapshots,
    write_end_of_day_report,
)


def _snapshot(timestamp, total_asset, *, account="1234****", mode="PAPER"):
    return {
        "timestamp": dt.datetime.fromisoformat(timestamp),
        "mode": mode,
        "strategy": "aggressive",
        "account_scope": account,
        "cash": 500.0,
        "total_asset": float(total_asset),
        "position_count": 1,
    }


def _write_jsonl(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(json.dumps(row, default=str) for row in rows) + "\n",
        encoding="utf-8",
    )


def _operational_row(timestamp, *, orders=None):
    return {
        "timestamp": timestamp,
        "operational_status": "NORMAL",
        "data_health": {
            "expected_count": 2,
            "fresh_count": 2,
            "stale_count": 0,
            "missing_count": 0,
            "risk_checks_total": 1,
            "risk_checks_completed": 1,
        },
        "actual_orders": orders or {},
    }


class FakeDB:
    def fetch_all(self, query, params):
        if "GROUP BY o.order_status_code" in query:
            return [{"order_status_code": "FILLED", "count": 1}]
        return [{
            "order_side_code": "BUY",
            "amount": 100_000.0,
            "commission": 0.0,
            "tax": 0.0,
            "slippage": 20.0,
        }]


def test_load_account_snapshots_rejects_legacy_unscoped_rows(tmp_path):
    path = tmp_path / "snapshots.jsonl"
    _write_jsonl(path, [{
        "timestamp": "2026-07-20T09:00:00+09:00",
        "mode": "PAPER",
        "strategy": "aggressive",
        "account_scope": "UNKNOWN",
        "cash": 1_000,
        "total_asset": 1_000,
    }])

    with pytest.raises(ValueError, match="unscoped"):
        load_account_snapshots(
            path, mode="PAPER", through_date=dt.date(2026, 7, 20)
        )


def test_calculate_performance_adjusts_declared_external_cash_flow():
    baseline = {
        "baseline_timestamp": "2026-07-20T08:30:00+09:00",
        "baseline_total_asset": 1_000.0,
        "benchmark_date": "2026-07-17",
        "benchmark_close": 100.0,
        "account_scope": "1234****",
        "strategy": "aggressive",
    }
    rows = [
        _snapshot("2026-07-20T15:20:00+09:00", 1_100),
        _snapshot("2026-07-21T15:20:00+09:00", 1_211),
    ]
    metrics, trend, errors = calculate_performance(
        rows,
        baseline=baseline,
        benchmark_closes={
            dt.date(2026, 7, 17): 100.0,
            dt.date(2026, 7, 20): 102.0,
            dt.date(2026, 7, 21): 105.0,
        },
        cash_flows=[{
            "date": dt.date(2026, 7, 21), "amount": 100.0, "reason": "deposit"
        }],
        total_costs=11.1,
    )

    assert errors == []
    assert metrics["net_return"] == pytest.approx(0.111)
    assert metrics["benchmark_return"] == pytest.approx(0.05)
    assert metrics["cost_drag"] == pytest.approx(0.0111)
    assert trend[1]["daily_return"] == pytest.approx(0.01)


def test_dry_run_report_is_operational_only_and_ready_after_one_day(tmp_path):
    log_dir = tmp_path / "logs" / "dry_run"
    _write_jsonl(
        log_dir / "operational_health.jsonl",
        [_operational_row("2026-07-20T15:20:00+09:00")],
    )

    report = build_end_of_day_report(
        mode="DRY_RUN",
        report_date=dt.date(2026, 7, 20),
        log_dir=log_dir,
        promotion_dir=tmp_path / "reports" / "promotion",
    )

    assert report["performance"]["validation_status"] == "NOT_APPLICABLE"
    assert report["promotion"]["target_mode"] == "PAPER"
    assert report["promotion"]["ready"] is True
    assert report["operations"]["observed_trading_days"] == 1


def test_paper_report_writes_flat_real_readiness_snapshot(tmp_path):
    report_date = dt.date(2026, 7, 20)
    log_dir = tmp_path / "logs" / "paper"
    promotion_dir = tmp_path / "reports" / "promotion"
    paper_dir = promotion_dir / "paper"
    _write_jsonl(
        log_dir / "operational_health.jsonl",
        [_operational_row("2026-07-20T15:20:00+09:00")],
    )
    _write_jsonl(log_dir / "account_snapshots.jsonl", [
        {
            **_snapshot("2026-07-20T08:30:00+09:00", 1_000),
            "timestamp": "2026-07-20T08:30:00+09:00",
        },
        {
            **_snapshot("2026-07-20T15:20:00+09:00", 1_020),
            "timestamp": "2026-07-20T15:20:00+09:00",
        },
    ])
    paper_dir.mkdir(parents=True)
    (paper_dir / "baseline.json").write_text(json.dumps({
        "baseline_timestamp": "2026-07-20T08:30:00+09:00",
        "baseline_total_asset": 1_000.0,
        "benchmark_date": "2026-07-17",
        "benchmark_close": 100.0,
        "mode": "PAPER",
        "strategy": "aggressive",
        "account_scope": "1234****",
    }), encoding="utf-8")
    (paper_dir / "cash_flows.json").write_text(json.dumps({
        "account_scope": "1234****", "entries": []
    }), encoding="utf-8")

    def benchmark_loader(start, end):
        return pd.Series(
            [100.0, 101.0],
            index=pd.to_datetime(["2026-07-17", "2026-07-20"]),
        )

    report = write_end_of_day_report(
        mode="PAPER",
        report_date=report_date,
        log_dir=log_dir,
        promotion_dir=promotion_dir,
        benchmark_loader=benchmark_loader,
        db=FakeDB(),
        as_of=dt.datetime(2026, 7, 20, 16, 0, tzinfo=dt.timezone(dt.timedelta(hours=9))),
    )
    readiness = json.loads(
        (promotion_dir / "real_readiness.json").read_text(encoding="utf-8")
    )

    assert report["validation"]["status"] == "READY"
    assert report["performance"]["net_return"] == pytest.approx(0.02)
    assert readiness["validation_status"] == "READY"
    assert readiness["net_return"] == pytest.approx(0.02)
    assert (paper_dir / "daily" / "2026-07-20.md").exists()


def test_initialize_baseline_requires_same_day_scoped_snapshot(tmp_path):
    report_date = dt.date(2026, 7, 20)
    log_dir = tmp_path / "logs" / "paper"
    promotion_dir = tmp_path / "reports" / "promotion"
    _write_jsonl(log_dir / "account_snapshots.jsonl", [{
        **_snapshot("2026-07-20T08:30:00+09:00", 1_000),
        "timestamp": "2026-07-20T08:30:00+09:00",
    }])

    def benchmark_loader(start, end):
        return pd.Series(
            [2_900.0], index=pd.to_datetime(["2026-07-16"])
        )

    baseline = initialize_baseline(
        mode="PAPER",
        report_date=report_date,
        log_dir=log_dir,
        promotion_dir=promotion_dir,
        confirmation=BASELINE_CONFIRMATION,
        benchmark_loader=benchmark_loader,
    )

    assert baseline["account_scope"] == "1234****"
    assert baseline["benchmark_date"] == "2026-07-16"
    with pytest.raises(FileExistsError):
        initialize_baseline(
            mode="PAPER",
            report_date=report_date,
            log_dir=log_dir,
            promotion_dir=promotion_dir,
            confirmation=BASELINE_CONFIRMATION,
            benchmark_loader=benchmark_loader,
        )


def test_baseline_check_rejects_current_account_mismatch(tmp_path):
    report_date = dt.date(2026, 7, 20)
    promotion_dir = tmp_path / "reports" / "promotion"
    paper_dir = promotion_dir / "paper"
    paper_dir.mkdir(parents=True)
    (paper_dir / "baseline.json").write_text(json.dumps({
        "mode": "PAPER",
        "account_scope": "BASE****",
        "strategy": "aggressive",
        "baseline_timestamp": "2026-07-20T08:30:00+09:00",
        "baseline_total_asset": 1_000,
        "benchmark_date": "2026-07-16",
        "benchmark_close": 2_900,
    }), encoding="utf-8")
    (paper_dir / "cash_flows.json").write_text(json.dumps({
        "account_scope": "BASE****", "entries": []
    }), encoding="utf-8")
    log_dir = tmp_path / "logs" / "paper"
    _write_jsonl(log_dir / "account_snapshots.jsonl", [{
        **_snapshot("2026-07-20T09:00:00+09:00", 1_000, account="OTHER****"),
        "timestamp": "2026-07-20T09:00:00+09:00",
    }])

    with pytest.raises(ValueError, match="does not match"):
        check_baseline(
            "PAPER",
            promotion_dir,
            log_dir=log_dir,
            through_date=report_date,
            require_latest_snapshot=True,
        )
