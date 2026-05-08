#!/usr/bin/env python3
"""Tests for cf_session_hook.py — verifies it reads session_id from stdin
so the value matches what PreToolUse / UserPromptSubmit will see."""
import io
import json
import os
import sys
import tempfile
import unittest.mock as mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "core", "code-flow", "scripts"))
from cf_session_hook import main


def _run(stdin_payload: str, project_root: str, pid: int = 12345) -> dict:
    """Invoke main() with the given stdin and return parsed .inject-state."""
    with mock.patch("sys.stdin", io.StringIO(stdin_payload)), \
         mock.patch("os.getcwd", return_value=project_root), \
         mock.patch("os.getpid", return_value=pid):
        main()
    state_path = os.path.join(project_root, ".code-flow", ".inject-state")
    if not os.path.exists(state_path):
        return {}
    with open(state_path, "r", encoding="utf-8") as f:
        return json.load(f)


def test_session_hook_reads_session_id_from_stdin() -> None:
    """The whole point of P0-1: session_id from hook payload must win over PID."""
    with tempfile.TemporaryDirectory() as tmpdir:
        os.makedirs(os.path.join(tmpdir, ".code-flow"), exist_ok=True)
        payload = json.dumps({"session_id": "real-session-abc"})
        state = _run(payload, tmpdir, pid=99999)
        assert state["session_id"] == "real-session-abc", state
        assert state["injected_specs"] == []
        assert state["last_file"] == ""


def test_session_hook_falls_back_to_pid_when_stdin_empty() -> None:
    """No stdin → fall back to PID gracefully (older runtimes, unit tests)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        os.makedirs(os.path.join(tmpdir, ".code-flow"), exist_ok=True)
        state = _run("", tmpdir, pid=42)
        assert state["session_id"] == "42"


def test_session_hook_handles_non_dict_payload() -> None:
    """JSON array / string at top level → fall back, never crash."""
    with tempfile.TemporaryDirectory() as tmpdir:
        os.makedirs(os.path.join(tmpdir, ".code-flow"), exist_ok=True)
        state = _run('["not", "a", "dict"]', tmpdir, pid=7)
        assert state["session_id"] == "7"


def test_session_hook_creates_dir_if_missing() -> None:
    """No .code-flow dir yet → hook creates it and writes the state."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Intentionally do NOT pre-create .code-flow
        state = _run(json.dumps({"session_id": "fresh"}), tmpdir, pid=1)
        assert state["session_id"] == "fresh"
        assert os.path.isdir(os.path.join(tmpdir, ".code-flow"))


def test_session_hook_resets_injected_specs() -> None:
    """Existing state with stale injected_specs must be replaced with []."""
    with tempfile.TemporaryDirectory() as tmpdir:
        cf_dir = os.path.join(tmpdir, ".code-flow")
        os.makedirs(cf_dir, exist_ok=True)
        state_path = os.path.join(cf_dir, ".inject-state")
        with open(state_path, "w", encoding="utf-8") as f:
            json.dump({
                "session_id": "old",
                "injected_specs": ["scripts/_map.md", "cli/_map.md"],
                "last_file": "src/cli.js",
            }, f)

        state = _run(json.dumps({"session_id": "new"}), tmpdir, pid=2)
        assert state["session_id"] == "new"
        assert state["injected_specs"] == []
        assert state["last_file"] == ""
