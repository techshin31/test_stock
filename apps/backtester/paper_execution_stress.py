"""Run strategy experiments under execution outcomes observed in PAPER."""
from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from apps.backtester.config import build_db_config, load_env
from apps.backtester.paper_strategy_experiments import run_experiments, write_outputs
from core.analytics.execution_outcome_model import calibrate_execution_outcomes
from storage.postgres.connection import PostgreDB


KST = ZoneInfo("Asia/Seoul")
SCENARIO_CODES = ("STABILIZED_POSTERIOR_MEAN", "STABILIZED_WILSON_LOWER")
DECISION_VARIANTS = ("A_CURRENT", "R_TREND_REARM", "C_CAP10", "C_CAP08")
RISK_CONTROL_VARIANTS = ("C_CAP10", "C_CAP08")
RISK_THRESHOLDS = {
    "total_return_floor": -0.10,
    "max_drawdown_floor": -0.20,
    "annualized_turnover_ceiling": 30.0,
}


def _metric_view(metrics: dict) -> dict:
    return {
        key: metrics[key]
        for key in (
            "total_return",
            "max_drawdown",
            "annualized_turnover",
            "total_cost_ratio",
            "average_exposure",
            "hard_stop_count",
            "trailing_stop_count",
            "confirmed_reentries",
        )
    }


def _risk_control_gate(scenarios: dict[str, dict]) -> dict:
    checks = []
    robust_variants = []
    for variant in RISK_CONTROL_VARIANTS:
        scenario_rows = []
        for scenario, metrics in scenarios.items():
            values = metrics[variant]
            passed = (
                values["total_return"] >= RISK_THRESHOLDS["total_return_floor"]
                and values["max_drawdown"] >= RISK_THRESHOLDS["max_drawdown_floor"]
                and values["annualized_turnover"]
                <= RISK_THRESHOLDS["annualized_turnover_ceiling"]
            )
            scenario_rows.append({
                "scenario": scenario,
                "passed": passed,
                "total_return": values["total_return"],
                "max_drawdown": values["max_drawdown"],
                "annualized_turnover": values["annualized_turnover"],
            })
        all_pass = all(row["passed"] for row in scenario_rows)
        if all_pass:
            robust_variants.append(variant)
        checks.append({
            "variant": variant,
            "all_scenarios_pass": all_pass,
            "scenario_checks": scenario_rows,
        })
    return {
        "thresholds": dict(RISK_THRESHOLDS),
        "checks": checks,
        "robust_variants": robust_variants,
        "fallback_available": bool(robust_variants),
        "production_rule_changed": False,
        "manual_review_required": True,
    }


