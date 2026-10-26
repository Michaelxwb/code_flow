#!/usr/bin/env python3
"""Claude-style PreToolUse protocol entry; edit rules live in cf_edit_service."""
import json
import os
import sys

from codeflow.core.cf_core import ensure_utf8_io, resolve_session_id, timing_log
from codeflow.core.cf_log import warn
from codeflow.spec.cf_edit_service import prepare_edit
from codeflow.spec.cf_injection import injection_output, pre_tool_payload
from codeflow.core.cf_native_paths import project_root


def main() -> None:
    try:
        ensure_utf8_io()
        if sys.stdin.isatty():
            warn("cf_pre_tool_hook.py: missing stdin event")
            return
        raw = sys.stdin.read()
        if not raw.strip():
            return
        data = json.loads(raw)
        tool = data.get("tool_name", "")
        path = (data.get("tool_input") or {}).get("file_path", "")
        if tool not in {"Edit", "Write", "MultiEdit"} or not isinstance(path, str) or not path:
            return
        directory = os.getcwd()
        root = project_root(directory)
        if not root:
            return
        absolute = path if os.path.isabs(path) else os.path.join(directory, path)
        with injection_output():
            text, blocked = prepare_edit(root, absolute, resolve_session_id(data), tool)
            if text:
                sys.stdout.write(json.dumps(pre_tool_payload(text, blocked), ensure_ascii=False))
                sys.stdout.flush()
    except Exception as exc:
        warn(f"cf_pre_tool_hook.py error: {exc}")
        text = f"SPEC_WORKFLOW_BLOCKED [pre_tool_error]: {exc}"
        sys.stdout.write(json.dumps(pre_tool_payload(text, True), ensure_ascii=False))
