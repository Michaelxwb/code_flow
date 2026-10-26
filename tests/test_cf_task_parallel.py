#!/usr/bin/env python3
"""[parallel] 任务级 worktree 编排回归测试（真实 git 仓库，无 mock）。

覆盖 prepare 预检/自动提交/批次校验、collect 回并前校验、cleanup 清理与分支回收。
"""
import json
import io
import os
import re
import socket
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest  # noqa: E402


SCRIPTS = Path(__file__).resolve().parents[1] / "src/core/code-flow/scripts"
sys.path.insert(0, str(SCRIPTS))

from cf_acceptance_manifest import write_manifest  # noqa: E402
from cf_acceptance_runner import run_manifest  # noqa: E402
from codeflow.evidence.cf_evidence_store import EvidenceStore  # noqa: E402
from cf_task_parallel import ParallelError, _cleanup_block_reason, cleanup, collect, main, merge, prepare  # noqa: E402


def test_cleanup_requires_passed_merge() -> None:
    assert _cleanup_block_reason({"merge": {"status": "blocked"}}, False)[0] == "merge_not_passed"
    assert _cleanup_block_reason({"merge": {"status": "running"}}, False)[0] == "merge_not_passed"
    assert _cleanup_block_reason({"merge": {"status": "blocked", "code": "batch_smoke_failed"}}, False)[0] == "batch_smoke_failed"
    assert _cleanup_block_reason({"merge": {"status": "passed"}}, False)[0] == ""
    assert _cleanup_block_reason({"merge": {"status": "blocked"}}, True)[0] == ""
    assert _cleanup_block_reason({"batch_smoke": {"status": "failed"}}, False)[0] == "batch_smoke_failed"
    partial = {
        "merge": {
            "status": "passed", "full_batch": False,
            "merged": ["TASK-001"], "all_tasks": ["TASK-001", "TASK-002"],
        },
    }
    assert _cleanup_block_reason(partial, False)[0] == "partial_merge"
    complete = {
        "merge": {
            "status": "passed", "full_batch": True,
            "merged": ["TASK-001", "TASK-002"], "all_tasks": ["TASK-001", "TASK-002"],
        },
    }
    assert _cleanup_block_reason(complete, False)[0] == ""


TASK_FILE = ".code-flow/tasks/2026-09-29/demo/demo.md"

