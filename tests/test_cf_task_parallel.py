#!/usr/bin/env python3
"""[parallel] 任务级 worktree 编排回归测试（真实 git 仓库，无 mock）。

覆盖 prepare 预检/自动提交/批次校验、collect 回并前校验、cleanup 清理与分支回收。
"""
import json
import io
import subprocess
import sys
from pathlib import Path

import pytest  # noqa: E402


SCRIPTS = Path(__file__).resolve().parents[1] / "src/core/code-flow/scripts"
sys.path.insert(0, str(SCRIPTS))

from cf_task_parallel import ParallelError, cleanup, collect, main, prepare  # noqa: E402


TASK_FILE = ".code-flow/tasks/2026-09-29/demo/demo.md"

TASK_BODY = """# 并行演示

- **Updated**: 2026-09-29

## Acceptance Coverage

| 场景ID | 状态 |
|--------|------|
| S-01 | planned |

---

## TASK-001: A

- **Status**: draft
- **Depends**:

### Log
- [2026-09-29] created (draft)

---

## TASK-002: B

- **Status**: draft
- **Depends**:

### Log
- [2026-09-29] created (draft)

---

## TASK-003: C

- **Status**: draft
- **Depends**: TASK-001

### Log
- [2026-09-29] created (draft)
"""

GITIGNORE = """.active-task.json
.active-task.lock
.debug.log
specs/_session/
worktrees/
"""


def _git(root: Path, *arguments: str) -> str:
    result = subprocess.run(
        ("git", *arguments), cwd=str(root), text=True, encoding="utf-8", capture_output=True, check=False
    )
    assert result.returncode == 0, f"git {' '.join(arguments)}: {result.stderr}"
    return result.stdout


def _repo(tmp_path: Path) -> Path:
    root = tmp_path / "proj"
    root.mkdir()
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "cf@test")
    _git(root, "config", "user.name", "cf-test")
    (root / ".code-flow").mkdir()
    (root / ".code-flow/.gitignore").write_text(GITIGNORE, encoding="utf-8")
    task_dir = root / ".code-flow/tasks/2026-09-29/demo"
    task_dir.mkdir(parents=True)
    (task_dir / "demo.md").write_text(TASK_BODY, encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "init")
    return root


def _set_status(worktree: Path, task: str, status: str) -> None:
    task_path = worktree / TASK_FILE
    text = task_path.read_text(encoding="utf-8")
    index = text.index(f"## {task}:")
    head, tail = text[:index], text[index:]
    tail = tail.replace("- **Status**: draft", f"- **Status**: {status}", 1)
    task_path.write_text(head + tail, encoding="utf-8")


def _finish_task(root: Path, task: str, status: str = "done") -> None:
    worktree = root / ".code-flow/worktrees/run-1" / task
    (worktree / f"impl-{task}.txt").write_text(task, encoding="utf-8")
    _set_status(worktree, task, status)
    _git(worktree, "add", "-A")
    _git(worktree, "commit", "-q", "-m", f"cf-task({task}): demo")


