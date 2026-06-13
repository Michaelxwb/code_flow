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
    lines = ["收尾校验未通过（cf-stop，FEAT-03）："]
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
        config = load_config(project_root)
        if not config:
            return
        if not resolve_quality_loop(config)["stop_check"]:
            return
        sid = resolve_session_id(data)
        files = session_edited_files(project_root, sid)
        if not files:
            return
        validators = load_validators(project_root)
        if not validators:
            return  # E-05: 无 validation.yml 静默
        failures, truncated = run_validators(project_root, validators, files, sid)
        if not failures:
            return  # 全过静默（S-05）
        payload = {"decision": "block", "reason": _reason_text(failures, truncated)}
        sys.stdout.write(json.dumps(payload, ensure_ascii=False))
    except Exception as exc:
        _log(f"cf_stop_hook error: {exc}")
        return


if __name__ == "__main__":
    main()
