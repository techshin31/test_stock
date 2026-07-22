"""Cross-platform process locks with human-readable owner metadata."""
from __future__ import annotations

import datetime
import json
import os
import platform
import socket
import threading
from pathlib import Path


class ProcessAlreadyRunning(RuntimeError):
    """Raised when another process owns an instance lock."""


def current_runtime_id() -> str:
    """Identify the OS/container namespace that owns process IDs and locks."""
    configured = os.getenv("QUANTPILOT_RUNTIME_ID", "").strip()
    if configured:
        return configured
    return f"{platform.system().lower()}:{socket.gethostname()}"


def _atomic_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    temporary.replace(path)


class ProcessHeartbeat:
    """Publish fresh, namespace-aware liveness evidence for external auditors."""

    def __init__(
        self,
        path: Path,
        mode: str,
        *,
        label: str,
        interval_seconds: float = 5.0,
    ):
        if interval_seconds <= 0:
            raise ValueError("interval_seconds must be positive")
        self.path = Path(path)
        self.mode = mode
        self.label = label
        self.interval_seconds = interval_seconds
        self.pid = os.getpid()
        self.runtime_id = current_runtime_id()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def _payload(self) -> dict:
        return {
            "pid": self.pid,
            "mode": self.mode,
            "label": self.label,
            "runtime_id": self.runtime_id,
            "updated_at": datetime.datetime.now().astimezone().isoformat(
                timespec="seconds"
            ),
        }

    def _run(self) -> None:
        while not self._stop.wait(self.interval_seconds):
            _atomic_json(self.path, self._payload())

    def start(self):
        _atomic_json(self.path, self._payload())
        self._thread = threading.Thread(
            target=self._run,
            name=f"{self.label}-heartbeat",
            daemon=True,
        )
        self._thread.start()
        return self

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=max(1.0, self.interval_seconds * 2))
            self._thread = None
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            if (
                int(payload.get("pid", -1)) == self.pid
                and payload.get("runtime_id") == self.runtime_id
                and payload.get("label") == self.label
            ):
                self.path.unlink(missing_ok=True)
        except (OSError, ValueError, TypeError):
            pass


class ProcessInstanceLock:
    def __init__(self, path: Path, mode: str, *, label: str = "process"):
        self.path = Path(path)
        self.mode = mode
        self.label = label
        self.handle = None
        self.metadata_path = self.path.with_suffix(self.path.suffix + ".json")

    def acquire(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = self.path.open("a+b")
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"\0")
            handle.flush()
        handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            handle.close()
            owner = ""
            try:
                payload = json.loads(self.metadata_path.read_text(encoding="utf-8"))
                owner = f" (pid={payload.get('pid')}, mode={payload.get('mode')})"
            except (OSError, ValueError, TypeError):
                pass
            raise ProcessAlreadyRunning(
                f"another {self.label} instance is already running{owner}"
            ) from exc

        self.handle = handle
        self.metadata_path.write_text(
            json.dumps(
                {
                    "pid": os.getpid(),
                    "mode": self.mode,
                    "label": self.label,
                    "runtime_id": current_runtime_id(),
                    "acquired_at": datetime.datetime.now().astimezone().isoformat(),
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        return self

    def release(self):
        if self.handle is None:
            return
        try:
            self.handle.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(self.handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(self.handle.fileno(), fcntl.LOCK_UN)
        finally:
            self.handle.close()
            self.handle = None
            try:
                payload = json.loads(self.metadata_path.read_text(encoding="utf-8"))
                if int(payload.get("pid", -1)) == os.getpid():
                    self.metadata_path.unlink(missing_ok=True)
            except (OSError, ValueError, TypeError):
                pass


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


def is_process_lock_held(path: Path) -> bool:
    """Non-destructively check whether an OS process lock is actively held.

    Returns True if and only if another running process holds the file lock.
    Does not modify metadata or lock files.
    """
    path = Path(path)
    if path.name.endswith(".json"):
        lock_file = path.with_name(path.name[:-5])
        meta_file = path
    else:
        lock_file = path
        meta_file = path.with_suffix(path.suffix + ".json")

    if not lock_file.is_file():
        return False

    if meta_file.is_file():
        try:
            payload = json.loads(meta_file.read_text(encoding="utf-8"))
            pid = int(payload.get("pid", -1))
            if pid > 0 and not is_process_alive(pid):
                return False
        except (OSError, ValueError, TypeError):
            pass

    try:
        handle = lock_file.open("r+b")
    except (OSError, IOError):
        return True

    try:
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            return False
        except (OSError, IOError):
            return True
    finally:
        handle.close()


def is_process_runtime_live(
    metadata: dict,
    lock_path: Path,
    heartbeat_path: Path,
    *,
    now: datetime.datetime | None = None,
    maximum_heartbeat_age_seconds: float = 30.0,
) -> tuple[bool, str]:
    """Validate local OS locks or a fresh heartbeat from another namespace."""
    try:
        pid = int(metadata.get("pid", -1))
    except (TypeError, ValueError):
        return False, "invalid pid"
    runtime_id = str(metadata.get("runtime_id") or "")
    if pid <= 0 or not runtime_id:
        return False, "runtime metadata incomplete"

    if runtime_id == current_runtime_id():
        alive = is_process_alive(pid) and is_process_lock_held(lock_path)
        return alive, "local_os_lock" if alive else "local process/lock not held"

    try:
        heartbeat = json.loads(Path(heartbeat_path).read_text(encoding="utf-8"))
        updated_at = datetime.datetime.fromisoformat(str(heartbeat["updated_at"]))
        if updated_at.tzinfo is None:
            updated_at = updated_at.replace(tzinfo=datetime.timezone.utc)
        reference = now or datetime.datetime.now().astimezone()
        if reference.tzinfo is None:
            reference = reference.replace(tzinfo=datetime.timezone.utc)
        age = (reference.astimezone(datetime.timezone.utc) - updated_at.astimezone(
            datetime.timezone.utc
        )).total_seconds()
        matches = (
            int(heartbeat.get("pid", -1)) == pid
            and heartbeat.get("mode") == metadata.get("mode")
            and heartbeat.get("label") == metadata.get("label")
            and heartbeat.get("runtime_id") == runtime_id
        )
        fresh = -5.0 <= age <= maximum_heartbeat_age_seconds
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
        return False, "foreign heartbeat unavailable"
    if not matches:
        return False, "foreign heartbeat metadata mismatch"
    if not fresh:
        return False, f"foreign heartbeat stale age={age:.1f}s"
    return True, f"foreign heartbeat age={age:.1f}s runtime={runtime_id}"
