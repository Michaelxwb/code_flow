#!/usr/bin/env python3
"""Shared execution substrate: deadline-aware argv subprocess runner.

All check executors (acceptance scenarios, Spec verifiers, session
validators) funnel through here so one entry deadline constrains the whole
chain, commands never pass through a shell, and unrun work is reported as
`incomplete` instead of silently skipped or falsely passed.
"""

from __future__ import annotations

import hashlib
import os
import re
import signal
import shlex
import json
import subprocess
import sys
import time
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from typing import Callable, Iterator, Mapping, Optional, Sequence

_EXECUTIONS: ContextVar[Optional[dict[str, dict[str, object]]]] = ContextVar("cf_executions", default=None)
_REPORTS: ContextVar[Optional[list[dict[str, object]]]] = ContextVar("cf_reports", default=None)
_SECRET_OPTION = re.compile(r"(?i)^--?(?:api[-_]?key|access[-_]?token|token|password|passwd|secret|credential)$")
_SECRET_ASSIGNMENT = re.compile(r"(?i)(--?(?:api[-_]?key|access[-_]?token|token|password|passwd|secret|credential)=)([^\s]+)")
_RUNTIME_ENV = frozenset(("CF_RUNTIME_COMMAND", "CF_RUNTIME_ACTION", "CF_CLI_VERSION"))


def redact_sensitive_text(value: str) -> str:
    """Hide inherited sensitive environment values from diagnostics."""
    names = ("SECRET", "TOKEN", "PASSWORD", "PASSWD", "CREDENTIAL", "API_KEY", "PRIVATE_KEY")
    secrets = {item for key, item in os.environ.items()
               if item and any(name in key.upper() for name in names)}
    for secret in sorted(secrets, key=len, reverse=True):
        value = value.replace(secret, "[REDACTED]")
    return _SECRET_ASSIGNMENT.sub(r"\1[REDACTED]", value)


def _redact_sequence(values: Sequence[object]) -> list[object]:
    result: list[object] = []
    hide_next = False
    for item in values:
        if hide_next:
            result.append("[REDACTED]")
            hide_next = False
            continue
        result.append(redact_sensitive_payload(item))
        hide_next = isinstance(item, str) and bool(_SECRET_OPTION.fullmatch(item))
    return result


def redact_sensitive_payload(value: object) -> object:
    """Return a JSON-compatible copy with sensitive strings redacted."""
    if isinstance(value, str):
        return redact_sensitive_text(value)
    if isinstance(value, Mapping):
        return {key: redact_sensitive_payload(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return _redact_sequence(value)
    return value


@contextmanager
def report_session() -> Iterator[list[dict[str, object]]]:
    reports: list[dict[str, object]] = []
    token = _REPORTS.set(reports)
    try:
        yield reports
    finally:
        _REPORTS.reset(token)


def record_report(report: Mapping[str, object]) -> None:
    reports = _REPORTS.get()
    if reports is not None:
        reports.append(dict(report))


def report_requested() -> bool:
    return _REPORTS.get() is not None


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


def command_environment(env: Optional[Mapping[str, str]] = None) -> dict[str, str]:
    """Do not pass CLI dispatch metadata into user checks."""
    environment = {key: value for key, value in os.environ.items() if key not in _RUNTIME_ENV}
    environment.update({str(key): str(value) for key, value in (env or {}).items()})
    return environment


def execution_key(argv: Sequence[str], cwd: str, timeout: float,
                  env: Optional[Mapping[str, str]] = None) -> str:
    """Identity of a command under the current process environment."""
    environment = command_environment(env)
    payload: list[object] = [list(argv), str(Path(cwd).resolve()), float(timeout), sorted(environment.items())]
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False).encode()).hexdigest()


def execution_environment_hash(env: Optional[Mapping[str, str]] = None) -> str:
    """Bind evidence to inherited and explicit environment without exposing values."""
    environment = command_environment(env)
    payload = json.dumps(sorted(environment.items()), ensure_ascii=False)
    return hashlib.sha256(payload.encode()).hexdigest()


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
    env: Optional[Mapping[str, str]] = None,
    identity_context: Optional[Mapping[str, object]] = None,
) -> dict[str, object]:
    """Run argv synchronously under timeout+deadline. Never uses a shell."""
    key = execution_key(argv, cwd, timeout, env)
    if identity_context:
        payload = json.dumps(identity_context, sort_keys=True, ensure_ascii=False, default=str)
        key = hashlib.sha256(f"{key}:{payload}".encode()).hexdigest()
    cache = _EXECUTIONS.get()
    fingerprint = ""
    if cache is not None:
        root = _fingerprint_git(cwd, "rev-parse", "--show-toplevel")
        if root is not None and root.returncode == 0:
            fingerprint = worktree_fingerprint(root.stdout.strip())
    key = hashlib.sha256(f"{key}:{fingerprint}".encode()).hexdigest() if fingerprint else ""
    if cache is not None and key and key in cache:
        return {**cache[key], "execution_ms": 0.0, "execution_reused": True}
    started = time.monotonic()
    result = _execute(argv, cwd, timeout, deadline, env)
    result["execution_ms"] = ((time.monotonic() - started) * 1000
                              if result.get("execution_started", True) else 0.0)
    result["execution_reused"] = False
    if cache is not None and key and result["status"] == "ok" and result["returncode"] == 0:
        cache[key] = result
    return result


