"""Active task marker, lock and Git ownership scope.

The marker is the persisted fact behind a running TASK; the Markdown view is
synced elsewhere. This module owns marker serialization, the cross-process
lock, and the Git baseline that defines owned paths.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from fnmatch import fnmatchcase
import json
import os
from pathlib import Path
from typing import Mapping, Optional, Sequence

from codeflow.core import cf_git
from codeflow.spec.cf_spec_context_model import (
    ContextError,
    atomic_text,
    mapping_field,
    now_iso,
    sequence_field,
    string_field,
)


ACTIVE_STATUSES = frozenset(("activating", "active", "paused", "blocked", "completed"))
DEFAULT_ACTIVE_EXCLUDES = (
    ".code-flow/tasks/*",
    ".code-flow/specs/_session/*",
    ".code-flow/migrations/*",
    ".code-flow/.*state*",
    ".code-flow/.*cache*",
    ".code-flow/.session-log.jsonl",
    ".code-flow/.active-task.json",
    ".code-flow/.active-task.lock",
    ".code-flow/.stop.lock",
    ".code-flow/worktrees/*",
    ".code-flow/sessions/*",
)


@dataclass(frozen=True)
class PathSnapshot:
    status: str
    content_sha256: str


@dataclass(frozen=True)
class ActiveBaseline:
    head: Optional[str]
    captured_at: str
    preexisting_changes: Mapping[str, PathSnapshot]
    # head is frozen at start and never rewritten: task scope is the union of
    # everything committed since head plus all working-tree changes.
    # last_seen_head is observation-only (diagnostics), never scope input.
    last_seen_head: Optional[str] = None


@dataclass(frozen=True)
class ActiveTask:
    version: int
    task_dir: str
    task_id: str
    status: str
    context_sha256: str
    baseline: ActiveBaseline
    owned_paths: tuple[str, ...]
    excluded_paths: tuple[str, ...]


@dataclass(frozen=True)
class DoctorResult:
    action: str
    active: ActiveTask


def active_paths(root: str) -> tuple[Path, Path]:
    flow = Path(root) / ".code-flow"
    return flow / ".active-task.json", flow / ".active-task.lock"


def _context_git_error(exc: cf_git.GitError, root: str) -> ContextError:
    codes = ("git_unavailable", "invalid_git_status")
    code = exc.code if exc.code in codes else "git_error"
    return ContextError(code, "git", exc.message, root)


def _git_head(root: str) -> Optional[str]:
    try:
        return cf_git.run_git(root, ("rev-parse", "HEAD")).strip()
    except cf_git.GitError as exc:
        if "unknown revision" in exc.message or "ambiguous argument" in exc.message:
            return None
        raise _context_git_error(exc, root) from exc


def git_changes(root: str) -> Mapping[str, str]:
    try:
        return cf_git.changed_entries(root)
    except cf_git.GitError as exc:
        raise _context_git_error(exc, root) from exc


def is_excluded(path: str, patterns: Sequence[str]) -> bool:
    return any(fnmatchcase(path, pattern) for pattern in patterns)


def active_data(active: ActiveTask) -> dict[str, object]:
    changes = {
        path: {"status": item.status, "content_sha256": item.content_sha256}
        for path, item in sorted(active.baseline.preexisting_changes.items())
    }
    return {
        "version": active.version,
        "task_dir": active.task_dir,
        "task_id": active.task_id,
        "status": active.status,
        "context_sha256": active.context_sha256,
        "baseline": {
            "head": active.baseline.head,
            "last_seen_head": active.baseline.last_seen_head,
            "captured_at": active.baseline.captured_at,
            "preexisting_changes": changes,
        },
        "owned_paths": list(active.owned_paths),
        "excluded_paths": list(active.excluded_paths),
    }


def _snapshot_from_data(value: object, path: str) -> PathSnapshot:
    data = mapping_field(value, "preexisting_changes[]", path)
    content_hash = data.get("content_sha256")
    return PathSnapshot(
        string_field(data.get("status"), "status", path),
        content_hash if isinstance(content_hash, str) else "",
    )


def active_from_data(value: object, path: str) -> ActiveTask:
    data = mapping_field(value, "active", path)
    baseline_data = mapping_field(data.get("baseline"), "baseline", path)
    raw_changes = mapping_field(
        baseline_data.get("preexisting_changes"), "baseline.preexisting_changes", path
    )
    version = data.get("version")
    head = baseline_data.get("head")
    if version != 1 or (head is not None and not isinstance(head, str)):
        raise ContextError("invalid_active_marker", "version/baseline.head", "schema 不受支持", path)
    status = string_field(data.get("status"), "status", path)
    if status not in ACTIVE_STATUSES:
        raise ContextError("invalid_active_marker", "status", status, path)
    baseline = ActiveBaseline(
        head,
        string_field(baseline_data.get("captured_at"), "captured_at", path),
        {key: _snapshot_from_data(item, path) for key, item in raw_changes.items()},
        baseline_data.get("last_seen_head") if isinstance(baseline_data.get("last_seen_head"), str) else None,
    )
    return ActiveTask(
        1,
        string_field(data.get("task_dir"), "task_dir", path),
        string_field(data.get("task_id"), "task_id", path),
        status,
        string_field(data.get("context_sha256"), "context_sha256", path),
        baseline,
        tuple(string_field(item, "owned_paths[]", path) for item in sequence_field(data.get("owned_paths"), "owned_paths", path)),
        tuple(string_field(item, "excluded_paths[]", path) for item in sequence_field(data.get("excluded_paths"), "excluded_paths", path)),
    )


def save_active_task(root: str, active: ActiveTask) -> None:
    marker = active_paths(root)[0]
    marker.parent.mkdir(parents=True, exist_ok=True)
    atomic_text(marker, json.dumps(active_data(active), ensure_ascii=False, indent=2) + "\n")


def load_active_task(root: str) -> ActiveTask:
    marker = active_paths(root)[0]
    try:
        value = json.loads(marker.read_text(encoding="utf-8"))
        return active_from_data(value, str(marker))
    except ContextError:
        raise
    except (OSError, json.JSONDecodeError) as exc:
        raise ContextError("invalid_active_marker", "active", str(exc), str(marker)) from exc


def _lock_stale(lock: Path) -> bool:
    """A lock is stale when its file is unreadable, carries no valid PID, or the
    owning process is gone. A lock we cannot prove dead is never deleted (PID
    reuse is accepted as a rare race)."""
    try:
        data = json.loads(lock.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return True
    pid = data.get("pid")
    if not isinstance(pid, int) or pid <= 0:
        return True
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return True
    except (PermissionError, OSError):
        return False
    return False


def acquire_active_lock(root: str) -> Path:
    marker, lock = active_paths(root)
    lock.parent.mkdir(parents=True, exist_ok=True)
    descriptor = -1
    for _attempt in range(2):
        try:
            descriptor = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            break
        except FileExistsError:
            if not _lock_stale(lock):
                raise ContextError("active_lock_exists", "active.lock", "运行 doctor 检查残留 lock", str(lock)) from None
            try:
                lock.unlink()
            except OSError as exc:
                raise ContextError("active_lock_exists", "active.lock", f"残留 lock 清理失败: {exc}", str(lock)) from exc
    else:
        raise ContextError("active_lock_exists", "active.lock", "残留 lock 无法清理", str(lock))
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(json.dumps({"pid": os.getpid(), "marker": str(marker)}))
    return lock


def release_active_lock(lock: Path) -> None:
    try:
        lock.unlink()
    except FileNotFoundError:
        return


def committed_since(root: str, base_head: Optional[str]) -> Mapping[str, str]:
    """Paths committed between the frozen baseline head and current HEAD.

    Returns {} when there is no baseline (pre-commit repo) or the range is
    unresolvable (rewritten/pruned history) — working-tree changes still
    flow through business_changes, so scope never goes fully blind.
    """
    if not base_head:
        return {}
    try:
        output = cf_git.run_git(root, ("diff", "--name-status", "-z", base_head, "HEAD", "--"))
    except cf_git.GitError:
        return {}
    names: dict[str, str] = {}
    tokens = output.split("\0")
    index = 0
    while index < len(tokens) and tokens[index]:
        status, index = tokens[index], index + 1
        code = status[:1]
        if code in ("R", "C"):
            if index + 1 >= len(tokens):
                break
            new_path, old_path = tokens[index], tokens[index + 1]
            index += 2
            if new_path:
                names[new_path] = "renamed"
            if old_path:
                names[old_path] = "deleted"
            continue
        if index >= len(tokens) or not tokens[index]:
            break
        names[tokens[index]] = {"M": "modified", "A": "added", "D": "deleted"}.get(code, "changed")
        index += 1
    return names


def business_changes(root: str, excludes: Sequence[str]) -> Mapping[str, str]:
    return {
        path: status
        for path, status in git_changes(root).items()
        if not is_excluded(path, excludes)
    }


def new_active(
    root: str,
    task_dir: str,
    task_id: str,
    context_sha256: str,
    owned_preexisting: Sequence[str],
) -> ActiveTask:
    changes = business_changes(root, DEFAULT_ACTIVE_EXCLUDES)
    owned = tuple(sorted(set(owned_preexisting)))
    unknown = tuple(path for path in owned if path not in changes)
    unowned = tuple(path for path in changes if path not in owned)
    if unknown:
        raise ContextError("unknown_owned_path", "owned_paths", ", ".join(unknown), root)
    if unowned:
        raise ContextError("unowned_changes", "owned_paths", ", ".join(unowned), root)
    # content_sha256 was a per-file hash but is never consumed by any gate (only
    # baseline.head is compared); keep the schema field empty so start never hashes
    # every uncommitted file.
    snapshots = {
        path: PathSnapshot(status, "") for path, status in changes.items()
    }
    head = _git_head(root)
    baseline = ActiveBaseline(head, now_iso(), snapshots, head)
    return ActiveTask(
        1, task_dir, task_id, "activating", context_sha256, baseline, owned, DEFAULT_ACTIVE_EXCLUDES
    )


def start_active_task(
    root: str,
    task_dir: str,
    task_id: str,
    context_sha256: str,
    owned_preexisting: Sequence[str] = (),
) -> ActiveTask:
    marker = active_paths(root)[0]
    lock = acquire_active_lock(root)
    try:
        if marker.exists():
            raise ContextError("active_exists", "active", "当前 worktree 已有 active TASK", str(marker))
        active = new_active(root, task_dir, task_id, context_sha256, owned_preexisting)
        save_active_task(root, active)
        active = replace(active, status="active")
        save_active_task(root, active)
        return active
    finally:
        release_active_lock(lock)


def _transition_active(root: str, expected: Sequence[str], target: str) -> ActiveTask:
    lock = acquire_active_lock(root)
    try:
        active = load_active_task(root)
        if active.status not in expected:
            raise ContextError("invalid_active_transition", "status", f"{active.status} -> {target}", root)
        current_head = _git_head(root)
        if active.baseline.head != current_head:
            # Mid-task commits are a normal workflow. The baseline head stays
            # frozen so committed work never drops out of scope; only the
            # observation field advances for diagnostics.
            active = replace(active, baseline=replace(active.baseline, last_seen_head=current_head))
        updated = replace(active, status=target)
        save_active_task(root, updated)
        return updated
    finally:
        release_active_lock(lock)


def pause_active_task(root: str) -> ActiveTask:
    return _transition_active(root, ("active",), "paused")


def block_active_task(root: str) -> ActiveTask:
    return _transition_active(root, ("active",), "blocked")


def resume_active_task(root: str) -> ActiveTask:
    return _transition_active(root, ("paused", "blocked"), "active")


def current_owned_paths(root: str, active: ActiveTask) -> tuple[str, ...]:
    changes = business_changes(root, active.excluded_paths)
    committed = {
        path: status
        for path, status in committed_since(root, active.baseline.head).items()
        if not is_excluded(path, active.excluded_paths)
    }
    return tuple(sorted(set(active.owned_paths).union(changes).union(committed)))


def complete_active_task(root: str, gate_passed: bool) -> ActiveTask:
    if not gate_passed:
        raise ContextError("gate_failed", "gate", "Done Gate 未通过", root)
    completed = _transition_active(root, ("active",), "completed")
    marker = active_paths(root)[0]
    try:
        marker.unlink()
    except OSError as exc:
        raise ContextError("active_cleanup_failed", "active", str(exc), str(marker)) from exc
    return completed


def doctor_active_task(
    root: str, expected_context_sha256: str, abandon: bool = False, resync: bool = False
) -> DoctorResult:
    marker, lock = active_paths(root)
    try:
        active = load_active_task(root)
    except ContextError as exc:
        raise ContextError("recovery_required", "active", exc.message, str(marker)) from exc
    if abandon:
        marker.unlink()
        release_active_lock(lock)
        return DoctorResult("abandoned", replace(active, status="completed"))
    if resync:
        # Self-heal: the context file is authoritative and the marker hash is a
        # cache. Accept the current context when the marker is the only
        # inconsistency; bind/decision/refresh already re-sync automatically,
        # so this covers legacy markers and manual context edits.
        repaired = replace(active, status="active", context_sha256=expected_context_sha256)
        save_active_task(root, repaired)
        release_active_lock(lock)
        return DoctorResult("resynced", repaired)
    proven = active.context_sha256 == expected_context_sha256
    proven = proven and active.baseline.head == _git_head(root)
    if active.status != "activating" or not proven:
        raise ContextError("recovery_required", "active", "状态或 hash 无法证明可自动恢复", str(marker))
    repaired = replace(active, status="active")
    save_active_task(root, repaired)
    release_active_lock(lock)
    return DoctorResult("resumed", repaired)
