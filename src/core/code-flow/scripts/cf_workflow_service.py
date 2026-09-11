#!/usr/bin/env python3
"""Unified workflow state machine: single entry for task state transitions.

Markdown task files are a readable view; the active marker plus Context are
the facts. Every transition below validates preconditions, mutates the marker
through cf_spec_context primitives, and syncs the Markdown view in the same
call with a recovery journal. Interrupted transitions can be rolled forward;
concurrent user edits block recovery instead of being overwritten.
"""

from __future__ import annotations

import re
import json
from dataclasses import replace
from datetime import date
from pathlib import Path
from typing import Mapping, Optional, Sequence
from cf_spec_context import ActiveTask, SpecContext
from cf_workflow_transaction import recover_transition
from cf_task_state import FINISHED_STATUSES


class WorkflowError(ValueError):
    """Fail-closed transition error with a stable code."""

    def __init__(self, code: str, message: str, details: tuple[str, ...] = ()) -> None:
        self.code = code
        self.details = details
        super().__init__(f"[{code}] {message}" + (f": {'; '.join(details)}" if details else ""))


def locate_task_file(task_dir: str, task_id: str) -> Optional[Path]:
    """Find the unique task file containing the TASK section."""
    matches: list[Path] = []
    try:
        files = sorted(Path(task_dir).glob("*.md"))
    except OSError:
        return None
    for path in files:
        if path.name.endswith((".prd.md", ".design.md")):
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            continue
        if f"## {task_id}:" in content:
            matches.append(path)
    return matches[0] if len(matches) == 1 else None


def read_task_section(task_file: str, task_id: str) -> str:
    try:
        text = Path(task_file).read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise WorkflowError("task_read_error", str(exc)) from exc
    start = text.find(f"## {task_id}:")
    if start == -1:
        raise WorkflowError("task_not_found", task_id, (task_file,))
    end = text.find("\n## TASK-", start)
    return text[start:] if end == -1 else text[start:end]


def section_status(section: str) -> str:
    """Markdown status; absent Status line means draft (pre-contract tasks)."""
    match = re.search(r"(?m)^- \*\*Status\*\*:[ \t]*([^\n]+)", section)
    return match.group(1).strip() if match else "draft"


def section_depends(section: str) -> tuple[str, ...]:
    match = re.search(r"(?m)^- \*\*Depends\*\*:[ \t]*([^\n]*)", section)
    if match is None:
        return ()
    return tuple(part.strip() for part in re.split(r"[,，\s]+", match.group(1).strip()) if re.fullmatch(r"TASK-\d+", part.strip()))


def section_notes(section: str) -> tuple[str, ...]:
    return tuple(
        line.strip()
        for line in section.splitlines()
        if "#NOTES" in line
    )


def _all_statuses(task_file: str) -> Mapping[str, str]:
    try:
        text = Path(task_file).read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return {}
    statuses: dict[str, str] = {}
    for match in re.finditer(r"(?m)^## (TASK-\d+):[^\n]*$", text):
        section = read_task_section(task_file, match.group(1))
        statuses[match.group(1)] = section_status(section)
    return statuses


def check_startable(task_file: str, task_id: str) -> list[str]:
    """Collectors of start blockers; empty means the TASK may start."""
    section = read_task_section(task_file, task_id)
    status = section_status(section)
    blockers: list[str] = []
    if status == "blocked":
        blockers.append(f"{task_id} is blocked; resolve Log BLOCKED entries first")
    elif status == "done":
        blockers.append(f"{task_id} is already done; verify contract or reopen explicitly")
    elif status not in ("draft", "in-progress"):
        blockers.append(f"{task_id} has unexpected status '{status}'")
    notes = section_notes(section)
    if notes:
        blockers.append(f"{len(notes)} unresolved #NOTES: {notes[0][:80]}")
    statuses = _all_statuses(task_file)
    unmet = [dep for dep in section_depends(section) if statuses.get(dep) not in FINISHED_STATUSES]
    if unmet:
        rendered = ", ".join(dep + "(" + str(statuses.get(dep, "missing")) + ")" for dep in unmet)
        blockers.append("unmet depends: " + rendered)
    return blockers


