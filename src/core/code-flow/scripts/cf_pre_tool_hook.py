#!/usr/bin/env python3
"""PreToolUse hook: advisory Context/scope guidance on Edit/Write/MultiEdit.

Hot-path policy: never deny the tool; inject context or guidance instead.
Hard enforcement lives at the checkpoints (start / done / stop), not here.
"""

import json
import os
from pathlib import Path
import sys

import cf_log
from cf_core import _log, ensure_utf8_io, load_config, normalize_path, resolve_enforcement, resolve_session_id
from cf_session_state import load_session_state, save_session_state
from cf_spec_context import load_active_task, load_context
from cf_spec_resolver import resolve_candidates
from cf_spec_router import RouterError, route_prompt

_WARN_TEXT = "⚠ Spec Workflow 校验未通过（warn 模式）：{message} — 建议运行 cf-spec doctor 检查。"


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


def _inject(text: str) -> dict[str, object]:
    return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "additionalContext": text}}


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
        sid = resolve_session_id(data)
        config = load_config(root)
        enforcement = resolve_enforcement(config) if config else "required"
        absolute = file_path if os.path.isabs(file_path) else os.path.join(root, file_path)
        relative = normalize_path(os.path.relpath(absolute, root))
        try:
            expanded = _active_expansion(root, relative)
            result = route_prompt(root, (relative,), sid)
        except RouterError as exc:
            if enforcement == "required":
                sys.stdout.write(json.dumps(_inject(f"SPEC_WORKFLOW_BLOCKED [{exc.code}]: {exc}. Run cf-spec doctor before continuing."), ensure_ascii=False))
            elif enforcement == "warn":
                sys.stdout.write(json.dumps(_inject(_WARN_TEXT.format(message=str(exc))), ensure_ascii=False))
            return
        if expanded:
            message = f"⚠ 该路径引入未绑定 required Spec：{', '.join(expanded)} — 建议先 refresh Context / Plan 再继续编辑。"
            sys.stdout.write(json.dumps(_inject(message), ensure_ascii=False))
            return
        text = result.text
        if result.mode == "task" and result.context_sha256:
            # The projection is already in context from the prompt route unless
            # the bound rules changed; skip per-edit re-injection.
            state = load_session_state(root)
            if state.get("injected_sha256") == result.context_sha256:
                text = ""
            else:
                state["injected_sha256"] = result.context_sha256
                save_session_state(root, state)
        if text:
            sys.stdout.write(json.dumps(_inject(text), ensure_ascii=False))
        cf_log.append_event(root, "edit_intent", {"file": relative, "tool": tool_name, "specs": list(result.specs)}, sid)
    except (json.JSONDecodeError, OSError, ValueError) as exc:
        _log(f"cf_pre_tool_hook error: {exc}")


if __name__ == "__main__":
    main()
