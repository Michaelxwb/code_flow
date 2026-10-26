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
from codeflow.cli.cf_spec_context import ActiveTask, SpecContext
from codeflow.task.cf_task_doc import TaskDocument, TaskDocumentError, parse_task_document
from codeflow.spec.cf_workflow_transaction import recover_transition
from codeflow.core.cf_task_state import FINISHED_STATUSES


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


def _task_document(task_file: str) -> TaskDocument:
    try:
        text = Path(task_file).read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise WorkflowError("task_read_error", str(exc)) from exc
    try:
        return parse_task_document(text, source=str(task_file))
    except TaskDocumentError as exc:
        raise WorkflowError(exc.code, str(exc), exc.details) from exc


def read_task_section(task_file: str, task_id: str) -> str:
    for task in _task_document(task_file).tasks:
        if task.id == task_id:
            return task.body
    raise WorkflowError("task_not_found", task_id, (task_file,))


def section_status(section: str) -> str:
    """Markdown status; absent Status line means draft (pre-contract tasks)."""
    return parse_task_document(section).tasks[0].status


def task_truth_issues(task_file: str, task_id: str, context: SpecContext,
                      spec_ids: Optional[set[str]] = None) -> tuple[str, ...]:
    """Return required Rule refs whose status contradicts the Markdown claim.

    The Markdown is a view. A TASK claiming done/verified while its required
    code (or, for verified, review) Rules are not verified is a documentation
    lie; archive/verify callers must fail closed instead of trusting the prose.
    """
    section = read_task_section(task_file, task_id)
    status = section_status(section)
    if status not in FINISHED_STATUSES:
        return ()
    stages = ("code", "review") if status == "verified" else ("code",)
    issues: list[str] = []
    for binding in context.bindings:
        for rule in binding.rules:
            if rule.enforcement != "required" or rule.verifier_stage not in stages:
                continue
            stage_status = rule.stage_status.get(rule.verifier_stage)
            actual = stage_status.status if stage_status is not None else "missing"
            if status == "done" and spec_ids is not None and actual == "unverified":
                from codeflow.cli.cf_spec_gate import evidence_deferral_kind
                latest = stage_status.evidence[-1] if stage_status.evidence else None
                deferred = evidence_deferral_kind(latest)
                if deferred == "heavy" or (deferred == "review_stage" and binding.spec_id not in spec_ids):
                    continue
            if actual != "verified":
                issues.append(f"{binding.spec_id}#{rule.ref}: {actual}")
    return tuple(sorted(set(issues)))


def section_depends(section: str) -> tuple[str, ...]:
    return parse_task_document(section).tasks[0].depends


def section_notes(section: str) -> tuple[str, ...]:
    return tuple(
        line.strip()
        for line in section.splitlines()
        if "#NOTES" in line
    )


def _all_statuses(task_file: str) -> Mapping[str, str]:
    return {task.id: task.status for task in _task_document(task_file).tasks}


def check_startable(task_file: str, task_id: str) -> list[str]:
    """Collectors of start blockers; empty means the TASK may start."""
    section = read_task_section(task_file, task_id)
    status = section_status(section)
    blockers: list[str] = []
    if status == "blocked":
        blockers.append(f"{task_id} is blocked; resolve Log BLOCKED entries first")
    elif status == "done":
        blockers.append(f"{task_id} is already done; verify contract or reopen explicitly")
    elif status not in ("draft", "in-progress", "provisional"):
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


def _log_list_end(section: str, heading: re.Match) -> int:
    """`### Log` 列表最后一项的末尾偏移；无条目时为标题行末。"""
    body_start = heading.end()
    boundary = re.search(r"(?m)^#{2,3} |^---[ \t]*$", section[body_start:])
    body_end = body_start + (boundary.start() if boundary is not None else len(section) - body_start)
    entries = list(re.finditer(r"(?m)^- .*$", section[body_start:body_end]))
    return body_start + (entries[-1].end() if entries else 0)


def _trailing_separator_at(section: str) -> int:
    """段落尾部 `---` 分隔符的起始偏移（取最后一个）；无分隔符时为段落末尾。"""
    at = len(section)
    for match in re.finditer(r"(?m)^---[ \t]*$", section):
        at = match.start()
    return at


def _append_log_entry(section: str, log_line: str) -> str:
    """把生命周期记录追加进 `### Log` 列表（无该小节时在尾部分隔符前新建）。

    历史缺陷：直接追加到 section 末尾会落在 `---` 分隔符之后，并吞掉下一节前的
    空行；这里始终在段落内容区内插入，保持分隔符与空行原样。
    """
    heading = re.search(r"(?m)^### Log[ \t]*$", section)
    if heading is not None:
        at = _log_list_end(section, heading)
        return section[:at] + f"\n{log_line}" + section[at:]
    at = _trailing_separator_at(section)
    head, tail = section[:at].rstrip(), section[at:].lstrip("\n")
    body = f"{head}\n\n### Log\n{log_line}\n"
    return body + (f"\n{tail}" if tail else "")


