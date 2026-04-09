#!/usr/bin/env python3
"""Tests for cf_lane.py new command."""

import io
import os
import subprocess
import sys
import tempfile
import unittest.mock as mock
from contextlib import redirect_stderr, redirect_stdout

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "core", "code-flow", "scripts"))

from cf_lane import main, resolve_task_file
from cf_lane_core import load_lanes


TASK_TEMPLATE = """# Tasks: Demo\n\n- **Source**: docs/demo.md\n- **Created**: 2026-04-08\n- **Updated**: 2026-04-08\n- **Lifecycle**: approved\n\n## TASK-001: Demo\n\n- **Status**: draft\n- **Priority**: P0\n- **Depends**:\n\n### Checklist\n- [ ] one\n\n### Log\n- [2026-04-08] created (draft)\n"""


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


def _write_task(repo: str, rel: str = ".code-flow/tasks/2026-04-08/worktree-parallel.md", commit: bool = True) -> str:
    abs_path = os.path.join(repo, rel)
    os.makedirs(os.path.dirname(abs_path), exist_ok=True)
    with open(abs_path, "w", encoding="utf-8") as f:
        f.write(TASK_TEMPLATE)
    if commit:
        _git(repo, "add", "--", rel)
        _git(repo, "commit", "-m", "add task")
    return rel


def _write_task_without_lifecycle(repo: str, rel: str = ".code-flow/tasks/2026-04-08/draft-only.md") -> str:
    content = TASK_TEMPLATE.replace("- **Lifecycle**: approved\n", "")
    abs_path = os.path.join(repo, rel)
    os.makedirs(os.path.dirname(abs_path), exist_ok=True)
    with open(abs_path, "w", encoding="utf-8") as f:
        f.write(content)
    _git(repo, "add", "--", rel)
    _git(repo, "commit", "-m", "add draft-only task")
    return rel


def test_resolve_task_file_short_name_unique() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        _init_repo(tmpdir)
        rel = _write_task(tmpdir)
        resolved = resolve_task_file(tmpdir, "worktree-parallel")
        assert resolved == rel


def test_resolve_task_file_multiple_matches() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        _init_repo(tmpdir)
        _write_task(tmpdir, ".code-flow/tasks/2026-04-08/worktree-parallel.md", commit=False)
        _write_task(tmpdir, ".code-flow/tasks/2026-04-09/worktree-parallel.md", commit=False)
        try:
            resolve_task_file(tmpdir, "worktree-parallel")
        except ValueError as exc:
            assert "multiple paths" in str(exc)
        else:
            assert False, "expected ValueError"


def test_new_creates_lane_and_worktree() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        repo = os.path.join(tmpdir, "repo")
        wt = os.path.join(tmpdir, "wt")
        os.makedirs(repo, exist_ok=True)
        _init_repo(repo)
        rel = _write_task(repo)

        out = io.StringIO()
        err = io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = main(["--project-root", repo, "new", "worktree-parallel", "--worktree", wt])
        assert code == 0, err.getvalue()

        lanes = load_lanes(repo)
        assert len(lanes["lanes"]) == 1
        lane = lanes["lanes"][0]
        assert lane["task_file"] == rel
        assert lane["status"] == "active"
        assert os.path.isdir(wt)


def test_new_dep_lane_missing_fails() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        repo = os.path.join(tmpdir, "repo")
        wt = os.path.join(tmpdir, "wt")
        os.makedirs(repo, exist_ok=True)
        _init_repo(repo)
        _write_task(repo)

        out = io.StringIO()
        err = io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = main([
                "--project-root", repo, "new", "worktree-parallel", "--worktree", wt,
                "--dep-type", "hard", "--dep-lane", "lane-missing"
            ])
        assert code == 1
        assert "dep-lane not found" in err.getvalue()


def test_new_branch_conflict_fails() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        repo = os.path.join(tmpdir, "repo")
        wt = os.path.join(tmpdir, "wt")
        os.makedirs(repo, exist_ok=True)
        _init_repo(repo)
        _write_task(repo)
        _git(repo, "branch", "feat/worktree-parallel")

        out = io.StringIO()
        err = io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = main(["--project-root", repo, "new", "worktree-parallel", "--worktree", wt])
        assert code == 1
        assert "branch already exists" in err.getvalue()


