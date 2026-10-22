#!/usr/bin/env python3
"""Worktree isolation contract for acceptance checks.

Isolated checks receive a deterministic namespace so parallel worktrees never
share ports or databases. Shared checks stay serial by default: they may pass
`parallel_safe: true`, but the effective answer is always false because a
shared service cannot be partitioned across worktrees.
"""

from __future__ import annotations

import hashlib
import os
import re
import shlex
from pathlib import Path
from typing import Mapping, Optional
from uuid import uuid4

ENV_SCOPES = ("shared", "isolated")
_SAFE_COMPONENT = re.compile(r"[^a-z0-9]+")


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