def _today() -> str:
    return date.today().isoformat()


def _set_status(section: str, status: str, log_line: str = "") -> str:
    if re.search(r"(?m)^- \*\*Status\*\*:", section):
        section = re.sub(r"(?m)^- \*\*Status\*\*:.*$", f"- **Status**: {status}", section, count=1)
    else:
        anchor = re.search(r"(?m)^## TASK-\d+:.*$", section)
        insert_at = anchor.end() if anchor else 0
        section = section[:insert_at] + f"\n- **Status**: {status}" + section[insert_at:]
    if log_line and log_line not in section.splitlines():
        section = section.rstrip() + ("\n" if "### Log" in section else "\n\n### Log\n") + log_line + "\n"
    return section


def _render_markdown(text: str, task_id: str, status: str, log_line: str = "", prepend: str = "") -> str:
    match = re.search(rf"(?ms)^## {re.escape(task_id)}:.*?(?=^## |\Z)", text)
    if match is None:
        raise WorkflowError("task_not_found", task_id)
    section = _set_status(match.group(0), status, log_line)
    if prepend and prepend not in section:
        section = section.replace("### Log", prepend + "\n### Log", 1) if "### Log" in section else section + "\n" + prepend + "\n"
    text = text[:match.start()] + section + text[match.end():]
    return re.sub(r"(?m)^- \*\*Updated\*\*:.*$", f"- **Updated**: {_today()}", text, count=1)


def _sync_markdown(task_file: str, task_id: str, status: str, log_line: str = "", prepend: str = "") -> str:
    from cf_spec_context import _atomic_text
    target = Path(task_file)
    text = target.read_text(encoding="utf-8")
    _atomic_text(target, _render_markdown(text, task_id, status, log_line, prepend))
    return "synced"


def _commit_state(root: str, task_file: str, task_id: str, status: str, previous: Optional[ActiveTask],
                  updated: Optional[ActiveTask], log_line: str = "", prepend: str = "") -> str:
    from cf_spec_context import _active_data
    from cf_workflow_transaction import commit_transition
    marker = Path(root) / ".code-flow/.active-task.json"
    marker_before = marker.read_text(encoding="utf-8") if marker.exists() else None
    actual = json.loads(marker_before) if marker_before is not None else None
    expected = _active_data(previous) if previous is not None else None
    if actual != expected:
        raise WorkflowError("active_mismatch", "active task changed before commit")
    marker_after = json.dumps(_active_data(updated), ensure_ascii=False, indent=2) + "\n" if updated is not None else None
    task = Path(task_file)
    before = task.read_text(encoding="utf-8")
    after = _render_markdown(before, task_id, status, log_line, prepend)
    try:
        commit_transition(root, task, before, after, marker_before, marker_after)
    except (OSError, ValueError) as exc:
        raise WorkflowError("transition_failed", str(exc)) from exc
    return "synced"


def _resolve_paths(root: str, task_dir: str, task_file: str) -> tuple[Path, Path]:
    base = Path(root)
    directory = Path(task_dir) if Path(task_dir).is_absolute() else base / task_dir
    candidate = Path(task_file) if Path(task_file).is_absolute() else base / task_file
    if base.resolve() not in candidate.resolve().parents or candidate.parent.resolve() != directory.resolve() or not candidate.is_file():
        raise WorkflowError("invalid_task_file", str(candidate), (str(directory),))
    return directory, candidate


def _validate_start_manifest(directory: Path, candidate: Path) -> None:
    if "## Acceptance Coverage" not in candidate.read_text(encoding="utf-8"):
        return
    manifest_file = directory / ".acceptance-manifest.json"
    if not manifest_file.is_file():
        raise WorkflowError("acceptance_manifest_missing", str(manifest_file), ("run plan verification and lock the manifest",))
    from cf_acceptance_manifest import validate_manifest
    valid, reason = validate_manifest(str(candidate), str(manifest_file))
    if not valid:
        raise WorkflowError(reason or "acceptance_manifest_invalid", str(manifest_file), ("run plan verification before coding",))


