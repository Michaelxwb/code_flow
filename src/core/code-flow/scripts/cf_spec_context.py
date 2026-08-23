#!/usr/bin/env python3
"""Persisted Spec Context schema, binding and confirmation commands."""

from __future__ import annotations

import argparse
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from fnmatch import fnmatchcase
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from typing import IO, Mapping, Optional, Sequence

import yaml

from cf_spec_metadata import SpecHashes, SpecMetadata, SpecRule, load_spec_metadata
from cf_spec_resolver import SpecCandidate, resolve_candidates


CONTEXT_VERSION = 1
STAGE_STATUSES = frozenset(
    ("pending", "applied", "not_applicable", "waived", "verified", "stale", "conflict", "unverified")
)
DECISION_KINDS = frozenset(("not_applicable", "waived", "manual_verification"))
_AGENT_IDENTITIES = frozenset(("agent", "assistant", "codex", "claude", "opencode", "costrict"))
ACTIVE_STATUSES = frozenset(("activating", "active", "paused", "blocked", "completed"))
DEFAULT_ACTIVE_EXCLUDES = (
    ".code-flow/tasks/*",
    ".code-flow/specs/_session/*",
    ".code-flow/migrations/*",
    ".code-flow/.*state*",
    ".code-flow/.session-log.jsonl",
    ".code-flow/.active-task.json",
    ".code-flow/.active-task.lock",
)


class ContextError(ValueError):
    """A stable context error suitable for JSON CLI output."""

    def __init__(self, code: str, field: str, message: str, path: str = "") -> None:
        self.code = code
        self.field = field
        self.message = message
        self.path = path
        location = f"{path}: " if path else ""
        super().__init__(f"{location}{code} {field}: {message}")

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code, "field": self.field, "message": self.message, "path": self.path}


@dataclass(frozen=True)
class ContextSource:
    type: str
    ref: str


@dataclass(frozen=True)
class Decision:
    kind: str
    reason: str
    confirmed_by: str
    confirmed_at: str
    source: str
    expires_at: Optional[str]


@dataclass(frozen=True)
class ArtifactRef:
    artifact: str
    section_id: str
    item_id: str
    artifact_sha256: str


@dataclass(frozen=True)
class RuleStageStatus:
    status: str
    refs: tuple[ArtifactRef, ...]
    decision: Optional[Decision]
    evidence: tuple[Mapping[str, object], ...]


@dataclass(frozen=True)
class RuleBinding:
    ref: str
    summary: str
    text_sha256: str
    enforcement: str
    verifier_ref: str
    stage_status: Mapping[str, RuleStageStatus]


@dataclass(frozen=True)
class SpecBinding:
    spec_id: str
    path: str
    hashes: SpecHashes
    selected_by: str
    reason: str
    enforcement: str
    stages: tuple[str, ...]
    rules: tuple[RuleBinding, ...]
    status: str = "active"


@dataclass(frozen=True)
class SpecContext:
    version: int
    task: str
    enforcement: str
    updated_at: str
    sources: tuple[ContextSource, ...]
    bindings: tuple[SpecBinding, ...]


@dataclass(frozen=True)
class BindingInput:
    candidate: SpecCandidate
    selected_by: str
    reason: str


@dataclass(frozen=True)
class DriftChange:
    kind: str
    spec_id: str
    rule_ref: str
    old_hash: str
    new_hash: str
    stages: tuple[str, ...]


@dataclass(frozen=True)
class DriftResult:
    context: SpecContext
    changes: tuple[DriftChange, ...]


@dataclass(frozen=True)
class PathSnapshot:
    status: str
    content_sha256: str


@dataclass(frozen=True)
class ActiveBaseline:
    head: Optional[str]
    captured_at: str
    preexisting_changes: Mapping[str, PathSnapshot]


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


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _atomic_text(target: Path, text: str) -> None:
    temporary = ""
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=str(target.parent),
            prefix=f".{target.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary = handle.name
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    except OSError as exc:
        if temporary and Path(temporary).exists():
            Path(temporary).unlink()
        raise ContextError("atomic_write_error", "file", str(exc), str(target)) from exc


def _active_paths(root: str) -> tuple[Path, Path]:
    flow = Path(root) / ".code-flow"
    return flow / ".active-task.json", flow / ".active-task.lock"


def _run_git(root: str, arguments: Sequence[str]) -> str:
    try:
        result = subprocess.run(
            ("git", *arguments), cwd=root, text=True, capture_output=True, check=False
        )
    except OSError as exc:
        raise ContextError("git_unavailable", "git", str(exc), root) from exc
    if result.returncode != 0:
        message = result.stderr.strip() or "Git command failed"
        raise ContextError("git_error", "git", message, root)
    return result.stdout


def _git_head(root: str) -> Optional[str]:
    try:
        return _run_git(root, ("rev-parse", "HEAD")).strip()
    except ContextError as exc:
        if "unknown revision" in exc.message or "ambiguous argument" in exc.message:
            return None
        raise


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


def _git_changes(root: str) -> Mapping[str, str]:
    output = _run_git(root, ("status", "--porcelain=v1", "-z", "--untracked-files=all"))
    records = output.split("\0")
    changes: dict[str, str] = {}
    index = 0
    while index < len(records) and records[index]:
        record = records[index]
        if len(record) < 4:
            raise ContextError("invalid_git_status", "git.status", record, root)
        code, path = record[:2], record[3:]
        index += 1
        if "R" in code or "C" in code:
            # porcelain -z rename/copy emits two records: "XY <new>" then "<old>"
            if index >= len(records) or not records[index]:
                raise ContextError("invalid_git_status", "git.status", f"{code} {path}", root)
            old_path = records[index]
            index += 1
            changes[path] = _status_name(code)
            changes[old_path] = "deleted"
            continue
        changes[path] = _status_name(code)
    return changes


def _is_excluded(path: str, patterns: Sequence[str]) -> bool:
    return any(fnmatchcase(path, pattern) for pattern in patterns)


def _path_hash(root: str, path: str) -> str:
    target = Path(root) / path
    digest = hashlib.sha256()
    if target.is_file():
        with target.open("rb") as handle:
            for chunk in iter(lambda: handle.read(65536), b""):
                digest.update(chunk)
    return digest.hexdigest()


