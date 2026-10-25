#!/usr/bin/env python3
"""Per-check input hashing: content-addressed identity for incremental verify.

`check.inputs` declares the files a check depends on. Hashing only those files
lets `changed` rerun affected checks instead of the whole worktree. When inputs
are absent the caller falls back to the repo-wide fingerprint with scope=repo.
"""

from __future__ import annotations

import hashlib
import json
import fnmatch
import re
import subprocess
from pathlib import Path
from typing import Mapping, Optional, Sequence


def glob_to_regex(pattern: str) -> re.Pattern:
    """Translate a git-style glob to regex; `**/` matches zero directories."""
    out: list[str] = []
    index = 0
    while index < len(pattern):
        char = pattern[index]
        if char == "*":
            if pattern[index:index + 3] == "**/":
                out.append("(?:.*/)?")
                index += 3
                continue
            if pattern[index:index + 2] == "**":
                out.append(".*")
                index += 2
                continue
            out.append("[^/]*")
            index += 1
            continue
        if char == "?":
            out.append("[^/]")
        else:
            out.append(re.escape(char))
        index += 1
    return re.compile("^" + "".join(out) + "$")


def match_path(path: str, pattern: str) -> bool:
    normalized = path.replace("\\", "/")
    # Git pathspec: a pattern without a slash matches at any depth.
    if "/" not in pattern:
        return fnmatch.fnmatchcase(normalized.rsplit("/", 1)[-1], pattern)
    return bool(glob_to_regex(pattern).match(normalized))


def _git(root: str, *arguments: str) -> Optional[str]:
    completed = subprocess.run(
        ("git", "-C", root, *arguments), text=True, encoding="utf-8", capture_output=True, check=False
    )
    return completed.stdout if completed.returncode == 0 else None


def expand_inputs(root: str, patterns: Sequence[str]) -> tuple[str, ...]:
    """Tracked + untracked files matching the declared input globs."""
    if not patterns:
        return ()
    tracked = _git(root, "ls-files")
    untracked = _git(root, "ls-files", "--others", "--exclude-standard")
    if tracked is None or untracked is None:
        return ()
    paths: set[str] = set()
    for line in (tracked + untracked).splitlines():
        path = line.strip()
        if path and any(match_path(path, pattern) for pattern in patterns):
            paths.add(path)
    return tuple(sorted(paths))


def hash_files(root: str, paths: Sequence[str]) -> Optional[dict[str, str]]:
    """Batch-hash worktree contents (one git process)."""
    if not paths:
        return {}
    completed = subprocess.run(
        ("git", "-C", root, "hash-object", "--stdin-paths"),
        input="\n".join(paths) + "\n", text=True, encoding="utf-8", capture_output=True, check=False,
    )
    if completed.returncode != 0:
        return None
    hashes = completed.stdout.splitlines()
    if len(hashes) != len(paths):
        return None
    return {path: sha.strip() for path, sha in zip(paths, hashes)}


def check_input_hash(root: str, check: Mapping[str, object],
                     fallback: str = "") -> dict[str, object]:
    """Return {"input_hash", "scope"} for one check."""
    return check_input_hashes(root, {"": check}, fallback)[""]


def _registered_fallback(check: Mapping[str, object], fallback: str) -> str:
    registration = {key: check[key] for key in ("suite", "test_ids", "markers", "collect") if key in check}
    if not fallback or not registration:
        return fallback
    payload = json.dumps([fallback, registration], sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()


def check_input_hashes(root: str, checks: Mapping[str, Mapping[str, object]],
                       fallback: str = "") -> dict[str, dict[str, object]]:
    """Hash the union of all declared inputs once, then derive per-check identities."""
    patterns_by_check: dict[str, list[str]] = {}
    for check_id, check in checks.items():
        value = check.get("inputs")
        patterns_by_check[check_id] = [str(item) for item in value] if isinstance(value, list) else []
    all_patterns = sorted({pattern for values in patterns_by_check.values() for pattern in values})
    repo_files = _repo_files(root) if all_patterns else ()
    matched: dict[str, list[str]] = {}
    union: set[str] = set()
    for check_id, patterns in patterns_by_check.items():
        files = [path for path in repo_files if any(match_path(path, pattern) for pattern in patterns)]
        matched[check_id] = files
        union.update(files)
    hashed = hash_files(root, sorted(union))
    result: dict[str, dict[str, object]] = {}
    for check_id, patterns in patterns_by_check.items():
        bound_fallback = _registered_fallback(checks[check_id], fallback)
        if not patterns:
            result[check_id] = {"input_hash": bound_fallback, "scope": "repo"}
            continue
        if not matched[check_id]:
            result[check_id] = {"input_hash": bound_fallback, "scope": "empty"}
            continue
        if hashed is None:
            result[check_id] = {"input_hash": "", "scope": "unavailable"}
            continue
        check = checks[check_id]
        identity = {
            key: check.get(key) for key in
            ("command", "cwd", "timeout", "env", "env_scope", "preflight", "parallel_safe", "profile")
        }
        identity.update({key: check[key] for key in ("suite", "test_ids", "markers", "collect") if key in check})
        payload = json.dumps(
            [identity, sorted((path, hashed[path]) for path in matched[check_id])],
            ensure_ascii=False, sort_keys=True,
        )
        result[check_id] = {
            "input_hash": hashlib.sha256(payload.encode("utf-8")).hexdigest(),
            "scope": "inputs",
        }
    return result


def _repo_files(root: str) -> tuple[str, ...]:
    tracked = _git(root, "ls-files")
    untracked = _git(root, "ls-files", "--others", "--exclude-standard")
    if tracked is None or untracked is None:
        return ()
    return tuple(sorted({line.strip() for line in (tracked + untracked).splitlines() if line.strip()}))
