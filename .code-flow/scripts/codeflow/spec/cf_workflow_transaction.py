"""Recoverable workflow commits under the active-task lock."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from codeflow.core import cf_fs
from codeflow.spec.cf_active_task import acquire_active_lock, release_active_lock


def _read(path: Path) -> Optional[str]:
    try:
        return path.read_bytes().decode("utf-8")
    except FileNotFoundError:
        return None


def _write(path: Path, value: Optional[str]) -> None:
    if _read(path) == value:
        return
    if value is None:
        path.unlink()
    else:
        cf_fs.atomic_write_text(path, value)


def _journal_path(root: str) -> Path:
    return Path(root) / ".code-flow/.workflow-transition.json"


def _records(root: str, data: object) -> list[dict[str, object]]:
    if not isinstance(data, dict) or data.get("version") not in (1, 2):
        raise ValueError("workflow recovery: invalid journal")
    rows = data.get("files")
    if not isinstance(rows, list) or len(rows) != (2 if data["version"] == 1 else 3):
        raise ValueError("workflow recovery: invalid files")
    base = Path(root).resolve()
    marker = base / ".code-flow/.active-task.json"
    task_row = rows[-2]
    if not isinstance(task_row, dict) or not isinstance(task_row.get("path"), str):
        raise ValueError("workflow recovery: invalid task record")
    task = Path(task_row["path"]).resolve()
    context = task.parent / "spec-context.yml" if len(rows) == 3 else None
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("path"), str):
            raise ValueError("workflow recovery: invalid record")
        path = Path(row["path"]).resolve()
        if base not in path.parents or (path != marker and path != context and path.suffix != ".md"):
            raise ValueError("workflow recovery: out-of-scope path")
        for field in ("before", "after"):
            if field not in row or (row[field] is not None and not isinstance(row[field], str)):
                raise ValueError("workflow recovery: invalid contents")
        if _read(path) not in (row["before"], row["after"]):
            raise ValueError(f"workflow recovery: concurrent change to {path}")
    if (task.suffix != ".md" or Path(rows[-1]["path"]).resolve() != marker
            or len({str(Path(row["path"]).resolve()) for row in rows}) != len(rows)):
        raise ValueError("workflow recovery: marker must be last")
    if context is not None and Path(rows[0]["path"]).resolve() != context:
        raise ValueError("workflow recovery: invalid Context record")
    return rows


def recover_transition(root: str) -> bool:
    journal = _journal_path(root)
    if not journal.exists():
        return False
    lock = acquire_active_lock(root)
    try:
        if not journal.exists():
            return False
        rows = _records(root, json.loads(journal.read_text(encoding="utf-8")))
        for row in rows:
            _write(Path(row["path"]), row["after"])
        journal.unlink()
        return True
    finally:
        release_active_lock(lock)


def commit_transition(root: str, task: Path, before: str, after: str,
                      marker_before: Optional[str], marker_after: Optional[str], *,
                      context_change: Optional[tuple[Path, str, str]] = None) -> None:
    marker = Path(root).resolve() / ".code-flow/.active-task.json"
    rows = [{"path": str(task.resolve()), "before": before, "after": after},
            {"path": str(marker), "before": marker_before, "after": marker_after}]
    if context_change is not None:
        context, context_before, context_after = context_change
        rows.insert(0, {"path": str(context.resolve()), "before": context_before, "after": context_after})
    record = {"version": 2 if context_change is not None else 1, "files": rows}
    journal = _journal_path(root)
    lock = acquire_active_lock(root)
    try:
        if journal.exists():
            raise ValueError("workflow recovery required before transition")
        _records(root, record)
        if any(_read(Path(row["path"])) != row["before"] for row in rows):
            raise ValueError("workflow concurrent change; retry transition")
        cf_fs.atomic_write_text(journal, json.dumps(record, ensure_ascii=False))
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
        release_active_lock(lock)
