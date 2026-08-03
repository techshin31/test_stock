"""Summarise PAPER incident episodes without changing readiness policy."""

from __future__ import annotations

import argparse
import datetime as dt
import json
from collections import Counter, defaultdict
from pathlib import Path
from zoneinfo import ZoneInfo

from core.analytics.trading_kpis import extract_critical_incidents


KST = ZoneInfo("Asia/Seoul")


def build_report(
    log_path: Path,
    *,
    through_date: dt.date | None = None,
    generated_at: dt.datetime | None = None,
) -> dict:
    incidents = extract_critical_incidents(log_path, through_date=through_date)
    by_date: dict[str, list[dict]] = defaultdict(list)
    for incident in incidents:
        by_date[str(incident.get("date") or "UNKNOWN")].append(incident)

    daily = []
    for date_value in sorted(by_date):
        rows = by_date[date_value]
        classes = Counter(str(row.get("event_class") or "UNKNOWN") for row in rows)
        statuses = Counter(str(row.get("status") or "UNKNOWN") for row in rows)
        active = sum(row.get("resolution_status") == "ACTIVE" for row in rows)
        safety = classes.get("SAFETY_CONTROL", 0)
        daily.append(
            {
                "date": date_value,
                "episode_count": len(rows),
                "safety_control_episode_count": safety,
                "non_safety_episode_count": len(rows) - safety,
                "active_episode_count": active,
                "event_class_counts": dict(classes),
                "status_counts": dict(statuses),
                "top_summaries": dict(
                    Counter(str(row.get("summary") or "UNKNOWN") for row in rows).most_common(5)
                ),
            }
        )

    generated = (generated_at or dt.datetime.now(KST)).astimezone(KST)
    classes = Counter(str(row.get("event_class") or "UNKNOWN") for row in incidents)
    active = sum(row.get("resolution_status") == "ACTIVE" for row in incidents)
    safety = classes.get("SAFETY_CONTROL", 0)
    return {
        "schema_version": 1,
        "generated_at": generated.isoformat(timespec="seconds"),
        "mode": "PAPER",
        "source": str(log_path),
        "through_date": through_date.isoformat() if through_date else None,
        "grain": "one extracted incident episode",
        "summary": {
            "episode_count": len(incidents),
            "safety_control_episode_count": safety,
            "non_safety_episode_count": len(incidents) - safety,
            "active_episode_count": active,
            "event_class_counts": dict(classes),
            "policy": (
                "This is explanatory evidence only. It does not reclassify or relax "
                "the existing readiness gate."
            ),
        },
        "daily": daily,
    }


def write_report(report: dict, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Summarise PAPER incident episodes without changing readiness policy."
    )
    parser.add_argument("--log", default="logs/paper/operational_health.jsonl")
    parser.add_argument("--through-date", default=None)
    parser.add_argument(
        "--output", default="reports/analysis/paper_incident_evidence/latest.json"
    )
    args = parser.parse_args()
    through_date = (
        dt.date.fromisoformat(args.through_date) if args.through_date else None
    )
    report = build_report(Path(args.log), through_date=through_date)
    write_report(report, Path(args.output))
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
