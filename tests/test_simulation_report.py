import datetime as dt
import json

from core.execution.simulation_report import (
    build_simulation_report,
    write_simulation_report,
)


def _seed(log_dir, report_date):
    log_dir.mkdir(parents=True)
    (log_dir / "sim_account.json").write_text(json.dumps({
        "cash": 400_000,
        "positions": {
            "005930": {"qty": 100, "avg_price": 900, "current_price": 1000}
        },
        "orders": {
            "one": {
                "symbol": "005930", "side": "BUY", "qty": 100,
                "status": "FILLED", "commission": 10, "tax": 0,
                "slippage_cost": 20,
                "created_at": f"{report_date.isoformat()}T09:01:00",
            }
        },
    }), encoding="utf-8")
    (log_dir / "decision_state.json").write_text(json.dumps({
        "updated_at": f"{report_date.isoformat()}T15:20:00",
        "decisions": [{"target_weight": 0.2}],
    }), encoding="utf-8")
    (log_dir / "account_history.csv").write_text(
        "timestamp,mode,cash,total_asset,position_count\n"
        f"{report_date.isoformat()}T09:00:00,SIMULATE,500000,500000,0\n"
        f"{report_date.isoformat()}T15:20:00,SIMULATE,400000,500000,1\n",
        encoding="utf-8",
    )


def test_simulation_report_passes_and_writes_both_formats(tmp_path):
    report_date = dt.date(2026, 7, 13)
    log_dir = tmp_path / "simulate"
    _seed(log_dir, report_date)

    report = write_simulation_report(log_dir, report_date)

    assert report["health"] == "PASS"
    assert report["account"]["position_count"] == 1
    assert report["trading"]["buy_count"] == 1
    assert (log_dir / "reports" / "2026-07-13.json").exists()
    assert (log_dir / "reports" / "2026-07-13.md").exists()


def test_simulation_report_allows_many_positions_but_fails_total_weight_limit(tmp_path):
    report_date = dt.date(2026, 7, 13)
    log_dir = tmp_path / "simulate"
    _seed(log_dir, report_date)
    account = json.loads((log_dir / "sim_account.json").read_text(encoding="utf-8"))
    account["positions"].update({
        str(index): {"qty": 1, "avg_price": 1, "current_price": 1}
        for index in range(6)
    })
    (log_dir / "sim_account.json").write_text(json.dumps(account), encoding="utf-8")
    decision = json.loads((log_dir / "decision_state.json").read_text(encoding="utf-8"))
    decision["decisions"] = [{"target_weight": 0.5}, {"target_weight": 0.5}]
    (log_dir / "decision_state.json").write_text(json.dumps(decision), encoding="utf-8")

    report = build_simulation_report(log_dir, report_date)

    assert report["health"] == "FAIL"
    failed = {row["name"] for row in report["checks"] if not row["passed"]}
    assert "position_limit" not in failed
    assert "target_weight_limit" in failed
