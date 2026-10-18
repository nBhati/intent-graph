"""Exclusive project write lock (architecture section 9.4).

POSIX uses ``fcntl.flock``; Windows uses ``msvcrt.locking``. Lock files live in
``.intentgraph/locks/`` and are excluded from version control.
"""
from __future__ import annotations

import os
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from ..errors import LockTimeout

if os.name == "nt":  # pragma: no cover - exercised only on Windows
    import msvcrt

    def _try_lock(fd: int) -> bool:
        try:
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            return True
        except OSError:
            return False

    def _unlock(fd: int) -> None:
        try:
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        except OSError:
            pass
else:
    import fcntl

    def _try_lock(fd: int) -> bool:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except OSError:
            return False

    def _unlock(fd: int) -> None:
        fcntl.flock(fd, fcntl.LOCK_UN)


@contextmanager
def exclusive_lock(path: Path, timeout: float = 10.0, poll: float = 0.05) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o644)
    deadline = time.monotonic() + timeout
    try:
        while not _try_lock(fd):
            if time.monotonic() >= deadline:
                raise LockTimeout(f"could not acquire write lock {path} within {timeout}s", details={"lock": str(path)})
            time.sleep(poll)
        try:
            os.write(fd, f"{os.getpid()}\n".encode())
        except OSError:
            pass
        try:
            yield
        finally:
            _unlock(fd)
    finally:
        os.close(fd)
