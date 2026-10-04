"""OpenCode v2 native event RPC; no Claude/Codex hook wire translation."""
import json
import os
import sys

import cf_log
from cf_core import _log, ensure_utf8_io
from cf_edit_service import after_edit, prepare_edit
from cf_exec_base import execution_session
from cf_native_paths import project_root, validated_paths
from cf_patch import FileOperation, parse_patch
from cf_runtime_install import verify_install
from cf_stop_hook import build_stop_result
from cf_user_prompt_hook import build_prompt_context


def edit_paths(root: str, directory: str, event: dict[str, object]) -> tuple[tuple[str, bool], ...]:
    tool, inputs = event.get("tool"), event.get("input")
    if not isinstance(inputs, dict):
        raise ValueError("native tool input must be an object")
    if tool in {"edit", "write"}:
        path = inputs.get("path")
        if not isinstance(path, str) or not path or "\x00" in path:
            raise ValueError(f"{tool}.input.path must be a nonempty path")
        operations = (FileOperation("update", path),)
    elif tool == "patch":
        command = inputs.get("patchText")
        if not isinstance(command, str):
            raise ValueError("patch.input.patchText must be a string")
        operations = parse_patch(command)
    else:
        return ()
    return validated_paths(root, directory, operations)


def tool_result(root: str, directory: str, kind: str, event: dict[str, object], sid: str) -> dict[str, object]:
    tool = event.get("tool")
    if tool not in {"edit", "write", "patch"}:
        return {"context": "", "blocked": False}
    if kind == "tool.after" and event.get("status") != "completed":
        cf_log.degrade(root, "opencode_tool", f"{tool}: edit not confirmed (status={event.get('status')})", sid)
        return {"context": "", "blocked": False}
    paths = edit_paths(root, directory, event)
    text = []
    blocked = False
    for path, deleted in paths:
        if kind == "tool.before":
            feedback, rejected = prepare_edit(root, path, sid, str(tool))
            blocked = blocked or rejected
        else:
            feedback = after_edit(root, path, sid, str(tool), deleted)
        if feedback:
            text.append(feedback)
    context = "\n\n".join(dict.fromkeys(text))
    return {"context": context, "blocked": blocked}


def dispatch(data: dict[str, object]) -> dict[str, object]:
    kind, directory, event = data.get("kind"), data.get("directory"), data.get("event")
    if not isinstance(directory, str) or not os.path.isabs(directory) or not isinstance(event, dict):
        raise ValueError("native event requires absolute session directory and an event object")
    sid = event.get("sessionID")
    if not isinstance(sid, str) or not sid:
        raise ValueError("native event requires sessionID")
    root = project_root(directory)
    if not root:
        return {"context": "", "blocked": False}
    verify_install(root)
    if kind == "session.prompt":
        prompt = event.get("prompt")
        if not isinstance(prompt, dict) or not isinstance(prompt.get("text"), str):
            raise ValueError("native prompt.text must be a string")
        text, mode = build_prompt_context(prompt["text"], sid, root)
        return {"context": text, "blocked": mode == "blocked"}
    if kind in {"tool.before", "tool.after"}:
        return tool_result(root, directory, kind, event, sid)
    if kind == "session.idle":
        with execution_session():
            result = build_stop_result(root, sid)
        return {"context": result.get("reason", ""), "blocked": result.get("decision") == "block"}
    raise ValueError(f"unknown native event kind: {kind}")


def main() -> None:
    ensure_utf8_io()
    try:
        data = json.loads(sys.stdin.read())
        if not isinstance(data, dict):
            raise ValueError("native RPC input must be an object")
        result = dispatch(data)
    except Exception as exc:
        _log(f"cf_opencode_event error: {exc}")
        result = {"error": f"code-flow OpenCode runtime failed: {exc}. Run code-flow migrate --runtime --dry-run, then --apply."}
    sys.stdout.write(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
