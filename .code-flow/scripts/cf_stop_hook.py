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
import fnmatch
import json
import math
import os
import re
import sys
import time

import cf_log
from cf_exec_base import build_argv, remaining_seconds, run_command, execution_session
from cf_spec_context import load_active_task
from cf_task_runtime import run_done_gate
from cf_acceptance_evidence import line_status, scenario_line
from cf_core import (
    _log,
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
_BRACE_RE = re.compile(r"\{([^{}]+)\}")
_TASK_SECTION_RE = re.compile(
    r"(?ms)^## (TASK-\d+):.*?(?=^## TASK-\d+:|\Z)"
)
_SCENARIO_RE = re.compile(r"\b[SEB]-\d+\b")
_UNVERIFIED_RE = re.compile(r"\b(?:planned|pending|tbd)\b", re.IGNORECASE)


def expand_braces(pattern: str) -> list:
    """Expand one level of `{a,b}` alternation → list of fnmatch patterns."""
    match = _BRACE_RE.search(pattern)
    if not match:
        return [pattern]
    head, tail = pattern[: match.start()], pattern[match.end():]
    out = []
    for option in match.group(1).split(","):
        out.extend(expand_braces(head + option + tail))
    return out


def trigger_matches(trigger: str, rel_path: str) -> bool:
    """fnmatch with brace expansion; `**/` prefix also matches root files."""
    rel_path = normalize_path(rel_path)
    for pattern in expand_braces(trigger or ""):
        candidates = [pattern]
        if pattern.startswith("**/"):
            candidates.append(pattern[3:])
        if any(fnmatch.fnmatch(rel_path, p) for p in candidates):
            return True
    return False


def load_validators(project_root: str) -> list:
    path = os.path.join(project_root, ".code-flow", "validation.yml")
    if not os.path.exists(path):
        return []
    try:
        import yaml
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        validators = data.get("validators")
        return validators if isinstance(validators, list) else []
    except Exception as exc:
        _log(f"cf_stop_hook validation.yml parse failed: {exc}")
        return []


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
        coverage_rows = [line for line in coverage.splitlines() if scenario_line(line, scenario)]
        cells = coverage_rows[0].strip().strip("|").split("|") if coverage_rows else []
        deferred = status.group(1).strip() == "done" and len(cells) >= 3 and cells[2].strip().lower() == "e2e"
        allowed = {"verified", "e2e_deferred"} if deferred else {"verified"}
        states = []
        for body in (contract, evidence, coverage):
            found = [line_status(line, scenario) for line in body.splitlines() if scenario_line(line, scenario)]
            states.append(found[-1] if found else "")
        if not all(state in allowed for state in states):
            return f"{task_id} 的 {scenario} 状态未闭环（planned/pending/TBD/failed 或缺少 verified；仅实现阶段 E2E 可 e2e_deferred）"
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
            _log(f"cf_stop_hook task read failed: {exc}")
            continue
        if "## Acceptance Coverage" not in text:
            continue
        coverage = text.split("## Acceptance Coverage", 1)[1].split("## TASK-", 1)[0]
        for match in _TASK_SECTION_RE.finditer(text):
            detail = _acceptance_gap(match.group(1), match.group(0), coverage)
            if detail:
                failures.append({
                    "name": "任务验收契约",
                    "on_fail": "补齐设计场景的测试映射与执行证据后再完成任务",
                    "detail": detail,
                })
    return failures


def _validator_failure(validator: dict, detail: str, incomplete: bool = False) -> dict:
    result = {"name": validator.get("name", "validator"),
              "on_fail": validator.get("on_fail", ""), "detail": detail}
    if incomplete:
        result["incomplete"] = True
    return result


def _validator_argv(root: str, validator: dict, matched: list, strict: bool) -> list:
    existing = [name for name in matched if os.path.isfile(os.path.join(root, name))]
    template = str(validator.get("command", ""))
    if "{files}" in template and not existing:
        return []
    argv = build_argv(template, existing)
    if not argv and strict:
        raise ValueError("validator command missing")
    return argv


def _validator_result(root: str, validator: dict, argv: list, sid: str,
                      deadline: float, strict: bool) -> tuple[list, bool]:
    try:
        timeout = float(validator.get("timeout", 30000)) / 1000.0
    except (ValueError, TypeError):
        if strict:
            return [_validator_failure(validator, "invalid validator timeout")], False
        timeout = 30.0
    if not math.isfinite(timeout) or timeout <= 0:
        return [_validator_failure(validator, "invalid validator timeout")], False
    outcome = run_command(argv, root, timeout, deadline)
    passed = outcome["status"] == "ok" and outcome["returncode"] == 0
    if outcome["status"] == "deadline_exceeded":
        return [_validator_failure(validator, "预算耗尽未执行", True)], True
    timed_out = outcome["status"] == "timeout"
    detail = (f"超时（>{timeout:.0f}s），未完成" if timed_out else
              (str(outcome.get("stdout", "")) + str(outcome.get("stderr", ""))).strip()[-400:])
    if outcome["status"] == "spawn_error":
        cf_log.degrade(root, "stop_check", f"{validator.get('name')}:{outcome['stderr']}", sid)
        if not strict:
            return [], False
    cf_log.append_event(root, "stop_check",
                        {"trigger": validator.get("trigger", ""),
                         "cmd": str(validator.get("command", ""))[:120], "passed": passed}, sid)
    return ([] if passed else [_validator_failure(validator, detail)]), timed_out


def run_validators(
    project_root: str, validators: list, files: list, sid: str,
    total_budget: float = TOTAL_BUDGET_SECONDS,
    deadline: float = 0.0,
    strict: bool = False,
) -> tuple:
    """Match validators, execute argv under one deadline, report unrun work."""
    failures, truncated = [], False
    deadline = deadline or time.monotonic() + total_budget
    for validator in validators:
        if not isinstance(validator, dict):
            if strict:
                failures.append(_validator_failure({}, "invalid validator record"))
            continue
        matched = [f for f in files if trigger_matches(validator.get("trigger", ""), f)]
        if not matched:
            continue
        remaining = remaining_seconds(deadline)
        if remaining is not None and remaining <= 0:
            failures.append(_validator_failure(validator, "预算耗尽未执行", True))
            truncated = True
            continue
        try:
            argv = _validator_argv(project_root, validator, matched, strict)
        except ValueError as exc:
            failures.append(_validator_failure(validator, f"validator 配置错误: {exc}"))
            continue
        if not argv:
            continue
        errors, incomplete = _validator_result(project_root, validator, argv, sid, deadline, strict)
        failures.extend(errors)
        truncated = truncated or incomplete
    return failures, truncated


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


def _main() -> None:
    try:
        ensure_utf8_io()
        raw = sys.stdin.read()
        if not raw.strip():
            return
        data = json.loads(raw)
        if data.get("stop_hook_active"):
            return  # 已因本 hook 续跑过一轮，避免循环
        project_root = os.getcwd()
        sid = resolve_session_id(data)
        config = load_config(project_root)
        if not config:
            return
        enforcement = resolve_enforcement(config)
        if enforcement == "inject":
            return  # 轻量模式：只注入不门禁，停止会话不受限
        marker = os.path.join(project_root, ".code-flow", ".active-task.json")
        has_active = os.path.exists(marker)
        files = []
        # Single entry deadline constrains the whole chain (Done + validators),
        # so long checks end as `incomplete` instead of being killed by the
        # host without a verdict.
        deadline = time.monotonic() + TOTAL_BUDGET_SECONDS
        if has_active:
            try:
                active = load_active_task(project_root)
                task_dir = os.path.join(project_root, active.task_dir)
                gate_remaining = deadline - time.monotonic()
                done = run_done_gate(project_root, task_dir, budget=min(GATE_BUDGET_SECONDS, max(gate_remaining, 0.01)))
            except (OSError, ValueError) as exc:
                if enforcement == "required":
                    payload = {"decision": "block", "reason": f"SPEC_WORKFLOW_BLOCKED: active task is invalid: {exc}"}
                    sys.stdout.write(json.dumps(payload, ensure_ascii=False))
                    return
                cf_log.append_event(project_root, "stop_check", {"gate": "invalid_active_nonfatal", "error": str(exc)}, sid)
                files = []
            else:
                if done.decision != "pass":
                    reason = done.message or "当前 TASK required Spec verifier/Evidence 未通过；修复或重新对齐后再 Done。"
                    if any(item.get("error_code") == "verifier_budget_exhausted" for item in done.evidence):
                        reason += "（验证预算不足，部分 verifier 未运行，请拆分 TASK 或减少验证命令）"
                    if enforcement == "required":
                        payload = {"decision": "block", "reason": reason}
                        sys.stdout.write(json.dumps(payload, ensure_ascii=False))
                        return
                    cf_log.append_event(project_root, "stop_check", {"gate": "blocked_nonfatal", "reason": reason}, sid)
                files = list(done.files)
        if not resolve_quality_loop(config)["stop_check"]:
            return
        if not has_active:
            files = session_edited_files(project_root, sid)
        if not files:
            return
        acceptance_failures = task_acceptance_failures(project_root, files)
        validators = load_validators(project_root)
        failures, truncated = run_validators(
            project_root, validators, files, sid, deadline=deadline
        ) if validators else ([], False)
        failures = acceptance_failures + failures
        if not failures:
            return  # 全过或无 validation.yml 且无验收缺口时静默
        if enforcement == "warn":
            cf_log.append_event(
                project_root, "stop_check",
                {"failures": [item["name"] for item in failures], "nonfatal": True},
                sid,
            )
            return
        payload = {"decision": "block", "reason": _reason_text(failures, truncated)}
        sys.stdout.write(json.dumps(payload, ensure_ascii=False))
    except Exception as exc:
        _log(f"cf_stop_hook error: {exc}")
        if locals().get("enforcement") == "required":
            sys.stdout.write(json.dumps({"decision": "block", "reason": f"SPEC_WORKFLOW_BLOCKED: {exc}"}, ensure_ascii=False))
        return


def main() -> None:
    with execution_session():
        _main()


if __name__ == "__main__":
    main()
    timing_log("cf_stop_hook")