def run_stress_suite(
    db: PostgreDB,
    *,
    ledger_path: Path,
    ideal_metrics_path: Path,
    output_dir: Path,
) -> dict:
    orders = pd.read_csv(ledger_path, dtype={"symbol": "string"})
    calibration = calibrate_execution_outcomes(orders)
    ideal = json.loads(ideal_metrics_path.read_text(encoding="utf-8"))
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "execution_calibration.json").write_text(
        json.dumps(calibration, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    scenarios: dict[str, dict] = {
        "IDEAL_FULL_FILL": {
            code: _metric_view(ideal["summary"][code]) for code in DECISION_VARIANTS
        }
    }
    for scenario_code in SCENARIO_CODES:
        calibrated = calibration["scenarios"][scenario_code]
        execution_model = {
            "code": scenario_code,
            "application": calibrated["application"],
            "buy_fill_fraction": float(calibrated["buy_fill_fraction"]),
            "sell_fill_fraction": float(calibrated["sell_fill_fraction"]),
        }
        result, frames = run_experiments(
            db, pass_only=True, execution_model=execution_model
        )
        write_outputs(result, frames, output_dir / scenario_code.lower())
        scenarios[scenario_code] = {
            code: _metric_view(result["summary"][code]) for code in DECISION_VARIANTS
        }

    candidate = "R_TREND_REARM"
    baseline = "A_CURRENT"
    scenario_checks = []
    for scenario_code, metrics in scenarios.items():
        candidate_metrics = metrics[candidate]
        baseline_metrics = metrics[baseline]
        return_improves = (
            candidate_metrics["total_return"] > baseline_metrics["total_return"]
        )
        drawdown_improves = (
            candidate_metrics["max_drawdown"]
            > baseline_metrics["max_drawdown"]
        )
        turnover_improves = (
            candidate_metrics["annualized_turnover"]
            < baseline_metrics["annualized_turnover"]
        )
        scenario_checks.append(
            {
                "scenario": scenario_code,
                "return_improves": return_improves,
                "drawdown_improves": drawdown_improves,
                "turnover_improves": turnover_improves,
                "passed": return_improves and drawdown_improves and turnover_improves,
                "candidate_return": candidate_metrics["total_return"],
                "baseline_return": baseline_metrics["total_return"],
                "candidate_mdd": candidate_metrics["max_drawdown"],
                "baseline_mdd": baseline_metrics["max_drawdown"],
                "candidate_turnover": candidate_metrics["annualized_turnover"],
                "baseline_turnover": baseline_metrics["annualized_turnover"],
            }
        )
    sample_ready = calibration["calibration_status"] == "READY"
    all_scenarios_pass = all(row["passed"] for row in scenario_checks)
    risk_control_gate = _risk_control_gate(scenarios)
    blockers = []
    if not sample_ready:
        blockers.append(
            "post-hardening BUY and SELL samples have not each reached 30 orders"
        )
    if not all_scenarios_pass:
        blockers.append(
            "trend-rearm does not improve return, drawdown, and turnover in every execution scenario"
        )
    summary = {
        "schema_version": 1,
        "generated_at": dt.datetime.now(KST).isoformat(timespec="seconds"),
        "mode": "PAPER",
        "observe_only": True,
        "production_rule_changed": False,
        "ledger_evidence": {
            "order_count": int(len(orders)),
            "latest_order_at": (
                str(orders["created_at"].dropna().max())
                if "created_at" in orders and not orders["created_at"].dropna().empty
                else None
            ),
        },
        "calibration_status": calibration["calibration_status"],
        "execution_samples": calibration["stabilized"],
        "scenarios": scenarios,
        "candidate": candidate,
        "baseline": baseline,
        "scenario_checks": scenario_checks,
        "risk_control_gate": risk_control_gate,
        "promotion_gate": {
            "ready": sample_ready and all_scenarios_pass,
            "minimum_side_sample": calibration["minimum_side_sample"],
            "sample_ready": sample_ready,
            "all_execution_scenarios_pass": all_scenarios_pass,
            "manual_review_required": True,
            "blockers": blockers,
        },
        "sources": [str(ledger_path), str(ideal_metrics_path)],
    }
    (output_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    pd.DataFrame(scenario_checks).to_csv(
        output_dir / "scenario_checks.csv", index=False, encoding="utf-8-sig"
    )
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Stress PAPER strategy candidates with observed execution outcomes."
    )
    parser.add_argument(
        "--ledger",
        default="reports/analysis/paper_ledger_latest/order_lifecycle.csv",
    )
    parser.add_argument(
        "--ideal-metrics",
        default="reports/analysis/paper_reentry_experiments/pass_only/metrics.json",
    )
    parser.add_argument(
        "--output-dir",
        default="reports/analysis/paper_execution_stress/latest",
    )
    args = parser.parse_args()
    load_env()
    db = PostgreDB(build_db_config())
    try:
        result = run_stress_suite(
            db,
            ledger_path=Path(args.ledger),
            ideal_metrics_path=Path(args.ideal_metrics),
            output_dir=Path(args.output_dir),
        )
    finally:
        db.close()
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
