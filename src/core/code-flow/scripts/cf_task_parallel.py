#!/usr/bin/env python3
"""Task-level worktree orchestration for parallel batch execution.

`cf-task:start` 整文件模式对拓扑批次内的独立 TASK 并行派发子 agent 时，本脚本
负责可测试的确定性步骤，子 agent 派发与合并冲突解决仍由命令提示词编排：

  prepare  预检（git 仓库 / worktree 忽略规则 / 无 active marker / tracked 干净）
           → 自动提交仅位于需求目录内的流程产物 → 校验任务可并行 → 建 worktree+分支
  collect  回并前校验：改动已提交、Status 已 done/verified、marker 已清理
  merge    按 TASK-ID 顺序回并：worktree 内 rebase → 状态文件冲突按确定性并集规则
           解决 → 主区 --no-ff 合并 → refresh 收敛；代码文件冲突保留人工（fail-closed）
  cleanup  合并完成后移除 worktree；已合入的分支一并删除，未合入的保留可追溯

协议（详见 cf-task:start 命令正文）：
- worktree: .code-flow/worktrees/<run-id>/<TASK-ID>/
- branch:   cf-task/<slug>/<run-id>/<TASK-ID>
- 元数据:   .code-flow/worktrees/<run-id>/run.json（base head / 任务清单）

stdout 始终为 JSON：{"ok": true, ...} 或 {"ok": false, "code": ..., "message": ...}。
预检失败时命令方回退串行，不得手工绕过本脚本建 worktree/分支。
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import IO, Optional, Sequence

from cf_task_index import parse_task_file
from cf_task_index import task_batches
from cf_task_merge import merge_context_text
from cf_task_merge import merge_manifest_text
from cf_task_merge import merge_task_markdown
from cf_task_state import FINISHED_STATUSES


WORKTREES_DIR = ".code-flow/worktrees"
MARKER = ".code-flow/.active-task.json"
GITIGNORE = ".code-flow/.gitignore"
_RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_TASK_ID = re.compile(r"^TASK-\d+$")


class ParallelError(ValueError):
    """Precondition or protocol violation with a stable machine code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _run_git(root: Path, arguments: Sequence[str]) -> str:
    result = subprocess.run(
        ("git", *arguments), cwd=str(root), text=True, encoding="utf-8", capture_output=True, check=False
    )
    if result.returncode != 0:
        message = result.stderr.strip() or "Git command failed"
        raise ParallelError("git_error", message)
    return result.stdout


def _assert_repo(root: Path) -> None:
    try:
        top = _run_git(root, ("rev-parse", "--show-toplevel")).strip()
    except ParallelError as exc:
        raise ParallelError("git_unavailable", "并行执行需要 git 仓库") from exc
    if Path(top).resolve() != root:
        raise ParallelError("not_project_root", f"root 必须是仓库根目录: {top}")


def _status_paths(root: Path) -> list[str]:
    output = _run_git(root, ("status", "--porcelain=v1", "-z", "--untracked-files=all"))
    tokens = output.split("\0")
    paths: list[str] = []
    index = 0
    while index < len(tokens) and tokens[index]:
        record = tokens[index]
        if len(record) < 4:
            raise ParallelError("invalid_git_status", record)
        code, path = record[:2], record[3:]
        paths.append(path)
        if code[:1] in ("R", "C"):
            if index + 1 < len(tokens) and tokens[index + 1]:
                paths.append(tokens[index + 1])
            index += 2
        else:
            index += 1
    return paths


def _require_ignored(root: Path) -> None:
    ignore = root / GITIGNORE
    try:
        text = ignore.read_text(encoding="utf-8")
    except OSError as exc:
        raise ParallelError("worktrees_not_ignored", f"缺少 {GITIGNORE}: {exc}") from exc
    if "worktrees/" not in text.split():
        raise ParallelError(
            "worktrees_not_ignored", f"{GITIGNORE} 缺少 worktrees/ 规则，请先运行 code-flow init 升级"
        )


def _require_no_active(root: Path) -> None:
    if (root / MARKER).exists():
        raise ParallelError("active_exists", "主 worktree 已有 active TASK，先 finish/doctor 后再并行")


