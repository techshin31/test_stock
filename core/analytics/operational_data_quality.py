"""Profile PAPER operational-log completeness without mutating trading state.

The trader already fails closed when market data is missing or stale.  This
module preserves that signal as a compact, inspectable evidence artifact so
historical gaps can be investigated without rewriting the original scans.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Iterable
from zoneinfo import ZoneInfo


KST = ZoneInfo("Asia/Seoul")
FRESHNESS_GATE = 0.995


def _parse_timestamp(value: object) -> dt.datetime | None:
    if not value:
        return None
    try:
        parsed = dt.datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=KST)
    return parsed.astimezone(KST)


def _rows(path: Path) -> tuple[list[dict], int]:
    rows: list[dict] = []
    parse_errors = 0
    if not path.exists():
        return rows, 0
    for line in path.read_text(encoding="utf-8-sig", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            parse_errors += 1
            continue
        if isinstance(payload, dict):
            rows.append(payload)
    return rows, parse_errors


def _normalise_tickers(values: object) -> list[str]:
    if not isinstance(values, list):
        return []
    return sorted({str(value).strip().upper() for value in values if str(value).strip()})


def _mode(values: Iterable[int]) -> int:
    counts = Counter(values)
    return counts.most_common(1)[0][0] if counts else 0


def _classify_gap(
    *,
    affected_scan_count: int,
    scan_count: int,
    ticker_counts: Counter[str],
) -> str:
    if affected_scan_count == 0:
        return "CLEAN"
    top_count = ticker_counts.most_common(1)[0][1] if ticker_counts else 0
    # A repeated ticker indicates a symbol-specific/vendor issue; a small
    # number of simultaneous missing symbols is more consistent with a
    # transient batch response.  The labels are investigative hints, not a
    # reason to relax the readiness gate.
    if top_count >= 3 and top_count >= max(affected_scan_count * 0.25, 3):
        return "PERSISTENT_TICKER_GAP"
    if affected_scan_count <= max(3, scan_count * 0.02):
        return "TRANSIENT_BATCH_GAP"
    return "REPEATED_BATCH_GAP"


def _signal_evaluation(row: dict) -> dict | None:
    """Return the diagnostic signal summary embedded in an observation."""
    health = row.get("data_health") or {}
    value = health.get("signal_evaluation")
    if not isinstance(value, dict):
        value = row.get("signal_evaluation")
    return value if isinstance(value, dict) else None


def _validate_signal_evaluation(row: dict, signal: dict) -> list[str]:
    """Validate signal-reason counts without changing trading decisions."""
    errors: list[str] = []
    health = row.get("data_health") or {}
    expected = int(health.get("expected_count") or 0)
    try:
        evaluated = int(signal.get("evaluated_count"))
    except (TypeError, ValueError):
        evaluated = -1
        errors.append("evaluated_count is not an integer")
    if expected > 0 and evaluated != expected:
        errors.append(f"evaluated_count={evaluated} != expected_count={expected}")

    reason_counts = signal.get("reason_counts")
    if not isinstance(reason_counts, dict):
        errors.append("reason_counts is not an object")
    else:
        try:
            reason_total = sum(int(value) for value in reason_counts.values())
        except (TypeError, ValueError):
            reason_total = -1
            errors.append("reason_counts contains a non-integer value")
        if reason_total != evaluated:
            errors.append(f"reason_total={reason_total} != evaluated_count={evaluated}")

    try:
        selected = int(signal.get("selected_count"))
    except (TypeError, ValueError):
        selected = -1
        errors.append("selected_count is not an integer")
    if selected < 0 or (evaluated >= 0 and selected > evaluated):
        errors.append(f"selected_count={selected} is outside evaluated range")

    try:
        target_weight_sum = float(signal.get("target_weight_sum"))
    except (TypeError, ValueError):
        target_weight_sum = -1.0
        errors.append("target_weight_sum is not numeric")
    if target_weight_sum < 0:
        errors.append(f"target_weight_sum={target_weight_sum} is negative")
    return errors


def _signal_quality(rows: list[dict]) -> dict:
    """Profile coverage and internal consistency of signal diagnostics."""
    observed = 0
    valid = 0
    invalid = 0
    errors: list[str] = []
    for row in rows:
        signal = _signal_evaluation(row)
        if signal is None:
            continue
        observed += 1
        row_errors = _validate_signal_evaluation(row, signal)
        if row_errors:
            invalid += 1
            timestamp = str(row.get("timestamp") or "unknown")
            errors.extend(f"{timestamp}: {error}" for error in row_errors)
        else:
            valid += 1
    coverage = observed / len(rows) if rows else 0.0
    validity = valid / observed if observed else 0.0
    return {
        "observed_row_count": observed,
        "valid_row_count": valid,
        "invalid_row_count": invalid,
        "coverage_rate": coverage,
        "validity_rate": validity,
        "errors": errors[:20],
    }


def build_report(
    log_path: Path,
    *,
    generated_at: dt.datetime | None = None,
    freshness_gate: float = FRESHNESS_GATE,
) -> dict:
    """Build a date-segmented completeness report from operational JSONL."""

    rows, parse_errors = _rows(log_path)
    # Readiness and EOD reports are keyed by the observation/session date,
    # while ``expected_date`` describes the market-data bar being evaluated.
    # Keep both so a delayed scan is not incorrectly attributed to the bar
    # date (the historical gaps in this project otherwise appear one day
    # early).
    by_date: dict[str, list[dict]] = defaultdict(list)
    unscoped_rows = 0
    for row in rows:
        health = row.get("data_health") or {}
        expected_date = str(health.get("expected_date") or "").strip()
        timestamp = _parse_timestamp(row.get("timestamp"))
        partition_date = timestamp.date().isoformat() if timestamp else expected_date
        if not partition_date:
            unscoped_rows += 1
            continue
        by_date[partition_date].append(row)

    date_reports: list[dict] = []
    for expected_date in sorted(by_date):
        date_rows = by_date[expected_date]
        signal_quality = _signal_quality(date_rows)
        expected_dates = sorted(
            {
                str((row.get("data_health") or {}).get("expected_date") or "").strip()
                for row in date_rows
                if str((row.get("data_health") or {}).get("expected_date") or "").strip()
            }
        )
        expected_counts: list[int] = []
        freshness_rates: list[float] = []
        missing_counter: Counter[str] = Counter()
        stale_counter: Counter[str] = Counter()
        dependency_counter: Counter[str] = Counter()
        bad_timestamps: list[dt.datetime] = []
        scan_clean_flags: list[bool] = []
        for row in date_rows:
            health = row.get("data_health") or {}
            expected = int(health.get("expected_count") or 0)
            fresh = int(health.get("fresh_count") or 0)
            expected_counts.append(expected)
            freshness_rates.append(fresh / expected if expected else 0.0)
            missing = _normalise_tickers(health.get("missing_tickers"))
            stale = _normalise_tickers(health.get("stale_tickers"))
            missing_counter.update(missing)
            stale_counter.update(stale)
            dependency_counter.update(
                str(error).strip()
                for error in (health.get("dependency_errors") or [])
                if str(error).strip()
            )
            scan_clean_flags.append(
                not missing and not stale and not (health.get("dependency_errors") or [])
            )
            if missing or stale or health.get("dependency_errors"):
                timestamp = _parse_timestamp(row.get("timestamp"))
                if timestamp:
                    bad_timestamps.append(timestamp)

        scan_count = len(date_rows)
        affected_scan_count = sum(
            1
            for row in date_rows
            if (
                _normalise_tickers((row.get("data_health") or {}).get("missing_tickers"))
                or _normalise_tickers((row.get("data_health") or {}).get("stale_tickers"))
                or (row.get("data_health") or {}).get("dependency_errors")
            )
        )
        cell_freshness_rate = (
            sum(freshness_rates) / len(freshness_rates) if freshness_rates else 0.0
        )
        scan_freshness_rate = (
            sum(scan_clean_flags) / len(scan_clean_flags) if scan_clean_flags else 0.0
        )
        quality_issue = bool(affected_scan_count)
        strict_readiness_blocked = scan_freshness_rate < 1.0
        date_reports.append(
            {
                "observation_date": expected_date,
                "expected_dates": expected_dates,
                "scan_count": scan_count,
                "expected_count_mode": _mode(expected_counts),
                "affected_scan_count": affected_scan_count,
                "affected_scan_rate": affected_scan_count / scan_count if scan_count else 0.0,
                "data_freshness_rate": scan_freshness_rate,
                "cell_freshness_rate": cell_freshness_rate,
                "freshness_gate": freshness_gate,
                "freshness_gate_failed": scan_freshness_rate < freshness_gate,
                "quality_issue": quality_issue,
                "readiness_blocked": strict_readiness_blocked,
                "gap_classification": _classify_gap(
                    affected_scan_count=affected_scan_count,
                    scan_count=scan_count,
                    ticker_counts=missing_counter,
                ),
                "missing_observation_count": sum(missing_counter.values()),
                "missing_ticker_counts": dict(missing_counter.most_common()),
                "stale_ticker_counts": dict(stale_counter.most_common()),
                "dependency_error_counts": dict(dependency_counter.most_common()),
                "first_bad_observation_at": (
                    min(bad_timestamps).isoformat(timespec="seconds") if bad_timestamps else None
                ),
                "last_bad_observation_at": (
                    max(bad_timestamps).isoformat(timespec="seconds") if bad_timestamps else None
                ),
                "signal_evaluation": signal_quality,
            }
        )

    generated = (generated_at or dt.datetime.now(KST)).astimezone(KST)
    blocked_dates = [
        row["observation_date"] for row in date_reports if row["readiness_blocked"]
    ]
    issue_dates = [
        row["observation_date"] for row in date_reports if row["quality_issue"]
    ]
    signal_quality = _signal_quality(rows)
    return {
        "schema_version": 1,
        "generated_at": generated.isoformat(timespec="seconds"),
        "mode": "PAPER",
        "source": str(log_path),
        "grain": "one operational health observation per trader scan",
        "freshness_gate": freshness_gate,
        "profile": {
            "row_count": len(rows),
            "date_count": len(date_reports),
            "parse_error_count": parse_errors,
            "unscoped_row_count": unscoped_rows,
            "first_observation_at": (
                min(
                    timestamps
                    for timestamps in (_parse_timestamp(row.get("timestamp")) for row in rows)
                    if timestamps is not None
                ).isoformat(timespec="seconds")
                if any(_parse_timestamp(row.get("timestamp")) for row in rows)
                else None
            ),
            "last_observation_at": (
                max(
                    timestamps
                    for timestamps in (_parse_timestamp(row.get("timestamp")) for row in rows)
                    if timestamps is not None
                ).isoformat(timespec="seconds")
                if any(_parse_timestamp(row.get("timestamp")) for row in rows)
                else None
            ),
            "signal_evaluation": signal_quality,
        },
        "date_reports": date_reports,
        "summary": {
            "blocked_date_count": len(blocked_dates),
            "blocked_dates": blocked_dates,
            "quality_issue_date_count": len(issue_dates),
            "quality_issue_dates": issue_dates,
            "clean_date_count": len(date_reports) - len(blocked_dates),
            "signal_evaluation": signal_quality,
            "evidence_policy": (
                "Missing or stale observations remain blockers; this artifact never rewrites "
                "historical scans or upgrades a date to READY."
            ),
        },
    }


def write_report(report: dict, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Profile PAPER operational-log data completeness without broker writes."
    )
    parser.add_argument("--log", default="logs/paper/operational_health.jsonl")
    parser.add_argument(
        "--output", default="reports/analysis/paper_data_quality_gaps/latest.json"
    )
    parser.add_argument("--freshness-gate", type=float, default=FRESHNESS_GATE)
    args = parser.parse_args()
    report = build_report(Path(args.log), freshness_gate=args.freshness_gate)
    write_report(report, Path(args.output))
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