def test_prepare_creates_worktrees_and_main_stays_clean(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    result = prepare(root, TASK_FILE, ["TASK-001", "TASK-002"], "run-1")
    assert result["ok"] is True
    assert [item["task"] for item in result["worktrees"]] == ["TASK-001", "TASK-002"]
    for item in result["worktrees"]:
        assert Path(item["path"]).is_dir()
        assert (Path(item["path"]) / TASK_FILE).is_file()
        assert item["branch"] in _git(root, "branch", "--list", item["branch"])
    # worktree 与 run.json 均被忽略，主工作区保持干净
    assert _git(root, "status", "--porcelain=v1", "--untracked-files=all") == ""
    meta = json.loads((root / ".code-flow/worktrees/run-1/run.json").read_text(encoding="utf-8"))
    assert meta["task_file"] == TASK_FILE
    assert len(meta["worktrees"]) == 2


def test_prepare_auto_commits_task_artifacts_only(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    task_path = root / TASK_FILE
    task_path.write_text(task_path.read_text(encoding="utf-8") + "\n<!-- edited -->\n", encoding="utf-8")
    result = prepare(root, TASK_FILE, ["TASK-001"], "run-1")
    assert result["ok"] is True
    assert "chore(cf-task)" in _git(root, "log", "-1", "--pretty=%s")
    worktree_task = Path(result["worktrees"][0]["path"]) / TASK_FILE
    assert "<!-- edited -->" in worktree_task.read_text(encoding="utf-8")


def test_prepare_refuses_dirty_outside_task_dir(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    (root / "outside.txt").write_text("dirty", encoding="utf-8")
    with pytest.raises(ParallelError) as exc:
        prepare(root, TASK_FILE, ["TASK-001"], "run-1")
    assert exc.value.code == "dirty_tree"


def test_prepare_refuses_unready_and_non_draft_tasks(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    with pytest.raises(ParallelError) as exc:
        prepare(root, TASK_FILE, ["TASK-003"], "run-1")
    assert exc.value.code == "task_not_ready"
    (root / "outside.txt").write_text("dirty", encoding="utf-8")
    _git(root, "add", "outside.txt")
    with pytest.raises(ParallelError) as exc:
        prepare(root, TASK_FILE, ["TASK-001", "TASK-001"], "run-1")
    assert exc.value.code in ("duplicate_task", "dirty_tree")


def test_prepare_refuses_active_marker_and_missing_ignore(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    marker = root / ".code-flow/.active-task.json"
    marker.write_text("{}", encoding="utf-8")
    with pytest.raises(ParallelError) as exc:
        prepare(root, TASK_FILE, ["TASK-001"], "run-1")
    assert exc.value.code == "active_exists"
    marker.unlink()
    (root / ".code-flow/.gitignore").write_text(".active-task.json\n", encoding="utf-8")
    with pytest.raises(ParallelError) as exc:
        prepare(root, TASK_FILE, ["TASK-001"], "run-1")
    assert exc.value.code == "worktrees_not_ignored"


def test_collect_requires_finished_committed_and_clean(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    prepare(root, TASK_FILE, ["TASK-001", "TASK-002"], "run-1")
    initial = collect(root, "run-1", None)
    assert initial["ok"] is False
    assert {item["code"] for item in initial["results"]} == {"no_commits"}
    _finish_task(root, "TASK-001")
    _finish_task(root, "TASK-002", status="verified")
    done = collect(root, "run-1", None)
    assert done["ok"] is True
    assert {item["task"]: item["status"] for item in done["results"]} == {"TASK-001": "done", "TASK-002": "verified"}
    assert done["results"][0]["files"]

    stale = root / ".code-flow/worktrees/run-1/TASK-001"
    (stale / "impl-TASK-001.txt").write_text("dirty", encoding="utf-8")
    dirty = collect(root, "run-1", ["TASK-001"])
    assert dirty["ok"] is False and dirty["results"][0]["code"] == "worktree_dirty"

    _git(stale, "checkout", "--", "impl-TASK-001.txt")
    (stale / ".code-flow/.active-task.json").write_text("{}", encoding="utf-8")
    marked = collect(root, "run-1", ["TASK-001"])
    assert marked["ok"] is False and marked["results"][0]["code"] == "active_marker_present"


def test_cleanup_removes_worktrees_and_only_merged_branches(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    prepare(root, TASK_FILE, ["TASK-001", "TASK-002"], "run-1")
    _finish_task(root, "TASK-001")
    _finish_task(root, "TASK-002")
    for item in json.loads((root / ".code-flow/worktrees/run-1/run.json").read_text(encoding="utf-8"))["worktrees"]:
        if item["task"] == "TASK-001":
            _git(root, "merge", "--no-ff", "-q", "-m", "merge TASK-001", item["branch"])
    result = cleanup(root, "run-1", force=False)
    assert result["ok"] is True
    merged = next(item for item in result["results"] if item["task"] == "TASK-001")
    unmerged = next(item for item in result["results"] if item["task"] == "TASK-002")
    assert merged["branch_deleted"] is True
    assert unmerged["branch_deleted"] is False
    assert _git(root, "branch", "--list", "cf-task/*").strip() != ""
    assert not (root / ".code-flow/worktrees/run-1").exists()


def test_cleanup_refuses_dirty_worktree_without_force(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    prepare(root, TASK_FILE, ["TASK-001"], "run-1")
    worktree = root / ".code-flow/worktrees/run-1/TASK-001"
    (worktree / "uncommitted.txt").write_text("x", encoding="utf-8")
    result = cleanup(root, "run-1", force=False)
    assert result["ok"] is False
    assert result["results"][0]["code"] == "worktree_dirty"
    assert worktree.is_dir()
    forced = cleanup(root, "run-1", force=True)
    assert forced["ok"] is True
    assert not worktree.exists()


def test_cli_prepare_emits_json_and_exit_codes(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    stdout = io.StringIO()
    code = main(
        ["prepare", "--root", str(root), "--task-file", TASK_FILE, "--tasks", "TASK-001", "--run-id", "run-cli", "--json"],
        stdout=stdout,
    )
    assert code == 0
    payload = json.loads(stdout.getvalue())
    assert payload["ok"] is True and payload["run_id"] == "run-cli"
    bad = io.StringIO()
    code = main(
        ["prepare", "--root", str(root), "--task-file", TASK_FILE, "--tasks", "TASK-003", "--run-id", "run-bad"],
        stdout=bad,
    )
    assert code == 2
    assert json.loads(bad.getvalue())["code"] == "task_not_ready"
