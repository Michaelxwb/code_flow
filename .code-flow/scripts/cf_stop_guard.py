"""Nonblocking process lock for Stop gates; the OS releases abandoned locks."""
from __future__ import annotations

from contextlib import contextmanager
import json
import os
from pathlib import Path
from typing import IO, Iterator


class StopAlreadyRunning(ValueError):
    pass


def _lock(handle: IO[str]) -> None:
    if os.name == "nt":
        import msvcrt
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
    else:
        import fcntl
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)


def _unlock(handle: IO[str]) -> None:
    if os.name == "nt":
        import msvcrt
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        import fcntl
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


@contextmanager
def stop_guard(root: str, sid: str) -> Iterator[None]:
    path = Path(root) / ".code-flow/.stop.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+", encoding="utf-8") as handle:
        try:
            _lock(handle)
        except OSError as exc:
            handle.seek(0)
            owner = handle.read(512).strip() or "owner unavailable"
            raise StopAlreadyRunning(f"stop_already_running: {owner}; 等待该进程结束后重试 Stop") from exc
        try:
            handle.seek(0)
            handle.truncate()
            json.dump({"pid": os.getpid(), "session_id": sid}, handle)
            handle.flush()
            yield
        finally:
            _unlock(handle)