def _write_projection(root: str, candidate: Path, context: SpecContext, task_id: str, session_output: str) -> Path:
    from cf_spec_context import _atomic_text
    from cf_spec_session import project_task_session
    try:
        projection = project_task_session(context, str(candidate), task_id)
    except ValueError as exc:
        raise WorkflowError("task_projection_failed", str(exc)) from exc
    if projection.truncated:
        raise WorkflowError("task_projection_truncated", task_id, ("split the TASK before coding",))
    output = Path(session_output) if session_output else (
        Path(root) / ".code-flow/specs/_session" / f"task-{candidate.stem}.md"
    )
    try:
        output.parent.mkdir(parents=True, exist_ok=True)
        _atomic_text(output, projection.text)
    except (OSError, ValueError) as exc:
        raise WorkflowError("session_write_failed", str(exc)) from exc
    return output


def start_task(
    root: str,
    task_dir: str,
    task_file: str,
    task_id: str,
    owned_paths: Sequence[str] = (),
    session_output: str = "",
) -> dict[str, object]:
    """Full Start Gate: hard preconditions first, then the guarded pipeline
    (refresh → manifest check → projection → activation), then the Markdown
    view flips to in-progress in the same call."""
    from cf_spec_context import load_context, refresh_context, save_context, _new_active
    from cf_spec_session import context_sha256

    recover_transition(root)
    directory, candidate = _resolve_paths(root, task_dir, task_file)
    blockers = check_startable(str(candidate), task_id)
    marker_active = (Path(root) / ".code-flow" / ".active-task.json").exists()
    if marker_active:
        blockers = [f"active_exists: run cf-spec doctor before starting {task_id}"] + blockers
    if blockers:
        raise WorkflowError("start_blocked", task_id, tuple(blockers))

    context_path = directory / "spec-context.yml"
    refreshed = refresh_context(load_context(str(context_path)), root, artifact_root=str(directory))
    save_context(str(context_path), refreshed.context)
    # No marker exists at this point (active_exists raised above), so no
    # re-sync is needed before activation below.
    current_hash = context_sha256(refreshed.context)
    owned = tuple(item for item in owned_paths if isinstance(item, str))
    _validate_start_manifest(directory, candidate)
    output = _write_projection(root, candidate, refreshed.context, task_id, session_output)
    try:
        active = replace(_new_active(root, str(directory), task_id, current_hash, owned), status="active")
        markdown = _commit_state(root, str(candidate), task_id, "in-progress", None, active, f"- [{_today()}] started")
    except Exception as exc:
        code = getattr(exc, "code", "activation_failed") if isinstance(exc, ValueError) else "activation_failed"
        raise WorkflowError(str(code), str(exc)) from exc
    from cf_spec_context import _active_data

    return {
        "ok": True,
        "context_sha256": current_hash,
        "refresh_changes": [item.__dict__ for item in refreshed.changes],
        "active": _active_data(active),
        "session_output": str(output),
        "acceptance_manifest": str(directory / ".acceptance-manifest.json") if (directory / ".acceptance-manifest.json").is_file() else None,
        "markdown": markdown,
    }


def _require_marker_task(root: str, task_id: str, task_dir: str, task_file: str) -> None:
    from cf_spec_context import ContextError, load_active_task

    recover_transition(root)
    try:
        active = load_active_task(root)
    except (ContextError, OSError, ValueError) as exc:
        raise WorkflowError("no_active_task", str(exc)) from exc
    directory, candidate = _resolve_paths(root, task_dir, task_file)
    if active.task_id != task_id or (Path(root) / active.task_dir).resolve() != directory.resolve():
        raise WorkflowError("active_mismatch", f"marker={active.task_id} requested={task_id}")
    located = locate_task_file(str(directory), task_id)
    if located is None or located.resolve() != candidate.resolve():
        raise WorkflowError("active_mismatch", "TASK file must be unique and match the active demand")


