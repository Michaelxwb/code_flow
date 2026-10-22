#!/usr/bin/env python3
"""Worktree isolation contract for acceptance checks.

Isolated checks receive a deterministic namespace so parallel worktrees never
share ports or databases. Shared checks stay serial by default: they may pass
`parallel_safe: true`, but the effective answer is always false because a
shared service cannot be partitioned across worktrees.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
import socket
import subprocess
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Mapping, Optional
from uuid import uuid4

ENV_SCOPES = ("shared", "isolated")
_SAFE_COMPONENT = re.compile(r"[^a-z0-9]+")
_LOCK_RELATIVE = Path("code-flow/locks/shared-env.lock")
_LOCK_POLL_SECONDS = 0.05
DEFAULT_SHARED_LOCK_WAIT = 300.0
DEFAULT_SHARED_LOCK_STALE = 1800.0


class SharedEnvLockTimeout(TimeoutError):
    """A shared environment stayed locked past the configured wait budget."""

    def __init__(self, path: Path, waited: float) -> None:
        super().__init__(f"shared environment lock timeout after {waited:.1f}s: {path}")
        self.path = path
        self.waited = waited


def env_scope(check: Mapping[str, object]) -> str:
    value = check.get("env_scope", "shared")
    return value if value in ENV_SCOPES else "shared"


def is_isolated(check: Mapping[str, object]) -> bool:
    return env_scope(check) == "isolated"


def effective_parallel_safe(check: Mapping[str, object]) -> bool:
    """Shared environments are never parallel-safe, regardless of the flag."""
    if not is_isolated(check):
        return False
    declared = check.get("parallel_safe", True)
    return declared is not False


def worktree_identity(root: str, explicit: str = "") -> str:
    for candidate in (explicit, os.environ.get("CF_WORKTREE_ID", "")):
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()
    name = Path(root).resolve().name
    return name or "worktree"


def resolve_run_id(explicit: str = "") -> str:
    for candidate in (explicit, os.environ.get("CF_RUN_ID", "")):
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()
    return uuid4().hex


def port_offset(worktree_id: str) -> int:
    digest = hashlib.sha256(worktree_id.encode("utf-8")).hexdigest()
    return 10000 + int(digest[:4], 16) % 40000


def db_suffix(worktree_id: str) -> str:
    slug = _SAFE_COMPONENT.sub("_", worktree_id.strip().lower()).strip("_") or "worktree"
    digest = hashlib.sha256(worktree_id.encode("utf-8")).hexdigest()[:6]
    return f"_{slug}_{digest}"


def worktree_namespace(root: str, worktree_id: str = "", run_id: str = "", task_id: str = "") -> dict[str, str]:
    """Stable per-worktree namespace injected into isolated child processes."""
    identity = worktree_identity(root, worktree_id)
    return {
        "CF_WORKTREE_ID": identity,
        "CF_RUN_ID": resolve_run_id(run_id),
        "CF_TASK_ID": task_id or os.environ.get("CF_TASK_ID", ""),
        "CF_PORT_OFFSET": str(port_offset(identity)),
        "CF_DB_SUFFIX": db_suffix(identity),
    }


def check_environment(
    check: Mapping[str, object], root: str, namespace: Optional[Mapping[str, str]] = None
) -> dict[str, str]:
    """Environment overlay for a check: isolated only, shared is untouched."""
    if not is_isolated(check):
        return {}
    resolved = dict(namespace) if namespace is not None else worktree_namespace(root)
    return {key: str(value) for key, value in resolved.items()}


def _git_common_dir(root: str) -> Path:
    """Directory shared by every worktree of the same repository."""
    result = subprocess.run(
        ("git", "rev-parse", "--git-common-dir"),
        cwd=str(root), text=True, encoding="utf-8", capture_output=True, check=False,
    )
    if result.returncode == 0 and result.stdout.strip():
        common = Path(result.stdout.strip())
        return common if common.is_absolute() else (Path(root) / common).resolve()
    return (Path(root) / ".code-flow").resolve()


def shared_env_lock_path(root: str) -> Path:
    """Lock file lives in the git common dir so all worktrees contend for it."""
    return _git_common_dir(root) / _LOCK_RELATIVE


def _lock_payload(token: str, run_id: str, worktree_id: str) -> dict[str, object]:
    return {
        "token": token,
        "pid": os.getpid(),
        "host": socket.gethostname(),
        "created_at": time.time(),
        "run_id": run_id,
        "worktree_id": worktree_id,
    }


def _read_lock(path: Path) -> Optional[dict[str, object]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _lock_is_stale(path: Path, stale_after: float) -> bool:
    """Age is authoritative; a dead local PID is stale before the timeout."""
    try:
        stat = path.stat()
    except OSError:
        return False
    data = _read_lock(path)
    if data is None:
        # A writer may be between O_CREAT and its first write; only break files
        # that stayed unreadable beyond the grace window.
        grace = min(max(stale_after, 0.1), 1.0)
        return time.time() - stat.st_mtime >= grace
    created = data.get("created_at")
    if isinstance(created, (int, float)) and time.time() - float(created) >= stale_after:
        return True
    if data.get("host") == socket.gethostname():
        pid = data.get("pid")
        if isinstance(pid, int) and pid > 0:
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                return True
            except (PermissionError, OSError):
                return False
    return False


def _acquire_shared_lock(path: Path, wait: float, stale_after: float, token: str,
                         run_id: str, worktree_id: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + wait
    while True:
        try:
            descriptor = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            if _lock_is_stale(path, stale_after):
                try:
                    path.unlink()
                except FileNotFoundError:
                    pass
                continue
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise SharedEnvLockTimeout(path, wait) from None
            time.sleep(min(_LOCK_POLL_SECONDS, remaining))
            continue
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(_lock_payload(token, run_id, worktree_id), ensure_ascii=False))
            handle.flush()
            os.fsync(handle.fileno())
        return


def _release_shared_lock(path: Path, token: str) -> None:
    data = _read_lock(path)
    if not isinstance(data, dict) or data.get("token") != token:
        return
    try:
        path.unlink()
    except FileNotFoundError:
        return


@contextmanager
def shared_env_lock(
    root: str,
    *,
    wait: Optional[float] = None,
    stale_after: Optional[float] = None,
    run_id: str = "",
    worktree_id: str = "",
) -> Iterator[dict[str, object]]:
    """Cross-worktree lock for shared (non-partitionable) environment checks.

    The lock is a JSON sidecar in the git common directory with an owner token.
    Wait and stale budgets are explicit so a crashed worktree cannot block the
    batch forever, while a live owner keeps the lock until released.
    """
    path = shared_env_lock_path(root)
    resolved_wait = DEFAULT_SHARED_LOCK_WAIT if wait is None else max(0.0, float(wait))
    resolved_stale = DEFAULT_SHARED_LOCK_STALE if stale_after is None else max(0.1, float(stale_after))
    token = uuid4().hex
    identity = worktree_id or worktree_identity(root)
    key = run_id or resolve_run_id()
    _acquire_shared_lock(path, resolved_wait, resolved_stale, token, key, identity)
    try:
        yield {"path": str(path), "token": token, "run_id": key, "worktree_id": identity}
    finally:
        _release_shared_lock(path, token)


def preflight_commands(check: Mapping[str, object]) -> list[list[str]]:
    """Normalize preflight entries (argv array or shell words) to argv arrays."""
    raw = check.get("preflight", [])
    if not isinstance(raw, list):
        raise ValueError("invalid check preflight: expected list")
    commands: list[list[str]] = []
    for entry in raw:
        if isinstance(entry, str):
            argv = shlex.split(entry)
        elif isinstance(entry, list) and all(isinstance(token, str) for token in entry):
            argv = list(entry)
        else:
            raise ValueError("invalid check preflight entry: expected argv array or command string")
        if not argv or any(not token for token in argv):
            raise ValueError("invalid check preflight entry: empty argv")
        commands.append(argv)
    return commands