def _set_status(section: str, status: str, log_line: str = "") -> str:
    if re.search(r"(?m)^- \*\*Status\*\*:", section):
        section = re.sub(r"(?m)^(- \*\*Status\*\*:)[^\r\n]*", rf"\1 {status}", section, count=1)
    else:
        line_end = section.find("\n")
        if line_end == -1:
            insert_at = len(section)
        elif line_end > 0 and section[line_end - 1] == "\r":
            insert_at = line_end - 1
        else:
            insert_at = line_end
        eol = "\r\n" if "\r\n" in section else "\n"
        section = section[:insert_at] + eol + f"- **Status**: {status}" + section[insert_at:]
    if log_line and log_line not in section.splitlines():
        section = _append_log_entry(section, log_line)
    return section


def _section_span(text: str, task_id: str) -> tuple[int, int]:
    """Offsets of one TASK section in the original text (line endings preserved)."""
    heading = f"## {task_id}:"
    start = end = -1
    offset = 0
    for line in text.splitlines(keepends=True):
        content = line.rstrip("\r\n")
        if content.startswith(heading):
            if start != -1:
                raise WorkflowError("duplicate_task_id", task_id)
            start = offset
        elif start != -1 and content.startswith("## "):
            end = offset
            break
        offset += len(line)
    if start == -1:
        raise WorkflowError("task_not_found", task_id)
    return start, len(text) if end == -1 else end


def _render_markdown(text: str, task_id: str, status: str, log_line: str = "", prepend: str = "") -> str:
    try:
        document = parse_task_document(text)
    except TaskDocumentError as exc:
        raise WorkflowError(exc.code, str(exc), exc.details) from exc
    if not any(task.id == task_id for task in document.tasks):
        raise WorkflowError("task_not_found", task_id)
    start, end = _section_span(text, task_id)
    section = text[start:end]
    updated = _set_status(section, status, log_line)
    if not prepend and status in ("done", "verified"):
        updated = re.sub(r"(?m)^> (?:PROVISIONAL|BLOCKED):[^\n]*\n?", "", updated)
    if prepend and prepend not in updated:
        if "### Log" in updated:
            updated = updated.replace("### Log", prepend + "\n### Log", 1)
        else:
            at = _trailing_separator_at(updated)
            head, tail = updated[:at].rstrip(), updated[at:].lstrip("\n")
            updated = f"{head}\n\n{prepend}\n" + (f"\n{tail}" if tail else "")
    text = text[:start] + updated + text[end:]
    return re.sub(r"(?m)^(- \*\*Updated\*\*:)[^\r\n]*", rf"\1 {_today()}", text, count=1)


def _sync_markdown(task_file: str, task_id: str, status: str, log_line: str = "", prepend: str = "") -> str:
    from codeflow.core.cf_fs import atomic_write_text
    target = Path(task_file)
    text = target.read_text(encoding="utf-8")
    atomic_write_text(target, _render_markdown(text, task_id, status, log_line, prepend))
    return "synced"


def _commit_state(root: str, task_file: str, task_id: str, status: str, previous: Optional[ActiveTask],
                  updated: Optional[ActiveTask], log_line: str = "", prepend: str = "") -> str:
    from codeflow.cli.cf_spec_context import _active_data
    from codeflow.spec.cf_workflow_transaction import commit_transition
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
    from codeflow.cli.cf_acceptance_manifest import validate_manifest
    valid, reason = validate_manifest(str(candidate), str(manifest_file))
    if not valid:
        raise WorkflowError(reason or "acceptance_manifest_invalid", str(manifest_file), ("run plan verification before coding",))


def _write_projection(root: str, candidate: Path, context: SpecContext, task_id: str, session_output: str) -> Path:
    from codeflow.core.cf_fs import atomic_write_text
    from codeflow.cli.cf_spec_session import project_task_session
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
        atomic_write_text(output, projection.text)
    except (OSError, ValueError) as exc:
        raise WorkflowError("session_write_failed", str(exc)) from exc
    return output