def hash_worktree_paths(project_root: str, paths: Sequence[str]) -> Optional[list]:
    """Batch-hash worktree file contents (single `git hash-object` process)."""
    if not paths:
        return []
    try:
        completed = subprocess.run(
            ("git", "-C", project_root, "hash-object", "--stdin-paths"),
            input="\n".join(paths) + "\n", text=True, capture_output=True, timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        sys.stderr.write(f"worktree hashing failed: {exc}\n")
        return None
    if completed.returncode != 0:
        return None
    hashes = completed.stdout.splitlines()
    if len(hashes) != len(paths):
        return None
    return [(path, sha.strip()) for path, sha in zip(paths, hashes)]


def _fingerprint_git(root: str, *arguments: str) -> Optional[subprocess.CompletedProcess]:
    try:
        return subprocess.run(
            ("git", "-C", root, *arguments), text=True, encoding="utf-8",
            capture_output=True, check=False, timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        sys.stderr.write(f"worktree fingerprint failed: {exc}\n")
        return None


def _runtime_path(path: str) -> bool:
    return path.startswith(".code-flow/") or Path(path).name == ".acceptance-manifest.json"


def _fingerprint_changes(status: str, contents: dict[str, str], include_untracked: bool,
                         untracked_filter: Optional[Callable[[str], bool]]) -> Optional[list[str]]:
    changed: list[str] = []
    for line in status.splitlines():
        code, path = line[:2], line[3:].strip()
        if " -> " in path:
            path = path.split(" -> ", 1)[1].strip()
        if not path or _runtime_path(path):
            continue
        if path.startswith('"'):
            return None  # Quoted/escaped paths cannot be identified reliably.
        if code.strip() == "??":
            if include_untracked and (untracked_filter is None or untracked_filter(path)):
                changed.append(path)
        elif "D" in code:
            contents.pop(path, None)
        else:
            changed.append(path)
    return changed


def worktree_fingerprint(project_root: str, untracked_filter: Optional[Callable[[str], bool]] = None,
                         include_untracked: bool = True) -> str:
    """Hash real content including new files, excluding workflow runtime state.

    Staging/committing unchanged bytes does not change identity. Ignored files
    never participate; test outputs must be Git-ignored. Explicit check inputs
    are hashed separately. Return an empty identity when it cannot be proven.
    """
    tree = _fingerprint_git(project_root, "ls-tree", "-r", "HEAD")
    status = _fingerprint_git(project_root, "status", "--porcelain", "--untracked-files=all")
    if tree is None or status is None or tree.returncode != 0 or status.returncode != 0:
        return ""
    contents: dict[str, str] = {}
    for line in tree.stdout.splitlines():
        meta, _, path = line.partition("\t")
        fields = meta.split()
        if path and len(fields) >= 3 and not _runtime_path(path):
            contents[path] = fields[2]
    changed = _fingerprint_changes(status.stdout, contents, include_untracked, untracked_filter)
    if changed is None:
        return ""
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
    return digest.hexdigest()


def _execute(argv: Sequence[str], cwd: str, timeout: float, deadline: Optional[float],
             env: Optional[Mapping[str, str]] = None) -> dict[str, object]:
    remaining = remaining_seconds(deadline)
    if remaining is not None and remaining <= 0:
        return {"status": "deadline_exceeded", "returncode": None, "stdout": "", "stderr": "",
                "execution_started": False}
    # When the entry deadline is tighter than the command timeout, expiry is
    # unexecuted work (`incomplete`), never a product failure.
    deadline_bounded = remaining is not None and remaining <= timeout
    effective = min(timeout, remaining) if remaining is not None else timeout
    child_env = command_environment(env)
    try:
        proc = subprocess.Popen(
            list(argv), cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            env=child_env, start_new_session=os.name != "nt",
        )
        out, err = proc.communicate(timeout=max(effective, 0.01))
    except subprocess.TimeoutExpired as exc:
        return _timeout_result(proc, exc, deadline_bounded)
    except OSError as exc:
        return {"status": "spawn_error", "returncode": None, "stdout": "", "stderr": str(exc),
                "execution_started": False}
    return {"status": "ok", "returncode": proc.returncode, "stdout": out or "", "stderr": err or ""}


def _timeout_result(proc: subprocess.Popen, expired: subprocess.TimeoutExpired,
                    deadline_bounded: bool) -> dict[str, object]:
    if os.name != "nt":
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass  # The process group already exited between timeout and kill.
    else:
        subprocess.run(("taskkill", "/F", "/T", "/PID", str(proc.pid)),
                       capture_output=True, timeout=2, check=False)
        proc.kill()
    try:
        out, err = proc.communicate(timeout=1)
    except subprocess.TimeoutExpired:
        out, err = expired.stdout, expired.stderr
        for pipe in (proc.stdout, proc.stderr):
            if pipe is not None:
                pipe.close()
    def tail(value: object) -> str:
        return (value.decode(errors="replace") if isinstance(value, bytes) else str(value or ""))[-4000:]
    return {"status": "deadline_exceeded" if deadline_bounded else "timeout", "returncode": None,
            "stdout": tail(out), "stderr": tail(err)}
