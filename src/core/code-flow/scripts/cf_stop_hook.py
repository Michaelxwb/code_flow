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
import os
import re
import subprocess
import sys

import cf_log
from cf_spec_context import load_active_task
from cf_task_runtime import run_done_gate
from cf_core import (
    _log,
    ensure_utf8_io,
    load_config,
    normalize_path,
    resolve_quality_loop,
    resolve_session_id,
)

TOTAL_BUDGET_SECONDS = 30.0
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
    if not status or status.group(1).strip() != "done":
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
    if _UNVERIFIED_RE.search(contract) or _UNVERIFIED_RE.search(evidence):
        return f"{task_id} 验收契约仍有 planned/pending/TBD"
    for scenario in scenarios:
        contract_ok = any(scenario in line and "verified" in line.lower()
                          for line in contract.splitlines())
        evidence_ok = any(scenario in line and "verified" in line.lower()
                          for line in evidence.splitlines())
        coverage_ok = any(scenario in line and "verified" in line.lower()
                          for line in coverage.splitlines())
        if not contract_ok or not evidence_ok or not coverage_ok:
            return f"{task_id} 的 {scenario} 未在覆盖表、契约和证据中全部 verified"
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


def run_validators(
    project_root: str, validators: list, files: list, sid: str,
    total_budget: float = TOTAL_BUDGET_SECONDS,
) -> tuple:
    """Run matching validators serially → (failures, truncated)."""
    import time
    failures = []
    truncated = False
    deadline = time.monotonic() + total_budget
    for validator in validators:
        if not isinstance(validator, dict):
            continue
        matched = [f for f in files if trigger_matches(validator.get("trigger", ""), f)]
        if not matched:
            continue
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            truncated = True
            break
        try:
            timeout = min(float(validator.get("timeout", 30000)) / 1000.0, remaining)
        except (ValueError, TypeError):
            timeout = remaining
        command = str(validator.get("command", "")).replace(
            "{files}", " ".join(matched)
        )
        if not command.strip():
            continue
        passed = False
        detail = ""
        try:
            proc = subprocess.run(
                command, shell=True, cwd=project_root,
                capture_output=True, text=True, timeout=timeout,
            )
            passed = proc.returncode == 0
            if not passed:
                detail = (proc.stdout + proc.stderr).strip()[-400:]
        except subprocess.TimeoutExpired:
            detail = f"超时（>{timeout:.0f}s），跳过"
            truncated = True
        except Exception as exc:
            # 命令在环境中不可用等：降级跳过，不打扰（E 场景）
            cf_log.degrade(project_root, "stop_check", f"{validator.get('name')}:{exc}", sid)
            continue
        cf_log.append_event(
            project_root, "stop_check",
            {"trigger": validator.get("trigger", ""),
             "cmd": str(validator.get("command", ""))[:120], "passed": passed},
            sid,
        )
        if not passed:
            failures.append({
                "name": validator.get("name", "validator"),
                "on_fail": validator.get("on_fail", ""),
                "detail": detail,
            })
    return failures, truncated


def _reason_text(failures: list, truncated: bool) -> str:
    lines = ["收尾校验未通过（cf-stop）："]
    for item in failures:
        lines.append(f"✗ {item['name']}：{item['on_fail']}")
        if item["detail"]:
            lines.append(f"  输出片段: {item['detail'][:200]}")
    if truncated:
        lines.append("（总预算 30s 已用尽，以上为已完成部分）")
    lines.append("请修复后再结束。")
    return "\n".join(lines)


def main() -> None:
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
        marker = os.path.join(project_root, ".code-flow", ".active-task.json")
        has_active = os.path.exists(marker)
        files = []
        if has_active:
            try:
                active = load_active_task(project_root)
                task_dir = os.path.join(project_root, active.task_dir)
                done = run_done_gate(project_root, task_dir)
            except (OSError, ValueError) as exc:
                payload = {"decision": "block", "reason": f"SPEC_WORKFLOW_BLOCKED: active task is invalid: {exc}"}
                sys.stdout.write(json.dumps(payload, ensure_ascii=False))
                return
            if done.decision != "pass":
                payload = {"decision": "block", "reason": "当前 TASK required Spec verifier/Evidence 未通过；修复或重新对齐后再 Done。"}
                sys.stdout.write(json.dumps(payload, ensure_ascii=False))
                return
            files = list(done.files)
        config = load_config(project_root)
        if not config:
            return
        if not resolve_quality_loop(config)["stop_check"]:
            return
        if not has_active:
            files = session_edited_files(project_root, sid)
        if not files:
            return
        acceptance_failures = task_acceptance_failures(project_root, files)
        validators = load_validators(project_root)
        failures, truncated = run_validators(
            project_root, validators, files, sid
        ) if validators else ([], False)
        failures = acceptance_failures + failures
        if not failures:
            return  # 全过或无 validation.yml 且无验收缺口时静默
        payload = {"decision": "block", "reason": _reason_text(failures, truncated)}
        sys.stdout.write(json.dumps(payload, ensure_ascii=False))
    except Exception as exc:
        _log(f"cf_stop_hook error: {exc}")
        return


if __name__ == "__main__":
    main()
