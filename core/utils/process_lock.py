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
