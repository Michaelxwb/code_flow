#!/usr/bin/env python3
import json
import os
import time

from cf_lane_core import gc_inject_states, inject_state_file_path, legacy_inject_state_path


def main() -> None:
    """Reset inject state for this session.

    Instead of deleting the state file (which breaks other sessions),
    write a fresh state with the current session's PID.
    Other sessions will detect the PID mismatch and reset their own state.
    """
    try:
        project_root = os.getcwd()
        sid = str(os.getpid())
        gc_inject_states(project_root, ttl_seconds=24 * 3600)
        state_path = inject_state_file_path(project_root, sid)
        payload = {
            "session_id": sid,
            "pid": int(os.getpid()),
            "start_at": time.time(),
            "injected_specs": [],
            "last_file": "",
        }
        os.makedirs(os.path.dirname(state_path), exist_ok=True)
        with open(state_path, "w", encoding="utf-8") as f:
            json.dump(payload, f)
    except Exception:
        try:
            project_root = os.getcwd()
            state_path = legacy_inject_state_path(project_root)
            payload = {
                "session_id": str(os.getpid()),
                "pid": int(os.getpid()),
                "start_at": time.time(),
                "injected_specs": [],
                "last_file": "",
            }
            os.makedirs(os.path.dirname(state_path), exist_ok=True)
            with open(state_path, "w", encoding="utf-8") as f:
                json.dump(payload, f)
        except Exception:
            return


if __name__ == "__main__":
    main()
