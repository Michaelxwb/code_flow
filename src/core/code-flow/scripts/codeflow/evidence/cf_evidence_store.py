#!/usr/bin/env python3
"""Central evidence sidecar: per-check runs, latest pointers and compaction.

Evidence lives outside the worktree so parallel worktrees and plan re-locks
cannot lose or conflict on execution history:

    $(git rev-parse --git-common-dir)/code-flow/evidence/<requirement>/
        <check_id>/<run_id>.json
        <check_id>/latest.json
        _context/<verifier_ref>/<stage>.json   # compacted history sidecar

Non-git projects fall back to ``<project>/.code-flow/evidence/``. All writes
are atomic via ``cf_fs``; runs are deduplicated by ``run_id``
and ``latest.json`` only moves forward. ``compact_context`` keeps the latest
evidence entry per rule/stage and archives older entries with an upper bound.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import shutil
from typing import Iterable, Mapping, Optional, Sequence

from codeflow.core import cf_fs
from codeflow.core import cf_git
from urllib.parse import urlparse

SCHEMA_VERSION = 1
DEFAULT_HISTORY_LIMIT = 200
LATEST_NAME = "latest.json"
HISTORY_DIR = "_context"
CI_STATUSES = frozenset(("passed", "failed", "incomplete"))
_DEFAULT_REQUIREMENT = "_default"
_UNSAFE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_COMMIT = re.compile(r"^[0-9a-f]{7,40}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class EvidenceStoreError(ValueError):
    """Stable, explicit store/compaction failure."""

    def __init__(self, code: str, field: str, message: str, path: str = "") -> None:
        super().__init__(message)
        self.code = code
        self.field = field
        self.message = message
        self.path = path


def _safe_component(value: object, field: str) -> str:
    text = _UNSAFE.sub("_", str(value).strip())
    if not text or text in (".", ".."):
        raise EvidenceStoreError("invalid_component", field, "evidence path component must be non-empty", str(value))
    return text


def _run_git(root: Path, arguments: Sequence[str]) -> Optional[str]:
    """Tolerant git read: non-git projects read as missing (None)."""
    try:
        return cf_git.run_git(str(root), arguments)
    except (cf_git.GitError, UnicodeError):
        return None


def discover_project_root(start: object) -> Path:
    path = Path(start).expanduser()
    if not path.exists():
        path = path.parent
    path = path.resolve()
    if path.is_file():
        path = path.parent
    top = _run_git(path, ("rev-parse", "--show-toplevel"))
    if top and top.strip():
        return Path(top.strip()).resolve()
    for candidate in (path, *path.parents):
        if (candidate / ".code-flow").is_dir():
            return candidate
    return path


def _git_common_dir(project_root: Path) -> Optional[Path]:
    common = _run_git(project_root, ("rev-parse", "--git-common-dir"))
    if not common or not common.strip():
        return None
    resolved = Path(common.strip())
    if not resolved.is_absolute():
        resolved = project_root / resolved
    return resolved.resolve()


def git_commit(start: object) -> str:
    root = discover_project_root(start)
    return (_run_git(root, ("rev-parse", "HEAD")) or "").strip()


def _active_requirement(root: Path) -> str:
    marker = root / ".code-flow" / ".active-task.json"
    try:
        data = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError):
        return ""
    task_dir = data.get("task_dir") if isinstance(data, Mapping) else None
    return requirement_key(task_dir) if isinstance(task_dir, str) and task_dir.strip() else ""


def requirement_key(task_dir: object) -> str:
    """Collision-safe requirement key: date + name when available."""
    path = Path(task_dir)
    name = _safe_component(path.name or _DEFAULT_REQUIREMENT, "requirement")
    parent = path.parent.name
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", parent or ""):
        return f"{parent}--{name}"
    return name


def evidence_root(root: object, requirement: str = "") -> Path:
    project = discover_project_root(root)
    common = _git_common_dir(project)
    base = common / "code-flow" / "evidence" if common is not None else project / ".code-flow" / "evidence"
    name = requirement or _active_requirement(project) or _DEFAULT_REQUIREMENT
    return base / _safe_component(name, "requirement")


def _atomic_text(target: Path, text: str) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        cf_fs.atomic_write_text(target, text)
    except OSError as exc:
        raise EvidenceStoreError("atomic_write_error", "file", str(exc), str(target)) from exc


def _atomic_json(target: Path, payload: Mapping[str, object]) -> None:
    _atomic_text(target, json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=False) + "\n")


def _read_mapping(path: Path) -> Optional[dict[str, object]]:
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError):
        return None
    return dict(loaded) if isinstance(loaded, Mapping) else None


def _ci_text(run: Mapping[str, object], field: str) -> str:
    value = run.get(field)
    if not isinstance(value, str) or not value.strip():
        raise EvidenceStoreError("invalid_ci_run", field, f"CI evidence requires a non-empty {field}")
    return value.strip()


def validate_ci_run(run: Mapping[str, object]) -> None:
    """Reject CI evidence without commit/run_url/exit_code/input_hash provenance."""
    if run.get("source") != "ci":
        raise EvidenceStoreError("invalid_ci_run", "source", "CI evidence requires source=ci")
    run_url = _ci_text(run, "run_url")
    parsed = urlparse(run_url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise EvidenceStoreError("invalid_ci_run", "run_url", "run_url must be an http(s) CI run URL")
    commit = _ci_text(run, "commit")
    if not _COMMIT.match(commit):
        raise EvidenceStoreError("invalid_ci_run", "commit", "commit must be a 7-40 char git sha")
    input_hash = _ci_text(run, "input_hash")
    if not _SHA256.match(input_hash):
        raise EvidenceStoreError("invalid_ci_run", "input_hash", "input_hash must be a sha256 hex digest")
    exit_code = run.get("exit_code")
    if isinstance(exit_code, bool) or not isinstance(exit_code, int):
        raise EvidenceStoreError("invalid_ci_run", "exit_code", "exit_code must be an integer")
    status = _ci_text(run, "status")
    if status not in CI_STATUSES:
        raise EvidenceStoreError("invalid_ci_run", "status", "status must be passed/failed/incomplete")
    _ci_text(run, "run_id")


def _timestamp(value: object) -> float:
    if not isinstance(value, str) or not value.strip():
        return 0.0
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return 0.0
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.timestamp()


def _run_sort_key(run: Mapping[str, object]) -> tuple[float, str]:
    return (_timestamp(run.get("executed_at")), str(run.get("run_id") or run.get("result_sha256") or ""))


def _entry_key(item: Mapping[str, object]) -> tuple[str, str, Optional[str]]:
    identity = item.get("verifier_ref") or item.get("check_id") or item.get("id") or ""
    result = item.get("result_sha256") or item.get("run_id") or ""
    diff = None if item.get("error_code") == "skipped_in_cheap_gate" else item.get("diff_sha256")
    return (str(identity), str(result), diff if isinstance(diff, str) else None)


def _dedupe(entries: Iterable[Mapping[str, object]]) -> list[dict[str, object]]:
    order: list[tuple[str, str, Optional[str]]] = []
    by_key: dict[tuple[str, str, Optional[str]], dict[str, object]] = {}
    for entry in entries:
        item = dict(entry)
        key = _entry_key(item)
        if key in by_key:
            order.remove(key)
        order.append(key)
        by_key[key] = item
    return [by_key[key] for key in order]


def history_file_path(store: "EvidenceStore", check_id: str, stage: str = "code") -> Path:
    return store.directory / HISTORY_DIR / _safe_component(check_id, "check_id") / f"{_safe_component(stage, 'stage')}.json"


def append_history(path: Path, entries: Iterable[Mapping[str, object]], max_history: int = DEFAULT_HISTORY_LIMIT) -> int:
    existing: list[dict[str, object]] = []
    if path.is_file():
        loaded = _read_mapping(path)
        if loaded is not None and isinstance(loaded.get("entries"), list):
            existing = [dict(item) for item in loaded["entries"] if isinstance(item, Mapping)]
        else:
            raise EvidenceStoreError("history_corrupt", "entries", "history sidecar is not a valid entry list", str(path))
    merged = _dedupe([*existing, *entries])
    merged.sort(key=_run_sort_key)
    limit = max(0, int(max_history))
    kept = merged[-limit:] if limit else []
    _atomic_json(path, {"schema": SCHEMA_VERSION, "updated_at": datetime.now(timezone.utc).isoformat(), "entries": kept})
    return len(kept)


class EvidenceStore:
    """One requirement's evidence directory, rooted in the git common dir."""

    def __init__(self, root: object, requirement: str = "") -> None:
        self.root = discover_project_root(root)
        self.requirement = requirement or _active_requirement(self.root) or _DEFAULT_REQUIREMENT
        self.migrated_runs = self.migrate_legacy()

    def _legacy_directories(self) -> list[Path]:
        """Pre-date--name evidence lived under the requirement basename."""
        match = re.fullmatch(r"\d{4}-\d{2}-\d{2}--(.+)", self.requirement)
        name = match.group(1) if match else self.requirement
        if name == self.requirement:
            return []
        project = self.root
        common = _git_common_dir(project)
        central = ((common / "code-flow" / "evidence") if common is not None
                   else (project / ".code-flow" / "evidence"))
        return [path for path in (central / name, project / ".code-flow" / "evidence" / name)
                if path.is_dir() and path.resolve() != self.directory.resolve()]

    def migrate_legacy(self) -> int:
        """Copy old basename evidence into the date--name store without overwriting."""
        copied = 0
        marker = self.directory / ".legacy-migrated"
        if marker.is_file():
            return 0
        for legacy in self._legacy_directories():
            for source in legacy.rglob("*"):
                if not source.is_file():
                    continue
                target = self.directory / source.relative_to(legacy)
                target.parent.mkdir(parents=True, exist_ok=True)
                if not target.exists():
                    shutil.copy2(source, target)
                    copied += 1
        if copied:
            _atomic_text(marker, json.dumps({"copied": copied}) + "\n")
        return copied

    @property
    def directory(self) -> Path:
        return evidence_root(self.root, self.requirement)

    def check_directory(self, check_id: str) -> Path:
        return self.directory / _safe_component(check_id, "check_id")

    def run_path(self, check_id: str, run_id: str) -> Path:
        return self.check_directory(check_id) / f"{_safe_component(run_id, 'run_id')}.json"

    def latest_path(self, check_id: str) -> Path:
        return self.check_directory(check_id) / LATEST_NAME

    def history_path(self, check_id: str, stage: str = "code") -> Path:
        return history_file_path(self, check_id, stage)

    def _update_latest(self, check_id: str, run: Mapping[str, object]) -> None:
        target = self.latest_path(check_id)
        current = _read_mapping(target)
        if current is not None and _run_sort_key(current) > _run_sort_key(run):
            return
        _atomic_json(target, run)

    def write_run(self, check_id: str, run: Mapping[str, object]) -> dict[str, object]:
        if not isinstance(run, Mapping):
            raise EvidenceStoreError("invalid_run", "run", "run must be a mapping")
        data = dict(run)
        identity = str(check_id or data.get("check_id") or "").strip()
        if not identity:
            raise EvidenceStoreError("invalid_run", "check_id", "check_id must be non-empty")
        run_id = data.get("run_id")
        if not isinstance(run_id, str) or not run_id.strip():
            raise EvidenceStoreError("invalid_run", "run_id", "run_id must be non-empty")
        if data.get("source") == "ci":
            validate_ci_run(data)
        data["check_id"] = identity
        target = self.run_path(identity, run_id)
        if target.exists():
            existing = _read_mapping(target)
            self._update_latest(identity, existing if existing is not None else data)
            return {"status": "duplicate", "check_id": identity, "run_id": run_id, "path": str(target)}
        _atomic_json(target, data)
        self._update_latest(identity, data)
        return {"status": "created", "check_id": identity, "run_id": run_id, "path": str(target)}

    def read_run(self, check_id: str, run_id: str) -> Optional[dict[str, object]]:
        return _read_mapping(self.run_path(check_id, run_id))

    def list_runs(self, check_id: str) -> list[dict[str, object]]:
        directory = self.check_directory(check_id)
        if not directory.is_dir():
            return []
        runs: dict[str, dict[str, object]] = {}
        for path in sorted(directory.glob("*.json")):
            item = _read_mapping(path)
            if item is None:
                continue
            run_id = item.get("run_id")
            runs[str(run_id) if isinstance(run_id, str) else path.stem] = item
        return sorted(runs.values(), key=_run_sort_key)

    def read_latest(self, check_id: str) -> Optional[dict[str, object]]:
        # latest.json is only a hint: concurrent worktrees may write it out of
        # order. The run files themselves are immutable and authoritative.
        runs = self.list_runs(check_id)
        return runs[-1] if runs else None

    def store_run(self, check_id: str, run: Mapping[str, object]) -> dict[str, object]:
        return self.write_run(check_id, run)

    def latest(self, check_id: str) -> Optional[dict[str, object]]:
        return self.read_latest(check_id)

    def runs(self, check_id: str) -> list[dict[str, object]]:
        return self.list_runs(check_id)

    def export(self, target: Optional[object] = None) -> dict[str, object]:
        checks: dict[str, list[dict[str, object]]] = {}
        if self.directory.is_dir():
            for directory in sorted(self.directory.iterdir()):
                if directory.is_dir() and directory.name != HISTORY_DIR:
                    runs = self.list_runs(directory.name)
                    if runs:
                        checks[directory.name] = runs
        payload = {
            "schema": SCHEMA_VERSION,
            "requirement": self.requirement,
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "checks": checks,
        }
        if target is None:
            return payload
        destination = Path(target)
        _atomic_json(destination, payload)
        return {"status": "exported", "path": str(destination), "checks": len(checks), "runs": sum(len(items) for items in checks.values())}

    def import_file(self, source: object) -> dict[str, object]:
        path = Path(source)
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, ValueError) as exc:
            raise EvidenceStoreError("import_read_error", "file", str(exc), str(path)) from exc
        if not isinstance(loaded, Mapping):
            raise EvidenceStoreError("invalid_import", "file", "import payload must be a mapping", str(path))
        checks = loaded.get("checks")
        imported = duplicates = 0
        if isinstance(checks, Mapping):
            for check_id, runs in checks.items():
                if not isinstance(runs, list):
                    raise EvidenceStoreError("invalid_import", "checks", "check runs must be a list", str(path))
                for run in runs:
                    if not isinstance(run, Mapping):
                        raise EvidenceStoreError("invalid_import", "run", "run must be a mapping", str(path))
                    outcome = self.write_run(str(check_id), run)
                    imported += outcome["status"] == "created"
                    duplicates += outcome["status"] == "duplicate"
        elif isinstance(loaded.get("runs"), list):
            for run in loaded["runs"]:
                if not isinstance(run, Mapping):
                    raise EvidenceStoreError("invalid_import", "run", "run must be a mapping", str(path))
                check_id = str(run.get("check_id") or run.get("scenario_id") or "unknown")
                outcome = self.write_run(check_id, run)
                imported += outcome["status"] == "created"
                duplicates += outcome["status"] == "duplicate"
        else:
            raise EvidenceStoreError("invalid_import", "file", "import payload needs checks or runs", str(path))
        return {"status": "imported", "imported": imported, "duplicates": duplicates}

    def import_evidence(self, source: object) -> dict[str, object]:
        return self.import_file(source)