def _active_data(active: ActiveTask) -> dict[str, object]:
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
            "captured_at": active.baseline.captured_at,
            "preexisting_changes": changes,
        },
        "owned_paths": list(active.owned_paths),
        "excluded_paths": list(active.excluded_paths),
    }


def _snapshot_from_data(value: object, path: str) -> PathSnapshot:
    data = _mapping(value, "preexisting_changes[]", path)
    return PathSnapshot(
        _string(data.get("status"), "status", path),
        _string(data.get("content_sha256"), "content_sha256", path),
    )


def _active_from_data(value: object, path: str) -> ActiveTask:
    data = _mapping(value, "active", path)
    baseline_data = _mapping(data.get("baseline"), "baseline", path)
    raw_changes = _mapping(
        baseline_data.get("preexisting_changes"), "baseline.preexisting_changes", path
    )
    version = data.get("version")
    head = baseline_data.get("head")
    if version != 1 or (head is not None and not isinstance(head, str)):
        raise ContextError("invalid_active_marker", "version/baseline.head", "schema 不受支持", path)
    status = _string(data.get("status"), "status", path)
    if status not in ACTIVE_STATUSES:
        raise ContextError("invalid_active_marker", "status", status, path)
    baseline = ActiveBaseline(
        head,
        _string(baseline_data.get("captured_at"), "captured_at", path),
        {key: _snapshot_from_data(item, path) for key, item in raw_changes.items()},
    )
    return ActiveTask(
        1,
        _string(data.get("task_dir"), "task_dir", path),
        _string(data.get("task_id"), "task_id", path),
        status,
        _string(data.get("context_sha256"), "context_sha256", path),
        baseline,
        tuple(_string(item, "owned_paths[]", path) for item in _sequence(data.get("owned_paths"), "owned_paths", path)),
        tuple(_string(item, "excluded_paths[]", path) for item in _sequence(data.get("excluded_paths"), "excluded_paths", path)),
    )


def save_active_task(root: str, active: ActiveTask) -> None:
    marker, unused_lock = _active_paths(root)
    del unused_lock
    marker.parent.mkdir(parents=True, exist_ok=True)
    _atomic_text(marker, json.dumps(_active_data(active), ensure_ascii=False, indent=2) + "\n")


def load_active_task(root: str) -> ActiveTask:
    marker, unused_lock = _active_paths(root)
    del unused_lock
    try:
        value = json.loads(marker.read_text(encoding="utf-8"))
        return _active_from_data(value, str(marker))
    except ContextError:
        raise
    except (OSError, json.JSONDecodeError) as exc:
        raise ContextError("invalid_active_marker", "active", str(exc), str(marker)) from exc


def resync_active_hash(root: str, task_dir: str, current_sha256: str) -> bool:
    """Re-sync the active marker's context hash after toolchain-initiated
    context edits (bind/decision/refresh) so they never surface as
    unrecoverable active_context_drift. No-op without an active marker or when
    the hash already matches; never raises on a missing marker."""
    marker = Path(root) / ".code-flow" / ".active-task.json"
    if not marker.exists():
        return False
    active = load_active_task(root)
    if active.context_sha256 == current_sha256:
        return False
    save_active_task(root, replace(active, context_sha256=current_sha256))
    return True


def _find_root(task_dir: str) -> Optional[str]:
    """Walk up from a task dir to the project root that owns its marker."""
    current = Path(task_dir).resolve()
    for candidate in (current, *current.parents):
        if (candidate / ".code-flow" / ".active-task.json").exists():
            return str(candidate)
    return None


def _resync_after_save(args: argparse.Namespace, context_path: Path) -> bool:
    """Post-save marker re-sync used by CLI commands that persist the context."""
    root = getattr(args, "root", "") or _find_root(str(context_path.parent)) or ""
    if not root:
        return False
    current = context_sha256(load_context(str(context_path)))
    return resync_active_hash(root, str(context_path.parent), current)


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


def _acquire_active_lock(root: str) -> Path:
    marker, lock = _active_paths(root)
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


def _release_active_lock(lock: Path) -> None:
    try:
        lock.unlink()
    except FileNotFoundError:
        return


def _business_changes(root: str, excludes: Sequence[str]) -> Mapping[str, str]:
    return {
        path: status
        for path, status in _git_changes(root).items()
        if not _is_excluded(path, excludes)
    }


def _new_active(
    root: str,
    task_dir: str,
    task_id: str,
    context_sha256: str,
    owned_preexisting: Sequence[str],
) -> ActiveTask:
    changes = _business_changes(root, DEFAULT_ACTIVE_EXCLUDES)
    owned = tuple(sorted(set(owned_preexisting)))
    unknown = tuple(path for path in owned if path not in changes)
    unowned = tuple(path for path in changes if path not in owned)
    if unknown:
        raise ContextError("unknown_owned_path", "owned_paths", ", ".join(unknown), root)
    if unowned:
        raise ContextError("unowned_changes", "owned_paths", ", ".join(unowned), root)
    snapshots = {
        path: PathSnapshot(status, _path_hash(root, path)) for path, status in changes.items()
    }
    baseline = ActiveBaseline(_git_head(root), _now(), snapshots)
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
    marker, unused_lock = _active_paths(root)
    del unused_lock
    lock = _acquire_active_lock(root)
    try:
        if marker.exists():
            raise ContextError("active_exists", "active", "当前 worktree 已有 active TASK", str(marker))
        active = _new_active(root, task_dir, task_id, context_sha256, owned_preexisting)
        save_active_task(root, active)
        active = replace(active, status="active")
        save_active_task(root, active)
        return active
    finally:
        _release_active_lock(lock)


def _transition_active(root: str, expected: Sequence[str], target: str) -> ActiveTask:
    lock = _acquire_active_lock(root)
    try:
        active = load_active_task(root)
        if active.status not in expected:
            raise ContextError("invalid_active_transition", "status", f"{active.status} -> {target}", root)
        current_head = _git_head(root)
        if active.baseline.head != current_head:
            # Mid-task commits are a normal workflow; re-baseline instead of
            # bricking pause/resume/complete on any unrelated commit.
            active = replace(active, baseline=replace(active.baseline, head=current_head))
        updated = replace(active, status=target)
        save_active_task(root, updated)
        return updated
    finally:
        _release_active_lock(lock)


def pause_active_task(root: str) -> ActiveTask:
    return _transition_active(root, ("active",), "paused")


