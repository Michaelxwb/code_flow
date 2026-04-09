#!/usr/bin/env python3
"""Tests for cf-lane close/cancel commands."""

import io
import os
import subprocess
import sys
import tempfile
import unittest.mock as mock
from contextlib import redirect_stderr, redirect_stdout

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "core", "code-flow", "scripts"))

from cf_lane import main
from cf_lane_core import load_lanes


def _git(cwd: str, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


def _init_repo(path: str) -> None:
    _git(path, "init")
    _git(path, "config", "user.email", "test@example.com")
    _git(path, "config", "user.name", "Test User")
    with open(os.path.join(path, "README.md"), "w", encoding="utf-8") as f:
        f.write("demo\n")
    _git(path, "add", "README.md")
    _git(path, "commit", "-m", "init")
    _git(path, "branch", "-M", "main")


def _write_task(repo: str, rel: str, status: str = "done") -> str:
    content = (
        "# Tasks: Demo\n\n"
        "- **Source**: docs/demo.md\n"
        "- **Created**: 2026-04-08\n"
        "- **Updated**: 2026-04-08\n\n"
        "## TASK-001: Demo\n\n"
        f"- **Status**: {status}\n"
        "- **Priority**: P0\n"
        "- **Depends**:\n\n"
        "### Checklist\n"
        "- [x] one\n\n"
        "### Log\n"
        "- [2026-04-08] created\n"
    )
    abs_path = os.path.join(repo, rel)
    os.makedirs(os.path.dirname(abs_path), exist_ok=True)
    with open(abs_path, "w", encoding="utf-8") as f:
        f.write(content)
    return rel


def test_close_rejects_when_task_not_done() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        repo = os.path.join(tmpdir, "repo")
        wt = os.path.join(tmpdir, "wt")
        os.makedirs(repo, exist_ok=True)
        _init_repo(repo)
        task = _write_task(repo, ".code-flow/tasks/2026-04-08/t1.md", status="draft")
        _git(repo, "add", "--", task)
        _git(repo, "commit", "-m", "add task")

        assert main(["--project-root", repo, "new", "t1", "--worktree", wt]) == 0
        lane_id = load_lanes(repo)["lanes"][0]["lane_id"]

        out = io.StringIO()
        err = io.StringIO()
        with mock.patch("cf_lane._run_validate", return_value=None), \
             redirect_stdout(out), redirect_stderr(err):
            code = main(["--project-root", repo, "close", lane_id, "--keep-worktree"])
        assert code == 1
        assert "task is not done" in err.getvalue()


def test_close_hard_dependency_requires_upstream_closed() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        repo = os.path.join(tmpdir, "repo")
        wt_a = os.path.join(tmpdir, "wt-a")
        wt_b = os.path.join(tmpdir, "wt-b")
        os.makedirs(repo, exist_ok=True)
        _init_repo(repo)
        t_a = _write_task(repo, ".code-flow/tasks/2026-04-08/upstream.md", status="done")
        t_b = _write_task(repo, ".code-flow/tasks/2026-04-08/downstream.md", status="done")
        _git(repo, "add", "--", t_a, t_b)
        _git(repo, "commit", "-m", "add tasks")

        assert main([
            "--project-root", repo, "new", "upstream", "--worktree", wt_a, "--branch", "feat/upstream"
        ]) == 0
        upstream_lane = load_lanes(repo)["lanes"][0]
        assert main([
            "--project-root", repo, "new", "downstream", "--worktree", wt_b, "--branch", "feat/downstream",
            "--dep-type", "hard", "--dep-lane", upstream_lane["lane_id"]
        ]) == 0
        downstream_lane = load_lanes(repo)["lanes"][1]

        with mock.patch("cf_lane._run_validate", return_value=None):
            code_blocked = main(["--project-root", repo, "close", downstream_lane["lane_id"], "--keep-worktree"])
            assert code_blocked == 1
            assert main(["--project-root", repo, "close", upstream_lane["lane_id"], "--keep-worktree"]) == 0
            assert main(["--project-root", repo, "close", downstream_lane["lane_id"], "--keep-worktree"]) == 0

        lanes = load_lanes(repo)["lanes"]
        assert lanes[0]["status"] == "closed"
        assert lanes[1]["status"] == "closed"


def test_close_soft_dependency_requires_accept_flag() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        repo = os.path.join(tmpdir, "repo")
        wt_a = os.path.join(tmpdir, "wt-a")
        wt_b = os.path.join(tmpdir, "wt-b")
        os.makedirs(repo, exist_ok=True)
        _init_repo(repo)
        t_a = _write_task(repo, ".code-flow/tasks/2026-04-08/upstream.md", status="done")
        t_b = _write_task(repo, ".code-flow/tasks/2026-04-08/downstream.md", status="done")
        _git(repo, "add", "--", t_a, t_b)
        _git(repo, "commit", "-m", "add tasks")

        assert main([
            "--project-root", repo, "new", "upstream", "--worktree", wt_a, "--branch", "feat/upstream"
        ]) == 0
        upstream_lane = load_lanes(repo)["lanes"][0]
        assert main([
            "--project-root", repo, "new", "downstream", "--worktree", wt_b, "--branch", "feat/downstream",
            "--dep-type", "soft", "--dep-lane", upstream_lane["lane_id"]
        ]) == 0
        downstream_lane = load_lanes(repo)["lanes"][1]

        with mock.patch("cf_lane._run_validate", return_value=None):
            assert main(["--project-root", repo, "close", downstream_lane["lane_id"], "--keep-worktree"]) == 1
            assert main([
                "--project-root", repo, "close", downstream_lane["lane_id"],
                "--keep-worktree", "--accept-soft-risk"
            ]) == 0


def test_cancel_keep_marks_cancelled_and_blocks_sync_close() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        repo = os.path.join(tmpdir, "repo")
        wt = os.path.join(tmpdir, "wt")
        os.makedirs(repo, exist_ok=True)
        _init_repo(repo)
        task = _write_task(repo, ".code-flow/tasks/2026-04-08/t1.md", status="done")
        _git(repo, "add", "--", task)
        _git(repo, "commit", "-m", "add task")

        assert main(["--project-root", repo, "new", "t1", "--worktree", wt]) == 0
        lane_id = load_lanes(repo)["lanes"][0]["lane_id"]
        assert main(["--project-root", repo, "cancel", lane_id, "--keep-worktree"]) == 0

        lane = load_lanes(repo)["lanes"][0]
        assert lane["status"] == "cancelled"
        assert main(["--project-root", repo, "sync", lane_id]) == 1
        with mock.patch("cf_lane._run_validate", return_value=None):
            assert main(["--project-root", repo, "close", lane_id, "--keep-worktree"]) == 1


def test_cancel_rollback_resets_task_status_to_draft() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        repo = os.path.join(tmpdir, "repo")
        wt = os.path.join(tmpdir, "wt")
        os.makedirs(repo, exist_ok=True)
        _init_repo(repo)
        task = _write_task(repo, ".code-flow/tasks/2026-04-08/t1.md", status="done")
        _git(repo, "add", "--", task)
        _git(repo, "commit", "-m", "add task")

        assert main(["--project-root", repo, "new", "t1", "--worktree", wt]) == 0
        lane_id = load_lanes(repo)["lanes"][0]["lane_id"]
        assert main([
            "--project-root", repo, "cancel", lane_id, "--keep-worktree", "--task-policy", "rollback"
        ]) == 0

        with open(os.path.join(repo, task), "r", encoding="utf-8") as f:
            content = f.read()
        assert "- **Status**: draft" in content
        assert "- **Lifecycle**: approved" in content


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
