"""Cross-platform process locks with human-readable owner metadata."""
from __future__ import annotations

import datetime
import json
import os
from pathlib import Path


class ProcessAlreadyRunning(RuntimeError):
    """Raised when another process owns an instance lock."""


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
