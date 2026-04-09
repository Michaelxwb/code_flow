#!/usr/bin/env python3
"""Tests for cf-lane sync command."""

import io
import os
import subprocess
import sys
import tempfile
from contextlib import redirect_stderr, redirect_stdout

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "core", "code-flow", "scripts"))

from cf_lane import main
from cf_lane_core import load_lanes


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


def _write_task(repo: str, rel: str) -> str:
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
        "- [2026-04-08] created (draft)\n"
    )
    abs_path = os.path.join(repo, rel)
    os.makedirs(os.path.dirname(abs_path), exist_ok=True)
    with open(abs_path, "w", encoding="utf-8") as f:
        f.write(content)
    return rel


def test_sync_none_defaults_to_main_and_updates_metadata() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        repo = os.path.join(tmpdir, "repo")
        wt = os.path.join(tmpdir, "wt")
        os.makedirs(repo, exist_ok=True)
        _init_repo(repo)

        task = _write_task(repo, ".code-flow/tasks/2026-04-08/t1.md")
        with open(os.path.join(repo, "feature.txt"), "w", encoding="utf-8") as f:
            f.write("base\n")
        _git(repo, "add", "--", task, "feature.txt")
        _git(repo, "commit", "-m", "add task and file")

        assert main(["--project-root", repo, "new", "t1", "--worktree", wt]) == 0
        lane_id = load_lanes(repo)["lanes"][0]["lane_id"]

        with open(os.path.join(repo, "feature.txt"), "w", encoding="utf-8") as f:
            f.write("main-update\n")
        _git(repo, "add", "--", "feature.txt")
        _git(repo, "commit", "-m", "update on main")

        out = io.StringIO()
        err = io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = main(["--project-root", repo, "sync", lane_id])
        assert code == 0, err.getvalue()
        updated = load_lanes(repo)["lanes"][0]
        assert updated["last_sync_from"] == "main"
        with open(os.path.join(wt, "feature.txt"), "r", encoding="utf-8") as f:
            assert "main-update" in f.read()


def test_sync_hard_defaults_to_dep_branch() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        repo = os.path.join(tmpdir, "repo")
        wt_base = os.path.join(tmpdir, "wt-base")
        wt_child = os.path.join(tmpdir, "wt-child")
        os.makedirs(repo, exist_ok=True)
        _init_repo(repo)

        t_base = _write_task(repo, ".code-flow/tasks/2026-04-08/base.md")
        t_child = _write_task(repo, ".code-flow/tasks/2026-04-08/child.md")
        _git(repo, "add", "--", t_base, t_child)
        _git(repo, "commit", "-m", "add task files")

        assert main([
            "--project-root", repo, "new", "base", "--worktree", wt_base, "--branch", "feat/base"
        ]) == 0
        dep_lane = load_lanes(repo)["lanes"][0]
        assert main([
            "--project-root", repo, "new", "child", "--worktree", wt_child, "--branch", "feat/child",
            "--dep-type", "hard", "--dep-lane", dep_lane["lane_id"]
        ]) == 0
        child_lane = load_lanes(repo)["lanes"][1]

        with open(os.path.join(wt_base, "shared.txt"), "w", encoding="utf-8") as f:
            f.write("from-upstream\n")
        _git(wt_base, "add", "--", "shared.txt")
        _git(wt_base, "commit", "-m", "upstream change")

        out = io.StringIO()
        err = io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = main(["--project-root", repo, "sync", child_lane["lane_id"]])
        assert code == 0, err.getvalue()
        with open(os.path.join(wt_child, "shared.txt"), "r", encoding="utf-8") as f:
            assert "from-upstream" in f.read()
        refreshed = load_lanes(repo)["lanes"][1]
        assert refreshed["last_sync_from"] == "feat/base"


def test_sync_conflict_aborts_merge_and_returns_error() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        repo = os.path.join(tmpdir, "repo")
        wt = os.path.join(tmpdir, "wt")
        os.makedirs(repo, exist_ok=True)
        _init_repo(repo)

        with open(os.path.join(repo, "conflict.txt"), "w", encoding="utf-8") as f:
            f.write("base\n")
        task = _write_task(repo, ".code-flow/tasks/2026-04-08/conflict-task.md")
        _git(repo, "add", "--", "conflict.txt", task)
        _git(repo, "commit", "-m", "base conflict file and task")

        assert main(["--project-root", repo, "new", "conflict-task", "--worktree", wt]) == 0
        lane_id = load_lanes(repo)["lanes"][0]["lane_id"]

        with open(os.path.join(wt, "conflict.txt"), "w", encoding="utf-8") as f:
            f.write("lane-change\n")
        _git(wt, "add", "--", "conflict.txt")
        _git(wt, "commit", "-m", "lane change")

        with open(os.path.join(repo, "conflict.txt"), "w", encoding="utf-8") as f:
            f.write("main-change\n")
        _git(repo, "add", "--", "conflict.txt")
        _git(repo, "commit", "-m", "main change")

        out = io.StringIO()
        err = io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = main(["--project-root", repo, "sync", lane_id])
        assert code == 1
        assert "sync conflict files" in err.getvalue()
        assert "conflict.txt" in err.getvalue()
        merge_head = _git(wt, "rev-parse", "-q", "--verify", "MERGE_HEAD", check=False)
        assert merge_head.returncode != 0


def test_sync_from_dep_requires_dep_lane() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        repo = os.path.join(tmpdir, "repo")
        wt = os.path.join(tmpdir, "wt")
        os.makedirs(repo, exist_ok=True)
        _init_repo(repo)
        task = _write_task(repo, ".code-flow/tasks/2026-04-08/t1.md")
        _git(repo, "add", "--", task)
        _git(repo, "commit", "-m", "task")

        assert main(["--project-root", repo, "new", "t1", "--worktree", wt]) == 0
        lane_id = load_lanes(repo)["lanes"][0]["lane_id"]

        out = io.StringIO()
        err = io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = main(["--project-root", repo, "sync", lane_id, "--from", "dep"])
        assert code == 1
        assert "dep-lane is missing" in err.getvalue()


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
