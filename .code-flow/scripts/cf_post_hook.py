#!/usr/bin/env python3
"""Claude-style PostToolUse protocol entry; edit rules live in cf_edit_service."""
import json
import os
import sys

from cf_core import _log, ensure_utf8_io, resolve_session_id, timing_log
from cf_edit_service import after_edit


def main() -> None:
    try:
        ensure_utf8_io()
        if sys.stdin.isatty():
            _log("cf_post_hook.py: missing stdin event")
            return
        raw = sys.stdin.read()
        if not raw.strip():
            return
        data = json.loads(raw)
        tool = data.get("tool_name", "")
        path = (data.get("tool_input") or {}).get("file_path", "")
        if tool not in {"Edit", "Write", "MultiEdit"} or not isinstance(path, str) or not path:
            return
        text = after_edit(os.getcwd(), path, resolve_session_id(data), tool)
        if text:
            sys.stdout.write(json.dumps({"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": text}}, ensure_ascii=False))
    except Exception as exc:
        _log(f"cf_post_hook.py error: {exc}")


if __name__ == "__main__":
    main()
    timing_log("cf_post_hook")
