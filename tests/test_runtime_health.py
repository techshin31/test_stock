import datetime as dt
import json

from core.utils import runtime_health


KST = dt.timezone(dt.timedelta(hours=9))


def _write(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _seed_runtime_metadata(root):
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
        _write(lock_path.with_suffix(lock_path.suffix + ".json"), {
            "pid": 123,
            "mode": "PAPER",
            "label": label,
            "runtime_id": "paper-trader",
        })
        _write(root / "logs" / "paper" / heartbeat_name, {
            "pid": 123,
            "mode": "PAPER",
            "label": label,
            "runtime_id": "paper-trader",
            "updated_at": "2026-07-29T10:00:00+09:00",
        })


def test_paper_scheduler_health_requires_scheduler_and_supervisor(tmp_path, monkeypatch):
    _seed_runtime_metadata(tmp_path)
    monkeypatch.setattr(
        runtime_health,
        "is_process_runtime_live",
        lambda *args, **kwargs: (True, "local_os_lock"),
    )

    result = runtime_health.paper_scheduler_health(
        tmp_path,
        now=dt.datetime(2026, 7, 29, 10, 0, tzinfo=KST),
    )

    assert result["status"] == "healthy"
    assert [check["name"] for check in result["checks"]] == [
        "scheduler", "scheduler-supervisor"
    ]


def test_paper_scheduler_health_rejects_wrong_mode_or_dead_runtime(tmp_path, monkeypatch):
    _seed_runtime_metadata(tmp_path)
    metadata_path = tmp_path / "logs" / "scheduler.instance.lock.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata["mode"] = "REAL"
    _write(metadata_path, metadata)
    monkeypatch.setattr(
        runtime_health,
        "is_process_runtime_live",
        lambda *args, **kwargs: (False, "stale heartbeat"),
    )

    result = runtime_health.paper_scheduler_health(tmp_path)

    assert result["status"] == "unhealthy"
    assert all(not check["passed"] for check in result["checks"])
