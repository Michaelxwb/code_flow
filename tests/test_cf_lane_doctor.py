#!/usr/bin/env python3
"""Tests for cf-lane doctor command."""

import io
import json
import os
import subprocess
import sys
import tempfile
from contextlib import redirect_stderr, redirect_stdout

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "core", "code-flow", "scripts"))

from cf_lane import main
from cf_lane_core import lanes_file_path, load_lanes, resolve_common_dir


def _git(cwd: str, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=cwd, check=check, capture_output=True, text=True)


def _init_repo(path: str) -> None:
    _git(path, "init")
    _git(path, "config", "user.email", "test@example.com")
    _git(path, "config", "user.name", "Test User")
    with open(os.path.join(path, "README.md"), "w", encoding="utf-8") as f:
        f.write("demo\n")
    _git(path, "add", "README.md")
    _git(path, "commit", "-m", "init")
    _git(path, "branch", "-M", "main")


def _write_task(repo: str, rel: str = ".code-flow/tasks/2026-04-08/t1.md") -> str:
    content = (
        "# Tasks: Demo\n\n"
        "- **Source**: docs/demo.md\n"
        "- **Created**: 2026-04-08\n"
        "- **Updated**: 2026-04-08\n\n"
        "## TASK-001: Demo\n\n"
        "- **Status**: draft\n"
        "- **Priority**: P0\n"
        "- **Depends**:\n\n"
        "### Checklist\n"
        "- [ ] one\n\n"
        "### Log\n"
        "- [2026-04-08] created\n"
    )
    abs_path = os.path.join(repo, rel)
    os.makedirs(os.path.dirname(abs_path), exist_ok=True)
    with open(abs_path, "w", encoding="utf-8") as f:
        f.write(content)
    return rel


def _doctor_json(repo: str, *args: str) -> tuple[int, dict]:
    out = io.StringIO()
    err = io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = main(["--project-root", repo, "doctor", "--json", *args])
    payload = json.loads(out.getvalue()) if out.getvalue().strip() else {}
    return code, payload


def test_doctor_passes_on_healthy_registry() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        repo = os.path.join(tmpdir, "repo")
        wt = os.path.join(tmpdir, "wt")
        os.makedirs(repo, exist_ok=True)
        _init_repo(repo)
        task = _write_task(repo)
        _git(repo, "add", "--", task)
        _git(repo, "commit", "-m", "add task")
        assert main(["--project-root", repo, "new", "t1", "--worktree", wt]) == 0

        code, payload = _doctor_json(repo)
        assert code == 0
        assert payload["ok"] is True


def test_doctor_fix_marks_orphan_lane_cancelled() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        repo = os.path.join(tmpdir, "repo")
        wt = os.path.join(tmpdir, "wt")
        os.makedirs(repo, exist_ok=True)
        _init_repo(repo)
        task = _write_task(repo)
        _git(repo, "add", "--", task)
        _git(repo, "commit", "-m", "add task")
        assert main([
            "--project-root", repo, "new", "t1", "--worktree", wt, "--branch", "feat/t1"
        ]) == 0

        _git(repo, "worktree", "remove", "--force", wt)
        _git(repo, "branch", "-D", "feat/t1")

        code_before, payload_before = _doctor_json(repo)
        assert code_before == 1
        active_check = [c for c in payload_before["checks"] if c["name"] == "active_entities"][0]
        assert active_check["ok"] is False

        code_fix, payload_fix = _doctor_json(repo, "--fix")
        assert code_fix == 0
        assert payload_fix["ok"] is True
        actions = [f["action"] for f in payload_fix["fixes"]]
        assert "mark_orphan_cancelled" in actions
        lane = load_lanes(repo)["lanes"][0]
        assert lane["status"] == "cancelled"


def test_doctor_fix_cleans_stale_lock() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        repo = os.path.join(tmpdir, "repo")
        os.makedirs(repo, exist_ok=True)
        _init_repo(repo)
        lock_dir = os.path.join(resolve_common_dir(repo), "locks")
        os.makedirs(lock_dir, exist_ok=True)
        stale = os.path.join(lock_dir, "stale.lock")
        with open(stale, "w", encoding="utf-8") as f:
            json.dump({"pid": 999999, "host": "x", "start_at": 1.0, "command": "old"}, f)

        code_before, payload_before = _doctor_json(repo)
        assert code_before == 1
        stale_check = [c for c in payload_before["checks"] if c["name"] == "stale_lock"][0]
        assert stale_check["ok"] is False

        code_fix, payload_fix = _doctor_json(repo, "--fix")
        assert code_fix == 0
        assert payload_fix["ok"] is True
        assert not os.path.exists(stale)


def test_doctor_ci_skips_missing_worktree() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        repo = os.path.join(tmpdir, "repo")
        wt = os.path.join(tmpdir, "wt")
        os.makedirs(repo, exist_ok=True)
        _init_repo(repo)
        task = _write_task(repo)
        _git(repo, "add", "--", task)
        _git(repo, "commit", "-m", "add task")
        assert main(["--project-root", repo, "new", "t1", "--worktree", wt]) == 0
        _git(repo, "worktree", "remove", "--force", wt)

        code_default, _ = _doctor_json(repo)
        assert code_default == 1
        code_ci, payload_ci = _doctor_json(repo, "--ci")
        assert code_ci == 0
        assert payload_ci["ci_mode"] is True
        assert payload_ci["ok"] is True


def test_doctor_schema_error() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        repo = os.path.join(tmpdir, "repo")
        os.makedirs(repo, exist_ok=True)
        _init_repo(repo)
        path = lanes_file_path(repo)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"version": 2, "lanes": []}, f)

        code, payload = _doctor_json(repo)
        assert code == 1
        assert payload["ok"] is False
        assert payload["checks"][0]["name"] == "schema"
        lock_path = os.path.join(resolve_common_dir(repo), "locks", "lanes.lock")
        assert not os.path.exists(lock_path)


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
