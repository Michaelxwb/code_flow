#!/usr/bin/env python3
"""Tests for cf-lane check-merge command."""

import io
import json
import os
import subprocess
import sys
import tempfile
from contextlib import redirect_stderr, redirect_stdout

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "core", "code-flow", "scripts"))

from cf_lane import main
from cf_lane_core import load_lanes, save_lanes


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


def _write_task(repo: str, rel: str) -> str:
    content = (
        "# Tasks: Demo\n\n"
        "- **Source**: docs/demo.md\n"
        "- **Created**: 2026-04-08\n"
        "- **Updated**: 2026-04-08\n\n"
        "## TASK-001: Demo\n\n"
        "- **Status**: done\n"
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


def test_check_merge_hard_dependency_violation_and_pass_after_close() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        repo = os.path.join(tmpdir, "repo")
        wt_up = os.path.join(tmpdir, "wt-up")
        wt_down = os.path.join(tmpdir, "wt-down")
        os.makedirs(repo, exist_ok=True)
        _init_repo(repo)
        t_up = _write_task(repo, ".code-flow/tasks/2026-04-08/upstream.md")
        t_down = _write_task(repo, ".code-flow/tasks/2026-04-08/downstream.md")
        _git(repo, "add", "--", t_up, t_down)
        _git(repo, "commit", "-m", "add tasks")

        assert main([
            "--project-root", repo, "new", "upstream", "--worktree", wt_up, "--branch", "feat/upstream"
        ]) == 0
        upstream_lane = load_lanes(repo)["lanes"][0]
        assert main([
            "--project-root", repo, "new", "downstream", "--worktree", wt_down, "--branch", "feat/downstream",
            "--dep-type", "hard", "--dep-lane", upstream_lane["lane_id"]
        ]) == 0
        downstream_lane = load_lanes(repo)["lanes"][1]

        out = io.StringIO()
        err = io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = main([
                "--project-root", repo, "check-merge", "--lane", downstream_lane["lane_id"], "--json"
            ])
        assert code == 1
        payload = json.loads(out.getvalue())
        assert payload["ok"] is False
        assert payload["violations"][0]["code"] == "hard_dep_not_closed"

        registry = load_lanes(repo)
        registry["lanes"][0]["status"] = "closed"
        save_lanes(repo, registry)
        out2 = io.StringIO()
        with redirect_stdout(out2), redirect_stderr(io.StringIO()):
            code2 = main([
                "--project-root", repo, "check-merge", "--lane", downstream_lane["lane_id"], "--json"
            ])
        assert code2 == 0
        payload2 = json.loads(out2.getvalue())
        assert payload2["ok"] is True
        assert payload2["violations"] == []


def test_check_merge_detects_task_ownership_violation() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        repo = os.path.join(tmpdir, "repo")
        wt_a = os.path.join(tmpdir, "wt-a")
        wt_b = os.path.join(tmpdir, "wt-b")
        os.makedirs(repo, exist_ok=True)
        _init_repo(repo)
        t_a = _write_task(repo, ".code-flow/tasks/2026-04-08/a.md")
        t_b = _write_task(repo, ".code-flow/tasks/2026-04-08/b.md")
        _git(repo, "add", "--", t_a, t_b)
        _git(repo, "commit", "-m", "add tasks")

        assert main(["--project-root", repo, "new", "a", "--worktree", wt_a, "--branch", "feat/a"]) == 0
        assert main(["--project-root", repo, "new", "b", "--worktree", wt_b, "--branch", "feat/b"]) == 0
        lane_a = load_lanes(repo)["lanes"][0]

        task_b_path = os.path.join(wt_a, ".code-flow/tasks/2026-04-08/b.md")
        with open(task_b_path, "a", encoding="utf-8") as f:
            f.write("\n- NOTE: illegal edit\n")
        _git(wt_a, "add", "--", ".code-flow/tasks/2026-04-08/b.md")
        _git(wt_a, "commit", "-m", "edit task b from lane a")

        out = io.StringIO()
        with redirect_stdout(out), redirect_stderr(io.StringIO()):
            code = main(["--project-root", repo, "check-merge", "--lane", lane_a["lane_id"], "--json"])
        assert code == 1
        payload = json.loads(out.getvalue())
        assert payload["ok"] is False
        codes = [item["code"] for item in payload["violations"]]
        assert "task_ownership_violation" in codes


def test_check_merge_auto_resolves_lane_from_current_branch() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        repo = os.path.join(tmpdir, "repo")
        wt = os.path.join(tmpdir, "wt")
        os.makedirs(repo, exist_ok=True)
        _init_repo(repo)
        task = _write_task(repo, ".code-flow/tasks/2026-04-08/a.md")
        _git(repo, "add", "--", task)
        _git(repo, "commit", "-m", "add task")

        assert main(["--project-root", repo, "new", "a", "--worktree", wt, "--branch", "feat/a"]) == 0
        lane = load_lanes(repo)["lanes"][0]

        out = io.StringIO()
        with redirect_stdout(out), redirect_stderr(io.StringIO()):
            code = main(["--project-root", wt, "check-merge", "--json"])
        assert code == 0
        payload = json.loads(out.getvalue())
        assert payload["ok"] is True
        assert payload["lane_id"] == lane["lane_id"]


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
