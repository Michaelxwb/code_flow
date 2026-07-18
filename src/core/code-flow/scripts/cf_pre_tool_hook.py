#!/usr/bin/env python3
"""PreToolUse hook: enforce active Context or inject deterministic path Specs."""

import json
import os
from pathlib import Path
import sys

import cf_log
from cf_core import _log, ensure_utf8_io, normalize_path, resolve_session_id
from cf_spec_context import load_active_task, load_context
from cf_spec_resolver import resolve_candidates
from cf_spec_router import RouterError, route_prompt


def _active_expansion(root: str, relative: str) -> tuple[str, ...]:
    marker = Path(root) / ".code-flow/.active-task.json"
    if not marker.exists():
        return ()
    active = load_active_task(root)
    context = load_context(str(Path(root) / active.task_dir / "spec-context.yml"))
    bound = {item.spec_id for item in context.bindings}
    return tuple(
        item.spec_id for item in resolve_candidates(root, "code", (relative,))
        if item.spec_id not in bound and item.metadata.enforcement == "required"
    )


def _deny(reason: str) -> dict[str, object]:
    return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny", "permissionDecisionReason": reason}}


def main() -> None:
    try:
        ensure_utf8_io()
        raw = sys.stdin.read()
        if not raw.strip():
            return
        data = json.loads(raw)
        tool_name = data.get("tool_name", "")
        file_path = (data.get("tool_input") or {}).get("file_path", "")
        if tool_name not in {"Edit", "Write", "MultiEdit"} or not isinstance(file_path, str) or not file_path:
            return
        root = os.getcwd()
        absolute = file_path if os.path.isabs(file_path) else os.path.join(root, file_path)
        relative = normalize_path(os.path.relpath(absolute, root))
        expanded = _active_expansion(root, relative)
        if expanded:
            reason = f"SPEC_WORKFLOW_BLOCKED: path introduces required Specs {', '.join(expanded)}; refresh Context and Plan first."
            sys.stdout.write(json.dumps(_deny(reason), ensure_ascii=False))
            return
        sid = resolve_session_id(data)
        result = route_prompt(root, (relative,), sid)
        if result.text:
            payload = {"hookSpecificOutput": {"hookEventName": "PreToolUse", "additionalContext": result.text}}
            sys.stdout.write(json.dumps(payload, ensure_ascii=False))
        cf_log.append_event(root, "edit_intent", {"file": relative, "tool": tool_name, "specs": list(result.specs)}, sid)
    except RouterError as exc:
        sys.stdout.write(json.dumps(_deny(f"SPEC_WORKFLOW_BLOCKED [{exc.code}]: {exc}"), ensure_ascii=False))
    except (json.JSONDecodeError, OSError, ValueError) as exc:
        _log(f"cf_pre_tool_hook error: {exc}")


if __name__ == "__main__":
    main()
