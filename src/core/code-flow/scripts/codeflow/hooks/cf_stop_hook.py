#!/usr/bin/env python3
"""Stop Hook: run validation.yml checks on session-edited files (FEAT-03).

Flow: session edit events (cf_log) → match validator triggers → run commands
serially under a total budget → failures surface as {"decision": "block",
"reason": ...} so the agent fixes them before the session truly ends.

Protocol notes (deviation from the injection-hook contract, recorded in
TASK-010): the Stop event's feedback channel is decision/reason — there is no
additionalContext for Stop. `stop_hook_active` is respected so an already
continued session is never re-blocked (no loops). All-pass → silent exit 0.
"""
import json
import os
import re
import sys
import time

from codeflow.core import cf_log
from codeflow.core.cf_exec_base import execution_session
from codeflow.cli.cf_spec_context import load_active_task
from codeflow.task.cf_task_runtime import run_done_gate
from codeflow.core.cf_stop_guard import StopAlreadyRunning, stop_guard
from codeflow.acceptance.cf_acceptance_evidence import line_status, scenario_line
from codeflow.task.cf_task_doc import TaskDocumentError, parse_task_document
from codeflow.core.cf_validators import PARSE_ERROR, VALID, load_validators, run_validators
from codeflow.acceptance.cf_acceptance_manifest_core import coverage_execution
from codeflow.core.cf_core import (
    ensure_utf8_io,
    load_config,
    normalize_path,
    resolve_enforcement,
    resolve_quality_loop,
    resolve_session_id,
    timing_log,
)

TOTAL_BUDGET_SECONDS = 30.0
GATE_BUDGET_SECONDS = 25.0
_SCENARIO_RE = re.compile(r"\b[SEB]-\d+\b")
_UNVERIFIED_RE = re.compile(r"\b(?:planned|pending|tbd)\b", re.IGNORECASE)


def session_edited_files(project_root: str, sid: str) -> list:
    files = []
    seen = set()
    for event in cf_log.read_events(project_root, days=2, events=("edit",)):
        if event.get("sid") != sid:
            continue
        rel = (event.get("data") or {}).get("file")
        if rel and rel not in seen:
            seen.add(rel)
            files.append(rel)
    return files


def _root_scoped_files(project_root: str, files: list) -> list:
    """Drop worktree-internal / outside-root paths.

    Parallel subagents edit another working copy (.code-flow/worktrees/<run>/<TASK>/);
    those paths must not trigger this root's validators.
    """
    root = os.path.realpath(project_root)
    scoped = []
    for rel in files:
        path = normalize_path(rel)
        if path.startswith(".code-flow/worktrees/"):
            continue
        absolute = os.path.realpath(os.path.join(root, path))
        if absolute == root or absolute.startswith(root + os.sep):
            scoped.append(rel)
    return scoped


def _is_active_task_file(rel_path: str) -> bool:
    path = normalize_path(rel_path)
    if not path.startswith(".code-flow/tasks/") or "/archived/" in path:
        return False
    return path.endswith(".md") and not path.endswith((".design.md", ".prd.md"))


def _subsection(section: str, heading: str) -> str:
    match = re.search(
        rf"(?ms)^### {re.escape(heading)}\s*$\n(.*?)(?=^### |^## |\Z)",
        section,
    )
    return match.group(1) if match else ""


