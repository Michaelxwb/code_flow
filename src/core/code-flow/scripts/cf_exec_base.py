#!/usr/bin/env python3
"""Shared execution substrate: deadline-aware argv subprocess runner.

All check executors (acceptance scenarios, Spec verifiers, session
validators) funnel through here so one entry deadline constrains the whole
chain, commands never pass through a shell, and unrun work is reported as
`incomplete` instead of silently skipped or falsely passed.
"""

from __future__ import annotations

import shlex
import subprocess
import time
from pathlib import Path
from typing import Mapping, Optional, Sequence


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