def block_active_task(root: str) -> ActiveTask:
    return _transition_active(root, ("active",), "blocked")


def resume_active_task(root: str) -> ActiveTask:
    return _transition_active(root, ("paused", "blocked"), "active")


def current_owned_paths(root: str, active: ActiveTask) -> tuple[str, ...]:
    changes = _business_changes(root, active.excluded_paths)
    return tuple(sorted(set(active.owned_paths).union(changes)))


def complete_active_task(root: str, gate_passed: bool) -> ActiveTask:
    if not gate_passed:
        raise ContextError("gate_failed", "gate", "Done Gate 未通过", root)
    completed = _transition_active(root, ("active",), "completed")
    marker, unused_lock = _active_paths(root)
    del unused_lock
    try:
        marker.unlink()
    except OSError as exc:
        raise ContextError("active_cleanup_failed", "active", str(exc), str(marker)) from exc
    return completed


def doctor_active_task(
    root: str, expected_context_sha256: str, abandon: bool = False, resync: bool = False
) -> DoctorResult:
    marker, lock = _active_paths(root)
    try:
        active = load_active_task(root)
    except ContextError as exc:
        raise ContextError("recovery_required", "active", exc.message, str(marker)) from exc
    if abandon:
        marker.unlink()
        _release_active_lock(lock)
        return DoctorResult("abandoned", replace(active, status="completed"))
    if resync:
        # Self-heal: the context file is authoritative and the marker hash is a
        # cache. Accept the current context when the marker is the only
        # inconsistency; bind/decision/refresh already re-sync automatically,
        # so this covers legacy markers and manual context edits.
        repaired = replace(active, status="active", context_sha256=expected_context_sha256)
        save_active_task(root, repaired)
        _release_active_lock(lock)
        return DoctorResult("resynced", repaired)
    proven = active.context_sha256 == expected_context_sha256
    proven = proven and active.baseline.head == _git_head(root)
    if active.status != "activating" or not proven:
        raise ContextError("recovery_required", "active", "状态或 hash 无法证明可自动恢复", str(marker))
    repaired = replace(active, status="active")
    save_active_task(root, repaired)
    _release_active_lock(lock)
    return DoctorResult("resumed", repaired)


def _mapping(value: object, field: str, path: str) -> Mapping[str, object]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise ContextError("invalid_context", field, "必须是字符串 key mapping", path)
    return value


def _sequence(value: object, field: str, path: str) -> Sequence[object]:
    if not isinstance(value, list):
        raise ContextError("invalid_context", field, "必须是列表", path)
    return value


