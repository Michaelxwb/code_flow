#!/usr/bin/env python3
"""PostToolUse Hook: compliance feedback after Edit/Write (FEAT-01).

Flow (spec-quality-loop.design.md §3.4):
  edited file → matched domains → aggregate frontmatter checks of their
  constraint specs → run against on-disk content → feedback via
  additionalContext (advice only, never blocking) → violation events.

Protocol invariants (RULE-01/02):
  - always exit 0, stdout is JSON-only or empty (no-op);
  - violations only warn — there is no error severity;
  - same check+file reported once per session (RISK-05);
  - any internal failure degrades silently (stderr + degrade event).

Input (stdin): {"tool_name", "tool_input": {"file_path"}, "session_id"}
Output: {"hookSpecificOutput": {"hookEventName": "PostToolUse",
         "additionalContext": "..."}} or empty.
"""
import json
import os
import sys

import cf_log
from cf_spec_context import ContextError, load_active_task
from cf_task_runtime import evaluate_scope, run_done_gate
from cf_checks import (
    load_check_state,
    load_spec_checks,
    record_hits,
    run_checks,
    save_check_state,
)
from cf_core import (
    _log,
    build_effective_mapping,
    ensure_utf8_io,
    is_code_file,
    load_config,
    match_domains,
    normalize_path,
    normalize_spec_entry,
    resolve_quality_loop,
    resolve_session_id,
)

FEEDBACK_HINT = '如认为误报，直接告诉我"这是误报"，我会标记忽略。'
_REPORTED_KEY = "_reported"


def _collect_checks(project_root: str, domains: list, mapping: dict) -> list:
    """Aggregate checks of all constraint specs in matched domains.

    Each check is annotated with its source spec path. Checks apply whenever
    their own `files` glob matches — independent of injection tag gating.
    """
    specs_root = os.path.join(project_root, ".code-flow", "specs")
    collected = []
    seen_specs = set()
    for domain in domains:
        for entry in (mapping.get(domain) or {}).get("specs") or []:
            cfg = normalize_spec_entry(entry)
            rel = cfg.get("path")
            if not rel or rel in seen_specs or not cfg.get("tags"):
                continue
            seen_specs.add(rel)
            checks, _ = load_spec_checks(os.path.join(specs_root, rel))
            for check in checks:
                item = dict(check)
                item["spec"] = rel
                collected.append(item)
    return collected


def _session_reported(state: dict, sid: str) -> set:
    session = state.get(_REPORTED_KEY) or {}
    if session.get("sid") != sid:
        return set()
    return set(session.get("keys") or [])


def _save_reported(project_root: str, state: dict, sid: str, keys: set) -> None:
    state[_REPORTED_KEY] = {"sid": sid, "keys": sorted(keys)}
    save_check_state(project_root, state)


def _feedback_text(violations: list) -> str:
    lines = ["## Spec 合规反馈 (auto-check)", ""]
    for v in violations:
        lines.append(f"⚠ {v['message']}（规则: {v['spec']}#{v['check_id']}）")
        lines.append(f"  违规行 {v['line_no']}: {v['line']}")
    lines.append("")
    lines.append("请修正以上违规后再继续。" + FEEDBACK_HINT)
    return "\n".join(lines)


def _active_feedback(project_root: str) -> str:
    marker = os.path.join(project_root, ".code-flow", ".active-task.json")
    if not os.path.exists(marker):
        return ""
    active = load_active_task(project_root)
    task_dir = os.path.join(project_root, active.task_dir)
    scope = evaluate_scope(project_root, task_dir)
    if scope.decision == "pause":
        return scope.message
    result = run_done_gate(project_root, task_dir)
    failed = [item for item in result.evidence if item.get("status") != "verified"]
    if not failed:
        return ""
    refs = ", ".join(str(item.get("verifier_ref")) for item in failed)
    return f"当前 TASK required verifier 未通过：{refs}。修复后再继续。"


def main() -> None:
    try:
        ensure_utf8_io()
        raw = sys.stdin.read()
        if not raw.strip():
            return
        data = json.loads(raw)
        tool_name = data.get("tool_name", "")
        file_path = (data.get("tool_input") or {}).get("file_path", "")
        if tool_name not in {"Edit", "Write", "MultiEdit"}:
            return
        if not isinstance(file_path, str) or not file_path:
            return

        project_root = os.getcwd()
        try:
            active_feedback = _active_feedback(project_root)
        except (ContextError, OSError, ValueError) as exc:
            message = f"SPEC_WORKFLOW_BLOCKED: active task is invalid: {exc}"
            payload = {"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": message}}
            sys.stdout.write(json.dumps(payload, ensure_ascii=False))
            return
        if active_feedback:
            payload = {"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": active_feedback}}
            sys.stdout.write(json.dumps(payload, ensure_ascii=False))
            return
        config = load_config(project_root)
        if not config:
            return
        quality_loop = resolve_quality_loop(config)
        if not quality_loop["post_check"]:
            return

        abs_path = file_path
        if not os.path.isabs(abs_path):
            abs_path = os.path.join(project_root, file_path)
        rel_path = normalize_path(os.path.relpath(abs_path, project_root))
        sid = resolve_session_id(data)
        cf_log.append_event(project_root, "edit", {"file": rel_path, "tool": tool_name}, sid)
        if not is_code_file(rel_path, config.get("quality_loop") or {}):
            return
        mapping = build_effective_mapping(
            project_root, config.get("path_mapping") or {}
        )
        domains = match_domains(rel_path, mapping)
        if not domains:
            return

        checks = _collect_checks(project_root, domains, mapping)
        if not checks:
            return

        try:
            with open(abs_path, "r", encoding="utf-8") as f:
                content = f.read()
        except Exception:
            return

        state = load_check_state(project_root)
        violations, skipped = run_checks(checks, rel_path, content, state)
        for item in skipped:
            cf_log.degrade(
                project_root, "post_check",
                f"{item['check_id']}:{item['reason']}", sid,
            )
        if not violations:
            return

        spec_by_check = {c["id"]: c["spec"] for c in checks}
        reported = _session_reported(state, sid)
        fresh = []
        for v in violations:
            key = f"{v['check_id']}|{v['file']}"
            if key in reported:
                continue
            v["spec"] = spec_by_check.get(v["check_id"], "")
            fresh.append(v)
            reported.add(key)
        if not fresh:
            return

        # hit_count feeds the false-positive rate denominator (RULE-04)
        record_hits(project_root, sorted({v["check_id"] for v in fresh}))
        state = load_check_state(project_root)
        _save_reported(project_root, state, sid, reported)

        for v in fresh:
            cf_log.append_event(
                project_root, "violation",
                {"check_id": v["check_id"], "spec": v["spec"],
                 "file": v["file"], "severity": v["severity"]},
                sid,
            )

        payload = {
            "hookSpecificOutput": {
                "hookEventName": "PostToolUse",
                "additionalContext": _feedback_text(fresh),
            }
        }
        sys.stdout.write(json.dumps(payload, ensure_ascii=False))
    except Exception as exc:
        _log(f"cf_post_hook error: {exc}")
        return


if __name__ == "__main__":
    main()
