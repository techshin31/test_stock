"""Bounded restart and progress watchdog for the unified non-REAL watcher."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import signal
from datetime import datetime
from zoneinfo import ZoneInfo

from apps.system.processes import stop_child
from core.utils.process_lock import ProcessHeartbeat, ProcessInstanceLock


def progress_stalled(path, *, launched_at, now, timeout):
    try:
        modified = Path(path).stat().st_mtime
    except OSError:
        modified = launched_at
    return now - max(launched_at, modified) > timeout


def supervise(arguments, *, mode, max_restarts=3, stall_timeout=1800):
    from apps.system.workflow import PROJECT_ROOT, MODES
    if mode not in MODES or max_restarts < 0 or stall_timeout < 60:
        raise ValueError("invalid supervision settings")
    venue = MODES[mode]
    lock = ProcessInstanceLock(PROJECT_ROOT / "logs/scheduler.supervisor.instance.lock", venue,
                               label="scheduler-supervisor").acquire()
    directory = PROJECT_ROOT / "logs" / venue.lower()
    heartbeat = ProcessHeartbeat(directory / "scheduler_supervisor_runtime.json", venue,
                                  label="scheduler-supervisor").start()
    child = None
    previous_signal = signal.getsignal(signal.SIGTERM)
    def terminate(_signum, _frame):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, terminate)
    def event(name, attempt, code=None):
        directory.mkdir(parents=True, exist_ok=True)
        with (directory / "scheduler_supervisor.jsonl").open("a") as handle:
            handle.write(json.dumps({"timestamp": datetime.now(ZoneInfo("Asia/Seoul")).isoformat(), "mode": venue, "event": name,
                                     "restart_count": attempt, "exit_code": code,
                                     "detail": "unified workflow"}) + "\n")
    try:
        for attempt in range(max_restarts + 1):
            event("SUPERVISOR_STARTED", attempt)
            launched = time.time()
            child = subprocess.Popen([sys.executable, "-m", "apps.system", "run", "--watch", *arguments],
                cwd=PROJECT_ROOT, env=dict(os.environ, PYTHONPATH=str(PROJECT_ROOT), QUANTPILOT_SUPERVISED="1"),
                start_new_session=os.name != "nt")
            while child.poll() is None:
                if progress_stalled(PROJECT_ROOT / f"logs/system/{mode}/cycle.json",
                                    launched_at=launched, now=time.time(), timeout=stall_timeout):
                    event("PROGRESS_STALLED", attempt)
                    stop_child(child)
                    break
                time.sleep(1)
            code = child.wait()
            event("PROCESS_EXIT", attempt, code)
            if code in {0, 2, 130}:
                return code  # Ownership conflicts and operator stops are not recovery failures.
            if attempt < max_restarts:
                event("AUTO_RESTART_SCHEDULED", attempt, code)
                time.sleep(min(5 * 2 ** attempt, 60))
        return code
    except KeyboardInterrupt:
        return 130
    finally:
        signal.signal(signal.SIGTERM, previous_signal)
        if child is not None:
            stop_child(child)
        heartbeat.stop()
        lock.release()
