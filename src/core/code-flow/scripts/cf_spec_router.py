#!/usr/bin/env python3
"""Context-first prompt router for task, path, and Catalog modes."""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import tempfile
from typing import Mapping, Optional, Sequence

from cf_core import (
    assemble_context,
    build_effective_mapping,
    build_spec_catalog,
    compress_content,
    load_config,
    parse_spec_frontmatter,
    resolve_compress,
)
from cf_spec_context import ContextError, load_active_task, load_context
from cf_spec_resolver import resolve_candidates
from cf_spec_session import context_sha256, project_task_session


_PROJECTION_CACHE_PATH = ".code-flow/.task-projection-state.json"


@dataclass(frozen=True)
class RouteResult:
    mode: str
    text: str
    specs: tuple[str, ...]
    context_sha256: Optional[str] = None


class RouterError(ValueError):
    """Fail-closed routing error with a stable code."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


def _task_file(task_dir: Path, task_id: str) -> Path:
    matches = []
    for path in sorted(task_dir.glob("*.md")):
        if path.name.endswith((".prd.md", ".design.md")):
            continue
        if f"## {task_id}:" in path.read_text(encoding="utf-8"):
            matches.append(path)
    if len(matches) != 1:
        raise RouterError("task_file_ambiguous", f"{task_id} matched {len(matches)} task files")
    return matches[0]


def _projection_cache_path(root: str) -> Path:
    return Path(root) / _PROJECTION_CACHE_PATH


def _load_projection_cache(root: str) -> Mapping[str, object]:
    try:
        value = json.loads(_projection_cache_path(root).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _cached_projection(
    root: str, task_dir: Path, task_id: str, current_hash: str
) -> Optional[tuple[str, bool]]:
    cache = _load_projection_cache(root)
    if (
        cache.get("version") != 1
        or cache.get("task_id") != task_id
        or cache.get("context_sha256") != current_hash
        or not isinstance(cache.get("task_file"), str)
        or not isinstance(cache.get("text"), str)
        or not isinstance(cache.get("truncated"), bool)
    ):
        return None
    task_file = Path(str(cache["task_file"]))
    if task_file.parent != task_dir or not task_file.is_file():
        return None
    try:
        directory_mtime = task_dir.stat().st_mtime_ns
        task_mtime = task_file.stat().st_mtime_ns
    except OSError:
        return None
    if cache.get("task_dir_mtime_ns") != directory_mtime or cache.get("task_mtime_ns") != task_mtime:
        return None
    return str(cache["text"]), bool(cache["truncated"])


def _save_projection_cache(
    root: str,
    task_dir: Path,
    task_file: Path,
    task_id: str,
    current_hash: str,
    text: str,
    truncated: bool,
) -> None:
    try:
        payload = {
            "version": 1,
            "task_id": task_id,
            "context_sha256": current_hash,
            "task_file": str(task_file),
            "task_dir_mtime_ns": task_dir.stat().st_mtime_ns,
            "task_mtime_ns": task_file.stat().st_mtime_ns,
            "text": text,
            "truncated": truncated,
        }
        path = _projection_cache_path(root)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        os.replace(temporary, path)
    except (OSError, TypeError, UnicodeError):
        if "temporary" in locals() and temporary.exists():
            try:
                temporary.unlink()
            except OSError:
                pass


def _active_route(root: str) -> RouteResult:
    try:
        active = load_active_task(root)
        task_dir = (Path(root) / active.task_dir).resolve()
        context = load_context(str(task_dir / "spec-context.yml"))
    except (ContextError, OSError, ValueError) as exc:
        raise RouterError("invalid_active_task", str(exc)) from exc
    current_hash = context_sha256(context)
    if current_hash != active.context_sha256:
        raise RouterError(
            "active_context_drift",
            "active marker Context hash does not match; run `cf-spec doctor` (resync) to re-sync the marker before continuing",
        )
    cached = _cached_projection(root, task_dir, active.task_id, current_hash)
    if cached is None:
        task_file = _task_file(task_dir, active.task_id)
        projection = project_task_session(context, str(task_file), active.task_id)
        _save_projection_cache(
            root, task_dir, task_file, active.task_id, current_hash, projection.text, projection.truncated
        )
        text, truncated = projection.text, projection.truncated
    else:
        text, truncated = cached
    if truncated:
        raise RouterError("task_projection_truncated", "split the TASK before coding")
    refs = tuple(binding.spec_id for binding in context.bindings)
    return RouteResult("task", text, refs, current_hash)


def _read_candidates(root: str, paths: Sequence[str], compress: bool = True) -> RouteResult:
    try:
        candidates = resolve_candidates(root, "code", tuple(paths))
    except ValueError as exc:
        raise RouterError("invalid_spec_metadata", str(exc)) from exc
    specs = []
    for candidate in candidates:
        if candidate.scope == "unmatched":
            continue
        target = Path(root) / ".code-flow/specs" / candidate.path
        try:
            raw = target.read_text(encoding="utf-8")
        except OSError as exc:
            raise RouterError("spec_read_failed", f"{candidate.path}: {exc}") from exc
        unused_frontmatter, content = parse_spec_frontmatter(raw)
        del unused_frontmatter
        final_content = compress_content(content.strip()) if compress else content.strip()
        specs.append({"path": candidate.path, "content": final_content, "tier": 1})
    text = assemble_context(specs, "## Active Specs (path-mapped)") if specs else ""
    return RouteResult("path", text, tuple(item.path for item in candidates))


def _catalog_path(root: str) -> Path:
    return Path(root) / ".code-flow/.catalog-state.json"


def _load_catalog_state(root: str) -> dict[str, object]:
    path = _catalog_path(root)
    if not path.exists():
        return {"version": 1, "session_id": "", "prompt_count": 0, "last_emitted": 0}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RouterError("invalid_catalog_state", str(exc)) from exc
    if not isinstance(value, dict) or value.get("version") != 1:
        raise RouterError("invalid_catalog_state", "Catalog state schema must be version 1")
    return value


def _save_catalog_state(root: str, state: Mapping[str, object]) -> None:
    path = _catalog_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = ""
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
            temporary = handle.name
            json.dump(state, handle, ensure_ascii=False)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except OSError as exc:
        if temporary and Path(temporary).exists():
            Path(temporary).unlink()
        raise RouterError("catalog_state_write_failed", str(exc)) from exc


def _catalog_route(root: str, session_id: str, config: Mapping[str, object]) -> RouteResult:
    state = _load_catalog_state(root)
    same_session = state.get("session_id") == session_id
    count = int(state.get("prompt_count", 0)) + 1 if same_session else 1
    last = int(state.get("last_emitted", 0)) if same_session else 0
    workflow = config.get("spec_workflow") if isinstance(config.get("spec_workflow"), dict) else {}
    catalog_config = workflow.get("catalog") if isinstance(workflow.get("catalog"), dict) else {}
    window = int(catalog_config.get("dedup_window", 5))
    due = window <= 0 or last == 0 or count - last >= window
    next_state = {"version": 1, "session_id": session_id, "prompt_count": count, "last_emitted": count if due else last}
    _save_catalog_state(root, next_state)
    if not due:
        return RouteResult("catalog", "", ())
    budget = config.get("budget") if isinstance(config.get("budget"), dict) else {}
    maximum = int(budget.get("catalog_max", 200))
    mapping = build_effective_mapping(root, config.get("path_mapping") or {})
    return RouteResult("catalog", build_spec_catalog(root, mapping, maximum), ())


def route_prompt(root: str, paths: Sequence[str], session_id: str) -> RouteResult:
    """Choose exactly one route; an invalid active marker never falls back."""
    marker = Path(root) / ".code-flow/.active-task.json"
    if marker.exists():
        return _active_route(root)
    config = load_config(root)
    if not config:
        return RouteResult("none", "", ())
    if paths:
        quality = config.get("quality_loop")
        return _read_candidates(root, paths, resolve_compress(quality if isinstance(quality, dict) else {}))
    return _catalog_route(root, session_id, config)
