#!/usr/bin/env python3
"""SessionStart hook: reset .inject-state for the new session.

Reads the session_id from the hook payload (stdin JSON) so the value matches
what PreToolUse / UserPromptSubmit will write later — keeping the
"hook id 优先、回退 PID" contract in cf_core.resolve_session_id consistent
across the session. If stdin is empty (older runtime, unit test) we fall back
to the current PID; the next hook with a real session_id will then trigger
the normal session-mismatch reset path, so behavior degrades gracefully.
"""
import json
import os
import sys

from cf_core import ensure_utf8_io, resolve_session_id


def main() -> None:
    try:
        ensure_utf8_io()
        raw = sys.stdin.read()
        data = json.loads(raw) if raw and raw.strip() else {}
        if not isinstance(data, dict):
            data = {}
        sid = resolve_session_id(data)

        project_root = os.getcwd()
        state_path = os.path.join(project_root, ".code-flow", ".inject-state")
        os.makedirs(os.path.dirname(state_path), exist_ok=True)
        payload = {
            "session_id": sid,
            "injected_specs": [],
            "last_file": "",
        }
        with open(state_path, "w", encoding="utf-8") as f:
            json.dump(payload, f)
    except Exception:
        return


if __name__ == "__main__":
    main()
