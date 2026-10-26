#!/usr/bin/env python3
"""L0 Git primitives: one implementation of the git CLI for every consumer."""

from __future__ import annotations

import subprocess
from typing import Mapping, Optional, Sequence

_STATUS_ARGV = ("status", "--porcelain=v1", "-z", "--untracked-files=all")
_STATUS_NO_UNTRACKED_ARGV = ("status", "--porcelain=v1", "-z", "--untracked-files=no")


class GitError(RuntimeError):
    """Stable git failure carrying a machine code and the failing argv."""

    def __init__(self, code: str, message: str, *, argv: Sequence[str] = (),
                 returncode: Optional[int] = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.argv = tuple(argv)
        self.returncode = returncode


def run_git(root: str, argv: Sequence[str], *, timeout: float = 30) -> str:
    """Run git in root and return stdout; any failure raises GitError."""
    try:
        result = subprocess.run(
            ("git", *argv), cwd=root, text=True, encoding="utf-8",
            capture_output=True, check=False, timeout=timeout,
        )
    except OSError as exc:
        raise GitError("git_unavailable", str(exc), argv=argv) from exc
    except subprocess.TimeoutExpired as exc:
        raise GitError("git_timeout", f"git timed out after {timeout}s", argv=argv) from exc
    if result.returncode != 0:
        message = result.stderr.strip() or "Git command failed"
        raise GitError("git_error", message, argv=argv, returncode=result.returncode)
    return result.stdout


def _status_name(code: str) -> str:
    if code == "??":
        return "untracked"
    if "D" in code:
        return "deleted"
    if "A" in code:
        return "added"
    if "M" in code:
        return "modified"
    return "changed"


def changed_entries(root: str, *, include_untracked: bool = True) -> Mapping[str, str]:
    """Working-tree changes keyed by relative path; renames also name the old path."""
    argv = _STATUS_ARGV if include_untracked else _STATUS_NO_UNTRACKED_ARGV
    records = run_git(root, argv).split("\0")
    changes: dict[str, str] = {}
    index = 0
    while index < len(records) and records[index]:
        record = records[index]
        if len(record) < 4:
            raise GitError("invalid_git_status", record, argv=argv)
        code, path = record[:2], record[3:]
        index += 1
        if "R" in code or "C" in code:
            # porcelain -z rename/copy emits two records: "XY <new>" then "<old>"
            if index >= len(records) or not records[index]:
                raise GitError("invalid_git_status", f"{code} {path}", argv=argv)
            old_path = records[index]
            index += 1
            changes[path] = _status_name(code)
            changes[old_path] = "deleted"
            continue
        changes[path] = _status_name(code)
    return changes


def changed_files(root: str, *, include_untracked: bool = True) -> tuple[str, ...]:
    """Relative paths with uncommitted changes (working tree and index)."""
    return tuple(changed_entries(root, include_untracked=include_untracked))


def tracked_files(root: str) -> tuple[str, ...]:
    """Tracked relative paths; non-git projects read as an empty set."""
    try:
        output = run_git(root, ("ls-files",))
    except GitError:
        return ()
    return tuple(
        line.replace("\\", "/").strip() for line in output.splitlines() if line.strip()
    )
