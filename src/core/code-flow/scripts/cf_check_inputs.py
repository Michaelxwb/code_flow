#!/usr/bin/env python3
"""Per-check input hashing: content-addressed identity for incremental verify.

`check.inputs` declares the files a check depends on. Hashing only those files
lets `changed` rerun affected checks instead of the whole worktree. When inputs
are absent the caller falls back to the repo-wide fingerprint with scope=repo.
"""

from __future__ import annotations

import hashlib
import json
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
    return bool(glob_to_regex(pattern).match(path.replace("\\", "/")))


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
    identity = {
        key: check.get(key) for key in
        ("command", "cwd", "timeout", "env", "env_scope", "preflight", "parallel_safe", "profile")
    }
    patterns = [str(item) for item in check.get("inputs", [])] if isinstance(check.get("inputs"), list) else []
    files = expand_inputs(root, patterns)
    if not patterns or not files:
        return {"input_hash": fallback, "scope": "repo" if not patterns else "empty"}
    hashed = hash_files(root, files)
    if hashed is None:
        return {"input_hash": "", "scope": "unavailable"}
    payload = json.dumps([identity, sorted(hashed.items())], ensure_ascii=False, sort_keys=True)
    return {"input_hash": hashlib.sha256(payload.encode("utf-8")).hexdigest(), "scope": "inputs"}
