"""Reproducible research comparison for two versioned FA score models.

The output is intentionally research-only.  It evaluates historical monthly
allocation effects and never publishes a universe or submits an order.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path

from apps.backtester.config import build_db_config, load_env
from apps.backtester.fa_weighting_research import run_research
from apps.worker.fa_contract import (
    PAPER_TRADING_MODEL_VERSION,
    REAL_TRADING_MODEL_VERSION,
)
from storage.postgres.connection import PostgreDB


_COMPARISON_METRICS = (
    "months",
    "total_return",
    "cagr",
    "annual_volatility",
    "sharpe_zero_rf",
    "max_drawdown",
    "average_monthly_turnover",
    "total_cost_ratio",
)


def _metric_delta(baseline: dict, candidate: dict) -> dict[str, float]:
    return {
        metric: float(candidate[metric]) - float(baseline[metric])
        for metric in _COMPARISON_METRICS
    }


def _promotion_gate(baseline_direct: dict, candidate_direct: dict) -> dict:
    """Return an explicit research gate; it never grants order permission."""
    checks = {
        "same_period_count": (
            candidate_direct["months"] == baseline_direct["months"]
        ),
        "sharpe_not_lower": (
            candidate_direct["sharpe_zero_rf"]
            >= baseline_direct["sharpe_zero_rf"]
        ),
        "drawdown_not_worse": (
            candidate_direct["max_drawdown"]
            >= baseline_direct["max_drawdown"]
        ),
    }
    blockers = [
        name for name, passed in checks.items() if not passed
    ]
    return {
        "ready_for_manual_review": not blockers,
        "order_permission": "DENIED_BY_DESIGN",
        "checks": checks,
        "blockers": blockers,
    }


def run_model_evaluation(
    db: PostgreDB,
    *,
    baseline_model_version: str = REAL_TRADING_MODEL_VERSION,
    candidate_model_version: str = PAPER_TRADING_MODEL_VERSION,
) -> dict:
    baseline, _ = run_research(db, model_version=baseline_model_version)
    candidate, _ = run_research(db, model_version=candidate_model_version)
    baseline_direct = baseline["summary"]["fa_direct"]
    candidate_direct = candidate["summary"]["fa_direct"]
    candidate_equal = candidate["summary"]["equal"]
    promotion_gate = _promotion_gate(baseline_direct, candidate_direct)
    return {
        "generated_at": dt.datetime.now().isoformat(timespec="seconds"),
        "status": "RESEARCH_ONLY_NOT_AN_ORDER_PERMISSION",
        "baseline_model_version": baseline_model_version,
        "candidate_model_version": candidate_model_version,
        "methodology": {
            "comparison": "FA-score-direct monthly allocation, same cost and exposure assumptions",
            "baseline_metadata": baseline["metadata"],
            "candidate_metadata": candidate["metadata"],
        },
        "baseline": baseline["summary"],
        "candidate": candidate["summary"],
        "fa_direct_delta_candidate_minus_baseline": _metric_delta(
            baseline_direct, candidate_direct
        ),
        "candidate_fa_direct_minus_equal": _metric_delta(
            candidate_equal, candidate_direct
        ),
        "interpretation": {
            "candidate_sharpe_not_lower": promotion_gate["checks"]["sharpe_not_lower"],
            "candidate_drawdown_not_worse": promotion_gate["checks"]["drawdown_not_worse"],
            "candidate_has_same_period_count": promotion_gate["checks"]["same_period_count"],
        },
        "promotion_gate": promotion_gate,
        "limitations": [
            "This is a historical research comparison, not a forecast or a return guarantee.",
            "It isolates monthly FA allocation and does not replay sector selection, intraday execution, or live TA timing.",
            "A PASS research result does not publish the candidate model or grant order permission.",
        ],
    }


def write_evaluation(result: dict, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "metrics.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    delta = result["fa_direct_delta_candidate_minus_baseline"]
    lines = [
        "# Point-in-time FA model evaluation",
        "",
        f"Generated: {result['generated_at']}",
        f"Status: {result['status']}",
        "",
        "| Metric | Candidate minus baseline |",
        "|---|---:|",
    ]
    for metric, value in delta.items():
        rendered = f"{value:+.2%}" if metric != "months" and metric != "sharpe_zero_rf" else f"{value:+.3f}"
        lines.append(f"| {metric} | {rendered} |")
    lines.extend(["", "## Guardrails", ""])
    gate = result["promotion_gate"]
    lines.append(
        f"- Manual-review readiness: {gate['ready_for_manual_review']}"
    )
    lines.append(f"- Order permission: {gate['order_permission']}")
    if gate["blockers"]:
        lines.append(f"- Blocking checks: {', '.join(gate['blockers'])}")
    lines.extend(f"- {item}" for item in result["limitations"])
    (output_dir / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline-model", default=REAL_TRADING_MODEL_VERSION)
    parser.add_argument("--candidate-model", default=PAPER_TRADING_MODEL_VERSION)
    parser.add_argument("--output-dir", default="reports/analysis/fa_model_evaluation")
    args = parser.parse_args()
    load_env()
    db = PostgreDB(build_db_config())
    try:
        result = run_model_evaluation(
            db,
            baseline_model_version=args.baseline_model,
            candidate_model_version=args.candidate_model,
        )
    finally:
        db.close()
    write_evaluation(result, Path(args.output_dir))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
