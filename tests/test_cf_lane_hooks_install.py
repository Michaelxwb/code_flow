#!/usr/bin/env python3
"""Tests for pre-push hook installation."""

import io
import os
import stat
import subprocess
import sys
import tempfile
import unittest.mock as mock
from contextlib import redirect_stderr, redirect_stdout

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "core", "code-flow", "scripts"))

from cf_lane import _HOOK_MARKER, install_hooks, main


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


def test_install_hooks_first_time() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        _init_repo(tmpdir)
        status = install_hooks(tmpdir)
        assert status == "ok"
        hooks_path = _git(tmpdir, "config", "--get", "core.hooksPath").stdout.strip()
        assert hooks_path == ".code-flow/hooks"
        hook_file = os.path.join(tmpdir, ".code-flow/hooks/pre-push")
        with open(hook_file, "r", encoding="utf-8") as f:
            content = f.read()
        assert _HOOK_MARKER in content
        assert "check-merge" in content
        mode = os.stat(hook_file).st_mode
        assert mode & stat.S_IXUSR


def test_install_hooks_is_idempotent() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        _init_repo(tmpdir)
        first = install_hooks(tmpdir)
        second = install_hooks(tmpdir)
        assert first == "ok"
        assert "already installed" in second
        hook_file = os.path.join(tmpdir, ".code-flow/hooks/pre-push")
        with open(hook_file, "r", encoding="utf-8") as f:
            content = f.read()
        assert content.count(_HOOK_MARKER) == 1


def test_install_hooks_chains_existing_hooks_path() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        _init_repo(tmpdir)
        existing_dir = os.path.join(tmpdir, "custom-hooks")
        os.makedirs(existing_dir, exist_ok=True)
        existing_hook = os.path.join(existing_dir, "pre-push")
        with open(existing_hook, "w", encoding="utf-8") as f:
            f.write("#!/usr/bin/env sh\nexit 0\n")
        os.chmod(existing_hook, 0o755)
        _git(tmpdir, "config", "core.hooksPath", "custom-hooks")

        status = install_hooks(tmpdir)
        assert status == "ok"
        hook_file = os.path.join(tmpdir, ".code-flow/hooks/pre-push")
        with open(hook_file, "r", encoding="utf-8") as f:
            content = f.read()
        assert os.path.realpath(existing_hook) in content
        hooks_path = _git(tmpdir, "config", "--get", "core.hooksPath").stdout.strip()
        assert hooks_path == ".code-flow/hooks"


def test_new_does_not_fail_when_hook_install_fails() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        repo = os.path.join(tmpdir, "repo")
        wt = os.path.join(tmpdir, "wt")
        os.makedirs(repo, exist_ok=True)
        _init_repo(repo)
        task = _write_task(repo, ".code-flow/tasks/2026-04-08/t1.md")
        _git(repo, "add", "--", task)
        _git(repo, "commit", "-m", "add task")

        out = io.StringIO()
        err = io.StringIO()
        with mock.patch("cf_lane.install_hooks", side_effect=RuntimeError("boom")), \
             redirect_stdout(out), redirect_stderr(err):
            code = main(["--project-root", repo, "new", "t1", "--worktree", wt])
        assert code == 0, err.getvalue()
        assert "hooks_install: failed (boom)" in out.getvalue()


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