def block_task(root: str, task_dir: str, task_file: str, task_id: str, reason: str) -> dict[str, object]:
    """Block a TASK: marker (when it is ours and active) plus Markdown view."""
    from cf_spec_context import ContextError, load_active_task

    if not reason.strip():
        raise WorkflowError("block_reason_required", task_id)
    recover_transition(root)
    _, target = _resolve_paths(root, task_dir, task_file)
    task_file = str(target)
    section = read_task_section(task_file, task_id)
    if section_status(section) in FINISHED_STATUSES:
        raise WorkflowError("task_already_done", task_id, ("completed TASKs cannot be blocked",))
    marker = "skipped_no_marker"
    active = None
    updated = None
    try:
        active = load_active_task(root)
        _require_marker_task(root, task_id, task_dir, task_file)
        if active.task_id == task_id and active.status == "active":
            updated = replace(active, status="blocked")
            marker = "blocked"
        elif active.task_id == task_id:
            marker = active.status
            updated = active
    except ContextError:
        if (Path(root) / ".code-flow/.active-task.json").exists():
            raise
        marker = "skipped_no_marker"
    today = _today()
    markdown = _commit_state(
        root, task_file, task_id, "blocked", active, updated,
        f"- [{today}] blocked ({reason})",
        prepend=f"> BLOCKED: {reason}",
    )
    return {"ok": True, "task_id": task_id, "marker": marker, "markdown": markdown}


def resume_task(root: str, task_dir: str, task_file: str, task_id: str) -> dict[str, object]:
    """Resume a blocked/paused TASK after its blockers clear."""
    from cf_spec_context import load_active_task

    recover_transition(root)
    _, target = _resolve_paths(root, task_dir, task_file)
    task_file = str(target)
    active = None
    if (Path(root) / ".code-flow/.active-task.json").exists():
        _require_marker_task(root, task_id, task_dir, task_file)
        active = load_active_task(root)
        if active.status not in ("blocked", "paused"):
            raise WorkflowError("resume_unexpected_state", active.status, (task_id,))
    section = read_task_section(task_file, task_id)
    if active is None and section_status(section) != "blocked":
        raise WorkflowError("resume_unexpected_state", section_status(section), (task_id,))
    notes = section_notes(section)
    statuses = _all_statuses(task_file)
    unmet = [dep for dep in section_depends(section) if statuses.get(dep) not in FINISHED_STATUSES]
    if notes or unmet:
        raise WorkflowError(
            "resume_blocked", task_id,
            tuple(([f"{len(notes)} unresolved #NOTES"] if notes else []) + ([f"unmet depends: {', '.join(unmet)}"] if unmet else [])),
        )
    resumed = replace(active, status="active") if active is not None else None
    status = "in-progress" if resumed is not None else "draft"
    markdown = _commit_state(root, task_file, task_id, status, active, resumed, f"- [{_today()}] resumed ({status})")
    return {"ok": True, "task_id": task_id, "marker": resumed.status if resumed else "absent", "markdown": markdown}


def complete_task(root: str, task_dir: str, task_file: str, task_id: str, gate_passed: bool) -> dict[str, object]:
    """Complete a TASK after its Done Gate passed; syncs both records."""
    from cf_spec_context import load_active_task

    if not gate_passed:
        raise WorkflowError("gate_failed", task_id, ("Done Gate 未通过",))
    _require_marker_task(root, task_id, task_dir, task_file)
    _, target = _resolve_paths(root, task_dir, task_file)
    task_file = str(target)
    active = load_active_task(root)
    if active.status != "active":
        raise WorkflowError("invalid_active_transition", active.status)
    completed = replace(active, status="completed")
    from cf_spec_context import _active_data

    markdown = _commit_state(root, task_file, task_id, "done", active, None, f"- [{_today()}] completed (done)")
    return {"ok": True, "task_id": task_id, "active": _active_data(completed), "markdown": markdown}