def _acceptance_gap(task_id: str, section: str, coverage: str) -> str:

    status = re.search(r"(?m)^- \*\*Status\*\*: ([^\n]+)", section)
    # done = implementation finished; verified = E2E/final acceptance closed.
    # Both enter the same contract checks; anything else is still in flight.
    if not status or status.group(1).strip() not in ("done", "verified"):
        return ""
    refs_match = re.search(r"(?m)^- \*\*Acceptance-Refs\*\*: ([^\n]+)", section)
    if not refs_match:
        return f"{task_id} 缺少 Acceptance-Refs"
    refs = refs_match.group(1).strip()
    if refs.upper().startswith("N/A"):
        return ""
    scenarios = sorted(set(_SCENARIO_RE.findall(refs)))
    if not scenarios:
        return f"{task_id} Acceptance-Refs 未引用 S/E/B 场景"
    contract = _subsection(section, "Acceptance Contract")
    evidence = _subsection(section, "Acceptance Evidence")
    if not contract or not evidence:
        return f"{task_id} 缺少 Acceptance Contract 或 Acceptance Evidence"
    for scenario in scenarios:
        task_status = status.group(1).strip()
        row_kind, row_exec = coverage_execution(coverage, scenario)
        if task_status == "done" and (row_kind == "e2e" or row_exec == "deferred"):
            allowed = {"verified", "e2e_deferred"}
        elif task_status == "done" and row_kind == "manual":
            # manual 人工验收延后到需求级 verify-e2e 由用户一次性确认（confirm-manual 写回 verified）
            allowed = {"verified", "planned", "pending", "manual_pending"}
        else:
            allowed = {"verified"}
        states = []
        for body in (contract, evidence, coverage):
            found = [line_status(line, scenario) for line in body.splitlines() if scenario_line(line, scenario)]
            states.append(found[-1] if found else "")
        if not all(state in allowed for state in states):
            return f"{task_id} 的 {scenario} 状态未闭环（planned/pending/TBD/failed 或缺少 verified；仅实现阶段 E2E/显式 deferred 可 e2e_deferred、manual 可 manual_pending）"
    return ""


def task_acceptance_failures(project_root: str, files: list) -> list:
    """Check new-format task files; legacy tasks without coverage are ignored."""
    failures = []
    for rel_path in files:
        if not _is_active_task_file(rel_path):
            continue
        path = os.path.join(project_root, normalize_path(rel_path))
        try:
            with open(path, "r", encoding="utf-8") as f:
                text = f.read()
        except OSError as exc:
            cf_log.warn(f"cf_stop_hook task read failed: {exc}")
            continue
        if "## Acceptance Coverage" not in text:
            continue
        coverage = text.split("## Acceptance Coverage", 1)[1]
        boundary = coverage.find("\n## ")
        if boundary != -1:
            coverage = coverage[:boundary]
        try:
            document = parse_task_document(text, source=rel_path)
        except TaskDocumentError as exc:
            if exc.code == "task_document_empty":
                continue
            failures.append({
                "name": "任务段落解析",
                "on_fail": "修复任务文件中重复或损坏的 TASK 段落后再结束",
                "detail": str(exc),
            })
            continue
        for task in document.tasks:
            detail = _acceptance_gap(task.id, task.body, coverage)
            if detail:
                failures.append({
                    "name": "任务验收契约",
                    "on_fail": "补齐设计场景的测试映射与执行证据后再完成任务",
                    "detail": detail,
                })
    return failures


def _reason_text(failures: list, truncated: bool) -> str:
    lines = ["收尾校验未通过（cf-stop）："]
    for item in failures:
        tag = "（未执行）" if item.get("incomplete") else ""
        lines.append(f"✗ {item['name']}{tag}：{item['on_fail']}")
        if item["detail"]:
            lines.append(f"  输出片段: {item['detail'][:200]}")
    if truncated:
        lines.append("（总预算 30s 已用尽，以上为已完成部分）")
    lines.append("请修复后再结束。")
    return "\n".join(lines)


def _active_stop_scope(root: str, sid: str, enforcement: str, deadline: float) -> tuple[list[str], dict[str, str]]:
    try:
        active = load_active_task(root)
        remaining = deadline - time.monotonic()
        done = run_done_gate(root, os.path.join(root, active.task_dir), cheap=True,
                             budget=min(GATE_BUDGET_SECONDS, max(remaining, 0.01)))
    except (OSError, ValueError) as exc:
        if enforcement == "required":
            return [], {"decision": "block", "reason": f"SPEC_WORKFLOW_BLOCKED: active task is invalid: {exc}"}
        cf_log.append_event(root, "stop_check", {"gate": "invalid_active_nonfatal", "error": str(exc)}, sid)
        return [], {}
    if done.decision != "pass":
        reason = done.message or "当前 TASK required Spec verifier/Evidence 未通过；修复或重新对齐后再 Done。"
        if any(item.get("error_code") == "verifier_budget_exhausted" for item in done.evidence):
            reason += "（验证预算不足，部分 verifier 未运行，请拆分 TASK 或减少验证命令）"
        if enforcement == "required":
            return [], {"decision": "block", "reason": reason}
        cf_log.append_event(root, "stop_check", {"gate": "blocked_nonfatal", "reason": reason}, sid)
    return list(done.files), {}