TASK_BODY = """# 并行演示

- **Updated**: 2026-09-29

## Acceptance Coverage

| 场景ID | 状态 |
|--------|------|
| S-01 | planned |
| S-02 | planned |

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
.claude/settings.local.json
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


def test_invalid_worktree_runtime_removes_created_worktree_and_branch(tmp_path: Path) -> None:
    import hashlib
    root = _repo(tmp_path)
    owned = root / ".code-flow/runtime-commands.json"
    owned.write_text("committed runtime")
    (root / ".code-flow/.version").write_text("0.7.0")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "runtime")
    owned.write_text("locally changed runtime")
    manifest = {"schema_version": 1, "version": "0.7.0", "files": {
        ".code-flow/runtime-commands.json": hashlib.sha256(owned.read_bytes()).hexdigest()}}
    (root / ".code-flow/.runtime-install.json").write_text(json.dumps(manifest))
    from cf_task_parallel import _create_worktrees
    with pytest.raises(ParallelError) as error:
        _create_worktrees(root, TASK_FILE, ["TASK-001"], "invalid-runtime")
    assert error.value.code == "worktree_runtime_invalid"
    assert len(_git(root, "worktree", "list", "--porcelain").split("worktree ")) == 2
    assert not (root / ".code-flow/worktrees/invalid-runtime/TASK-001").exists()
    assert "invalid-runtime" not in _git(root, "branch", "--list")


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
    assert "git stash" in exc.value.message and "outside.txt" in exc.value.message


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
    assert {item["code"] for item in initial["results"]} == {"task_not_finished"}
    _finish_task(root, "TASK-001")
    _finish_task(root, "TASK-002", status="verified")
    done = collect(root, "run-1", None)
    assert done["ok"] is True
    assert {item["task"]: item["status"] for item in done["results"]} == {"TASK-001": "done", "TASK-002": "verified"}
    assert done["results"][0]["files"]

    stale = root / ".code-flow/worktrees/run-1/TASK-001"
    (stale / "impl-TASK-001.txt").write_text("dirty", encoding="utf-8")
    dirty = collect(root, "run-1", ["TASK-001"], commit=False)
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


def test_collect_auto_commits_finish_writeback(tmp_path: Path) -> None:
    """finish 回写（Evidence/状态）在任务 done 且 marker 清理后由 collect 自动提交。"""
    root = _repo(tmp_path)
    prepare(root, TASK_FILE, ["TASK-001"], "run-1")
    _finish_task(root, "TASK-001")
    worktree = root / ".code-flow/worktrees/run-1/TASK-001"
    task_path = worktree / TASK_FILE
    task_path.write_text(task_path.read_text(encoding="utf-8") + "\n<!-- finish writeback -->\n", encoding="utf-8")
    assert _git(worktree, "status", "--porcelain").strip() != ""

    result = collect(root, "run-1", ["TASK-001"])

    assert result["ok"] is True, result
    assert result["results"][0]["status"] == "done"
    assert _git(worktree, "status", "--porcelain").strip() == ""
    assert "finish 回写" in _git(worktree, "log", "-1", "--pretty=%s")

    task_path.write_text(task_path.read_text(encoding="utf-8") + "\n<!-- late edit -->\n", encoding="utf-8")
    strict = collect(root, "run-1", ["TASK-001"], commit=False)
    assert strict["ok"] is False and strict["results"][0]["code"] == "worktree_dirty"


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


def test_prepare_without_run_id_never_reuses_run_directory(tmp_path: Path) -> None:
    """同一秒内两次 prepare 必须得到不同的 run-id，不能覆盖 run.json。"""
    root = _repo(tmp_path)
    first = prepare(root, TASK_FILE, ["TASK-001"], None)
    second = prepare(root, TASK_FILE, ["TASK-002"], None)
    assert first["run_id"] != second["run_id"], "同秒 prepare 必须生成唯一 run-id"
    first_meta = json.loads(
        (root / f".code-flow/worktrees/{first['run_id']}/run.json").read_text(encoding="utf-8")
    )
    assert first_meta["run_id"] == first["run_id"]
    assert [item["task"] for item in first_meta["worktrees"]] == ["TASK-001"]
    assert (root / f".code-flow/worktrees/{first['run_id']}/TASK-001").is_dir(), "第一批 worktree 不得被遗弃"
    assert (root / f".code-flow/worktrees/{second['run_id']}/TASK-002").is_dir()


def test_collect_reports_corrupt_run_meta_as_json(tmp_path: Path) -> None:
    """run.json 损坏时必须给 run_corrupt JSON 错误，不能堆栈崩溃。"""
    root = _repo(tmp_path)
    run_dir = root / ".code-flow/worktrees/run-x"
    run_dir.mkdir(parents=True)
    (run_dir / "run.json").write_text('{"version": 1}', encoding="utf-8")
    stdout = io.StringIO()
    code = main(["collect", "--root", str(root), "--run-id", "run-x", "--json"], stdout=stdout)
    assert code == 2
    payload = json.loads(stdout.getvalue())
    assert payload["ok"] is False and payload["code"] == "run_corrupt"


def test_prepare_explicit_run_id_conflict_does_not_leak_worktrees(tmp_path: Path) -> None:
    """显式 run-id 已存在时提前拒绝，不得先建 worktree 再覆盖记录。"""
    root = _repo(tmp_path)
    prepare(root, TASK_FILE, ["TASK-001"], "run-fixed")
    before = sorted(item.name for item in (root / ".code-flow/worktrees/run-fixed").iterdir())
    with pytest.raises(ParallelError) as exc:
        prepare(root, TASK_FILE, ["TASK-002"], "run-fixed")
    assert exc.value.code == "run_id_conflict"
    after = sorted(item.name for item in (root / ".code-flow/worktrees/run-fixed").iterdir())
    assert before == after, "冲突时不得追加/覆盖第一批 worktree"
    branches = _git(root, "branch", "--list", "cf-task/*")
    assert branches.count("TASK-002") == 0


def _finish_parallel(root: Path, run: str, task: str, scenario: str) -> Path:
    """模拟 finish 回写：实现文件 + 任务区 Status + 覆盖状态列，然后提交。"""
    worktree = root / f".code-flow/worktrees/{run}" / task
    (worktree / f"impl-{task}.txt").write_text(task, encoding="utf-8")
    _set_status(worktree, task, "done")
    task_path = worktree / TASK_FILE
    lines = task_path.read_text(encoding="utf-8").splitlines()
    for position, line in enumerate(lines):
        if line.strip().startswith(f"| {scenario} "):
            lines[position] = line.replace("planned", "verified")
    task_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    _git(worktree, "add", "-A")
    _git(worktree, "commit", "-q", "-m", f"cf-task({task}): finish 回写")
    return worktree


def test_merge_resolves_shared_state_files_then_cleanup_deletes_branches(tmp_path: Path) -> None:
    """状态文件冲突（覆盖状态列）由 merge 自动并集，无需人工 rebase。"""
    root = _repo(tmp_path)
    prepare(root, TASK_FILE, ["TASK-001", "TASK-002"], "run-1")
    _finish_parallel(root, "run-1", "TASK-001", "S-01")
    _finish_parallel(root, "run-1", "TASK-002", "S-02")

    result = merge(root, "run-1", None)

    assert result["ok"] is True, result
    assert [item["status"] for item in result["results"]] == ["merged", "merged"]
    assert result["results"][1]["resolved"] == [TASK_FILE]
    text = (root / TASK_FILE).read_text(encoding="utf-8")
    assert "| S-01 | verified |" in text
    assert "| S-02 | verified |" in text
    assert "## TASK-001: A" in text and "- **Status**: done" in text
    assert "<<<<<<<" not in text

    again = merge(root, "run-1", None)
    assert again["ok"] is True
    assert [item["status"] for item in again["results"]] == ["already_merged", "already_merged"]

    cleaned = cleanup(root, "run-1", force=False)
    assert cleaned["ok"] is True
    assert all(item["branch_deleted"] for item in cleaned["results"])


def test_merge_reports_code_conflict_and_keeps_main_intact(tmp_path: Path) -> None:
    """代码文件冲突保留人工解决：中止 rebase，主工作区不受影响。"""
    root = _repo(tmp_path)
    (root / "shared.txt").write_text("base\n", encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "shared")
    prepare(root, TASK_FILE, ["TASK-001", "TASK-002"], "run-1")
    for task, marker in (("TASK-001", "alpha"), ("TASK-002", "beta")):
        worktree = root / ".code-flow/worktrees/run-1" / task
        (worktree / "shared.txt").write_text(marker + "\n", encoding="utf-8")
        _set_status(worktree, task, "done")
        _git(worktree, "add", "-A")
        _git(worktree, "commit", "-q", "-m", f"cf-task({task}): shared")
    _finish_parallel(root, "run-1", "TASK-001", "S-01")
    _finish_parallel(root, "run-1", "TASK-002", "S-02")

    result = merge(root, "run-1", None)

    assert result["ok"] is False
    assert result["results"][0]["status"] == "merged"
    failed = result["results"][1]
    assert failed["code"] == "code_conflict" and "shared.txt" in failed["message"]
    assert (root / "shared.txt").read_text(encoding="utf-8") == "alpha\n"
    worktree = root / ".code-flow/worktrees/run-1/TASK-002"
    assert _git(worktree, "status", "--porcelain").strip() == ""
    assert "TASK-002" in _git(root, "branch", "--list", "cf-task/*")


def test_cleanup_force_deletes_unmerged_branches(tmp_path: Path) -> None:
    """--force 表示用户明确接受删除未合入分支（保留排查是默认行为）。"""
    root = _repo(tmp_path)
    prepare(root, TASK_FILE, ["TASK-001"], "run-1")
    _finish_task(root, "TASK-001")
    result = cleanup(root, "run-1", force=True)
    assert result["ok"] is True
    assert result["results"][0]["branch_deleted"] is True
    assert _git(root, "branch", "--list", "cf-task/*").strip() == ""


def test_cli_merge_emits_json(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    prepare(root, TASK_FILE, ["TASK-001"], "run-cli-merge")
    _finish_parallel(root, "run-cli-merge", "TASK-001", "S-01")
    stdout = io.StringIO()
    code = main(["merge", "--root", str(root), "--run-id", "run-cli-merge", "--json"], stdout=stdout)
    assert code == 0
    payload = json.loads(stdout.getvalue())
    assert payload["ok"] is True
    assert payload["results"][0]["status"] == "merged"



def test_prepare_copies_ignored_managed_artifacts(tmp_path: Path) -> None:
    """settings.local.json 常被 gitignore，worktree 也必须拿到并通过对账。"""
    import hashlib

    root = _repo(tmp_path)
    settings = root / ".claude/settings.local.json"
    settings.parent.mkdir()
    settings.write_text('{"hooks": {}}\n', encoding="utf-8")
    runtime = root / ".code-flow/runtime-commands.json"
    runtime.write_text("{}\n", encoding="utf-8")
    (root / ".code-flow/.version").write_text("0.7.0", encoding="utf-8")
    manifest = {"schema_version": 1, "version": "0.7.0", "files": {
        ".claude/settings.local.json": hashlib.sha256(settings.read_bytes()).hexdigest(),
        ".code-flow/runtime-commands.json": hashlib.sha256(runtime.read_bytes()).hexdigest(),
    }}
    (root / ".code-flow/.runtime-install.json").write_text(json.dumps(manifest), encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "runtime")

    result = prepare(root, TASK_FILE, ["TASK-001"], "run-1")
    assert result["ok"] is True
    copied = Path(result["worktrees"][0]["path"]) / ".claude/settings.local.json"
    assert copied.read_text(encoding="utf-8") == '{"hooks": {}}\n'


EVIDENCE_TASK_FILE = ".code-flow/tasks/2026-09-29/evidence/evidence.md"

EVIDENCE_TASK_BODY = """# 并行证据演示

