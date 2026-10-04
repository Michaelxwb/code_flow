#!/usr/bin/env python3
"""Shared execution substrate: deadline-aware argv subprocess runner.

All check executors (acceptance scenarios, Spec verifiers, session
validators) funnel through here so one entry deadline constrains the whole
chain, commands never pass through a shell, and unrun work is reported as
`incomplete` instead of silently skipped or falsely passed.
"""

from __future__ import annotations

import hashlib
import shlex
import json
import subprocess
import time
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from typing import Callable, Iterator, Mapping, Optional, Sequence

_EXECUTIONS: ContextVar[Optional[dict[str, dict[str, object]]]] = ContextVar("cf_executions", default=None)


@contextmanager
def execution_session() -> Iterator[None]:
    """Share results only inside one validation operation, never across turns."""
    if _EXECUTIONS.get() is not None:
        yield
        return
    token = _EXECUTIONS.set({})
    try:
        yield
    finally:
        _EXECUTIONS.reset(token)


def invalidate_executions() -> None:
    cache = _EXECUTIONS.get()
    if cache is not None:
        cache.clear()


def execution_key(argv: Sequence[str], cwd: str, timeout: float) -> str:
    """Identity of a command under the current process environment."""
    return json.dumps([list(argv), str(Path(cwd).resolve()), float(timeout)], ensure_ascii=False)


def remaining_seconds(deadline: Optional[float]) -> Optional[float]:
    """Seconds left until the absolute monotonic deadline (None = unbounded)."""
    if deadline is None:
        return None
    return deadline - time.monotonic()


def build_argv(template: str, files: Sequence[str]) -> list[str]:
    """Expand a validator command template into argv without a shell.

    `{files}` must be a standalone token and expands to one argv entry per
    file (spaces/metachars safe). Embedded usage is a config error — refusing
    is safer than reintroducing shell splitting.
    """
    tokens = shlex.split(template or "")
    if not tokens:
        return []
    argv: list[str] = []
    for token in tokens:
        if token == "{files}":
            argv.extend(files)
        elif "{files}" in token:
            raise ValueError(f"validator command must keep {{files}} as a standalone token: {template!r}")
        else:
            argv.append(token)
    return argv


def run_command(
    argv: Sequence[str],
    cwd: str,
    timeout: float,
    deadline: Optional[float] = None,
) -> dict[str, object]:
    """Run argv synchronously under timeout+deadline. Never uses a shell."""
    key = execution_key(argv, cwd, timeout)
    cache = _EXECUTIONS.get()
    if cache is not None and key in cache:
        return dict(cache[key])
    result = _execute(argv, cwd, timeout, deadline)
    if cache is not None and result["status"] == "ok":
        cache[key] = result
    return result


def hash_worktree_paths(project_root: str, paths: Sequence[str]) -> Optional[list]:
    """Batch-hash worktree file contents (single `git hash-object` process)."""
    if not paths:
        return []
    completed = subprocess.run(
        ("git", "-C", project_root, "hash-object", "--stdin-paths"),
        input="\n".join(paths) + "\n", text=True, capture_output=True,
    )
    if completed.returncode != 0:
        return None
    hashes = completed.stdout.splitlines()
    if len(hashes) != len(paths):
        return None
    return [(path, sha.strip()) for path, sha in zip(paths, hashes)]


def worktree_fingerprint(project_root: str, untracked_filter: Optional[Callable[[str], bool]] = None,
                         include_untracked: bool = True) -> str:
    """Content-addressed fingerprint of the working tree, ignoring `.code-flow`.

    Committed content uses blob SHAs; modified/untracked files are hashed from
    the worktree. Git-ignored files never participate, so build artifacts do
    not invalidate caches. `untracked_filter` optionally narrows which
    untracked paths count (validators filter by trigger; acceptance scenarios
    pass `include_untracked=False` because the workflow commits before gates
    run and test artifacts must not invalidate evidence).
    Returns "" when identity cannot be proven (callers must disable reuse).
    """
    def _git(*arguments: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            ("git", "-C", project_root, *arguments),
            text=True, encoding="utf-8", capture_output=True, check=False,
        )

    tree = _git("ls-tree", "-r", "HEAD")
    status = _git("status", "--porcelain", "--untracked-files=all")
    if tree.returncode != 0 or status.returncode != 0:
        return ""
    contents: dict[str, str] = {}
    for line in tree.stdout.splitlines():
        meta, _, path = line.partition("\t")
        fields = meta.split()
        if path and len(fields) >= 3 and not path.startswith(".code-flow/"):
            contents[path] = fields[2]
    changed: list[str] = []
    deleted: list[str] = []
    for line in status.stdout.splitlines():
        code, path = line[:2], line[3:].strip()
        if " -> " in path:
            path = path.split(" -> ", 1)[1].strip()
        if not path or path.startswith(".code-flow/"):
            continue
        if path.startswith('"'):
            return ""  # quoted/escaped path: fail closed instead of mis-hashing
        if code.strip() == "??":
            if include_untracked and (untracked_filter is None or untracked_filter(path)):
                changed.append(path)
        elif "D" in code:
            contents.pop(path, None)
            deleted.append(path)
        else:
            changed.append(path)
    hashed = hash_worktree_paths(project_root, changed)
    if hashed is None:
        return ""
    for path, sha in hashed:
        contents[path] = sha
    digest = hashlib.sha256()
    for path in sorted(contents):
        digest.update(path.encode())
        digest.update(b"\0")
        digest.update(contents[path].encode())
        digest.update(b"\n")
    for path in sorted(deleted):
        digest.update(f"deleted:{path}".encode())
        digest.update(b"\n")
    return digest.hexdigest()


def _execute(argv: Sequence[str], cwd: str, timeout: float, deadline: Optional[float]) -> dict[str, object]:
    remaining = remaining_seconds(deadline)
    if remaining is not None and remaining <= 0:
        return {"status": "deadline_exceeded", "returncode": None, "stdout": "", "stderr": ""}
    effective = min(timeout, remaining) if remaining is not None else timeout
    try:
        proc = subprocess.run(
            list(argv), cwd=cwd, capture_output=True, text=True, timeout=max(effective, 0.01)
        )
    except subprocess.TimeoutExpired as exc:
        out = exc.stdout
        return {
            "status": "timeout",
            "returncode": None,
            "stdout": (out.decode() if isinstance(out, bytes) else (out or ""))[-4000:],
            "stderr": "",
        }
    except OSError as exc:
        return {"status": "spawn_error", "returncode": None, "stdout": "", "stderr": str(exc)}
    return {"status": "ok", "returncode": proc.returncode, "stdout": proc.stdout or "", "stderr": proc.stderr or ""}