def _string(value: object, field: str, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ContextError("invalid_context", field, "必须是非空字符串", path)
    return value.strip()


def _decision_string(value: object, field: str, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ContextError("invalid_decision", field, "必须是非空字符串", path)
    return value.strip()


def _timestamp(value: str, field: str) -> None:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ContextError("invalid_decision", field, "必须是 RFC3339 时间") from exc
    if parsed.tzinfo is None:
        raise ContextError("invalid_decision", field, "必须包含时区")


def _validate_decision(decision: Decision) -> None:
    if decision.kind not in DECISION_KINDS:
        raise ContextError("invalid_decision", "decision.kind", f"不支持 {decision.kind!r}")
    for field in ("reason", "confirmed_by", "confirmed_at", "source"):
        if not getattr(decision, field).strip():
            raise ContextError("invalid_decision", f"decision.{field}", "必须是非空字符串")
    identity = decision.confirmed_by.lower().split(":", 1)[0]
    if identity in _AGENT_IDENTITIES:
        raise ContextError("agent_confirmation_forbidden", "decision.confirmed_by", "Agent 不能自行确认")
    _timestamp(decision.confirmed_at, "decision.confirmed_at")
    if decision.kind == "waived" and not decision.expires_at:
        raise ContextError("invalid_decision", "decision.expires_at", "waived 必须有失效时间")
    if decision.expires_at:
        _timestamp(decision.expires_at, "decision.expires_at")


def _decision_from_data(value: object, path: str) -> Optional[Decision]:
    if value is None:
        return None
    data = _mapping(value, "decision", path)
    expires = data.get("expires_at")
    if expires is not None and not isinstance(expires, str):
        raise ContextError("invalid_decision", "decision.expires_at", "必须是字符串或 null", path)
    decision = Decision(
        _decision_string(data.get("kind"), "decision.kind", path),
        _decision_string(data.get("reason"), "decision.reason", path),
        _decision_string(data.get("confirmed_by"), "decision.confirmed_by", path),
        _decision_string(data.get("confirmed_at"), "decision.confirmed_at", path),
        _decision_string(data.get("source"), "decision.source", path),
        expires,
    )
    _validate_decision(decision)
    return decision


def _decision_data(decision: Optional[Decision]) -> Optional[dict[str, object]]:
    if decision is None:
        return None
    return {
        "kind": decision.kind,
        "reason": decision.reason,
        "confirmed_by": decision.confirmed_by,
        "confirmed_at": decision.confirmed_at,
        "source": decision.source,
        "expires_at": decision.expires_at,
    }


def _artifact_from_data(value: object, path: str) -> ArtifactRef:
    data = _mapping(value, "refs[]", path)
    return ArtifactRef(
        _string(data.get("artifact"), "refs[].artifact", path),
        _string(data.get("section_id"), "refs[].section_id", path),
        _string(data.get("item_id"), "refs[].item_id", path),
        _string(data.get("artifact_sha256"), "refs[].artifact_sha256", path),
    )


def _artifact_data(reference: ArtifactRef) -> dict[str, str]:
    return {
        "artifact": reference.artifact,
        "section_id": reference.section_id,
        "item_id": reference.item_id,
        "artifact_sha256": reference.artifact_sha256,
    }


def _stage_from_data(value: object, field: str, path: str) -> RuleStageStatus:
    data = _mapping(value, field, path)
    status = _string(data.get("status"), f"{field}.status", path)
    if status not in STAGE_STATUSES:
        raise ContextError("invalid_context", f"{field}.status", f"不支持 {status!r}", path)
    refs = tuple(_artifact_from_data(item, path) for item in _sequence(data.get("refs", []), f"{field}.refs", path))
    evidence = tuple(_mapping(item, f"{field}.evidence[]", path) for item in _sequence(data.get("evidence", []), f"{field}.evidence", path))
    decision = _decision_from_data(data.get("decision"), path)
    if status == "applied" and not refs:
        raise ContextError("invalid_context", f"{field}.refs", "applied 必须有 artifact ref", path)
    if status in ("not_applicable", "waived") and decision is None:
        raise ContextError("invalid_context", f"{field}.decision", f"{status} 必须有确认记录", path)
    return RuleStageStatus(status, refs, decision, evidence)


def _stage_data(status: RuleStageStatus) -> dict[str, object]:
    return {
        "status": status.status,
        "refs": [_artifact_data(item) for item in status.refs],
        "decision": _decision_data(status.decision),
        "evidence": [dict(item) for item in status.evidence],
    }


def _rule_from_data(value: object, path: str) -> RuleBinding:
    data = _mapping(value, "rules[]", path)
    stages = _mapping(data.get("stage_status"), "rules[].stage_status", path)
    parsed = {stage: _stage_from_data(item, f"stage_status.{stage}", path) for stage, item in stages.items()}
    return RuleBinding(
        _string(data.get("ref"), "rules[].ref", path),
        _string(data.get("summary"), "rules[].summary", path),
        _string(data.get("text_sha256"), "rules[].text_sha256", path),
        _string(data.get("enforcement"), "rules[].enforcement", path),
        _string(data.get("verifier_ref"), "rules[].verifier_ref", path),
        parsed,
    )


def _rule_data(rule: RuleBinding) -> dict[str, object]:
    return {
        "ref": rule.ref,
        "summary": rule.summary,
        "text_sha256": rule.text_sha256,
        "enforcement": rule.enforcement,
        "verifier_ref": rule.verifier_ref,
        "stage_status": {stage: _stage_data(status) for stage, status in rule.stage_status.items()},
    }


def _hashes_from_data(value: object, path: str) -> SpecHashes:
    data = _mapping(value, "hashes", path)
    return SpecHashes(
        _string(data.get("file_sha256"), "hashes.file_sha256", path),
        _string(data.get("metadata_sha256"), "hashes.metadata_sha256", path),
        _string(data.get("rules_sha256"), "hashes.rules_sha256", path),
    )


def _binding_from_data(value: object, path: str) -> SpecBinding:
    data = _mapping(value, "bindings[]", path)
    stages = tuple(_string(item, "bindings[].stages[]", path) for item in _sequence(data.get("stages"), "bindings[].stages", path))
    rules = tuple(_rule_from_data(item, path) for item in _sequence(data.get("rules"), "bindings[].rules", path))
    return SpecBinding(
        _string(data.get("spec_id"), "bindings[].spec_id", path),
        _string(data.get("path"), "bindings[].path", path),
        _hashes_from_data(data.get("hashes"), path),
        _string(data.get("selected_by"), "bindings[].selected_by", path),
        _string(data.get("reason"), "bindings[].reason", path),
        _string(data.get("enforcement"), "bindings[].enforcement", path),
        stages,
        rules,
        _string(data.get("status", "active"), "bindings[].status", path),
    )


def _binding_data(binding: SpecBinding) -> dict[str, object]:
    return {
        "spec_id": binding.spec_id,
        "path": binding.path,
        "status": binding.status,
        "hashes": {
            "file_sha256": binding.hashes.file_sha256,
            "metadata_sha256": binding.hashes.metadata_sha256,
            "rules_sha256": binding.hashes.rules_sha256,
        },
        "selected_by": binding.selected_by,
        "reason": binding.reason,
        "enforcement": binding.enforcement,
        "stages": list(binding.stages),
        "rules": [_rule_data(rule) for rule in binding.rules],
    }


def context_to_data(context: SpecContext) -> dict[str, object]:
    return {
        "version": context.version,
        "task": context.task,
        "enforcement": context.enforcement,
        "updated_at": context.updated_at,
        "sources": [{"type": item.type, "ref": item.ref} for item in context.sources],
        "bindings": [_binding_data(binding) for binding in context.bindings],
    }


def context_to_identity(context: SpecContext) -> dict[str, object]:
    """Stable identity projection for marker drift detection.

    Excludes volatile runtime state (`updated_at`, `stage_status` including
    evidence timestamps) so the active marker only invalidates when the bound
    rules themselves change (rule/spec text, bindings, sources).
    """
    return {
        "version": context.version,
        "task": context.task,
        "enforcement": context.enforcement,
        "sources": [{"type": item.type, "ref": item.ref} for item in context.sources],
        "bindings": [
            {
                "spec_id": binding.spec_id,
                "path": binding.path,
                "status": binding.status,
                "hashes": {
                    "file_sha256": binding.hashes.file_sha256,
                    "metadata_sha256": binding.hashes.metadata_sha256,
                    "rules_sha256": binding.hashes.rules_sha256,
                },
                "selected_by": binding.selected_by,
                "reason": binding.reason,
                "enforcement": binding.enforcement,
                "stages": list(binding.stages),
                "rules": [
                    {
                        "ref": rule.ref,
                        "summary": rule.summary,
                        "text_sha256": rule.text_sha256,
                        "enforcement": rule.enforcement,
                        "verifier_ref": rule.verifier_ref,
                    }
                    for rule in binding.rules
                ],
            }
            for binding in context.bindings
        ],
    }


def context_sha256(context: SpecContext) -> str:
    """Deterministic identity hash binding the active marker to the bound rules.

    Computed from the stable identity projection (never volatile runtime state),
    so evidence timestamps and stage statuses cannot drift the marker.
    """
    data = yaml.safe_dump(context_to_identity(context), sort_keys=True, allow_unicode=True).encode()
    return hashlib.sha256(data).hexdigest()


def new_context(task: str, sources: Sequence[tuple[str, str]]) -> SpecContext:
    if not task.strip():
        raise ContextError("invalid_context", "task", "必须是非空字符串")
    parsed = tuple(ContextSource(_string(kind, "sources[].type", ""), _string(ref, "sources[].ref", "")) for kind, ref in sources)
    return SpecContext(CONTEXT_VERSION, task.strip(), "required", _now(), parsed, ())


def load_context(path: str) -> SpecContext:
    try:
        loaded = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise ContextError("context_read_error", "file", str(exc), path) from exc
    data = _mapping(loaded, "context", path)
    version = data.get("version")
    if version != CONTEXT_VERSION:
        raise ContextError("unsupported_version", "version", f"仅支持 {CONTEXT_VERSION}，收到 {version!r}", path)
    source_values = _sequence(data.get("sources", []), "sources", path)
    sources = tuple(
        ContextSource(
            _string(_mapping(item, "sources[]", path).get("type"), "sources[].type", path),
            _string(_mapping(item, "sources[]", path).get("ref"), "sources[].ref", path),
        )
        for item in source_values
    )
    bindings = tuple(_binding_from_data(item, path) for item in _sequence(data.get("bindings", []), "bindings", path))
    return SpecContext(
        CONTEXT_VERSION,
        _string(data.get("task"), "task", path),
        _string(data.get("enforcement"), "enforcement", path),
        _string(data.get("updated_at"), "updated_at", path),
        sources,
        bindings,
    )


def save_context(path: str, context: SpecContext) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    text = yaml.safe_dump(context_to_data(context), sort_keys=False, allow_unicode=True)
    try:
        _atomic_text(target, text)
    except ContextError as exc:
        raise ContextError("context_write_error", "file", str(exc), path) from exc


def _binding_from_input(selection: BindingInput) -> SpecBinding:
    if not selection.selected_by.strip() or not selection.reason.strip():
        raise ContextError("invalid_binding", "selection", "selected_by/reason 必须非空")
    candidate = selection.candidate
    verifier_by_rule = {item.rule: item for item in candidate.metadata.verifiers}
    rules: list[RuleBinding] = []
    for rule in candidate.metadata.rules:
        if rule.enforcement == "informational":
            continue
        enforcement = "advisory" if candidate.metadata.enforcement == "advisory" else rule.enforcement
        statuses = {
            stage: RuleStageStatus("pending", (), None, ()) for stage in candidate.metadata.stages
        }
        verifier = verifier_by_rule.get(rule.ref)
        verifier_ref = f"{candidate.spec_id}#{rule.ref}" if verifier is not None else "advisory:none"
        rules.append(RuleBinding(rule.ref, rule.text, rule.text_sha256, enforcement, verifier_ref, statuses))
    return SpecBinding(
        candidate.spec_id,
        candidate.path,
        candidate.metadata.hashes,
        selection.selected_by.strip(),
        selection.reason.strip(),
        candidate.metadata.enforcement,
        candidate.metadata.stages,
        tuple(rules),
    )


def _rule_from_metadata(spec_id: str, metadata: SpecMetadata, rule: SpecRule) -> RuleBinding:
    enforcement = "advisory" if metadata.enforcement == "advisory" else rule.enforcement
    statuses = {stage: RuleStageStatus("pending", (), None, ()) for stage in metadata.stages}
    has_verifier = any(item.rule == rule.ref for item in metadata.verifiers)
    verifier_ref = f"{spec_id}#{rule.ref}" if has_verifier else "advisory:none"
    return RuleBinding(rule.ref, rule.text, rule.text_sha256, enforcement, verifier_ref, statuses)


def bind_specs(context: SpecContext, selections: Sequence[BindingInput]) -> SpecContext:
    bindings = {binding.spec_id: binding for binding in context.bindings}
    for selection in selections:
        incoming = _binding_from_input(selection)
        existing = bindings.get(incoming.spec_id)
        if existing is not None and existing.hashes != incoming.hashes:
            raise ContextError(
                "stale_binding",
                "selection",
                f"{incoming.spec_id} 已绑定版本发生变化，请先 refresh",
            )
        if existing is not None:
            incoming = replace(
                existing,
                selected_by=incoming.selected_by,
                reason=incoming.reason,
                enforcement=incoming.enforcement,
                stages=incoming.stages,
            )
        bindings[incoming.spec_id] = incoming
    ordered = tuple(bindings[key] for key in sorted(bindings))
    if ordered == context.bindings:
        return context
    return replace(context, updated_at=_now(), bindings=ordered)


def refresh_missing_specs(context: SpecContext, root: str) -> SpecContext:
    spec_root = Path(root) / ".code-flow" / "specs"
    bindings: list[SpecBinding] = []
    for binding in context.bindings:
        if (spec_root / binding.path).is_file():
            bindings.append(binding)
            continue
        rules = []
        for rule in binding.rules:
            stages = {stage: replace(status, status="stale") for stage, status in rule.stage_status.items()}
            rules.append(replace(rule, stage_status=stages))
        bindings.append(replace(binding, status="missing", rules=tuple(rules)))
    return replace(context, updated_at=_now(), bindings=tuple(bindings))


def _stale_rule(rule: RuleBinding) -> RuleBinding:
    statuses = {stage: replace(status, status="stale") for stage, status in rule.stage_status.items()}
    return replace(rule, stage_status=statuses)


def _removed_rule(rule: RuleBinding) -> RuleBinding:
    statuses = {
        stage: status
        if status.status in ("not_applicable", "waived") and status.decision is not None
        else replace(status, status="stale")
        for stage, status in rule.stage_status.items()
    }
    return replace(rule, stage_status=statuses)


def _file_sha256(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as exc:
        raise ContextError("artifact_read_error", "artifact", str(exc), str(path)) from exc


def _refresh_artifacts(
    spec_id: str, rule: RuleBinding, artifact_root: Path
) -> tuple[RuleBinding, tuple[DriftChange, ...]]:
    statuses = dict(rule.stage_status)
    changes: list[DriftChange] = []
    for stage, status in rule.stage_status.items():
        for reference in status.refs:
            path = artifact_root / reference.artifact
            current = _file_sha256(path) if path.is_file() else "missing"
            if current == reference.artifact_sha256:
                continue
            if status.status == "applied" and current != "missing":
                statuses[stage] = replace(
                    status,
                    refs=tuple(
                        replace(item, artifact_sha256=current) if item is reference else item
                        for item in status.refs
                    ),
                )
            else:
                statuses[stage] = replace(status, status="stale")
            changes.append(
                DriftChange("artifact_changed", spec_id, rule.ref, reference.artifact_sha256, current, (stage,))
            )
            break
    return replace(rule, stage_status=statuses), tuple(changes)


def _refresh_existing_rule(
    binding: SpecBinding, existing: RuleBinding, current: SpecRule, metadata: SpecMetadata
) -> tuple[RuleBinding, Optional[DriftChange]]:
    enforcement = "advisory" if metadata.enforcement == "advisory" else current.enforcement
    has_verifier = any(item.rule == current.ref for item in metadata.verifiers)
    verifier_ref = f"{binding.spec_id}#{current.ref}" if has_verifier else "advisory:none"
    updated = replace(
        existing,
        summary=current.text,
        text_sha256=current.text_sha256,
        enforcement=enforcement,
        verifier_ref=verifier_ref,
    )
    if existing.text_sha256 == current.text_sha256:
        return updated, None
    change = DriftChange(
        "rule_changed", binding.spec_id, current.ref, existing.text_sha256, current.text_sha256, tuple(existing.stage_status)
    )
    return _stale_rule(updated), change


def _refresh_binding(
    binding: SpecBinding, spec_root: Path, artifact_root: Path
) -> tuple[SpecBinding, tuple[DriftChange, ...]]:
    path = spec_root / binding.path
    if not path.is_file():
        stale = replace(binding, status="missing", rules=tuple(_stale_rule(rule) for rule in binding.rules))
        change = DriftChange("spec_missing", binding.spec_id, "", binding.hashes.file_sha256, "missing", binding.stages)
        return stale, (change,)
    metadata = load_spec_metadata(str(path))
    existing = {rule.ref: rule for rule in binding.rules}
    rules: list[RuleBinding] = []
    changes: list[DriftChange] = []
    if metadata.hashes.metadata_sha256 != binding.hashes.metadata_sha256:
        changes.append(
            DriftChange("metadata_changed", binding.spec_id, "", binding.hashes.metadata_sha256, metadata.hashes.metadata_sha256, ())
        )
    for current in metadata.rules:
        if current.enforcement == "informational":
            continue
        prior = existing.pop(current.ref, None)
        if prior is None:
            rule = _rule_from_metadata(binding.spec_id, metadata, current)
            changes.append(DriftChange("rule_added", binding.spec_id, current.ref, "", current.text_sha256, metadata.stages))
        else:
            rule, change = _refresh_existing_rule(binding, prior, current, metadata)
            if change is not None:
                changes.append(change)
        rule, artifact_changes = _refresh_artifacts(binding.spec_id, rule, artifact_root)
        rules.append(rule)
        changes.extend(artifact_changes)
    for removed in existing.values():
        rules.append(_removed_rule(removed))
        changes.append(DriftChange("rule_removed", binding.spec_id, removed.ref, removed.text_sha256, "missing", tuple(removed.stage_status)))
    updated = replace(binding, hashes=metadata.hashes, enforcement=metadata.enforcement, stages=metadata.stages, rules=tuple(rules), status="active")
    return updated, tuple(changes)


def refresh_context(context: SpecContext, root: str, artifact_root: Optional[str] = None) -> DriftResult:
    specs = Path(root) / ".code-flow" / "specs"
    artifacts = Path(artifact_root) if artifact_root is not None else Path(root)
    bindings: list[SpecBinding] = []
    changes: list[DriftChange] = []
    for binding in context.bindings:
        updated, binding_changes = _refresh_binding(binding, specs, artifacts)
        bindings.append(updated)
        changes.extend(binding_changes)
    refreshed = replace(context, updated_at=_now(), bindings=tuple(bindings))
    if refreshed.bindings == context.bindings:
        return DriftResult(context, tuple(changes))
    return DriftResult(refreshed, tuple(changes))


def diff_spec_hashes(context: SpecContext, root: str) -> DriftResult:
    return refresh_context(context, root)


def apply_decision(
    context: SpecContext,
    spec_id: str,
    rule_ref: str,
    stage: str,
    decision: Decision,
    batch: bool = False,
) -> SpecContext:
    if batch:
        raise ContextError("batch_confirmation_forbidden", "batch", "N/A/豁免必须逐项确认")
    _validate_decision(decision)
    target_status = {"not_applicable": "not_applicable", "waived": "waived", "manual_verification": "verified"}[decision.kind]
    found = False
    bindings: list[SpecBinding] = []
    for binding in context.bindings:
        changed_rules: list[RuleBinding] = []
        for rule in binding.rules:
            if binding.spec_id == spec_id and rule.ref == rule_ref:
                if stage not in rule.stage_status:
                    raise ContextError("unknown_stage", "stage", f"Rule 不适用于 {stage}")
                statuses = dict(rule.stage_status)
                statuses[stage] = replace(statuses[stage], status=target_status, decision=decision)
                rule = replace(rule, stage_status=statuses)
                found = True
            changed_rules.append(rule)
        bindings.append(replace(binding, rules=tuple(changed_rules)))
    if not found:
        raise ContextError("unknown_rule", "rule_ref", f"未找到 {spec_id}#{rule_ref}")
    return replace(context, updated_at=_now(), bindings=tuple(bindings))


def _upsert_artifact_ref(
    references: Sequence[ArtifactRef], replacement: ArtifactRef
) -> tuple[ArtifactRef, ...]:
    identity = (replacement.artifact, replacement.section_id, replacement.item_id)
    updated: list[ArtifactRef] = []
    replaced = False
    for reference in references:
        current = (reference.artifact, reference.section_id, reference.item_id)
        if current != identity:
            updated.append(reference)
        elif not replaced:
            updated.append(replacement)
            replaced = True
    if not replaced:
        updated.append(replacement)
    return tuple(updated)


def apply_artifact_ref(
    context: SpecContext,
    spec_id: str,
    rule_ref: str,
    stage: str,
    reference: ArtifactRef,
) -> SpecContext:
    found = False
    bindings: list[SpecBinding] = []
    for binding in context.bindings:
        rules: list[RuleBinding] = []
        for rule in binding.rules:
            if binding.spec_id == spec_id and rule.ref == rule_ref:
                if stage not in rule.stage_status:
                    raise ContextError("unknown_stage", "stage", f"Rule 不适用于 {stage}")
                statuses = dict(rule.stage_status)
                current = statuses[stage]
                refs = _upsert_artifact_ref(current.refs, reference)
                if current.decision is not None:
                    statuses[stage] = replace(current, refs=refs)
                else:
                    statuses[stage] = replace(current, status="applied", refs=refs)
                rule = replace(rule, stage_status=statuses)
                found = True
            rules.append(rule)
        bindings.append(replace(binding, rules=tuple(rules)))
    if not found:
        raise ContextError("unknown_rule", "rule_ref", f"未找到 {spec_id}#{rule_ref}")
    return replace(context, updated_at=_now(), bindings=tuple(bindings))


def _json_payload(stream: IO[str]) -> Mapping[str, object]:
    try:
        loaded = json.load(stream)
    except (json.JSONDecodeError, UnicodeError) as exc:
        raise ContextError("invalid_json", "stdin", str(exc)) from exc
    return _mapping(loaded, "stdin", "")


def _candidate_data(candidate: SpecCandidate) -> dict[str, object]:
    return {
        "spec_id": candidate.spec_id,
        "path": candidate.path,
        "scope": candidate.scope,
        "priority": candidate.priority,
        "matched_paths": list(candidate.matched_paths),
        "description": candidate.metadata.description,
        "enforcement": candidate.metadata.enforcement,
        "stages": list(candidate.metadata.stages),
        "hashes": {
            "file_sha256": candidate.metadata.hashes.file_sha256,
            "metadata_sha256": candidate.metadata.hashes.metadata_sha256,
            "rules_sha256": candidate.metadata.hashes.rules_sha256,
        },
        "rules": [
            {"ref": rule.ref, "text": rule.text, "enforcement": rule.enforcement}
            for rule in candidate.metadata.rules
        ],
    }


def _catalog_command(args: argparse.Namespace) -> dict[str, object]:
    candidates = resolve_candidates(args.root, args.stage, tuple(args.paths))
    return {
        "ok": True,
        "stage": args.stage,
        "total": len(candidates),
        "candidates": [_candidate_data(item) for item in candidates],
    }


def _application_ref(task_dir: str, value: Mapping[str, object]) -> ArtifactRef:
    artifact = _string(value.get("artifact"), "applications[].artifact", "")
    base = Path(task_dir).resolve()
    target = (base / artifact).resolve()
    if base != target and base not in target.parents:
        raise ContextError("artifact_outside_task", "applications[].artifact", artifact, task_dir)
    try:
        artifact_hash = hashlib.sha256(target.read_bytes()).hexdigest()
    except OSError as exc:
        raise ContextError("artifact_read_error", "applications[].artifact", str(exc), str(target)) from exc
    return ArtifactRef(
        artifact,
        _string(value.get("section_id"), "applications[].section_id", ""),
        _string(value.get("item_id"), "applications[].item_id", ""),
        artifact_hash,
    )


def _apply_payload(context: SpecContext, task_dir: str, payload: Mapping[str, object]) -> SpecContext:
    updated = context
    for raw in _sequence(payload.get("applications", []), "applications", ""):
        item = _mapping(raw, "applications[]", "")
        updated = apply_artifact_ref(
            updated,
            _string(item.get("spec_id"), "applications[].spec_id", ""),
            _string(item.get("rule_ref"), "applications[].rule_ref", ""),
            _string(item.get("stage"), "applications[].stage", ""),
            _application_ref(task_dir, item),
        )
    return updated


def _decision_command(args: argparse.Namespace, payload: Mapping[str, object]) -> dict[str, object]:
    context_path = Path(args.task_dir) / "spec-context.yml"
    decision = _decision_from_data(payload.get("decision"), str(context_path))
    if decision is None:
        raise ContextError("invalid_decision", "decision", "必须提供 decision")
    context = apply_decision(
        load_context(str(context_path)),
        _string(payload.get("spec_id"), "spec_id", ""),
        _string(payload.get("rule_ref"), "rule_ref", ""),
        _string(payload.get("stage"), "stage", ""),
        decision,
        payload.get("batch") is True,
    )
    save_context(str(context_path), context)
    _resync_after_save(args, context_path)
    return {"ok": True, "status": context.bindings[0].rules[0].stage_status[_string(payload.get("stage"), "stage", "")].status}


def _bind_command(args: argparse.Namespace, payload: Mapping[str, object]) -> dict[str, object]:
    context_path = Path(args.task_dir) / "spec-context.yml"
    paths = tuple(_string(item, "paths[]", "") for item in _sequence(payload.get("paths", []), "paths", ""))
    candidates = {item.spec_id: item for item in resolve_candidates(args.root, args.stage, paths)}
    selections: list[BindingInput] = []
    for raw in _sequence(payload.get("selections"), "selections", ""):
        item = _mapping(raw, "selections[]", "")
        spec_id = _string(item.get("spec_id"), "selections[].spec_id", "")
        if spec_id not in candidates:
            raise ContextError("unknown_candidate", "selections[].spec_id", spec_id)
        selections.append(
            BindingInput(
                candidates[spec_id],
                _string(item.get("selected_by"), "selections[].selected_by", ""),
                _string(item.get("reason"), "selections[].reason", ""),
            )
        )
    if context_path.exists():
        context = load_context(str(context_path))
    else:
        task = _string(payload.get("task"), "task", "")
        context = new_context(task, (("cli", "bind"),))
    context = bind_specs(context, selections)
    context = _apply_payload(context, args.task_dir, payload)
    save_context(str(context_path), context)
    _resync_after_save(args, context_path)
    applied = sum(
        status.status == "applied"
        for binding in context.bindings
        for rule in binding.rules
        for status in rule.stage_status.values()
    )
    return {"ok": True, "bindings": len(context.bindings), "applied": applied}


def _active_command(args: argparse.Namespace, payload: Mapping[str, object]) -> dict[str, object]:
    if args.active_action == "start":
        owned = tuple(
            _string(item, "owned_paths[]", "")
            for item in _sequence(payload.get("owned_paths", []), "owned_paths", "")
        )
        active = start_active_task(
            args.root, args.task_dir, args.task, args.context_sha256, owned
        )
        return {"ok": True, "active": _active_data(active)}
    if args.active_action == "pause":
        active = pause_active_task(args.root)
    elif args.active_action == "resume":
        active = resume_active_task(args.root)
    elif args.active_action == "block":
        active = block_active_task(args.root)
    elif args.active_action == "complete":
        active = complete_active_task(args.root, payload.get("gate_passed") is True)
    else:
        result = doctor_active_task(
            args.root,
            args.context_sha256,
            payload.get("abandon") is True,
            payload.get("resync") is True,
        )
        return {"ok": True, "action": result.action, "active": _active_data(result.active)}
    return {"ok": True, "active": _active_data(active)}


def _status_command(args: argparse.Namespace) -> dict[str, object]:
    """Human-readable Spec Context status: task, marker health, gate, rules."""
    from cf_spec_gate import result_to_data, validate_stage  # local import avoids module cycle

    context_path = Path(args.task_dir) / "spec-context.yml"
    context = load_context(str(context_path))
    gate = validate_stage(context, "code")
    root = getattr(args, "root", "") or _find_root(args.task_dir) or ""
    marker: dict[str, object] = {"exists": False}
    if root:
        marker_path = Path(root) / ".code-flow" / ".active-task.json"
        if marker_path.exists():
            active = load_active_task(root)
            marker = {
                "exists": True,
                "task_id": active.task_id,
                "status": active.status,
                "hash_match": active.context_sha256 == context_sha256(context),
                "baseline_head": active.baseline.head,
            }
    bindings = []
    for binding in context.bindings:
        rules = []
        for rule in binding.rules:
            status = rule.stage_status.get("code")
            rules.append(
                {
                    "ref": f"{binding.spec_id}#{rule.ref}",
                    "enforcement": rule.enforcement,
                    "status": status.status if status else "missing",
                    "verifier": rule.verifier_ref,
                }
            )
        bindings.append({"spec_id": binding.spec_id, "path": binding.path, "status": binding.status, "rules": rules})
    return {
        "task": context.task,
        "context_sha256": context_sha256(context),
        "gate": result_to_data(gate),
        "marker": marker,
        "bindings": bindings,
    }


def _status_text(data: dict[str, object]) -> str:
    lines = [f"# {data['task']} — Spec Context 状态"]
    marker = data["marker"]
    if marker["exists"]:
        match = "✓ 一致" if marker["hash_match"] else "✗ 漂移"
        lines.append(f"- TASK {marker['task_id']}（{marker['status']}），marker hash {match}")
        if not marker["hash_match"]:
            lines.append("  下一步: 运行 cf-spec doctor（resync 可自动重同步）")
    else:
        lines.append("- 无 active TASK（path/catalog 路由模式）")
    gate = data["gate"]
    if gate["decision"] == "pass":
        lines.append("- code Gate: ✓ pass")
    else:
        lines.append(f"- code Gate: ✗ block（{len(gate['errors'])} 项）")
        for issue in gate["errors"]:
            lines.append(f"  ✗ {issue['message']}")
    for binding in data["bindings"]:
        lines.append(f"- {binding['spec_id']}（{binding['path']}）— {binding['status']}")
        for rule in binding["rules"]:
            lines.append(f"  {rule['status']:<12} {rule['ref']}（{rule['verifier']}）")
    return "\n".join(lines)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="cf_spec_context.py")
    commands = parser.add_subparsers(dest="command", required=True)
    catalog = commands.add_parser("catalog")
    catalog.add_argument("--root", required=True)
    catalog.add_argument("--stage", required=True)
    catalog.add_argument("--paths", nargs="*", default=())
    catalog.add_argument("--json", action="store_true")
    decision = commands.add_parser("decision")
    decision.add_argument("--task-dir", required=True)
    decision.add_argument("--json", action="store_true")
    bind = commands.add_parser("bind")
    bind.add_argument("--task-dir", required=True)
    bind.add_argument("--root", required=True)
    bind.add_argument("--stage", required=True)
    bind.add_argument("--json", action="store_true")
    validate = commands.add_parser("validate")
    validate.add_argument("--task-dir", required=True)
    validate.add_argument("--json", action="store_true")
    status = commands.add_parser("status")
    status.add_argument("--task-dir", required=True)
    status.add_argument("--root", default="")
    status.add_argument("--json", action="store_true")
    for name in ("refresh", "refresh-missing"):
        refresh = commands.add_parser(name)
        refresh.add_argument("--task-dir", required=True)
        refresh.add_argument("--root", required=True)
        refresh.add_argument("--json", action="store_true")
    active = commands.add_parser("active")
    active_actions = active.add_subparsers(dest="active_action", required=True)
    for action in ("start", "pause", "resume", "block", "complete", "doctor"):
        command = active_actions.add_parser(action)
        command.add_argument("--root", required=True)
        command.add_argument("--task-dir", required=True)
        command.add_argument("--task", required=True)
        command.add_argument("--context-sha256", required=True)
        command.add_argument("--json", action="store_true")
    return parser


def _execute(args: argparse.Namespace, stdin: IO[str]) -> dict[str, object]:
    if args.command == "catalog":
        return _catalog_command(args)
    if args.command == "active":
        return _active_command(args, _json_payload(stdin))
    context_path = Path(args.task_dir) / "spec-context.yml"
    if args.command == "decision":
        return _decision_command(args, _json_payload(stdin))
    if args.command == "bind":
        return _bind_command(args, _json_payload(stdin))
    if args.command == "validate":
        context = load_context(str(context_path))
        return {"ok": True, "task": context.task, "bindings": len(context.bindings)}
    if args.command == "refresh-missing":
        context = refresh_missing_specs(load_context(str(context_path)), args.root)
        changes: tuple[DriftChange, ...] = ()
    else:
        result = refresh_context(load_context(str(context_path)), args.root, artifact_root=args.task_dir)
        context, changes = result.context, result.changes
    save_context(str(context_path), context)
    _resync_after_save(args, context_path)
    return {
        "ok": True,
        "missing": sum(item.status == "missing" for item in context.bindings),
        "changes": [change.__dict__ for change in changes],
    }


def main(argv: Optional[Sequence[str]] = None, stdin: IO[str] = sys.stdin, stdout: IO[str] = sys.stdout) -> int:
    try:
        args = _parser().parse_args(argv)
        if args.command == "status":
            data = _status_command(args)
            if args.json:
                stdout.write(json.dumps(data, ensure_ascii=False))
            else:
                stdout.write(_status_text(data) + "\n")
            return 0
        result = _execute(args, stdin)
        stdout.write(json.dumps(result, ensure_ascii=False))
        return 0
    except ContextError as exc:
        stdout.write(json.dumps({"ok": False, "error": exc.to_dict()}, ensure_ascii=False))
        return 3
    except Exception as exc:
        sys.stderr.write(f"cf_spec_context unexpected error: {exc}\n")
        stdout.write(json.dumps({"ok": False, "error": {"code": "internal_error"}}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
