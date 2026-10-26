#!/usr/bin/env python3
"""Codex native wire protocol. Never translate patches into Claude tool calls."""
import json
import os
import sys

from cf_core import _log, ensure_utf8_io
from cf_edit_service import after_edit, prepare_edits
from cf_injection import injection_output, pre_tool_payload
from cf_stop_hook import process_stop
from cf_user_prompt_hook import process_prompt
from cf_runtime_install import verify_install
from cf_exec_base import execution_session
import cf_log
from cf_patch import parse_patch
from cf_native_paths import project_root, validated_paths




def patch_succeeded(response: object) -> bool:
    if isinstance(response, dict):
        if response.get("error") or response.get("isError") or response.get("exit_code", 0) != 0:
            return False
        response = response.get("output", "")
    return isinstance(response, str) and response.startswith("Success. Updated the following files:")


def dispatch(data: dict[str, object]) -> None:
    cwd, sid, event = data.get("cwd"), data.get("session_id"), data.get("hook_event_name")
    if not isinstance(cwd, str) or not os.path.isabs(cwd) or not isinstance(sid, str) or not sid:
        raise ValueError("Codex hook requires absolute cwd and nonempty session_id")
    root = project_root(cwd)
    if not root:
        return
    verify_install(root)
    if event == "UserPromptSubmit":
        process_prompt(data, root)
        return
    if event == "Stop":
        with execution_session():
            process_stop(data, root)
        return
    if event not in {"PreToolUse", "PostToolUse"}:
        raise ValueError(f"unsupported Codex hook event: {event}")
    if data.get("tool_name") != "apply_patch":
        return
    if event == "PostToolUse" and not patch_succeeded(data.get("tool_response")):
        cf_log.degrade(root, "codex_post_tool", "patch success not confirmed; no edit evidence recorded", sid)
        return
    tool_input = data.get("tool_input")
    if not isinstance(tool_input, dict) or not isinstance(tool_input.get("command"), str):
        raise ValueError("apply_patch requires tool_input.command")
    paths = validated_paths(root, cwd, parse_patch(tool_input["command"]))
    if event == "PreToolUse":
        text, blocked = prepare_edits(root, tuple(path for path, _ in paths), sid, "apply_patch")
        if text:
            sys.stdout.write(json.dumps(pre_tool_payload(text, blocked), ensure_ascii=False))
        return
    feedback = []
    for path, deleted in paths:
        text = after_edit(root, path, sid, "apply_patch", deleted)
        if text and text not in feedback:
            feedback.append(text)
    if feedback:
        sys.stdout.write(json.dumps({"hookSpecificOutput": {"hookEventName": event,
                                    "additionalContext": "\n\n".join(feedback)}}, ensure_ascii=False))


def main() -> None:
    data: dict[str, object] = {}
    try:
        ensure_utf8_io()
        if sys.stdin.isatty():
            _log("cf_codex_hook: missing stdin event")
            return
        raw = sys.stdin.read()
        if raw.strip():
            data = json.loads(raw)
            if not isinstance(data, dict):
                raise ValueError("Codex hook event must be an object")
            with injection_output():
                dispatch(data)
                sys.stdout.flush()
    except Exception as exc:
        _log(f"cf_codex_hook error: {exc}")
        message = f"code-flow Codex hook failed: {exc}. Run code-flow migrate --runtime --dry-run, then --apply."
        payload = ({"decision": "block", "reason": message} if isinstance(data, dict) and data.get("hook_event_name") == "Stop"
                   else {"systemMessage": message})
        if isinstance(data, dict) and data.get("hook_event_name") == "PreToolUse":
            payload.update(pre_tool_payload(message, True))
        if isinstance(data, dict) and data.get("hook_event_name") == "UserPromptSubmit":
            payload.update(decision="block", reason=message)
        sys.stdout.write(json.dumps(payload, ensure_ascii=False))


if __name__ == "__main__":
    main()
