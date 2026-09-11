"""Recoverable two-file workflow commits under the active-task lock."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from cf_spec_context import _acquire_active_lock, _atomic_text, _release_active_lock


def _read(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None


def _write(path: Path, value: Optional[str]) -> None:
    if _read(path) == value:
        return
    if value is None:
        path.unlink()
    else:
        _atomic_text(path, value)


def _journal_path(root: str) -> Path:
    return Path(root) / ".code-flow/.workflow-transition.json"


def _records(root: str, data: object) -> list[dict[str, object]]:
    if not isinstance(data, dict) or data.get("version") != 1:
        raise ValueError("workflow recovery: invalid journal")
    rows = data.get("files")
    if not isinstance(rows, list) or len(rows) != 2:
        raise ValueError("workflow recovery: invalid files")
    base = Path(root).resolve()
    marker = base / ".code-flow/.active-task.json"
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("path"), str):
            raise ValueError("workflow recovery: invalid record")
        path = Path(row["path"]).resolve()
        if base not in path.parents or (path != marker and path.suffix != ".md"):
            raise ValueError("workflow recovery: out-of-scope path")
        for field in ("before", "after"):
            if field not in row or (row[field] is not None and not isinstance(row[field], str)):
                raise ValueError("workflow recovery: invalid contents")
        if _read(path) not in (row["before"], row["after"]):
            raise ValueError(f"workflow recovery: concurrent change to {path}")
    if Path(rows[1]["path"]).resolve() != marker or rows[0]["path"] == rows[1]["path"]:
        raise ValueError("workflow recovery: marker must be last")
    return rows


def recover_transition(root: str) -> bool:
    journal = _journal_path(root)
    if not journal.exists():
        return False
    lock = _acquire_active_lock(root)
    try:
        if not journal.exists():
            return False
        rows = _records(root, json.loads(journal.read_text(encoding="utf-8")))
        for row in rows:
            _write(Path(row["path"]), row["after"])
        journal.unlink()
        return True
    finally:
        _release_active_lock(lock)


def commit_transition(root: str, task: Path, before: str, after: str,
                      marker_before: Optional[str], marker_after: Optional[str]) -> None:
    marker = Path(root).resolve() / ".code-flow/.active-task.json"
    rows = [{"path": str(task.resolve()), "before": before, "after": after},
            {"path": str(marker), "before": marker_before, "after": marker_after}]
    journal = _journal_path(root)
    lock = _acquire_active_lock(root)
    try:
        if journal.exists():
            raise ValueError("workflow recovery required before transition")
        _records(root, {"version": 1, "files": rows})
        if any(_read(Path(row["path"])) != row["before"] for row in rows):
            raise ValueError("workflow concurrent change; retry transition")
        _atomic_text(journal, json.dumps({"version": 1, "files": rows}, ensure_ascii=False))
        try:
            for row in rows:
                _write(Path(row["path"]), row["after"])
        except (OSError, ValueError):
            for row in reversed(rows):
                _write(Path(row["path"]), row["before"])
            journal.unlink()
            raise
        journal.unlink()
    finally:
        _release_active_lock(lock)