def _commit_task_dir(root: Path, task_file: str) -> Optional[str]:
    # Git porcelain emits forward-slash paths; compare in POSIX form so
    # Windows backslash paths are not all classified as "outside".
    task_dir = Path(task_file).parent.as_posix()
    entries = _status_paths(root)
    outside = [
        path
        for path in entries
        if not (path == task_dir or path.startswith(f"{task_dir}/"))
    ]
    if outside:
        sample = ", ".join(outside[:8]) + (" ..." if len(outside) > 8 else "")
        raise ParallelError(
            "dirty_tree",
            "并行要求 tracked 工作区干净（需求目录以外仍有改动: "
            f"{sample}）。请先提交（git add -A && git commit -m 'wip'）"
            "或暂存（git stash push -u）后重试；需求目录内的流程产物会自动提交。",
        )
    if not entries:
        return None
    _run_git(root, ("add", "-A", "--", str(task_dir)))
    _run_git(root, ("commit", "-q", "-m", f"chore(cf-task): plan {Path(task_file).stem}"))
    return _run_git(root, ("rev-parse", "HEAD")).strip()


def _validate_batch(root: Path, task_file: str, tasks: Sequence[str]) -> str:
    path = root / task_file
    if not path.is_file():
        raise ParallelError("task_file_missing", f"任务文件不存在: {task_file}")
    try:
        nodes = parse_task_file(str(path))
    except ValueError as exc:
        raise ParallelError("task_parse_error", str(exc)) from exc
    by_id = {node.task_id: node for node in nodes}
    for task in tasks:
        if task not in by_id:
            raise ParallelError("unknown_task", f"{task} 不在任务文件中")
        if by_id[task].status != "draft":
            raise ParallelError("task_not_draft", f"{task} 当前 Status 为 {by_id[task].status}，不可并行激活")
    try:
        ready = task_batches(nodes)[0]
    except ValueError as exc:
        raise ParallelError("task_graph_error", str(exc)) from exc
    not_ready = [task for task in tasks if task not in ready]
    if not_ready:
        raise ParallelError("task_not_ready", f"依赖未完成，本批不可激活: {', '.join(not_ready)}（可激活: {', '.join(ready)}）")
    return str(path)


def _branch_slug(task_file: str) -> str:
    stem = Path(task_file).stem
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", stem).strip("-._")
    return slug[:40] or "batch"


def _worktree_paths(root: Path, run_id: str, task: str, task_file: str) -> tuple[Path, str]:
    branch = f"cf-task/{_branch_slug(task_file)}/{run_id}/{task}"
    return root / WORKTREES_DIR / run_id / task, branch


def _run_id() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def _unique_run_id(root: Path) -> str:
    """Second-precision run ids collide when two batches are dispatched in the
    same second; that overwrote run.json and orphaned the first run's worktrees.
    Suffix -2, -3, … until the run directory is free."""
    base = _run_id()
    identifier = base
    counter = 1
    while (root / WORKTREES_DIR / identifier).exists() or not _RUN_ID.match(identifier):
        counter += 1
        identifier = f"{base}-{counter}"
    return identifier


def _write_run_meta(run_dir: Path, payload: dict[str, object]) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    meta = run_dir / "run.json"
    if meta.exists():
        raise ParallelError("run_id_conflict", f"run 记录已存在: {meta}")
    temporary = meta.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(meta)