def _stop_feedback(root: str, sid: str, files: list[str], enforcement: str, deadline: float) -> dict[str, str]:
    if not files:
        return {}
    failures = task_acceptance_failures(root, files)
    truncated = False
    config = load_validators(root)
    if config.state == PARSE_ERROR:
        failures.append({
            "name": "validation.yml",
            "on_fail": "修复 .code-flow/validation.yml 的 YAML/结构错误后再结束",
            "detail": f"invalid_validation_config: {config.error}",
        })
    elif config.state == VALID:
        filtered = config.without_heavy()
        if filtered.validators:
            outcome = run_validators(root, filtered, files, sid, deadline=deadline)
            failures.extend(outcome.failures)
            truncated = outcome.truncated
    if not failures:
        return {}
    if enforcement == "warn":
        cf_log.append_event(root, "stop_check", {"failures": [item["name"] for item in failures], "nonfatal": True}, sid)
        return {}
    return {"decision": "block", "reason": _reason_text(failures, truncated)}


def build_stop_result(project_root: str, sid: str) -> dict[str, str]:
    enforcement = "required"
    try:
        config = load_config(project_root)
        if not config:
            return {}
        enforcement = resolve_enforcement(config)
        if enforcement == "inject":
            return {}
        active = os.path.exists(os.path.join(project_root, ".code-flow/.active-task.json"))
        enabled = resolve_quality_loop(config)["stop_check"]
        if not active and not enabled:
            return {}
        with stop_guard(project_root, sid):
            return _guarded_stop_result(project_root, sid, enforcement, active, enabled)
    except StopAlreadyRunning as exc:
        return {"decision": "block", "reason": str(exc)}
    except Exception as exc:
        cf_log.warn(f"cf_stop_hook error: {exc}")
        return {"decision": "block", "reason": f"SPEC_WORKFLOW_BLOCKED: {exc}"} if enforcement == "required" else {}


def _guarded_stop_result(root: str, sid: str, enforcement: str, active: bool, enabled: bool) -> dict[str, str]:
    deadline = time.monotonic() + TOTAL_BUDGET_SECONDS
    files, payload = _active_stop_scope(root, sid, enforcement, deadline) if active else ([], {})
    if not payload and enabled:
        if not active:
            files = _root_scoped_files(root, session_edited_files(root, sid))
        payload = _stop_feedback(root, sid, files, enforcement, deadline)
    return payload


def process_stop(data: dict[str, object], project_root: str) -> None:
    try:
        if data.get("stop_hook_active"):
            return
        payload = build_stop_result(project_root, resolve_session_id(data))
        if payload:
            sys.stdout.write(json.dumps(payload, ensure_ascii=False))
    except Exception as exc:
        cf_log.warn(f"cf_stop_hook error: {exc}")
        sys.stdout.write(json.dumps({"decision": "block", "reason": f"SPEC_WORKFLOW_BLOCKED: {exc}"}, ensure_ascii=False))


def _main() -> None:
    try:
        ensure_utf8_io()
        if sys.stdin.isatty():
            cf_log.warn("cf_stop_hook.py: missing stdin event")
            return
        raw = sys.stdin.read()
        if raw.strip():
            process_stop(json.loads(raw), os.getcwd())
    except (json.JSONDecodeError, OSError, ValueError) as exc:
        cf_log.warn(f"cf_stop_hook.py bad_stdin_json: {exc}")


def main() -> None:
    with execution_session():
        _main()
