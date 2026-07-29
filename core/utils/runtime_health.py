"""Container health checks for the supervised PAPER scheduler."""
from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path

from core.utils.process_lock import is_process_runtime_live


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def paper_scheduler_health(
    project_root: Path = PROJECT_ROOT,
    *,
    now: dt.datetime | None = None,
) -> dict:
    """Verify that both PAPER scheduler processes hold live runtime evidence."""
    root = Path(project_root)
    checks: list[dict] = []
    for lock_name, heartbeat_name, label in (
        (
            "scheduler.instance.lock",
            "scheduler_runtime.json",
            "scheduler",
        ),
        (
            "scheduler.supervisor.instance.lock",
            "scheduler_supervisor_runtime.json",
            "scheduler-supervisor",
        ),
    ):
        lock_path = root / "logs" / lock_name
        metadata_path = lock_path.with_suffix(lock_path.suffix + ".json")
        heartbeat_path = root / "logs" / "paper" / heartbeat_name
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            checks.append({
                "name": label,
                "passed": False,
                "detail": f"runtime metadata unavailable: {exc.__class__.__name__}",
            })
            continue
        live, evidence = is_process_runtime_live(
            metadata,
            lock_path,
            heartbeat_path,
            now=now,
        )
        passed = (
            metadata.get("mode") == "PAPER"
            and metadata.get("label") == label
            and live
        )
        checks.append({
            "name": label,
            "passed": passed,
            "detail": evidence,
        })
    return {
        "status": "healthy" if all(check["passed"] for check in checks) else "unhealthy",
        "checks": checks,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Check that the supervised PAPER scheduler is live."
    )
    parser.add_argument("--project-root", type=Path, default=PROJECT_ROOT)
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)
    result = paper_scheduler_health(args.project_root)
    if not args.quiet:
        print(json.dumps(result, ensure_ascii=False))
    return 0 if result["status"] == "healthy" else 1


if __name__ == "__main__":
    raise SystemExit(main())
