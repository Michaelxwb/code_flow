#!/usr/bin/env python3
"""[S-02][E-02] 任务变更范围并集与基线冻结回归测试。

真实边界：真实 git 仓库（tmp_path）+ 真实 cf_spec_context 状态机。
"""
import subprocess
import sys
from pathlib import Path

import pytest


SCRIPTS = Path(__file__).resolve().parents[1] / "src" / "core" / "code-flow" / "scripts"
sys.path.insert(0, str(SCRIPTS))

from cf_spec_context import (  # noqa: E402
    complete_active_task,
    current_owned_paths,
    load_active_task,
    pause_active_task,
    resume_active_task,
    start_active_task,
)


def _git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=root, capture_output=True, text=True, check=True
    )
    return result.stdout.strip()


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "t@t")
    _git(tmp_path, "config", "user.name", "t")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("print('hi')\n", encoding="utf-8")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-qm", "init")
    return tmp_path


def test_committed_changes_stay_in_scope(repo: Path) -> None:
    """[S-02] 中途 commit 后 Done 范围不得丢失。"""
    start_active_task(str(repo), "tasks/d", "TASK-001", "h" * 64, ())
    (repo / "src" / "app.py").write_text("print('bad')\n", encoding="utf-8")
    assert current_owned_paths(str(repo), load_active_task(str(repo))) == ("src/app.py",)
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "add print")
    assert current_owned_paths(str(repo), load_active_task(str(repo))) == ("src/app.py",)


def test_multiple_commits_rename_and_delete_stay_in_scope(repo: Path) -> None:
    """[S-02] 多次提交/重命名/删除同样保留在范围内。"""
    start_active_task(str(repo), "tasks/d", "TASK-001", "h" * 64, ())
    (repo / "src" / "app.py").write_text("print('one')\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "one")
    _git(repo, "mv", "src/app.py", "src/main.py")
    (repo / "src" / "other.py").write_text("x = 1\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "two")
    (repo / "src" / "other.py").unlink()
    scope = current_owned_paths(str(repo), load_active_task(str(repo)))
    assert "src/main.py" in scope
    assert "src/other.py" in scope or "src/app.py" in scope


def test_transition_does_not_rewrite_baseline_head(repo: Path) -> None:
    """[S-02] transition 不得改写冻结基线。"""
    active = start_active_task(str(repo), "tasks/d", "TASK-001", "h" * 64, ())
    frozen = active.baseline.head
    (repo / "src" / "app.py").write_text("print('x')\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "mid-task")
    pause_active_task(str(repo))
    resumed = resume_active_task(str(repo))
    assert resumed.baseline.head == frozen


def test_second_task_excludes_first_task_commits(repo: Path) -> None:
    """[E-02] TASK-B 范围不含 TASK-A 已提交内容。"""
    start_active_task(str(repo), "tasks/a", "TASK-A", "h" * 64, ())
    (repo / "src" / "app.py").write_text("print('a')\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "task a change")
    complete_active_task(str(repo), True)
    start_active_task(str(repo), "tasks/b", "TASK-B", "h" * 64, ())
    (repo / "src" / "b.py").write_text("y = 2\n", encoding="utf-8")
    assert current_owned_paths(str(repo), load_active_task(str(repo))) == ("src/b.py",)
