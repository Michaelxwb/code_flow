#!/usr/bin/env python3
"""Tests for cf-lane list/status commands."""

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


def _write_task(repo: str, rel: str, checklist: str = "- [ ] one\n") -> str:
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
        f"{checklist}\n"
        "### Log\n"
        "- [2026-04-08] created (draft)\n"
    )
    abs_path = os.path.join(repo, rel)
    os.makedirs(os.path.dirname(abs_path), exist_ok=True)
    with open(abs_path, "w", encoding="utf-8") as f:
        f.write(content)
    return rel


def _commit_tasks(repo: str, paths: list[str]) -> None:
    _git(repo, "add", "--", *paths)
    _git(repo, "commit", "-m", "add task files")


def test_list_filters_active_by_default_and_all_with_json() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        repo = os.path.join(tmpdir, "repo")
        os.makedirs(repo, exist_ok=True)
        _init_repo(repo)
        t1 = _write_task(repo, ".code-flow/tasks/2026-04-08/t1.md")
        t2 = _write_task(repo, ".code-flow/tasks/2026-04-08/t2.md")
        _commit_tasks(repo, [t1, t2])

        assert main(["--project-root", repo, "new", "t1", "--worktree", os.path.join(tmpdir, "wt1")]) == 0
        assert main(["--project-root", repo, "new", "t2", "--worktree", os.path.join(tmpdir, "wt2")]) == 0

        registry = load_lanes(repo)
        registry["lanes"][0]["status"] = "closed"
        save_lanes(repo, registry)

        out = io.StringIO()
        err = io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = main(["--project-root", repo, "list"])
        assert code == 0
        text = out.getvalue()
        assert "t2" in text
        assert "t1" not in text

        out_json = io.StringIO()
        with redirect_stdout(out_json), redirect_stderr(io.StringIO()):
            code_json = main(["--project-root", repo, "list", "--all", "--json"])
        assert code_json == 0
        payload = json.loads(out_json.getvalue())
        assert len(payload["lanes"]) == 2


def test_status_json_reports_progress_owner_and_hard_blocked() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        repo = os.path.join(tmpdir, "repo")
        os.makedirs(repo, exist_ok=True)
        _init_repo(repo)
        base = _write_task(repo, ".code-flow/tasks/2026-04-08/base.md")
        child = _write_task(repo, ".code-flow/tasks/2026-04-08/child.md", checklist="- [x] one\n- [ ] two\n")
        _commit_tasks(repo, [base, child])

        assert main([
            "--project-root", repo, "new", "base", "--worktree", os.path.join(tmpdir, "wt-base"),
            "--branch", "feat/base"
        ]) == 0
        dep_lane_id = load_lanes(repo)["lanes"][0]["lane_id"]
        assert main([
            "--project-root", repo, "new", "child", "--worktree", os.path.join(tmpdir, "wt-child"),
            "--branch", "feat/child", "--dep-type", "hard", "--dep-lane", dep_lane_id
        ]) == 0

        out = io.StringIO()
        err = io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = main(["--project-root", repo, "status", "--json"])
        assert code == 0, err.getvalue()
        payload = json.loads(out.getvalue())
        child_item = [lane for lane in payload["lanes"] if lane["task_file"].endswith("child.md")][0]
        assert child_item["task_progress"] == {"done": 1, "total": 2, "percent": 50}
        assert child_item["owner_lane"] == child_item["lane_id"]
        assert child_item["hard_blocked"] is True
        assert child_item["dep_status"] == "active"


def test_status_soft_risk_when_upstream_changed_after_last_sync() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        repo = os.path.join(tmpdir, "repo")
        os.makedirs(repo, exist_ok=True)
        _init_repo(repo)
        t1 = _write_task(repo, ".code-flow/tasks/2026-04-08/upstream.md")
        t2 = _write_task(repo, ".code-flow/tasks/2026-04-08/downstream.md")
        _commit_tasks(repo, [t1, t2])

        assert main([
            "--project-root", repo, "new", "upstream", "--worktree", os.path.join(tmpdir, "wt-up"),
            "--branch", "feat/upstream"
        ]) == 0
        dep_lane_id = load_lanes(repo)["lanes"][0]["lane_id"]
        assert main([
            "--project-root", repo, "new", "downstream", "--worktree", os.path.join(tmpdir, "wt-down"),
            "--branch", "feat/downstream", "--dep-type", "soft", "--dep-lane", dep_lane_id
        ]) == 0

        registry = load_lanes(repo)
        upstream = registry["lanes"][0]
        downstream = registry["lanes"][1]
        upstream["updated_at"] = "2026-04-08T11:30:00Z"
        downstream["last_sync_at"] = "2026-04-08T10:00:00Z"
        save_lanes(repo, registry)

        out = io.StringIO()
        with redirect_stdout(out), redirect_stderr(io.StringIO()):
            code = main(["--project-root", repo, "status", "--json"])
        assert code == 0
        payload = json.loads(out.getvalue())
        down_item = [lane for lane in payload["lanes"] if lane["task_file"].endswith("downstream.md")][0]
        assert down_item["soft_risk"] is True
        assert down_item["dep_status"] == "active"


def test_status_lane_not_found() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        repo = os.path.join(tmpdir, "repo")
        os.makedirs(repo, exist_ok=True)
        _init_repo(repo)

        out = io.StringIO()
        err = io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = main(["--project-root", repo, "status", "lane-missing"])
        assert code == 1
        assert "lane not found" in err.getvalue()


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