def remove_session_projection(root: str, task_file: str) -> str:
    """删除任务在 `specs/_session/` 的投影，返回 removed / absent / error: ...。

    投影是 start 生成的瞬时文件（`.gitignore` 忽略、不参与 Spec Catalog 与审计），
    任务完成后必须清理，避免往期任务的 Required Rules/Contract 被后续会话读到。
    清理失败不影响 Done 裁决，但状态必须显式返回。
    """
    projection = Path(root) / ".code-flow/specs/_session" / f"task-{Path(task_file).stem}.md"
    try:
        projection.unlink()
    except FileNotFoundError:
        return "absent"
    except OSError as exc:
        return f"error: {exc}"
    return "removed"


def cleanup_session_projections(root: str, directory: str) -> dict[str, object]:
    """按需求目录逐个任务文件删除 `_session` 投影（只动本需求的 task-<stem>.md）。"""
    removed: list[str] = []
    absent: list[str] = []
    errors: list[dict[str, str]] = []
    for task_file in sorted(Path(directory).glob("*.md")):
        if task_file.name.endswith((".design.md", ".prd.md")):
            continue
        relative = f".code-flow/specs/_session/task-{task_file.stem}.md"
        status = remove_session_projection(root, str(task_file))
        if status == "removed":
            removed.append(relative)
        elif status == "absent":
            absent.append(relative)
        else:
            errors.append({"path": relative, "error": status})
    return {
        "ok": not errors,
        "decision": "block" if errors else "pass",
        "removed": removed,
        "absent": absent,
        "errors": errors,
    }


def _worktree_registration_issue(root: str, task_id: str) -> str:
    """Refuse a parallel worktree that is not registered in its run.json.

    A background worker must not self-provision a worktree: the run ledger is
    what collect/merge later reads. Plain single-task runs are unaffected
    because their root is not under `.code-flow/worktrees/`.
    """
    path = Path(root).resolve()
    parts = path.parts
    try:
        flow_index = parts.index(".code-flow")
    except ValueError:
        return ""
    if flow_index + 1 >= len(parts) or parts[flow_index + 1] != "worktrees":
        return ""
    run_dir = path.parent
    meta_path = run_dir / "run.json"
    if not meta_path.is_file():
        return f"{path} is not registered in a parallel run (missing {meta_path})"
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return f"run.json unreadable: {exc}"
    if not isinstance(meta, Mapping):
        return f"run.json must be an object: {meta_path}"
    if (meta.get("version") != 1
            or not isinstance(meta.get("task_file"), str) or not meta.get("task_file")
            or not isinstance(meta.get("base_head"), str) or not meta.get("base_head")):
        return f"run.json is incomplete: {meta_path}"
    entries = meta.get("worktrees")
    if not isinstance(entries, list):
        return f"run.json worktrees must be a list: {meta_path}"
    for entry in entries:
        if not isinstance(entry, Mapping) or entry.get("task") != task_id:
            continue
        raw = entry.get("path")
        if not isinstance(raw, str) or not Path(raw).is_absolute():
            return f"run.json path for {task_id} must be an absolute path"
        entry_path = Path(raw).resolve()
        if entry_path == path:
            return ""
        return f"worktree path mismatch for {task_id}: run.json={entry_path}, cwd={path}"
    return f"{task_id} is not registered in {meta_path}"


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
    from codeflow.cli.cf_spec_context import load_context, refresh_context, save_context, _new_active
    from codeflow.cli.cf_spec_session import context_sha256

    recover_transition(root)
    directory, candidate = _resolve_paths(root, task_dir, task_file)
    registration = _worktree_registration_issue(root, task_id)
    if registration:
        raise WorkflowError("worktree_not_registered", task_id, (registration,))
    blockers = check_startable(str(candidate), task_id)
    marker_active = (Path(root) / ".code-flow" / ".active-task.json").exists()
    if marker_active:
        blockers = [f"active_exists: run cf-spec doctor before starting {task_id}"] + blockers
    if blockers:
        raise WorkflowError("start_blocked", task_id, tuple(blockers))

    context_path = directory / "spec-context.yml"
    if not context_path.is_file():
        raise WorkflowError(
            "context_missing",
            str(context_path),
            ("run cf-task:plan (bind --stage plan) or cf-spec refresh to create spec-context.yml before start",),
        )
    refreshed = refresh_context(load_context(str(context_path)), root, artifact_root=str(directory))
    # No marker exists at this point (active_exists raised above), so no
    # re-sync is needed before activation below.
    current_hash = context_sha256(refreshed.context)
    owned = tuple(item for item in owned_paths if isinstance(item, str))
    _validate_start_manifest(directory, candidate)
    from codeflow.acceptance.cf_acceptance_plan import build_e2e_plan
    try:
        e2e_plan = build_e2e_plan(
            str(directory / ".acceptance-manifest.json"), str(candidate), task_id
        )
    except (OSError, ValueError) as exc:
        raise WorkflowError("acceptance_manifest_invalid", task_id, (str(exc),)) from exc
    quality = e2e_plan.get("quality")
    if isinstance(quality, Mapping) and quality.get("ok") is not True:
        errors = quality.get("errors") if isinstance(quality.get("errors"), list) else []
        details = tuple(
            f"{item.get('scenario', '')}:{item.get('message', '')}".strip(":")
            for item in errors[:5] if isinstance(item, Mapping)
        )
        raise WorkflowError("e2e_plan_invalid", task_id, details or ("E2E plan quality gate failed",))
    # Persist the refreshed Context only after every start gate passed. A
    # manifest/E2E failure must not leave a half-updated Context behind.
    save_context(str(context_path), refreshed.context)
    output = _write_projection(root, candidate, refreshed.context, task_id, session_output)
    try:
        active = replace(_new_active(root, str(directory), task_id, current_hash, owned), status="active")
        markdown = _commit_state(root, str(candidate), task_id, "in-progress", None, active, f"- [{_today()}] started")
    except Exception as exc:
        code = getattr(exc, "code", "activation_failed") if isinstance(exc, ValueError) else "activation_failed"
        raise WorkflowError(str(code), str(exc)) from exc
    from codeflow.cli.cf_spec_context import _active_data

    return {
        "ok": True,
        "context_sha256": current_hash,
        "refresh_changes": [item.__dict__ for item in refreshed.changes],
        "active": _active_data(active),
        "session_output": str(output),
        "acceptance_manifest": str(directory / ".acceptance-manifest.json") if (directory / ".acceptance-manifest.json").is_file() else None,
        "e2e_plan": e2e_plan,
        "markdown": markdown,
    }