def test_new_worktree_path_conflict_fails() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        repo = os.path.join(tmpdir, "repo")
        wt = os.path.join(tmpdir, "wt")
        os.makedirs(repo, exist_ok=True)
        os.makedirs(wt, exist_ok=True)
        with open(os.path.join(wt, "placeholder.txt"), "w", encoding="utf-8") as f:
            f.write("occupied\n")

        _init_repo(repo)
        _write_task(repo)

        out = io.StringIO()
        err = io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = main(["--project-root", repo, "new", "worktree-parallel", "--worktree", wt])
        assert code == 1
        assert "worktree path conflict" in err.getvalue()


def test_new_hard_dep_uses_dep_branch_as_base() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        repo = os.path.join(tmpdir, "repo")
        wt_a = os.path.join(tmpdir, "wt-a")
        wt_b = os.path.join(tmpdir, "wt-b")
        os.makedirs(repo, exist_ok=True)
        _init_repo(repo)
        _write_task(repo, ".code-flow/tasks/2026-04-08/base-task.md")
        _write_task(repo, ".code-flow/tasks/2026-04-08/child-task.md")

        code_a = main([
            "--project-root", repo, "new", "base-task", "--worktree", wt_a, "--branch", "feat/base-task"
        ])
        assert code_a == 0
        lane_a = load_lanes(repo)["lanes"][0]

        code_b = main([
            "--project-root", repo, "new", "child-task", "--worktree", wt_b, "--branch", "feat/child-task",
            "--dep-type", "hard", "--dep-lane", lane_a["lane_id"]
        ])
        assert code_b == 0
        lanes = load_lanes(repo)["lanes"]
        child = [lane for lane in lanes if lane["task_file"].endswith("child-task.md")][0]
        assert child["base_branch"] == "feat/base-task"


def test_new_head_only_failure_rolls_back() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        repo = os.path.join(tmpdir, "repo")
        wt = os.path.join(tmpdir, "wt")
        os.makedirs(repo, exist_ok=True)
        _init_repo(repo)
        _write_task(repo, commit=False)

        out = io.StringIO()
        err = io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = main([
                "--project-root", repo, "new", "worktree-parallel", "--worktree", wt,
                "--task-sync", "head-only"
            ])
        assert code == 1
        assert "task not found in HEAD" in err.getvalue()

        branch_check = subprocess.run(
            ["git", "show-ref", "--verify", "refs/heads/feat/worktree-parallel"],
            cwd=repo,
            capture_output=True,
            text=True,
            check=False,
        )
        assert branch_check.returncode != 0


def test_new_lock_acquire_failure_returns_error() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        repo = os.path.join(tmpdir, "repo")
        os.makedirs(repo, exist_ok=True)
        _init_repo(repo)
        _write_task(repo)

        out = io.StringIO()
        err = io.StringIO()
        with mock.patch("cf_lane.acquire_lock", side_effect=TimeoutError("failed to acquire lock")), \
             redirect_stdout(out), redirect_stderr(err):
            code = main(["--project-root", repo, "new", "worktree-parallel", "--worktree", os.path.join(tmpdir, "wt")])
        assert code == 1
        assert "failed to acquire lock" in err.getvalue()


def test_new_without_task_lists_candidates() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        repo = os.path.join(tmpdir, "repo")
        os.makedirs(repo, exist_ok=True)
        _init_repo(repo)
        _write_task(repo)

        out = io.StringIO()
        err = io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = main(["--project-root", repo, "new"])
        assert code == 0
        text = out.getvalue()
        assert "Approved unbound tasks:" in text
        assert "worktree-parallel" in text


def test_new_without_task_does_not_treat_draft_as_approved_without_lifecycle() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        repo = os.path.join(tmpdir, "repo")
        os.makedirs(repo, exist_ok=True)
        _init_repo(repo)
        _write_task_without_lifecycle(repo)

        out = io.StringIO()
        err = io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = main(["--project-root", repo, "new"])
        assert code == 0
        assert "No approved and unbound task found." in out.getvalue()


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
    print(f"\\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