def store_run(root: object, requirement: str, check_id: str, run: Mapping[str, object]) -> dict[str, object]:
    return EvidenceStore(root, requirement).write_run(check_id, run)


def read_latest(root: object, requirement: str, check_id: str) -> Optional[dict[str, object]]:
    return EvidenceStore(root, requirement).read_latest(check_id)


def list_runs(root: object, requirement: str, check_id: str) -> list[dict[str, object]]:
    return EvidenceStore(root, requirement).list_runs(check_id)


def export_evidence(root: object, requirement: str, target: object) -> dict[str, object]:
    return EvidenceStore(root, requirement).export(target)


def import_evidence(root: object, requirement: str, source: object) -> dict[str, object]:
    return EvidenceStore(root, requirement).import_file(source)


def compact_evidence(
    evidence: Iterable[Mapping[str, object]] | Mapping[str, object],
    root: Optional[object] = None,
    requirement: str = "",
    check_id: str = "",
    history_path: Optional[object] = None,
    max_history: int = DEFAULT_HISTORY_LIMIT,
    archive: bool = True,
    store: Optional[EvidenceStore] = None,
    stage: str = "code",
) -> tuple[dict[str, object], ...]:
    """Keep only the latest evidence entry; archive older entries to a sidecar."""
    items = [evidence] if isinstance(evidence, Mapping) else list(evidence)
    deduped = _dedupe(item for item in items if isinstance(item, Mapping))
    if not deduped:
        return ()
    latest, older = deduped[-1], deduped[:-1]
    if archive and older:
        target = Path(history_path) if history_path is not None else None
        if target is None:
            active_store = store
            if active_store is None and root is not None:
                active_store = EvidenceStore(root, requirement)
            if active_store is not None:
                identity = check_id or str(latest.get("verifier_ref") or latest.get("check_id") or "context")
                target = active_store.history_path(identity, stage)
        if target is not None:
            append_history(target, older, max_history)
    return (latest,)