def _read_run_meta(root: Path, run_id: str) -> dict[str, object]:
    meta = root / WORKTREES_DIR / run_id / "run.json"
    try:
        data = json.loads(meta.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ParallelError("run_not_found", f"找不到并行记录 {meta}: {exc}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("base_head"), str) or not isinstance(data.get("task_file"), str):
        raise ParallelError("run_corrupt", f"并行记录损坏（缺 base_head/task_file）: {meta}")
    return data


def _create_worktrees(root: Path, task_file: str, tasks: Sequence[str], run_id: str) -> dict[str, object]:
    created: list[tuple[Path, str]] = []
    base_head = _run_git(root, ("rev-parse", "HEAD")).strip()
    try:
        for task in tasks:
            path, branch = _worktree_paths(root, run_id, task, task_file)
            if path.exists() or _branch_exists(root, branch):
                raise ParallelError("worktree_exists", f"{task} 的 worktree 或分支已存在: {branch}")
            path.parent.mkdir(parents=True, exist_ok=True)
            _run_git(root, ("worktree", "add", "-b", branch, str(path), "HEAD"))
            if not (path / task_file).is_file():
                raise ParallelError("task_file_missing", f"{task}: worktree 内缺少 {task_file}（需先提交任务文件）")
            created.append((path, branch))
    except ParallelError:
        for path, branch in created:
            _remove_worktree(root, path, force=True)
            _run_git(root, ("branch", "-D", branch))
        raise
    return {"base_head": base_head, "created": created}


def _branch_exists(root: Path, branch: str) -> bool:
    result = subprocess.run(
        ("git", "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}"),
        cwd=str(root), capture_output=True, check=False,
    )
    return result.returncode == 0


def _delete_branch(root: Path, branch: str, force: bool = False) -> bool:
    # 默认 -d 只删已合入分支；--force 表示用户明确接受未合入分支的删除。
    flag = "-D" if force else "-d"
    result = subprocess.run(
        ("git", "branch", flag, branch), cwd=str(root), capture_output=True, check=False,
    )
    return result.returncode == 0


def _remove_worktree(root: Path, path: Path, force: bool) -> None:
    arguments = ["worktree", "remove"]
    if force:
        arguments.append("--force")
    arguments.append(str(path))
    _run_git(root, tuple(arguments))


def _relative_task_file(root: Path, task_file: str) -> str:
    candidate = Path(task_file)
    absolute = candidate if candidate.is_absolute() else root / candidate
    try:
        return absolute.resolve().relative_to(root).as_posix()
    except ValueError as exc:
        raise ParallelError("task_file_outside_root", f"任务文件不在仓库内: {task_file}") from exc


def prepare(root: Path, task_file: str, tasks: Sequence[str], run_id: Optional[str]) -> dict[str, object]:
    root = root.resolve()
    _assert_repo(root)
    task_file = _relative_task_file(root, task_file)
    _require_ignored(root)
    _require_no_active(root)
    identifier = run_id or _unique_run_id(root)
    if not _RUN_ID.match(identifier):
        raise ParallelError("invalid_run_id", f"run-id 非法: {identifier}")
    if (root / WORKTREES_DIR / identifier / "run.json").exists():
        raise ParallelError(
            "run_id_conflict",
            f"run 记录已存在: {identifier}。请清理后重试（cleanup）或使用新的 run-id。",
        )
    if not tasks:
        raise ParallelError("no_tasks", "未指定并行 TASK")
    if len(set(tasks)) != len(tasks):
        raise ParallelError("duplicate_task", "并行 TASK 列表存在重复")
    for task in tasks:
        if not _TASK_ID.match(task):
            raise ParallelError("invalid_task_id", f"TASK-ID 非法: {task}")
    _validate_batch(root, task_file, tasks)
    _commit_task_dir(root, task_file)
    outcome = _create_worktrees(root, task_file, tasks, identifier)
    worktrees = [
        {"task": task, "branch": branch, "path": str(path)}
        for task, (path, branch) in zip(tasks, outcome["created"])
    ]
    _write_run_meta(
        root / WORKTREES_DIR / identifier,
        {"version": 1, "run_id": identifier, "task_file": task_file,
         "base_head": outcome["base_head"], "worktrees": worktrees},
    )
    return {"ok": True, "action": "prepare", "run_id": identifier, "task_file": task_file,
            "base_head": outcome["base_head"], "worktrees": worktrees}


def _collect_one(root: Path, entry: dict[str, object], base_head: str, task_file: str, commit: bool = True) -> dict[str, object]:
    task = str(entry["task"])
    path = Path(str(entry["path"]))
    branch = str(entry["branch"])
    if not path.is_dir():
        raise ParallelError("worktree_missing", f"{task}: worktree 不存在: {path}")
    try:
        nodes = parse_task_file(str(path / task_file))
    except ValueError as exc:
        raise ParallelError("task_parse_error", f"{task}: {exc}") from exc
    status = next((node.status for node in nodes if node.task_id == task), None)
    if status not in FINISHED_STATUSES:
        raise ParallelError("task_not_finished", f"{task}: Status 为 {status}，未通过 Done Gate")
    if (path / MARKER).exists():
        raise ParallelError("active_marker_present", f"{task}: marker 未清理，finish 未完成")
    dirty = _status_paths(path)
    if dirty:
        # finish 会在通过后回写 Evidence/状态；任务已 done 且 marker 已清理时，
        # 这些回写由 collect 自动提交（--no-commit 可关闭，保持严格模式）。
        if not commit:
            raise ParallelError(
                "worktree_dirty",
                f"{task}: 尚有未提交改动: {', '.join(dirty[:8])}；可在 worktree 内提交后重跑 collect，或去掉 --no-commit",
            )
        _run_git(path, ("add", "-A"))
        _run_git(path, ("commit", "-q", "-m", f"cf-task({task}): finish 回写验收证据与任务状态"))
    head = _run_git(path, ("rev-parse", "HEAD")).strip()
    if head == base_head:
        raise ParallelError("no_commits", f"{task}: worktree 无新提交")
    files = _run_git(root, ("diff", "--name-only", f"{base_head}..{branch}")).splitlines()
    return {"task": task, "branch": branch, "path": str(path), "head": head,
            "status": status, "files": sorted(item for item in files if item)}


def collect(root: Path, run_id: str, tasks: Optional[Sequence[str]], commit: bool = True) -> dict[str, object]:
    root = root.resolve()
    meta = _read_run_meta(root, run_id)
    entries = [item for item in meta.get("worktrees", []) if isinstance(item, dict)]
    if tasks:
        wanted = set(tasks)
        entries = [item for item in entries if item.get("task") in wanted]
    results: list[dict[str, object]] = []
    for entry in entries:
        try:
            results.append(_collect_one(root, entry, str(meta["base_head"]), str(meta["task_file"]), commit))
        except ParallelError as exc:
            results.append({"task": str(entry.get("task", "")), "ok": False, "code": exc.code, "message": exc.message})
    ok = bool(results) and all(item.get("code") is None for item in results)
    return {"ok": ok, "action": "collect", "run_id": run_id, "results": results}


# --- merge: rebase + deterministic state-file resolution + --no-ff back-merge ---

_MAX_CONFLICT_ROUNDS = 8
_STATE_MERGE_NAMES = ("spec-context.yml", ".acceptance-manifest.json")


def _git_try(root: Path, arguments: Sequence[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        ("git", *arguments), cwd=str(root), text=True, encoding="utf-8", capture_output=True, check=False
    )


def _output_tail(result: subprocess.CompletedProcess) -> str:
    text = (result.stderr or result.stdout or "").strip()
    return text[-300:]


def _abort_git(root: Path, *arguments: str) -> None:
    subprocess.run(("git", *arguments), cwd=str(root), capture_output=True, check=False)


def _unmerged_files(root: Path) -> list[str]:
    result = _git_try(root, ("diff", "--name-only", "--diff-filter=U"))
    return [line for line in result.stdout.splitlines() if line.strip()]


def _git_show(root: Path, stage: int, relative: str) -> str:
    result = _git_try(root, ("show", f":{stage}:{relative}"))
    if result.returncode != 0:
        raise ParallelError("conflict_stage_missing", f"{relative}: 缺少冲突 stage {stage}")
    return result.stdout


def _is_state_file(relative: str, task_file: str) -> bool:
    name = Path(relative).name
    if name in _STATE_MERGE_NAMES:
        return True
    parent = Path(task_file).parent.as_posix()
    return name.endswith(".md") and Path(relative).parent.as_posix() == parent


def _resolve_state_file(workdir: Path, relative: str, task: str) -> None:
    ours = _git_show(workdir, 2, relative)
    theirs = _git_show(workdir, 3, relative)
    name = Path(relative).name
    try:
        if name == "spec-context.yml":
            merged = merge_context_text(ours, theirs)
        elif name == ".acceptance-manifest.json":
            merged = merge_manifest_text(ours, theirs)
        elif "## TASK-" in ours or "## TASK-" in theirs:
            merged = merge_task_markdown(ours, theirs, task)
        else:
            raise ParallelError("state_file_unresolvable", f"{relative}: 非任务状态文件，需人工解决")
    except ValueError as exc:
        raise ParallelError("state_file_parse_error", f"{relative}: {exc}") from exc
    (workdir / relative).write_text(merged, encoding="utf-8")
    _run_git(workdir, ("add", "--", relative))


def _resolve_conflicts(workdir: Path, task: str, task_file: str, resolved: list[str]) -> None:
    unresolved = _unmerged_files(workdir)
    if not unresolved:
        raise ParallelError("conflict_state_lost", "冲突状态已丢失，无法自动解决")
    for relative in unresolved:
        if not _is_state_file(relative, task_file):
            raise ParallelError(
                "code_conflict",
                f"代码文件冲突需人工解决（状态文件已按并集规则自动处理）: {', '.join(unresolved)}",
            )
        _resolve_state_file(workdir, relative, task)
        if relative not in resolved:
            resolved.append(relative)


def _rebase_onto_main(path: Path, main_branch: str, task: str, task_file: str, resolved: list[str]) -> None:
    result = _git_try(path, ("rebase", main_branch))
    rounds = 0
    while result.returncode != 0 and rounds < _MAX_CONFLICT_ROUNDS:
        if not _unmerged_files(path):
            _abort_git(path, "rebase", "--abort")
            raise ParallelError("rebase_failed", f"{task}: git rebase 失败: {_output_tail(result)}")
        try:
            _resolve_conflicts(path, task, task_file, resolved)
        except ParallelError:
            _abort_git(path, "rebase", "--abort")
            raise
        result = _git_try(path, ("-c", "core.editor=true", "rebase", "--continue"))
        if result.returncode != 0:
            combined = (result.stdout or "") + (result.stderr or "")
            if "rebase --skip" in combined or "is now empty" in combined:
                result = _git_try(path, ("rebase", "--skip"))
        rounds += 1
    if result.returncode != 0:
        _abort_git(path, "rebase", "--abort")
        raise ParallelError("rebase_failed", f"{task}: git rebase 失败: {_output_tail(result)}")


def _merge_branch(root: Path, branch: str, task: str, task_file: str, resolved: list[str]) -> None:
    result = _git_try(root, ("merge", "--no-ff", "-m", f"merge cf-task {task}", branch))
    rounds = 0
    while result.returncode != 0 and rounds < _MAX_CONFLICT_ROUNDS:
        if not _unmerged_files(root):
            _abort_git(root, "merge", "--abort")
            raise ParallelError("merge_failed", f"{task}: git merge 失败: {_output_tail(result)}")
        try:
            _resolve_conflicts(root, task, task_file, resolved)
        except ParallelError:
            _abort_git(root, "merge", "--abort")
            raise
        result = _git_try(root, ("commit", "--no-edit"))
        rounds += 1
    if result.returncode != 0:
        _abort_git(root, "merge", "--abort")
        raise ParallelError("merge_failed", f"{task}: git merge 失败: {_output_tail(result)}")


def _branch_is_ancestor(root: Path, ancestor: str) -> bool:
    return _git_try(root, ("merge-base", "--is-ancestor", ancestor, "HEAD")).returncode == 0


def _merge_one(root: Path, main_branch: str, entry: dict, task_file: str) -> dict[str, object]:
    task = str(entry.get("task", ""))
    path = Path(str(entry.get("path", "")))
    branch = str(entry.get("branch", ""))
    if not path.is_dir():
        raise ParallelError("worktree_missing", f"{task}: worktree 不存在: {path}")
    if (path / MARKER).exists():
        raise ParallelError("active_marker_present", f"{task}: marker 未清理，finish 未完成")
    try:
        nodes = parse_task_file(str(path / task_file))
    except ValueError as exc:
        raise ParallelError("task_parse_error", f"{task}: {exc}") from exc
    status = next((node.status for node in nodes if node.task_id == task), None)
    if status not in FINISHED_STATUSES:
        raise ParallelError("task_not_finished", f"{task}: Status 为 {status}，未通过 Done Gate")
    if _status_paths(path):
        raise ParallelError("worktree_dirty", f"{task}: worktree 有未提交改动，先运行 collect")
    if _branch_is_ancestor(root, branch):
        return {"task": task, "ok": True, "status": "already_merged"}
    resolved: list[str] = []
    _rebase_onto_main(path, main_branch, task, task_file, resolved)
    _merge_branch(root, branch, task, task_file, resolved)
    return {
        "task": task, "ok": True, "status": "merged", "resolved": sorted(set(resolved)),
        "commit": _run_git(root, ("rev-parse", "HEAD")).strip(),
    }


def _refresh_demand(root: Path, task_file: str) -> str:
    demand = root / Path(task_file).parent
    script = root / ".code-flow" / "scripts" / "cf_spec_context.py"
    result = subprocess.run(
        (sys.executable, str(script), "refresh", "--task-dir", str(demand), "--root", str(root), "--json"),
        cwd=str(root), text=True, encoding="utf-8", capture_output=True, check=False,
    )
    if result.returncode == 0:
        return "pass"
    detail = (result.stdout or result.stderr or "").strip()
    return f"block: {detail[-200:]}"


def merge(root: Path, run_id: str, tasks: Optional[Sequence[str]]) -> dict[str, object]:
    root = root.resolve()
    _assert_repo(root)
    meta = _read_run_meta(root, run_id)
    main_branch = _run_git(root, ("rev-parse", "--abbrev-ref", "HEAD")).strip()
    if main_branch == "HEAD":
        raise ParallelError("detached_head", "主工作区处于 detached HEAD，无法回并")
    wanted = set(tasks) if tasks else None
    entries = [item for item in meta.get("worktrees", []) if isinstance(item, dict)]
    if wanted:
        entries = [item for item in entries if item.get("task") in wanted]
    entries.sort(key=lambda item: str(item.get("task", "")))
    task_file = str(meta["task_file"])
    results: list[dict[str, object]] = []
    for entry in entries:
        try:
            results.append(_merge_one(root, main_branch, entry, task_file))
        except ParallelError as exc:
            results.append(
                {"task": str(entry.get("task", "")), "ok": False, "code": exc.code, "message": exc.message}
            )
            break
    ok = bool(results) and all(item.get("ok") for item in results)
    payload: dict[str, object] = {
        "ok": ok, "action": "merge", "run_id": run_id,
        "main_branch": main_branch, "results": results,
    }
    if ok and (root / Path(task_file).parent / "spec-context.yml").is_file():
        payload["refresh"] = _refresh_demand(root, task_file)
    return payload


def cleanup(root: Path, run_id: str, force: bool) -> dict[str, object]:
    root = root.resolve()
    meta = _read_run_meta(root, run_id)
    results: list[dict[str, object]] = []
    for item in meta.get("worktrees", []):
        if not isinstance(item, dict):
            continue
        path = Path(str(item.get("path", "")))
        if not path.exists():
            results.append({"task": item.get("task"), "removed": False, "reason": "already_absent"})
            continue
        try:
            _require_clean_for_removal(path, force)
            _remove_worktree(root, path, force)
            branch = str(item.get("branch", ""))
            merged = _delete_branch(root, branch, force) if branch else False
            results.append({"task": item.get("task"), "removed": True, "branch_deleted": merged})
        except ParallelError as exc:
            results.append({"task": item.get("task"), "removed": False, "code": exc.code, "message": exc.message})
    _run_git(root, ("worktree", "prune"))
    run_dir = root / WORKTREES_DIR / run_id
    if run_dir.is_dir() and not any(child.is_dir() for child in run_dir.iterdir()):
        (run_dir / "run.json").unlink(missing_ok=True)
        run_dir.rmdir()
    ok = all(item.get("removed") or item.get("reason") == "already_absent" for item in results)
    return {"ok": ok, "action": "cleanup", "run_id": run_id, "results": results}


def _require_clean_for_removal(path: Path, force: bool) -> None:
    if force:
        return
    dirty = _status_paths(path)
    if dirty:
        raise ParallelError("worktree_dirty", f"worktree 有未提交改动: {', '.join(dirty[:8])}")


def _emit(payload: dict[str, object], stdout: IO[str]) -> None:
    stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")


def main(argv: Optional[Sequence[str]] = None, stdout: IO[str] = sys.stdout) -> int:
    parser = argparse.ArgumentParser(prog="cf_task_parallel.py")
    sub = parser.add_subparsers(dest="action", required=True)
    for name in ("prepare", "collect", "cleanup", "merge"):
        command = sub.add_parser(name)
        command.add_argument("--root", default=".")
        command.add_argument("--json", action="store_true")
    prepare_parser = sub.choices["prepare"]
    prepare_parser.add_argument("--task-file", required=True)
    prepare_parser.add_argument("--tasks", required=True)
    prepare_parser.add_argument("--run-id", default="")
    for name in ("collect", "cleanup", "merge"):
        sub.choices[name].add_argument("--run-id", required=True)
    sub.choices["collect"].add_argument("--tasks", default="")
    sub.choices["collect"].add_argument("--no-commit", action="store_true")
    sub.choices["cleanup"].add_argument("--force", action="store_true")
    sub.choices["merge"].add_argument("--tasks", default="")
    args = parser.parse_args(argv)
    root = Path(args.root).resolve()
    try:
        if args.action == "prepare":
            tasks = [item.strip() for item in args.tasks.split(",") if item.strip()]
            payload = prepare(root, args.task_file, tasks, args.run_id or None)
        elif args.action == "collect":
            tasks = [item.strip() for item in args.tasks.split(",") if item.strip()] or None
            payload = collect(root, args.run_id, tasks, commit=not args.no_commit)
        elif args.action == "merge":
            tasks = [item.strip() for item in args.tasks.split(",") if item.strip()] or None
            payload = merge(root, args.run_id, tasks)
        else:
            payload = cleanup(root, args.run_id, args.force)
    except ParallelError as exc:
        payload = {"ok": False, "action": args.action, "code": exc.code, "message": exc.message}
    _emit(payload, stdout)
    return 0 if payload.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