- **Updated**: 2026-09-29

## Acceptance Coverage

| 场景ID | 来源设计 | 测试层级 | 关键真实边界 | 负责任务 | 状态 | 执行命令 |
|--------|---------|---------|-------------|---------|------|---------|
| S-01 | demo.design.md#2.5 | integration | 真实 runner | TASK-001 | planned | ["python3", "-c", "print('ok')"] |
| S-02 | demo.design.md#2.5 | integration | 真实 runner | TASK-002 | planned | ["python3", "-c", "print('ok')"] |
| S-03 | demo.design.md#2.5 | integration | 真实 runner | TASK-003 | planned | ["python3", "-c", "print('ok')"] |

---

## TASK-001: A

- **Status**: draft
- **Depends**:
- **Acceptance-Refs**: S-01

### Log
- [2026-09-29] created (draft)

---

## TASK-002: B

- **Status**: draft
- **Depends**:
- **Acceptance-Refs**: S-02

### Log
- [2026-09-29] created (draft)

---

## TASK-003: C

- **Status**: draft
- **Depends**:
- **Acceptance-Refs**: S-03

### Log
- [2026-09-29] created (draft)
"""


def _evidence_repo(tmp_path: Path) -> Path:
    """真实 git 仓库 + 真实 schema3 manifest，三个独立 TASK 共享一个 check。"""
    root = tmp_path / "evidence-proj"
    root.mkdir()
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "cf@test")
    _git(root, "config", "user.name", "cf-test")
    (root / ".code-flow").mkdir()
    (root / ".code-flow/.gitignore").write_text(GITIGNORE, encoding="utf-8")
    (root / "src").mkdir()
    (root / "src/app.py").write_text("VALUE = 0\n", encoding="utf-8")
    task_dir = root / Path(EVIDENCE_TASK_FILE).parent
    task_dir.mkdir(parents=True)
    task_path = root / EVIDENCE_TASK_FILE
    task_path.write_text(EVIDENCE_TASK_BODY, encoding="utf-8")
    write_manifest(str(task_path), str(task_dir / ".acceptance-manifest.json"))
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "init evidence")
    return root


def _force_status(worktree: Path, task: str, status: str, task_file: str = EVIDENCE_TASK_FILE) -> None:
    """把 TASK 区 Status 改成任意状态（draft → provisional → blocked → done）。"""
    task_path = worktree / task_file
    text = task_path.read_text(encoding="utf-8")
    index = text.index(f"## {task}:")
    head, tail = text[:index], text[index:]
    tail, count = re.subn(r"(?m)^- \*\*Status\*\*:[ \t]*[^\n]+", f"- **Status**: {status}", tail, count=1)
    assert count == 1, f"{task}: Status 行缺失"
    task_path.write_text(head + tail, encoding="utf-8")


def _commit_worktree(worktree: Path, task: str) -> None:
    _git(worktree, "add", "-A")
    _git(worktree, "commit", "-q", "-m", f"cf-task({task}): fixture")


def _manifest_path(worktree: Path) -> Path:
    return worktree / Path(EVIDENCE_TASK_FILE).parent / ".acceptance-manifest.json"


def test_s06_three_worktrees_share_central_evidence_without_committing(tmp_path: Path) -> None:
    """S-06: 3 个真实 worktree 并行执行同一 check，证据集中且无冲突，collect 通过。"""
    root = _evidence_repo(tmp_path)
    tasks = ["TASK-001", "TASK-002", "TASK-003"]
    prepared = prepare(root, EVIDENCE_TASK_FILE, tasks, "run-central")
    assert prepared["ok"] is True
    by_task = {item["task"]: Path(item["path"]) for item in prepared["worktrees"]}

    def worker(task: str) -> dict[str, object]:
        worktree = by_task[task]
        (worktree / "src/app.py").write_text(f"VALUE = {task!r}\n", encoding="utf-8")
        outcome = run_manifest(str(_manifest_path(worktree)), str(worktree), write_evidence=True, owner=task)
        _force_status(worktree, task, "done")
        _commit_worktree(worktree, task)
        return {"task": task, "outcome": outcome}

    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = [pool.submit(worker, task) for task in tasks]
        outcomes = [future.result() for future in futures]

    for item in outcomes:
        assert item["outcome"]["decision"] == "pass", item

    common = Path(_git(root, "rev-parse", "--git-common-dir").strip())
    if not common.is_absolute():
        common = (root / common).resolve()
    from codeflow.evidence.cf_evidence_store import requirement_key
    requirement = requirement_key(Path(EVIDENCE_TASK_FILE).parent)
    store = EvidenceStore(root, requirement=requirement)
    assert store.directory.resolve() == (common / "code-flow/evidence" / requirement).resolve()

    manifest = json.loads(_manifest_path(root).read_text(encoding="utf-8"))
    check_ids = {str(item["check"]) for item in manifest["scenarios"]}
    assert len(check_ids) == 1, check_ids
    check_id = check_ids.pop()
    runs = store.list_runs(check_id)
    assert len(runs) == 3, runs
    assert len({str(run["run_id"]) for run in runs}) == 3
    assert all(run["exit_code"] == 0 and run["status"] == "passed" for run in runs)
    assert all(isinstance(run.get("input_hash"), str) and run["input_hash"] for run in runs)
    assert len({str(run["input_hash"]) for run in runs}) == 3, "三个 worktree 的内容指纹应各自独立"

    collected = collect(root, "run-central", None)
    assert collected["ok"] is True, collected
    assert {item["status"] for item in collected["results"]} == {"done"}
    assert collected["batch_smoke"] == "pending"
    for item in collected["results"]:
        assert item["evidence"]["required_checks"] == [check_id]
        assert item["evidence"]["verified_checks"] == [check_id]
        assert "src/app.py" in item["files"]
        assert all("code-flow/evidence" not in path for path in item["files"])

    for task, worktree in by_task.items():
        assert not (worktree / ".code-flow/evidence").exists()
        assert _git(worktree, "status", "--porcelain", "--untracked-files=all") == "", task


def test_e03_provisional_collect_rejects_and_lists_missing_checks(tmp_path: Path) -> None:
    """E-03: provisional/blocked 一律拒绝；提示先补 required 检查；补齐后放行。"""
    root = _evidence_repo(tmp_path)
    prepared = prepare(root, EVIDENCE_TASK_FILE, ["TASK-001"], "run-provisional")
    worktree = Path(prepared["worktrees"][0]["path"])
    (worktree / "impl-TASK-001.txt").write_text("impl\n", encoding="utf-8")

    _force_status(worktree, "TASK-001", "provisional")
    _commit_worktree(worktree, "TASK-001")
    provisional = collect(root, "run-provisional", ["TASK-001"])
    assert provisional["ok"] is False
    result = provisional["results"][0]
    assert result["code"] == "task_provisional"
    assert result["missing_checks"], result
    assert result["missing_checks"][0]["check_id"].startswith("CHK-")
    assert "S-01" in result["missing_checks"][0]["scenarios"]
    assert "required" in result["message"] and "先补" in result["message"]

    _force_status(worktree, "TASK-001", "blocked")
    _commit_worktree(worktree, "TASK-001")
    blocked = collect(root, "run-provisional", ["TASK-001"])
    assert blocked["ok"] is False
    assert blocked["results"][0]["code"] == "task_blocked"

    _force_status(worktree, "TASK-001", "done")
    _commit_worktree(worktree, "TASK-001")
    unverified = collect(root, "run-provisional", ["TASK-001"])
    assert unverified["ok"] is False
    assert unverified["results"][0]["code"] == "required_evidence_missing"
    assert unverified["results"][0]["missing_checks"]

    outcome = run_manifest(str(_manifest_path(worktree)), str(worktree), write_evidence=True, owner="TASK-001")
    assert outcome["decision"] == "pass", outcome
    recovered = collect(root, "run-provisional", ["TASK-001"])
    assert recovered["ok"] is True, recovered
    assert recovered["results"][0]["status"] == "done"
    assert recovered["batch_smoke"] == "pending"
    assert all("code-flow/evidence" not in path for path in recovered["results"][0]["files"])


BATCH_TASK_FILE = ".code-flow/tasks/2026-09-29/batch/batch.md"


def _batch_task_body(tasks, e2e_command) -> str:
    rows = []
    sections = []
    for index, task in enumerate(tasks, 1):
        scenario = f"S-{index:02d}"
        command = json.dumps([sys.executable, "-c", f"print('{task}')"])
        rows.append(
            f"| {scenario} | demo.design.md#2.5 | integration | 真实 runner | {task} | planned | {command} |"
        )
        refs = scenario + (", E-01" if index == 1 else "")
        sections.append(
            f"## {task}: {task}\n\n"
            f"- **Status**: draft\n"
            f"- **Depends**:\n"
            f"- **Acceptance-Refs**: {refs}\n\n"
            f"### Log\n- [2026-09-29] created (draft)\n"
        )
    rows.append(
        "| E-01 | demo.design.md#2.5 | e2e | 真实 shared env | "
        f"{tasks[0]} | planned | {json.dumps(e2e_command)} |"
    )
    return (
        "# 批次 smoke 演示\n\n"
        "- **Updated**: 2026-09-29\n\n"
        "## Acceptance Coverage\n\n"
        "| 场景ID | 来源设计 | 测试层级 | 关键真实边界 | 负责任务 | 状态 | 执行命令 |\n"
        "|--------|---------|---------|-------------|---------|------|---------|\n"
        + "\n".join(rows)
        + "\n\n---\n\n"
        + "\n---\n\n".join(sections)
    )


def _batch_repo(tmp_path: Path, tasks, e2e_command) -> Path:
    """真实 git 仓库 + schema3 manifest：每个 TASK 一个 functional check，一个 shared E2E。"""
    root = tmp_path / "batch-proj"
    root.mkdir()
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "cf@test")
    _git(root, "config", "user.name", "cf-test")
    (root / ".code-flow").mkdir()
    (root / ".code-flow/.gitignore").write_text(GITIGNORE, encoding="utf-8")
    task_dir = root / Path(BATCH_TASK_FILE).parent
    task_dir.mkdir(parents=True)
    task_path = root / BATCH_TASK_FILE
    task_path.write_text(_batch_task_body(tasks, e2e_command), encoding="utf-8")
    write_manifest(str(task_path), str(task_dir / ".acceptance-manifest.json"))
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "init batch")
    return root


def _batch_manifest(worktree: Path) -> Path:
    return worktree / Path(BATCH_TASK_FILE).parent / ".acceptance-manifest.json"


def _run_batch_worker(root: Path, run_id: str, task: str) -> dict[str, object]:
    worktree = root / f".code-flow/worktrees/{run_id}" / task
    (worktree / f"impl-{task}.txt").write_text(task + "\n", encoding="utf-8")
    _git(worktree, "add", "-A")
    _git(worktree, "commit", "-q", "-m", f"cf-task({task}): implementation")
    outcome = run_manifest(str(_batch_manifest(worktree)), str(worktree), write_evidence=True, owner=task)
    _force_status(worktree, task, "done", BATCH_TASK_FILE)
    _commit_worktree(worktree, task)
    return outcome


def _shared_marker_command(marker: Path) -> list[str]:
    return [
        sys.executable,
        "-c",
        "from pathlib import Path\n"
        f"p = Path({str(marker)!r})\n"
        "p.write_text((p.read_text() if p.exists() else '') + 'x')\n",
    ]


def test_batch_smoke_after_merge_runs_shared_e2e_once(tmp_path: Path) -> None:
    """S-07: collect 标 pending，merge 后在主 worktree 跑一次 smoke，shared E2E 只执行一次。"""
    marker = tmp_path / "shared-e2e.log"
    tasks = ["TASK-001", "TASK-002", "TASK-003"]
    root = _batch_repo(tmp_path, tasks, _shared_marker_command(marker))
    prepared = prepare(root, BATCH_TASK_FILE, tasks, "run-batch-smoke")
    assert prepared["ok"] is True

    with ThreadPoolExecutor(max_workers=3) as pool:
        outcomes = list(pool.map(lambda task: _run_batch_worker(root, "run-batch-smoke", task), tasks))
    assert all(item["decision"] == "pass" for item in outcomes), outcomes

    collected = collect(root, "run-batch-smoke", None)
    assert collected["ok"] is True, collected
    assert collected["batch_smoke"] == "pending"

    merged = merge(root, "run-batch-smoke", None)

    assert merged["ok"] is True, merged
    assert [item["status"] for item in merged["results"]] == ["merged", "merged", "merged"]
    smoke = merged["batch_smoke"]
    assert smoke["status"] == "passed"
    assert smoke["profile"] == "smoke"
    assert smoke["decision"] == "pass"
    assert smoke["executed"] == 1, smoke
    assert marker.read_text(encoding="utf-8") == "x", "shared E2E 必须只执行一次"


def test_batch_smoke_failure_keeps_worktrees_and_blocks_cleanup(tmp_path: Path) -> None:
    """S-07 失败面：smoke block 时不得 cleanup，也不得把任务标成 verified。"""
    failing = [sys.executable, "-c", "raise SystemExit(3)"]
    tasks = ["TASK-001", "TASK-002", "TASK-003"]
    root = _batch_repo(tmp_path, tasks, failing)
    prepare(root, BATCH_TASK_FILE, tasks, "run-batch-fail")
    for task in tasks:
        assert _run_batch_worker(root, "run-batch-fail", task)["decision"] == "pass"
    assert collect(root, "run-batch-fail", None)["batch_smoke"] == "pending"

    merged = merge(root, "run-batch-fail", None)

    assert merged["ok"] is False
    assert merged["code"] == "batch_smoke_failed"
    assert merged["batch_smoke"]["status"] == "failed"
    assert merged["batch_smoke"]["decision"] == "block"
    run_meta = json.loads((root / ".code-flow/worktrees/run-batch-fail/run.json").read_text(encoding="utf-8"))
    assert run_meta["merge"]["status"] == "blocked"
    assert run_meta["merge"]["code"] == "batch_smoke_failed"
    text = (root / BATCH_TASK_FILE).read_text(encoding="utf-8")
    task_sections = re.split(r"(?m)^## TASK-\d+:", text)
    for section in task_sections[1:]:
        assert "- **Status**: done" in section
        assert "- **Status**: verified" not in section
    for task in tasks:
        assert (root / ".code-flow/worktrees/run-batch-fail" / task).is_dir()

    cleaned = cleanup(root, "run-batch-fail", force=False)

    assert cleaned["ok"] is False
    assert {item["code"] for item in cleaned["results"]} == {"batch_smoke_failed"}
    for task in tasks:
        assert (root / ".code-flow/worktrees/run-batch-fail" / task).is_dir()


def test_batch_smoke_shared_env_lock_serializes_real_worktrees(tmp_path: Path) -> None:
    """shared 环境检查跨 worktree 串行：两个真实 worktree 的 shared E2E 不重叠。"""
    go = tmp_path / "shared-go"
    log = tmp_path / "shared-intervals.log"
    capture = (
        "import sys, time\n"
        "from pathlib import Path\n"
        "go = Path(sys.argv[1]); log = Path(sys.argv[2])\n"
        "while not go.exists():\n"
        "    time.sleep(0.01)\n"
        "start = time.time()\n"
        "time.sleep(0.4)\n"
        "end = time.time()\n"
        "with log.open('a') as handle:\n"
        "    handle.write(f'{sys.argv[3]} {start} {end}\\n')\n"
    )
    e2e_command = [sys.executable, "-c", capture, str(go), str(log), "shared"]
    tasks = ["TASK-001", "TASK-002"]
    root = _batch_repo(tmp_path, tasks, e2e_command)
    prepared = prepare(root, BATCH_TASK_FILE, tasks, "run-lock")
    assert prepared["ok"] is True

    from codeflow.core.cf_worktree_env import shared_env_lock_path

    env = dict(os.environ)
    env["PYTHONPATH"] = str(SCRIPTS) + os.pathsep + env.get("PYTHONPATH", "")
    processes = []
    ready_files = []
    for item in prepared["worktrees"]:
        worktree = Path(item["path"])
        ready = tmp_path / f"ready-{item['task']}"
        ready_files.append(ready)
        code = (
            "import json, sys\n"
            "from pathlib import Path\n"
            f"Path({str(ready)!r}).write_text('1')\n"
            f"sys.path.insert(0, {str(SCRIPTS)!r})\n"
            "from cf_acceptance_runner import run_manifest\n"
            f"result = run_manifest({str(_batch_manifest(worktree))!r}, {str(worktree)!r}, "
            "only_e2e=True, use_cache=False)\n"
            "print(json.dumps(result))\n"
        )
        processes.append(subprocess.Popen(
            (sys.executable, "-c", code), cwd=str(worktree), env=env,
            text=True, encoding="utf-8", stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        ))

    deadline = time.monotonic() + 15
    while time.monotonic() < deadline and not all(path.exists() for path in ready_files):
        time.sleep(0.02)
    assert all(path.exists() for path in ready_files), "两个 worker 必须都启动"
    lock = shared_env_lock_path(str(root))
    while time.monotonic() < deadline and not lock.exists():
        time.sleep(0.02)
    assert lock.exists(), "shared 环境锁必须被第一个 worktree 持有"
    time.sleep(0.2)
    go.write_text("go", encoding="utf-8")

    for process in processes:
        stdout, stderr = process.communicate(timeout=20)
        assert process.returncode == 0, stderr
        assert json.loads(stdout)["decision"] == "pass", stdout

    entries = [line.split() for line in log.read_text(encoding="utf-8").splitlines()]
    assert len(entries) == 2, entries
    intervals = sorted((float(start), float(end)) for _, start, end in entries)
    assert intervals[1][0] >= intervals[0][1] - 0.05, intervals


def test_batch_smoke_shared_env_lock_recovers_stale_owner(tmp_path: Path) -> None:
    """stale timeout：残留锁超过阈值可被后继 worktree 接管。"""
    root = _repo(tmp_path)
    from codeflow.core.cf_worktree_env import shared_env_lock, shared_env_lock_path

    lock = shared_env_lock_path(str(root))
    lock.parent.mkdir(parents=True, exist_ok=True)
    lock.write_text(json.dumps({
        "pid": 999999,
        "host": socket.gethostname(),
        "token": "stale-owner",
        "created_at": time.time() - 3600,
    }), encoding="utf-8")

    started = time.monotonic()
    with shared_env_lock(str(root), wait=2, stale_after=1) as info:
        assert Path(info["path"]) == lock
    assert time.monotonic() - started < 1.5
    assert not lock.exists()


def test_required_check_map_includes_all_scenario_checks() -> None:
    from cf_task_parallel import _required_check_map
    manifest = {"scenarios": [{
        "id": "S-01", "kind": "functional", "owner": "TASK-001",
        "checks": ["CHK-A", "CHK-B"],
    }]}
    required = _required_check_map(manifest, "TASK-001")
    assert required == {"CHK-A": ["S-01"], "CHK-B": ["S-01"]}