def _require_marker_task(root: str, task_id: str, task_dir: str, task_file: str) -> None:
    from codeflow.cli.cf_spec_context import ContextError, load_active_task

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
    from codeflow.cli.cf_spec_context import ContextError, load_active_task

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
    from codeflow.cli.cf_spec_context import load_active_task

    recover_transition(root)
    _, target = _resolve_paths(root, task_dir, task_file)
    task_file = str(target)
    active = None
    section = read_task_section(task_file, task_id)
    if (Path(root) / ".code-flow/.active-task.json").exists():
        _require_marker_task(root, task_id, task_dir, task_file)
        active = load_active_task(root)
        allowed_active = active.status in ("blocked", "paused", "provisional")
        provisional_active = active.status == "active" and section_status(section) == "provisional"
        if not allowed_active and not provisional_active:
            raise WorkflowError("resume_unexpected_state", active.status, (task_id,))
    if active is None and section_status(section) not in ("blocked", "provisional"):
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
    from codeflow.cli.cf_spec_context import load_active_task

    if not gate_passed:
        raise WorkflowError("gate_failed", task_id, ("Done Gate 未通过",))
    _require_marker_task(root, task_id, task_dir, task_file)
    _, target = _resolve_paths(root, task_dir, task_file)
    task_file = str(target)
    active = load_active_task(root)
    if active.status != "active":
        raise WorkflowError("invalid_active_transition", active.status)
    completed = replace(active, status="completed")
    from codeflow.cli.cf_spec_context import _active_data

    markdown = _commit_state(root, task_file, task_id, "done", active, None, f"- [{_today()}] completed (done)")
    return {"ok": True, "task_id": task_id, "active": _active_data(completed), "markdown": markdown}


def provisional_task(root: str, task_dir: str, task_file: str, task_id: str, reason: str) -> dict[str, object]:
    """Record a provisional finish without claiming done.

    The active marker stays active so the same TASK can be retried after the
    missing checks are fixed; provisional is explicitly open/unfinished for
    dependency, collect and archive gates.
    """
    from codeflow.cli.cf_spec_context import load_active_task

    recover_transition(root)
    _require_marker_task(root, task_id, task_dir, task_file)
    _, target = _resolve_paths(root, task_dir, task_file)
    task_file = str(target)
    if section_status(read_task_section(task_file, task_id)) in FINISHED_STATUSES:
        raise WorkflowError("task_already_done", task_id, ("completed TASKs cannot become provisional",))
    active = load_active_task(root)
    if active.status != "active":
        raise WorkflowError("invalid_active_transition", active.status)
    clean_reason = " ".join(reason.split())
    markdown = _commit_state(
        root, task_file, task_id, "provisional", active, active,
        f"- [{_today()}] provisional ({clean_reason})",
        prepend=f"> PROVISIONAL: {clean_reason}",
    )
    return {"ok": True, "task_id": task_id, "marker": "active", "markdown": markdown}
