#!/usr/bin/env python3
"""Tests for cf_session_hook.py."""

import json
import os
import subprocess
import sys
import tempfile
import unittest.mock as mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "core", "code-flow", "scripts"))

from cf_lane_core import compute_worktree_id, inject_state_file_path, resolve_common_dir
from cf_session_hook import main


def _init_git_repo(path: str) -> None:
    subprocess.run(["git", "init"], cwd=path, check=True, capture_output=True, text=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=path, check=True, capture_output=True, text=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=path, check=True, capture_output=True, text=True)
    with open(os.path.join(path, "README.md"), "w", encoding="utf-8") as f:
        f.write("demo\n")
    subprocess.run(["git", "add", "README.md"], cwd=path, check=True, capture_output=True, text=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=path, check=True, capture_output=True, text=True)


def test_session_hook_writes_new_state_and_gc_stale() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        _init_git_repo(tmpdir)
        wt_id = compute_worktree_id(tmpdir)
        stale_dir = os.path.join(resolve_common_dir(tmpdir), "inject-states", wt_id)
        os.makedirs(stale_dir, exist_ok=True)
        stale_path = os.path.join(stale_dir, "old.json")
        with open(stale_path, "w", encoding="utf-8") as f:
            json.dump({"session_id": "999999", "pid": 999999, "start_at": 1.0}, f)

        with mock.patch("os.getcwd", return_value=tmpdir), mock.patch("os.getpid", return_value=12345):
            main()

        assert not os.path.exists(stale_path)
        state_path = inject_state_file_path(tmpdir, "12345", wt_id)
        assert os.path.exists(state_path)
        with open(state_path, "r", encoding="utf-8") as f:
            payload = json.load(f)
        assert payload["session_id"] == "12345"
        assert payload["injected_specs"] == []


def test_session_hook_fallback_legacy_when_new_path_fails() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        os.makedirs(os.path.join(tmpdir, ".code-flow"), exist_ok=True)
        with mock.patch("os.getcwd", return_value=tmpdir), \
             mock.patch("cf_session_hook.inject_state_file_path", side_effect=RuntimeError("boom")), \
             mock.patch("os.getpid", return_value=123):
            main()

        legacy = os.path.join(tmpdir, ".code-flow", ".inject-state")
        assert os.path.exists(legacy)
        with open(legacy, "r", encoding="utf-8") as f:
            payload = json.load(f)
        assert payload["session_id"] == "123"


if __name__ == "__main__":
    import traceback

    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    passed = 0
    failed = 0
    for test in tests:
        try:
            test()
            passed += 1
            print(f"  PASS {test.__name__}")
        except Exception:
            failed += 1
            print(f"  FAIL {test.__name__}")
            traceback.print_exc()
    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