def compact_context(
    context: object,
    root: Optional[object] = None,
    requirement: str = "",
    store: Optional[EvidenceStore] = None,
    max_history: int = DEFAULT_HISTORY_LIMIT,
    archive: bool = True,
) -> object:
    """Return a SpecContext whose rule evidence contains only the latest entry."""
    active_store = store
    if active_store is None and root is not None and archive:
        task = getattr(context, "task", "") or requirement
        active_store = EvidenceStore(root, requirement or task)
    bindings = []
    for binding in getattr(context, "bindings", ()):
        rules = []
        for rule in binding.rules:
            statuses = {}
            for stage_name, status in rule.stage_status.items():
                kept = compact_evidence(
                    status.evidence,
                    check_id=rule.verifier_ref or f"{binding.spec_id}#{rule.ref}",
                    store=active_store,
                    max_history=max_history,
                    archive=archive,
                    stage=stage_name,
                )
                statuses[stage_name] = replace(status, evidence=kept)
            rules.append(replace(rule, stage_status=statuses))
        bindings.append(replace(binding, rules=tuple(rules)))
    return replace(context, bindings=tuple(bindings))


def compact_context_file(
    path: object,
    root: Optional[object] = None,
    requirement: str = "",
    max_history: int = DEFAULT_HISTORY_LIMIT,
    archive: bool = True,
) -> dict[str, object]:
    """Compact a persisted spec-context.yml in place and report what changed."""
    from cf_spec_context import load_context, save_context

    context_path = Path(path)
    context = load_context(str(context_path))
    project = root if root is not None else discover_project_root(context_path)
    name = requirement or getattr(context, "task", "") or context_path.parent.name
    store = EvidenceStore(project, name)
    before = sum(
        len(status.evidence)
        for binding in context.bindings
        for rule in binding.rules
        for status in rule.stage_status.values()
    )
    compacted = compact_context(context, store=store, max_history=max_history, archive=archive)
    after = sum(
        len(status.evidence)
        for binding in compacted.bindings
        for rule in binding.rules
        for status in rule.stage_status.values()
    )
    save_context(str(context_path), compacted)
    return {
        "status": "compacted",
        "path": str(context_path),
        "requirement": name,
        "before": before,
        "after": after,
        "archived": max(0, before - after),
        "history_directory": str(store.directory / HISTORY_DIR),
    }
