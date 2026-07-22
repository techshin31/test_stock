"""Bounded scheduler-process recovery for non-REAL trading modes.

The supervisor never changes trading configuration.  PAPER, DRY_RUN, and
SIMULATE may be restarted after an unexpected process exit; REAL deliberately
remains single-shot and requires a fresh manual launch through the existing
promotion gates.
"""
from __future__ import annotations

import argparse
import atexit
import datetime as dt
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Callable, Sequence

from core.utils.process_lock import ProcessAlreadyRunning, ProcessInstanceLock


PROJECT_ROOT = Path(__file__).resolve().parents[2]
RESTARTABLE_MODES = {"PAPER", "DRY_RUN", "SIMULATE"}
MODE_FLAGS = {
    "PAPER": "--paper",
    "DRY_RUN": "--dry-run",
    "SIMULATE": "--simulate",
    "REAL": "--live",
}


def _event(
    *,
    mode: str,
    event: str,
    exit_code: int | None,
    restart_count: int,
    detail: str,
) -> dict:
    return {
        "timestamp": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
        "mode": mode,
        "event": event,
        "exit_code": exit_code,
        "restart_count": restart_count,
        "detail": detail,
    }


def _append_jsonl(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


def is_process_alive(pid: int) -> bool:
    """Return whether a process is alive without signalling or modifying it."""
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes

        process_query_limited_information = 0x1000
        still_active = 259
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(
            process_query_limited_information, False, pid
        )
        if not handle:
            # Access denied still proves that a process owns the PID.
            return kernel32.GetLastError() == 5
        try:
            exit_code = ctypes.c_ulong()
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                return False
            return exit_code.value == still_active
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def supervise_existing(
    pid: int,
    command: Sequence[str],
    *,
    mode: str,
    max_restarts: int,
    restart_delay_seconds: float,
    poll_seconds: float,
    process_checker: Callable[[int], bool] = is_process_alive,
    runner: Callable[..., object] = subprocess.run,
    sleeper: Callable[[float], None] = time.sleep,
    event_sink: Callable[[dict], None] | None = None,
) -> int:
    """Attach to a running scheduler, then recover it only after it exits."""
    if poll_seconds <= 0:
        raise ValueError("poll_seconds must be positive")
    if event_sink:
        event_sink(
            _event(
                mode=mode.upper(),
                event="ATTACHED_TO_EXISTING",
                exit_code=None,
                restart_count=0,
                detail=f"pid={pid}, poll_seconds={poll_seconds:g}",
            )
        )
    while process_checker(pid):
        sleeper(poll_seconds)
    if event_sink:
        event_sink(
            _event(
                mode=mode.upper(),
                event="ATTACHED_PROCESS_EXITED",
                exit_code=None,
                restart_count=0,
                detail=f"pid={pid}",
            )
        )
    return run_supervised(
        command,
        mode=mode,
        max_restarts=max_restarts,
        restart_delay_seconds=restart_delay_seconds,
        runner=runner,
        sleeper=sleeper,
        event_sink=event_sink,
    )


def run_supervised(
    command: Sequence[str],
    *,
    mode: str,
    max_restarts: int,
    restart_delay_seconds: float,
    runner: Callable[..., object] = subprocess.run,
    sleeper: Callable[[float], None] = time.sleep,
    event_sink: Callable[[dict], None] | None = None,
) -> int:
    """Run a scheduler command and recover only eligible non-REAL modes."""
    normalized_mode = mode.upper()
    if normalized_mode not in MODE_FLAGS:
        raise ValueError(f"unsupported scheduler mode: {mode}")
    if max_restarts < 0:
        raise ValueError("max_restarts must be non-negative")
    if restart_delay_seconds < 0:
        raise ValueError("restart_delay_seconds must be non-negative")

    restart_count = 0
    while True:
        result = runner(list(command), check=False)
        exit_code = int(getattr(result, "returncode"))
        if event_sink:
            event_sink(
                _event(
                    mode=normalized_mode,
                    event="PROCESS_EXIT",
                    exit_code=exit_code,
                    restart_count=restart_count,
                    detail="scheduler process exited",
                )
            )
        if exit_code == 0:
            return 0
        # Exit 2 is an intentional safety refusal, including duplicate-instance
        # detection.  Retrying it would create a noisy restart loop.
        if exit_code == 2:
            return 2
        if normalized_mode not in RESTARTABLE_MODES:
            if event_sink:
                event_sink(
                    _event(
                        mode=normalized_mode,
                        event="AUTO_RESTART_DENIED",
                        exit_code=exit_code,
                        restart_count=restart_count,
                        detail="REAL scheduler requires a new manual gated launch",
                    )
                )
            return exit_code
        if restart_count >= max_restarts:
            if event_sink:
                event_sink(
                    _event(
                        mode=normalized_mode,
                        event="RESTART_LIMIT_REACHED",
                        exit_code=exit_code,
                        restart_count=restart_count,
                        detail=f"maximum automatic restarts={max_restarts}",
                    )
                )
            return exit_code

        restart_count += 1
        if event_sink:
            event_sink(
                _event(
                    mode=normalized_mode,
                    event="AUTO_RESTART_SCHEDULED",
                    exit_code=exit_code,
                    restart_count=restart_count,
                    detail=f"delay_seconds={restart_delay_seconds:g}",
                )
            )
        sleeper(restart_delay_seconds)


def run_recovery_self_test(output: Path) -> dict:
    """Prove fail-then-recover behavior without loading trading code or a broker."""
    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    state_path = output.with_suffix(output.suffix + ".state.tmp")
    state_path.unlink(missing_ok=True)
    child_code = (
        "from pathlib import Path; import sys; "
        f"p=Path({str(state_path)!r}); "
        "n=int(p.read_text() if p.exists() else '0')+1; "
        "p.write_text(str(n)); "
        "raise SystemExit(1 if n == 1 else 0)"
    )
    events: list[dict] = []
    try:
        exit_code = run_supervised(
            [sys.executable, "-c", child_code],
            mode="PAPER",
            max_restarts=2,
            restart_delay_seconds=0,
            event_sink=events.append,
        )
        attempts = sum(row["event"] == "PROCESS_EXIT" for row in events)
        process_exits = [
            row["exit_code"] for row in events if row["event"] == "PROCESS_EXIT"
        ]
        payload = {
            "schema_version": 1,
            "generated_at": dt.datetime.now().astimezone().isoformat(
                timespec="seconds"
            ),
            "scope": "PAPER_SCHEDULER_RECOVERY_SELF_TEST",
            "status": (
                "READY"
                if exit_code == 0
                and attempts == 2
                and process_exits == [1, 0]
                else "BLOCKED"
            ),
            "broker_loaded": False,
            "order_permission": "DENIED_BY_DESIGN",
            "tested_mode": "PAPER",
            "real_auto_restart_allowed": False,
            "attempts": attempts,
            "process_exit_codes": process_exits,
            "final_exit_code": exit_code,
            "events": events,
        }
        temp = output.with_suffix(output.suffix + ".tmp")
        temp.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        temp.replace(output)
        return payload
    finally:
        state_path.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Supervise scheduler.py with non-REAL bounded recovery."
    )
    parser.add_argument("--mode", choices=sorted(MODE_FLAGS))
    parser.add_argument("--attach-pid", type=int)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument(
        "--evidence",
        default="reports/analysis/scheduler_recovery_evidence.json",
    )
    parser.add_argument(
        "--max-restarts",
        type=int,
        default=int(os.getenv("SCHEDULER_MAX_RESTARTS", "5")),
    )
    parser.add_argument(
        "--restart-delay-seconds",
        type=float,
        default=float(os.getenv("SCHEDULER_RESTART_DELAY_SECONDS", "30")),
    )
    parser.add_argument(
        "--poll-seconds",
        type=float,
        default=float(os.getenv("SCHEDULER_SUPERVISOR_POLL_SECONDS", "5")),
    )
    args = parser.parse_args()

    if args.self_test:
        output = Path(args.evidence)
        if not output.is_absolute():
            output = PROJECT_ROOT / output
        payload = run_recovery_self_test(output)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0 if payload["status"] == "READY" else 1
    if not args.mode:
        parser.error("--mode is required unless --self-test is used")

    mode = args.mode.upper()
    log_path = PROJECT_ROOT / "logs" / mode.lower() / "scheduler_supervisor.jsonl"
    supervisor_lock = ProcessInstanceLock(
        PROJECT_ROOT / "logs" / "scheduler.supervisor.instance.lock",
        mode,
        label="scheduler-supervisor",
    )
    try:
        supervisor_lock.acquire()
    except ProcessAlreadyRunning as exc:
        print(f"[BLOCKED] {exc}")
        return 2
    atexit.register(supervisor_lock.release)
    command = [sys.executable, str(PROJECT_ROOT / "scheduler.py"), MODE_FLAGS[mode]]
    sink = lambda payload: _append_jsonl(log_path, payload)
    sink(
        _event(
            mode=mode,
            event="SUPERVISOR_STARTED",
            exit_code=None,
            restart_count=0,
            detail=(
                f"attach_pid={args.attach_pid}"
                if args.attach_pid
                else "child_launch=managed"
            ),
        )
    )
    if args.attach_pid:
        return supervise_existing(
            args.attach_pid,
            command,
            mode=mode,
            max_restarts=args.max_restarts,
            restart_delay_seconds=args.restart_delay_seconds,
            poll_seconds=args.poll_seconds,
            event_sink=sink,
        )
    return run_supervised(
        command,
        mode=mode,
        max_restarts=args.max_restarts,
        restart_delay_seconds=args.restart_delay_seconds,
        event_sink=sink,
    )


if __name__ == "__main__":
    raise SystemExit(main())
