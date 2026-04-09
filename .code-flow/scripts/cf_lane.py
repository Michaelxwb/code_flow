#!/usr/bin/env python3
"""Lane command entrypoint."""

from __future__ import annotations

import argparse
import glob
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from typing import Any

from cf_lane_core import (
    LaneSchemaError,
    acquire_lock,
    build_dep_graph,
    detect_cycle,
    get_task_owner,
    is_stale_lock,
    load_lanes,
    locks_dir_path,
    release_lock,
    run_git,
    save_lanes,
    sync_task_auto,
    sync_task_head_only,
)

_HOOK_MARKER = "code-flow check-merge"


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _normalize_rel(path: str, project_root: str) -> str:
    return os.path.relpath(path, project_root).replace(os.sep, "/")


_run_git = run_git


def _task_files(project_root: str) -> list[str]:
    pattern = os.path.join(project_root, ".code-flow", "tasks", "**", "*.md")
    files = glob.glob(pattern, recursive=True)
    result = []
    for path in files:
        rel = _normalize_rel(path, project_root)
        if "archived/" in rel:
            continue
        result.append(path)
    return sorted(result)


def _task_lifecycle(task_path: str) -> str:
    with open(task_path, "r", encoding="utf-8") as f:
        content = f.read()
    m = re.search(r"^- \*\*Lifecycle\*\*: ([^\n]+)$", content, re.M)
    if m:
        return m.group(1).strip().lower()
    m = re.search(r"^Lifecycle:\s*([^\n]+)$", content, re.M)
    if m:
        return m.group(1).strip().lower()
    return ""


def _task_slug(task_rel: str) -> str:
    name = os.path.splitext(os.path.basename(task_rel))[0].lower()
    slug = re.sub(r"[^a-z0-9]+", "-", name).strip("-")
    return slug or "lane"


def resolve_task_file(project_root: str, task_arg: str) -> str:
    if not task_arg:
        raise ValueError("task file is required")
    if task_arg.endswith(".md") or "/" in task_arg or "\\" in task_arg:
        candidate = task_arg
        if not os.path.isabs(candidate):
            candidate = os.path.join(project_root, candidate)
        if os.path.exists(candidate):
            rel = _normalize_rel(os.path.realpath(candidate), project_root)
            if rel.startswith(".code-flow/tasks/") and "archived/" not in rel:
                return rel
    name = task_arg[:-3] if task_arg.endswith(".md") else task_arg
    matches = []
    for path in _task_files(project_root):
        base = os.path.splitext(os.path.basename(path))[0]
        if base == name:
            matches.append(_normalize_rel(path, project_root))
    if not matches:
        raise ValueError(f"task file not found: {task_arg}")
    if len(matches) > 1:
        paths = "\n".join(f"- {m}" for m in matches)
        raise ValueError(f"task file matches multiple paths, please specify full path:\n{paths}")
    return matches[0]


def _approved_unbound_tasks(project_root: str, lanes: list[dict[str, Any]]) -> list[str]:
    result = []
    for task_path in _task_files(project_root):
        lifecycle = _task_lifecycle(task_path)
        if lifecycle != "approved":
            continue
        rel = _normalize_rel(task_path, project_root)
        owner = get_task_owner(lanes, rel)
        if owner:
            continue
        result.append(rel)
    return sorted(result)


def _branch_exists(project_root: str, branch: str) -> bool:
    result = _run_git(project_root, ["show-ref", "--verify", f"refs/heads/{branch}"], check=False)
    return result.returncode == 0


def _worktree_path(project_root: str, worktree_opt: str | None, task_rel: str) -> str:
    if worktree_opt:
        if os.path.isabs(worktree_opt):
            return os.path.realpath(worktree_opt)
        return os.path.realpath(os.path.join(project_root, worktree_opt))
    parent = os.path.dirname(project_root)
    repo_name = os.path.basename(project_root)
    return os.path.realpath(os.path.join(parent, f"{repo_name}-{_task_slug(task_rel)}"))


def _is_path_conflict(path: str) -> bool:
    if not os.path.exists(path):
        return False
    if not os.path.isdir(path):
        return True
    return bool(os.listdir(path))


def _find_dep_lane(lanes: list[dict[str, Any]], lane_id: str) -> dict[str, Any] | None:
    for lane in lanes:
        if lane.get("lane_id") == lane_id and lane.get("status") == "active":
            return lane
    return None


def _dep_type(dep_type: str | None, dep_lane: str | None) -> str:
    if dep_type:
        return dep_type
    return "hard" if dep_lane else "none"


def _base_branch(dep_type: str, dep_lane: dict[str, Any] | None) -> str:
    if dep_type == "hard":
        if not dep_lane:
            raise ValueError("hard dependency requires --dep-lane")
        return str(dep_lane.get("branch"))
    return "main"


def _lane_id(task_rel: str, lanes: list[dict[str, Any]]) -> str:
    prefix = _task_slug(task_rel)
    existing = {str(l.get("lane_id")) for l in lanes}
    for _ in range(20):
        candidate = f"{prefix}-{uuid.uuid4().hex[:8]}"
        if candidate not in existing:
            return candidate
    raise RuntimeError("failed to generate unique lane_id")


def _cleanup_new(project_root: str, worktree_path: str, branch: str, created_worktree: bool) -> list[str]:
    warnings: list[str] = []
    should_remove_worktree = created_worktree or bool(worktree_path and os.path.isdir(worktree_path))
    if should_remove_worktree:
        rm = _run_git(project_root, ["worktree", "remove", "--force", worktree_path], check=False)
        if rm.returncode != 0:
            warnings.append(f"failed to remove worktree {worktree_path}: {rm.stderr.strip()}")
    delete_branch = _run_git(project_root, ["branch", "-D", branch], check=False)
    if delete_branch.returncode != 0:
        warnings.append(f"failed to delete branch {branch}: {delete_branch.stderr.strip()}")
    return warnings


def _trigger_task_start(project_root: str, task_rel: str) -> str:
    task_name = os.path.splitext(os.path.basename(task_rel))[0]
    configured = os.environ.get("CF_TASK_START_CMD", "").strip()
    if configured:
        cmd = [*shlex.split(configured), task_name]
        result = subprocess.run(cmd, cwd=project_root, capture_output=True, text=True, check=False)
        if result.returncode != 0:
            detail = result.stderr.strip() or result.stdout.strip()
            return f"failed ({detail})"
        return "ok (configured)"
    cmd_path = shutil.which("cf-task-start")
    if not cmd_path:
        skill_path = os.path.join(project_root, ".agents", "skills", "cf-task-start", "SKILL.md")
        if os.path.exists(skill_path):
            return "manual (cf-task-start is skill-only; run via agent session)"
        return "skipped (cf-task-start command not available)"
    result = subprocess.run([cmd_path, task_name], cwd=project_root, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        return f"failed ({result.stderr.strip() or result.stdout.strip()})"
    return "ok"


def _hooks_dir(project_root: str) -> str:
    return os.path.join(project_root, ".code-flow", "hooks")


def _resolve_repo_path(project_root: str, maybe_rel: str) -> str:
    if os.path.isabs(maybe_rel):
        return os.path.realpath(maybe_rel)
    return os.path.realpath(os.path.join(project_root, maybe_rel))


def _current_hooks_path(project_root: str) -> str:
    result = _run_git(project_root, ["config", "--get", "core.hooksPath"], check=False)
    return result.stdout.strip()


def _write_executable(path: str, content: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    os.chmod(path, 0o755)


def _hook_script(chain_path: str) -> str:
    chain_line = ""
    if chain_path:
        escaped = shlex.quote(chain_path)
        chain_line = f'if [ -x {escaped} ]; then\n  {escaped} "$@"\nfi\n\n'
    return (
        "#!/usr/bin/env sh\n"
        "set -e\n\n"
        f"# {_HOOK_MARKER}\n"
        f"{chain_line}"
        "if command -v cf-lane >/dev/null 2>&1; then\n"
        "  cf-lane check-merge\n"
        "else\n"
        "  python3 .code-flow/scripts/cf_lane.py check-merge\n"
        "fi\n"
    )


def install_hooks(project_root: str) -> str:
    hooks_dir = _hooks_dir(project_root)
    target_hook = os.path.join(hooks_dir, "pre-push")
    os.makedirs(hooks_dir, exist_ok=True)

    existing_chain = ""
    current_hooks = _current_hooks_path(project_root)
    target_hooks_rel = ".code-flow/hooks"
    target_hooks_abs = os.path.realpath(hooks_dir)

    if current_hooks:
        current_abs = _resolve_repo_path(project_root, current_hooks)
        if os.path.realpath(current_abs) != target_hooks_abs:
            existing_chain = os.path.join(current_abs, "pre-push")
    else:
        legacy_hook = os.path.join(project_root, ".git", "hooks", "pre-push")
        if os.path.exists(legacy_hook):
            migrated = os.path.join(hooks_dir, "pre-push.legacy")
            if not os.path.exists(migrated):
                shutil.copy2(legacy_hook, migrated)
                os.chmod(migrated, 0o755)
            existing_chain = migrated

    if os.path.exists(target_hook):
        with open(target_hook, "r", encoding="utf-8") as f:
            current_content = f.read()
        if _HOOK_MARKER in current_content:
            _run_git(project_root, ["config", "core.hooksPath", target_hooks_rel], check=True)
            return "ok (already installed)"
        preserved = os.path.join(hooks_dir, "pre-push.user")
        if not os.path.exists(preserved):
            shutil.move(target_hook, preserved)
            os.chmod(preserved, 0o755)
        existing_chain = preserved

    _write_executable(target_hook, _hook_script(existing_chain))
    _run_git(project_root, ["config", "core.hooksPath", target_hooks_rel], check=True)
    return "ok"


def _trigger_doctor_fix(project_root: str) -> str:
    cmd_path = shutil.which("cf-lane")
    if not cmd_path:
        return "skipped (cf-lane not found in PATH)"
    result = subprocess.run(
        [cmd_path, "doctor", "--fix"],
        cwd=project_root,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip()
        return f"failed ({detail})"
    return "ok"


def _release_lock_safely(lock_path: str | None) -> None:
    if not lock_path:
        return
    try:
        release_lock(lock_path)
    except Exception as exc:
        print(f"WARNING: failed to release lock {lock_path}: {exc}", file=sys.stderr)


def _print_no_arg_help(project_root: str, lanes: list[dict[str, Any]]) -> int:
    tasks = _approved_unbound_tasks(project_root, lanes)
    if not tasks:
        print("No approved and unbound task found.")
        return 0
    print("Approved unbound tasks:")
    for rel in tasks:
        print(f"- {rel}")
    first = os.path.splitext(os.path.basename(tasks[0]))[0]
    print("Recommended command:")
    print(f"cf-lane new {first} --dep-type=none")
    return 0


def _parse_iso(value: str) -> float:
    if not value:
        return 0.0
    normalized = value.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(normalized).timestamp()
    except ValueError:
        return 0.0


def _task_progress(project_root: str, task_file: str) -> dict[str, int]:
    abs_path = os.path.join(project_root, task_file)
    if not os.path.exists(abs_path):
        return {"done": 0, "total": 0, "percent": 0}
    with open(abs_path, "r", encoding="utf-8") as f:
        content = f.read()
    marks = re.findall(r"^- \[([ xX])\] ", content, flags=re.M)
    total = len(marks)
    done = len([mark for mark in marks if mark.lower() == "x"])
    percent = int(done * 100 / total) if total > 0 else 0
    return {"done": done, "total": total, "percent": percent}


def _lane_health(lane: dict[str, Any], lane_map: dict[str, dict[str, Any]]) -> dict[str, Any]:
    dep_type = str(lane.get("dep_type") or "none")
    dep_lane_id = lane.get("dep_lane")
    if dep_type == "none":
        return {"dep_status": "none", "hard_blocked": False, "soft_risk": False}
    dep_lane = lane_map.get(str(dep_lane_id)) if dep_lane_id else None
    if not dep_lane:
        return {
            "dep_status": "missing",
            "hard_blocked": dep_type == "hard",
            "soft_risk": dep_type == "soft",
        }
    dep_status = str(dep_lane.get("status") or "unknown")
    hard_blocked = dep_type == "hard" and dep_status != "closed"
    soft_risk = False
    if dep_type == "soft":
        dep_updated = _parse_iso(str(dep_lane.get("updated_at") or ""))
        last_sync = _parse_iso(str(lane.get("last_sync_at") or ""))
        soft_risk = dep_updated > last_sync
    return {"dep_status": dep_status, "hard_blocked": hard_blocked, "soft_risk": soft_risk}


def _lane_report(
    project_root: str,
    lane: dict[str, Any],
    all_lanes: list[dict[str, Any]],
    lane_map: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    progress = _task_progress(project_root, str(lane.get("task_file") or ""))
    health = _lane_health(lane, lane_map)
    owner = get_task_owner(all_lanes, str(lane.get("task_file") or ""))
    report = dict(lane)
    report["task_progress"] = progress
    report["owner_lane"] = owner.get("lane_id") if owner else ""
    report.update(health)
    return report


def _selected_lanes(
    lanes: list[dict[str, Any]],
    show_all: bool,
    lane_id: str = "",
) -> list[dict[str, Any]]:
    if lane_id:
        return [lane for lane in lanes if lane.get("lane_id") == lane_id]
    if show_all:
        return list(lanes)
    return [lane for lane in lanes if lane.get("status") == "active"]


def _print_lane_list(lanes: list[dict[str, Any]]) -> int:
    if not lanes:
        print("No lanes found.")
        return 0
    print("Lanes:")
    for lane in lanes:
        dep_lane = lane.get("dep_lane") or "-"
        print(
            f"- {lane.get('lane_id')} [{lane.get('status')}] "
            f"task={lane.get('task_file')} branch={lane.get('branch')} "
            f"dep={lane.get('dep_type')}:{dep_lane}"
        )
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    project_root = os.path.realpath(args.project_root or os.getcwd())
    try:
        data = load_lanes(project_root)
        lanes = _selected_lanes(data.get("lanes") or [], args.all)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps({"lanes": lanes}, ensure_ascii=False, indent=2))
        return 0
    return _print_lane_list(lanes)


def _print_lane_status(reports: list[dict[str, Any]]) -> int:
    if not reports:
        print("No lanes found.")
        return 0
    for report in reports:
        lane_id = report.get("lane_id")
        progress = report.get("task_progress") or {}
        done = progress.get("done", 0)
        total = progress.get("total", 0)
        percent = progress.get("percent", 0)
        owner = report.get("owner_lane") or "-"
        dep = report.get("dep_lane") or "-"
        dep_status = report.get("dep_status")
        print(f"[{lane_id}] status={report.get('status')} owner={owner}")
        print(f"  task={report.get('task_file')} progress={done}/{total} ({percent}%)")
        print(f"  dep={report.get('dep_type')}:{dep} dep_status={dep_status}")
        if report.get("hard_blocked"):
            print("  hard_blocked=yes (upstream not closed)")
        if report.get("soft_risk"):
            print("  soft_risk=yes (upstream changed after last sync)")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    project_root = os.path.realpath(args.project_root or os.getcwd())
    try:
        data = load_lanes(project_root)
        lanes = data.get("lanes") or []
        selected = _selected_lanes(lanes, args.all, args.lane_id or "")
        if args.lane_id and not selected:
            print(f"ERROR: lane not found: {args.lane_id}", file=sys.stderr)
            return 1
        lane_map = {str(lane.get("lane_id")): lane for lane in lanes if lane.get("lane_id")}
        reports = [_lane_report(project_root, lane, lanes, lane_map) for lane in selected]
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps({"lanes": reports}, ensure_ascii=False, indent=2))
        return 0
    return _print_lane_status(reports)


def _resolve_sync_source(
    lane: dict[str, Any],
    lane_map: dict[str, dict[str, Any]],
    source_opt: str,
) -> str:
    dep_lane_id = str(lane.get("dep_lane") or "")
    dep_lane = lane_map.get(dep_lane_id) if dep_lane_id else None
    if source_opt == "main":
        return "main"
    if source_opt == "dep":
        if not dep_lane:
            raise ValueError("sync source dep requested but dep-lane is missing")
        return str(dep_lane.get("branch"))
    dep_type = str(lane.get("dep_type") or "none")
    if dep_type == "hard":
        if not dep_lane:
            raise ValueError("hard lane cannot sync from dep because dep-lane is missing")
        return str(dep_lane.get("branch"))
    if dep_type == "soft" and dep_lane:
        return str(dep_lane.get("branch"))
    return "main"


def _list_conflicts(project_root: str, worktree_path: str) -> list[str]:
    result = _run_git(
        project_root,
        ["diff", "--name-only", "--diff-filter=U"],
        cwd=worktree_path,
        check=False,
    )
    lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    return sorted(lines)


def _abort_sync(project_root: str, worktree_path: str, strategy: str) -> None:
    if strategy == "rebase":
        _run_git(project_root, ["rebase", "--abort"], cwd=worktree_path, check=False)
        return
    _run_git(project_root, ["merge", "--abort"], cwd=worktree_path, check=False)


def _run_sync(
    project_root: str,
    worktree_path: str,
    source_branch: str,
    strategy: str,
) -> tuple[bool, list[str], str]:
    if strategy == "rebase":
        result = _run_git(project_root, ["rebase", source_branch], cwd=worktree_path, check=False)
    else:
        result = _run_git(
            project_root,
            ["merge", "--no-edit", source_branch],
            cwd=worktree_path,
            check=False,
        )
    if result.returncode == 0:
        return True, [], ""
    conflicts = _list_conflicts(project_root, worktree_path)
    _abort_sync(project_root, worktree_path, strategy)
    detail = result.stderr.strip() or result.stdout.strip()
    return False, conflicts, detail


def _resolve_sync_target(
    project_root: str,
    lane_id: str,
    source_opt: str,
) -> tuple[str, str, str]:
    data = load_lanes(project_root)
    lanes = data.get("lanes") or []
    selected = _selected_lanes(lanes, True, lane_id)
    if not selected:
        raise ValueError(f"lane not found: {lane_id}")
    target = selected[0]
    if target.get("status") != "active":
        raise ValueError(f"lane is not active: {target.get('lane_id')}")
    lane_map = {str(item.get("lane_id")): item for item in lanes if item.get("lane_id")}
    source_branch = _resolve_sync_source(target, lane_map, source_opt)
    worktree_path = str(target.get("worktree_path") or "")
    if not os.path.isdir(worktree_path):
        raise FileNotFoundError(f"worktree path missing: {worktree_path}")
    return str(target.get("lane_id")), source_branch, worktree_path


def _persist_sync_result(project_root: str, lane_id: str, source_branch: str) -> dict[str, Any]:
    data = load_lanes(project_root)
    selected = _selected_lanes(data.get("lanes") or [], True, lane_id)
    if not selected:
        raise ValueError(f"lane not found after sync: {lane_id}")
    target = selected[0]
    if target.get("status") != "active":
        raise ValueError(f"lane is no longer active: {lane_id}")
    now = _now_iso()
    target["last_sync_from"] = source_branch
    target["last_sync_at"] = now
    target["updated_at"] = now
    save_lanes(project_root, data)
    return target


def cmd_sync(args: argparse.Namespace) -> int:
    project_root = os.path.realpath(args.project_root or os.getcwd())
    lock_path: str | None = None
    try:
        lock_path = acquire_lock(project_root, command="cf-lane sync")
        lane_id, source_branch, worktree_path = _resolve_sync_target(
            project_root,
            args.lane_id,
            args.from_source or "",
        )
        _release_lock_safely(lock_path)
        lock_path = None

        ok, conflicts, detail = _run_sync(project_root, worktree_path, source_branch, args.strategy)
        if not ok:
            if conflicts:
                print("ERROR: sync conflict files:", file=sys.stderr)
                for path in conflicts:
                    print(f"- {path}", file=sys.stderr)
            if detail:
                print(f"ERROR: {detail}", file=sys.stderr)
            print(
                "ERROR: sync aborted. Resolve conflicts, then rerun cf-lane sync.",
                file=sys.stderr,
            )
            return 1

        lock_path = acquire_lock(project_root, command="cf-lane sync")
        latest_lane = _persist_sync_result(project_root, lane_id, source_branch)
        print(f"lane_id: {latest_lane.get('lane_id')}")
        print(f"sync_from: {source_branch}")
        print(f"strategy: {args.strategy}")
        print("result: ok")
        return 0
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    finally:
        _release_lock_safely(lock_path)


def _task_statuses(project_root: str, task_file: str) -> list[str]:
    path = os.path.join(project_root, task_file)
    if not os.path.exists(path):
        raise FileNotFoundError(f"task file not found: {task_file}")
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()
    matches = re.findall(r"^- \*\*Status\*\*: ([^\n]+)$", content, flags=re.M)
    return [status.strip().lower() for status in matches]


def _task_done(project_root: str, task_file: str) -> bool:
    statuses = _task_statuses(project_root, task_file)
    return bool(statuses) and all(status == "done" for status in statuses)


def _run_validate(project_root: str) -> None:
    cmd_path = shutil.which("cf-validate")
    if not cmd_path:
        raise RuntimeError("cf-validate not found in PATH")
    result = subprocess.run([cmd_path], cwd=project_root, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip()
        raise RuntimeError(f"cf-validate failed: {detail}")


def _dep_lane_for_check(lane: dict[str, Any], lane_map: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    dep_lane_id = str(lane.get("dep_lane") or "")
    if not dep_lane_id:
        return None
    return lane_map.get(dep_lane_id)


def _verify_close_dependencies(
    lane: dict[str, Any],
    lane_map: dict[str, dict[str, Any]],
    accept_soft_risk: bool,
) -> None:
    dep_type = str(lane.get("dep_type") or "none")
    dep_lane = _dep_lane_for_check(lane, lane_map)
    if dep_type == "hard":
        if not dep_lane:
            raise ValueError("hard dependency lane is missing")
        if dep_lane.get("status") != "closed":
            raise ValueError(f"hard dependency not closed: {dep_lane.get('lane_id')}")
    if dep_type == "soft" and dep_lane and dep_lane.get("status") != "closed":
        if not accept_soft_risk:
            raise ValueError(
                "soft dependency not closed, use --accept-soft-risk to force close"
            )


def cmd_close(args: argparse.Namespace) -> int:
    project_root = os.path.realpath(args.project_root or os.getcwd())
    lock_path: str | None = None
    try:
        lock_path = acquire_lock(project_root, command="cf-lane close")
        data = load_lanes(project_root)
        lanes = data.get("lanes") or []
        selected = _selected_lanes(lanes, True, args.lane_id or "")
        if not selected:
            raise ValueError(f"lane not found: {args.lane_id}")
        target = selected[0]
        if target.get("status") != "active":
            raise ValueError(f"lane is not active: {target.get('lane_id')}")
        task_file = str(target.get("task_file") or "")
        if not _task_done(project_root, task_file):
            raise ValueError(f"task is not done: {task_file}")
        lane_map = {str(lane.get("lane_id")): lane for lane in lanes if lane.get("lane_id")}
        _verify_close_dependencies(target, lane_map, args.accept_soft_risk)
        _run_validate(project_root)
        if not args.keep_worktree:
            _run_git(
                project_root,
                ["worktree", "remove", str(target.get("worktree_path")), "--force"],
                check=True,
            )
        now = _now_iso()
        target["status"] = "closed"
        target["blocked_reason"] = ""
        target["updated_at"] = now
        save_lanes(project_root, data)
        print(f"lane_id: {target.get('lane_id')}")
        print("status: closed")
        print(f"worktree_removed: {str(not args.keep_worktree).lower()}")
        return 0
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    finally:
        _release_lock_safely(lock_path)


def _rollback_task_to_approved(project_root: str, task_file: str) -> None:
    path = os.path.join(project_root, task_file)
    if not os.path.exists(path):
        raise FileNotFoundError(f"task file not found: {task_file}")
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()
    updated = re.sub(r"^(- \*\*Lifecycle\*\*: ).+$", r"\1approved", content, flags=re.M)
    if updated == content:
        updated = re.sub(
            r"^(- \*\*Updated\*\*: .+)$",
            r"\1\n- **Lifecycle**: approved",
            updated,
            count=1,
            flags=re.M,
        )
    updated = re.sub(r"^(- \*\*Status\*\*: ).+$", r"\1draft", updated, flags=re.M)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    updated = re.sub(r"^(- \*\*Updated\*\*: ).+$", rf"\1{today}", updated, flags=re.M)
    with open(path, "w", encoding="utf-8") as f:
        f.write(updated)


def cmd_cancel(args: argparse.Namespace) -> int:
    project_root = os.path.realpath(args.project_root or os.getcwd())
    lock_path: str | None = None
    try:
        lock_path = acquire_lock(project_root, command="cf-lane cancel")
        data = load_lanes(project_root)
        lanes = data.get("lanes") or []
        selected = _selected_lanes(lanes, True, args.lane_id or "")
        if not selected:
            raise ValueError(f"lane not found: {args.lane_id}")
        target = selected[0]
        if target.get("status") != "active":
            raise ValueError(f"lane is not active: {target.get('lane_id')}")
        task_file = str(target.get("task_file") or "")
        if args.task_policy == "rollback":
            _rollback_task_to_approved(project_root, task_file)
        if not args.keep_worktree:
            _run_git(
                project_root,
                ["worktree", "remove", str(target.get("worktree_path")), "--force"],
                check=True,
            )
        now = _now_iso()
        target["status"] = "cancelled"
        target["blocked_reason"] = "cancelled"
        target["updated_at"] = now
        save_lanes(project_root, data)
        print(f"lane_id: {target.get('lane_id')}")
        print("status: cancelled")
        print(f"task_policy: {args.task_policy}")
        print(f"worktree_removed: {str(not args.keep_worktree).lower()}")
        return 0
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    finally:
        _release_lock_safely(lock_path)


def _lane_for_check_merge(
    project_root: str,
    lanes: list[dict[str, Any]],
    lane_id: str,
) -> dict[str, Any]:
    if lane_id:
        selected = _selected_lanes(lanes, True, lane_id)
        if not selected:
            raise ValueError(f"lane not found: {lane_id}")
        return selected[0]
    current_branch = _run_git(project_root, ["rev-parse", "--abbrev-ref", "HEAD"], check=True).stdout.strip()
    matches = [
        lane
        for lane in lanes
        if lane.get("status") == "active" and lane.get("branch") == current_branch
    ]
    if not matches:
        raise ValueError(f"no active lane bound to current branch: {current_branch}")
    return matches[0]


def _hard_dep_violations(
    lane: dict[str, Any],
    lane_map: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    violations: list[dict[str, Any]] = []
    visited: set[str] = set()
    current = lane
    while str(current.get("dep_type") or "none") == "hard":
        dep_lane_id = str(current.get("dep_lane") or "")
        if not dep_lane_id:
            violations.append(
                {
                    "code": "hard_dep_missing",
                    "message": f"hard dependency lane missing for {current.get('lane_id')}",
                    "details": {"lane_id": current.get("lane_id")},
                }
            )
            break
        if dep_lane_id in visited:
            break
        visited.add(dep_lane_id)
        dep = lane_map.get(dep_lane_id)
        if not dep:
            violations.append(
                {
                    "code": "hard_dep_missing",
                    "message": f"hard dependency lane not found: {dep_lane_id}",
                    "details": {"lane_id": current.get("lane_id"), "dep_lane": dep_lane_id},
                }
            )
            break
        if dep.get("status") != "closed":
            violations.append(
                {
                    "code": "hard_dep_not_closed",
                    "message": f"hard dependency lane not closed: {dep_lane_id}",
                    "details": {
                        "lane_id": current.get("lane_id"),
                        "dep_lane": dep_lane_id,
                        "dep_status": dep.get("status"),
                    },
                }
            )
            break
        current = dep
    return violations


def _changed_files_for_lane(project_root: str, lane: dict[str, Any]) -> list[str]:
    worktree_path = str(lane.get("worktree_path") or "")
    if not os.path.isdir(worktree_path):
        raise FileNotFoundError(f"worktree path missing: {worktree_path}")
    base_branch = str(lane.get("base_branch") or "main")
    result = _run_git(
        project_root,
        ["diff", "--name-only", f"{base_branch}...HEAD"],
        cwd=worktree_path,
        check=False,
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip()
        raise RuntimeError(f"failed to inspect lane diff: {detail}")
    files = [line.strip().replace("\\", "/") for line in result.stdout.splitlines() if line.strip()]
    return sorted(set(files))


def _ownership_violations(
    lane: dict[str, Any],
    lanes: list[dict[str, Any]],
    changed_files: list[str],
) -> list[dict[str, Any]]:
    lane_id = str(lane.get("lane_id") or "")
    violations: list[dict[str, Any]] = []
    for path in changed_files:
        if not path.startswith(".code-flow/tasks/"):
            continue
        if "/archived/" in path or not path.endswith(".md"):
            continue
        owner = get_task_owner(lanes, path)
        if not owner:
            continue
        owner_lane_id = str(owner.get("lane_id") or "")
        if owner_lane_id == lane_id:
            continue
        violations.append(
            {
                "code": "task_ownership_violation",
                "message": f"task file owned by another active lane: {path}",
                "details": {
                    "lane_id": lane_id,
                    "owner_lane": owner_lane_id,
                    "task_file": path,
                },
            }
        )
    return violations


def _print_check_merge_result(result: dict[str, Any]) -> int:
    if result.get("ok"):
        print("check-merge: pass")
        print(f"lane_id: {result.get('lane_id')}")
        return 0
    print("check-merge: fail")
    for item in result.get("violations") or []:
        print(f"- [{item.get('code')}] {item.get('message')}")
    return 1


def cmd_check_merge(args: argparse.Namespace) -> int:
    project_root = os.path.realpath(args.project_root or os.getcwd())
    try:
        data = load_lanes(project_root)
        lanes = data.get("lanes") or []
        lane_map = {str(lane.get("lane_id")): lane for lane in lanes if lane.get("lane_id")}
        lane = _lane_for_check_merge(project_root, lanes, args.lane or "")
        violations: list[dict[str, Any]] = []
        violations.extend(_hard_dep_violations(lane, lane_map))
        changed = _changed_files_for_lane(project_root, lane)
        violations.extend(_ownership_violations(lane, lanes, changed))
        result = {"ok": not violations, "lane_id": lane.get("lane_id"), "violations": violations}
    except Exception as exc:
        result = {
            "ok": False,
            "lane_id": args.lane or "",
            "violations": [{"code": "check_error", "message": str(exc), "details": {}}],
        }
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result.get("ok") else 1
    return _print_check_merge_result(result)


def _check_triplet(lanes: list[dict[str, Any]]) -> dict[str, Any]:
    missing = []
    for lane in lanes:
        lane_id = str(lane.get("lane_id") or "")
        required = {
            "branch": lane.get("branch"),
            "worktree_path": lane.get("worktree_path"),
            "task_file": lane.get("task_file"),
        }
        absent = [key for key, value in required.items() if not isinstance(value, str) or not value.strip()]
        if absent:
            missing.append({"lane_id": lane_id, "missing": absent})
    return {"name": "triplet", "ok": not missing, "issues": missing}


def _check_active_entities(project_root: str, lanes: list[dict[str, Any]], ci_mode: bool) -> dict[str, Any]:
    issues = []
    for lane in lanes:
        if lane.get("status") != "active":
            continue
        lane_id = str(lane.get("lane_id") or "")
        branch = str(lane.get("branch") or "")
        if not branch or not _branch_exists(project_root, branch):
            issues.append({"lane_id": lane_id, "problem": "missing_branch", "branch": branch})
        if ci_mode:
            continue
        wt_path = str(lane.get("worktree_path") or "")
        if not wt_path or not os.path.isdir(wt_path):
            issues.append({"lane_id": lane_id, "problem": "missing_worktree", "worktree_path": wt_path})
    return {"name": "active_entities", "ok": not issues, "issues": issues}


def _check_task_exclusive(lanes: list[dict[str, Any]]) -> dict[str, Any]:
    owner_by_task: dict[str, str] = {}
    dup = []
    for lane in lanes:
        if lane.get("status") != "active":
            continue
        task_file = str(lane.get("task_file") or "")
        lane_id = str(lane.get("lane_id") or "")
        if not task_file:
            continue
        owner = owner_by_task.get(task_file)
        if owner and owner != lane_id:
            dup.append({"task_file": task_file, "owners": sorted([owner, lane_id])})
            continue
        owner_by_task[task_file] = lane_id
    return {"name": "task_exclusive", "ok": not dup, "issues": dup}


def _check_dag(lanes: list[dict[str, Any]]) -> dict[str, Any]:
    graph = build_dep_graph(lanes)
    cycle = detect_cycle(graph)
    return {"name": "dependency_dag", "ok": not cycle, "issues": cycle}


def _collect_stale_locks(project_root: str, stale_seconds: float = 120.0) -> list[str]:
    lock_dir = locks_dir_path(project_root)
    stale = []
    try:
        names = os.listdir(lock_dir)
    except OSError:
        return stale
    for name in names:
        path = os.path.join(lock_dir, name)
        if not os.path.isfile(path):
            continue
        if is_stale_lock(path, stale_seconds):
            stale.append(path)
    return sorted(stale)


def _check_stale_lock(project_root: str) -> dict[str, Any]:
    stale = _collect_stale_locks(project_root)
    return {"name": "stale_lock", "ok": not stale, "issues": stale}


def _check_ownership(project_root: str, lanes: list[dict[str, Any]], ci_mode: bool) -> dict[str, Any]:
    issues = []
    active = [lane for lane in lanes if lane.get("status") == "active"]
    for lane in active:
        lane_id = str(lane.get("lane_id") or "")
        wt_path = str(lane.get("worktree_path") or "")
        if not os.path.isdir(wt_path):
            if ci_mode:
                continue
            issues.append({"lane_id": lane_id, "problem": "missing_worktree"})
            continue
        try:
            changed = _changed_files_for_lane(project_root, lane)
            violations = _ownership_violations(lane, lanes, changed)
            issues.extend(violations)
        except Exception as exc:
            issues.append({"lane_id": lane_id, "problem": "ownership_check_error", "message": str(exc)})
    return {"name": "ownership", "ok": not issues, "issues": issues}


def _collect_doctor_checks(project_root: str, lanes: list[dict[str, Any]], ci_mode: bool) -> list[dict[str, Any]]:
    return [
        {"name": "schema", "ok": True, "issues": []},
        _check_triplet(lanes),
        _check_active_entities(project_root, lanes, ci_mode),
        _check_task_exclusive(lanes),
        _check_dag(lanes),
        _check_stale_lock(project_root),
        _check_ownership(project_root, lanes, ci_mode),
    ]


def _fix_stale_locks(project_root: str) -> list[dict[str, Any]]:
    fixed = []
    stale = _collect_stale_locks(project_root)
    for path in stale:
        try:
            os.remove(path)
            fixed.append({"action": "remove_stale_lock", "path": path})
        except OSError as exc:
            fixed.append({"action": "remove_stale_lock_failed", "path": path, "error": str(exc)})
    return fixed


def _fix_orphan_lanes(project_root: str, lanes: list[dict[str, Any]], ci_mode: bool) -> list[dict[str, Any]]:
    fixed = []
    now = _now_iso()
    for lane in lanes:
        if lane.get("status") != "active":
            continue
        lane_id = str(lane.get("lane_id") or "")
        branch = str(lane.get("branch") or "")
        wt_path = str(lane.get("worktree_path") or "")
        missing = []
        if not branch or not _branch_exists(project_root, branch):
            missing.append("branch")
        if not ci_mode and (not wt_path or not os.path.isdir(wt_path)):
            missing.append("worktree")
        if not missing:
            continue
        lane["status"] = "cancelled"
        lane["blocked_reason"] = f"orphan:{','.join(missing)}"
        lane["updated_at"] = now
        fixed.append({"action": "mark_orphan_cancelled", "lane_id": lane_id, "missing": missing})
    return fixed


def _repair_lane_metadata(lanes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    fixed = []
    now = _now_iso()
    for lane in lanes:
        lane_id = str(lane.get("lane_id") or "")
        updates = []
        if not str(lane.get("updated_at") or ""):
            lane["updated_at"] = now
            updates.append("updated_at")
        if not str(lane.get("last_sync_from") or ""):
            lane["last_sync_from"] = str(lane.get("base_branch") or "main")
            updates.append("last_sync_from")
        if not str(lane.get("last_sync_at") or ""):
            lane["last_sync_at"] = str(lane.get("created_at") or now)
            updates.append("last_sync_at")
        if updates:
            fixed.append({"action": "repair_metadata", "lane_id": lane_id, "fields": updates})
    return fixed


def _apply_doctor_fix(project_root: str, data: dict[str, Any], ci_mode: bool) -> list[dict[str, Any]]:
    lanes = data.get("lanes") or []
    fixes: list[dict[str, Any]] = []
    fixes.extend(_fix_stale_locks(project_root))
    fixes.extend(_fix_orphan_lanes(project_root, lanes, ci_mode))
    fixes.extend(_repair_lane_metadata(lanes))
    return fixes


def _print_doctor(result: dict[str, Any]) -> int:
    print(f"doctor: {'pass' if result.get('ok') else 'fail'}")
    print(f"ci_mode: {str(result.get('ci_mode', False)).lower()}")
    for check in result.get("checks") or []:
        status = "ok" if check.get("ok") else "fail"
        issues = check.get("issues") or []
        print(f"- {check.get('name')}: {status} (issues={len(issues)})")
    fixes = result.get("fixes") or []
    if fixes:
        print("fixes:")
        for item in fixes:
            print(f"- {item.get('action')}")
    return 0 if result.get("ok") else 1


def _emit_doctor_result(as_json: bool, result: dict[str, Any]) -> int:
    if as_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result.get("ok") else 1
    return _print_doctor(result)


def cmd_doctor(args: argparse.Namespace) -> int:
    project_root = os.path.realpath(args.project_root or os.getcwd())
    ci_mode = bool(args.ci)
    lock_path: str | None = None
    result: dict[str, Any] = {"ci_mode": ci_mode, "checks": [], "fixes": []}
    try:
        lock_path = acquire_lock(project_root, command="cf-lane doctor")
        try:
            data = load_lanes(project_root)
        except LaneSchemaError as exc:
            result["checks"] = [{"name": "schema", "ok": False, "issues": [str(exc)]}]
            result["ok"] = False
            return _emit_doctor_result(args.json, result)

        lanes = data.get("lanes") or []
        checks = _collect_doctor_checks(project_root, lanes, ci_mode)
        fixes: list[dict[str, Any]] = []
        if args.fix:
            fixes = _apply_doctor_fix(project_root, data, ci_mode)
            if fixes:
                save_lanes(project_root, data)
            refreshed = load_lanes(project_root)
            checks = _collect_doctor_checks(project_root, refreshed.get("lanes") or [], ci_mode)
        result["checks"] = checks
        result["fixes"] = fixes
        result["ok"] = all(bool(check.get("ok")) for check in checks)
        return _emit_doctor_result(args.json, result)
    except Exception as exc:
        result["checks"] = [{"name": "doctor", "ok": False, "issues": [str(exc)]}]
        result["ok"] = False
        return _emit_doctor_result(args.json, result)
    finally:
        _release_lock_safely(lock_path)


def _new_candidate_mode(project_root: str) -> int:
    lock_path: str | None = None
    try:
        lock_path = acquire_lock(project_root, command="cf-lane new")
        data = load_lanes(project_root)
        return _print_no_arg_help(project_root, data.get("lanes") or [])
    finally:
        _release_lock_safely(lock_path)


def _prepare_new_request(
    project_root: str,
    args: argparse.Namespace,
    lanes: list[dict[str, Any]],
) -> dict[str, Any]:
    task_rel = resolve_task_file(project_root, args.task_file)
    owner = get_task_owner(lanes, task_rel)
    if owner:
        raise ValueError(f"task already bound by active lane: {owner.get('lane_id')}")
    dep_type = _dep_type(args.dep_type, args.dep_lane)
    dep_lane = _find_dep_lane(lanes, args.dep_lane) if args.dep_lane else None
    if args.dep_lane and not dep_lane:
        raise ValueError(f"dep-lane not found or not active: {args.dep_lane}")
    if dep_type in {"hard", "soft"} and not dep_lane:
        raise ValueError(f"dep-type {dep_type} requires --dep-lane")
    if dep_type == "none" and args.dep_lane:
        raise ValueError("dep-type none cannot be used with --dep-lane")
    lane_id = _lane_id(task_rel, lanes)
    edge = (lane_id, str(dep_lane.get("lane_id"))) if dep_lane else None
    cycle = detect_cycle(build_dep_graph(lanes), edge)
    if cycle:
        raise ValueError(f"dependency cycle detected: {' -> '.join(cycle)}")
    branch = args.branch or f"feat/{_task_slug(task_rel)}"
    if _branch_exists(project_root, branch):
        raise ValueError(f"branch already exists: {branch}")
    wt_path = _worktree_path(project_root, args.worktree, task_rel)
    if _is_path_conflict(wt_path):
        raise ValueError(f"worktree path conflict: {wt_path}")
    return {
        "lane_id": lane_id,
        "task_rel": task_rel,
        "dep_type": dep_type,
        "dep_lane": dep_lane,
        "branch": branch,
        "wt_path": wt_path,
        "base": _base_branch(dep_type, dep_lane),
    }


def _execute_new_create(
    project_root: str,
    request: dict[str, Any],
    task_sync: str,
) -> tuple[dict[str, Any], str]:
    _run_git(
        project_root,
        ["worktree", "add", "-b", request["branch"], request["wt_path"], request["base"]],
        check=True,
    )
    if task_sync == "head-only":
        sync_task_head_only(project_root, request["task_rel"])
        sync_mode = "head-only"
    else:
        sync_mode = sync_task_auto(
            project_root,
            request["task_rel"],
            request["wt_path"],
            request["branch"],
        )
    now = _now_iso()
    lane = {
        "lane_id": request["lane_id"],
        "task_file": request["task_rel"],
        "branch": request["branch"],
        "worktree_path": request["wt_path"],
        "dep_lane": request["dep_lane"].get("lane_id") if request["dep_lane"] else None,
        "dep_type": request["dep_type"],
        "base_branch": request["base"],
        "status": "active",
        "last_sync_from": request["base"],
        "last_sync_at": now,
        "blocked_reason": "",
        "created_at": now,
        "updated_at": now,
    }
    return lane, sync_mode


def _print_new_result(
    request: dict[str, Any],
    sync_mode: str,
    hook_status: str,
    hook_manual: str,
    task_start: str,
) -> int:
    print(f"lane_id: {request['lane_id']}")
    print(f"task_file: {request['task_rel']}")
    print(f"branch: {request['branch']}")
    print(f"worktree_path: {request['wt_path']}")
    print(f"dep_type: {request['dep_type']}")
    print(f"base_branch: {request['base']}")
    print(f"task_sync: {sync_mode}")
    print(f"hooks_install: {hook_status}")
    if hook_manual:
        print(f"hooks_manual: {hook_manual}")
    print(f"cf-task-start: {task_start}")
    return 0


def cmd_new(args: argparse.Namespace) -> int:
    project_root = os.path.realpath(args.project_root or os.getcwd())
    if not args.task_file:
        try:
            return _new_candidate_mode(project_root)
        except Exception as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 1

    lock_path: str | None = None
    request: dict[str, Any] = {}
    created_worktree = False
    try:
        lock_path = acquire_lock(project_root, command="cf-lane new")
        data = load_lanes(project_root)
        request = _prepare_new_request(project_root, args, data.get("lanes") or [])
        lane, sync_mode = _execute_new_create(project_root, request, args.task_sync)
        created_worktree = True
        data["lanes"].append(lane)
        save_lanes(project_root, data)
        _release_lock_safely(lock_path)
        lock_path = None
        hook_manual = ""
        try:
            hook_status = install_hooks(project_root)
        except Exception as hook_exc:
            hook_status = f"failed ({hook_exc})"
            hook_manual = "git config core.hooksPath .code-flow/hooks && chmod +x .code-flow/hooks/pre-push"
            print(f"WARNING: hooks install failed, manual install: {hook_manual}", file=sys.stderr)
        task_start = _trigger_task_start(project_root, request["task_rel"])
        return _print_new_result(request, sync_mode, hook_status, hook_manual, task_start)
    except Exception as exc:
        branch = str(request.get("branch") or "")
        wt_path = str(request.get("wt_path") or "")
        if branch and wt_path:
            for msg in _cleanup_new(project_root, wt_path, branch, created_worktree):
                print(f"WARNING: {msg}", file=sys.stderr)
        doctor_fix = _trigger_doctor_fix(project_root)
        if doctor_fix != "ok":
            print(f"WARNING: doctor --fix {doctor_fix}", file=sys.stderr)
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    finally:
        _release_lock_safely(lock_path)


def _add_parser_new(sub: Any) -> None:
    parser = sub.add_parser("new")
    parser.add_argument("task_file", nargs="?")
    parser.add_argument("--dep-lane", default="")
    parser.add_argument("--dep-type", choices=["none", "soft", "hard"], default="")
    parser.add_argument("--branch", default="")
    parser.add_argument("--worktree", default="")
    parser.add_argument("--task-sync", choices=["auto", "head-only"], default="auto")
    parser.add_argument("--yes", action="store_true")
    parser.set_defaults(handler=cmd_new)


def _add_parser_list(sub: Any) -> None:
    parser = sub.add_parser("list")
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.set_defaults(handler=cmd_list)


def _add_parser_status(sub: Any) -> None:
    parser = sub.add_parser("status")
    parser.add_argument("lane_id", nargs="?")
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.set_defaults(handler=cmd_status)


def _add_parser_sync(sub: Any) -> None:
    parser = sub.add_parser("sync")
    parser.add_argument("lane_id")
    parser.add_argument("--from", dest="from_source", choices=["main", "dep"], default="")
    parser.add_argument("--strategy", choices=["merge", "rebase"], default="merge")
    parser.add_argument("--yes", action="store_true")
    parser.set_defaults(handler=cmd_sync)


def _add_parser_close(sub: Any) -> None:
    parser = sub.add_parser("close")
    parser.add_argument("lane_id")
    parser.add_argument("--keep-worktree", action="store_true")
    parser.add_argument("--accept-soft-risk", action="store_true")
    parser.add_argument("--yes", action="store_true")
    parser.set_defaults(handler=cmd_close)


def _add_parser_cancel(sub: Any) -> None:
    parser = sub.add_parser("cancel")
    parser.add_argument("lane_id")
    parser.add_argument("--keep-worktree", action="store_true")
    parser.add_argument("--task-policy", choices=["keep", "rollback"], default="keep")
    parser.add_argument("--yes", action="store_true")
    parser.set_defaults(handler=cmd_cancel)


def _add_parser_check_merge(sub: Any) -> None:
    parser = sub.add_parser("check-merge")
    parser.add_argument("--lane", default="")
    parser.add_argument("--json", action="store_true")
    parser.set_defaults(handler=cmd_check_merge)


def _add_parser_doctor(sub: Any) -> None:
    parser = sub.add_parser("doctor")
    parser.add_argument("--fix", action="store_true")
    parser.add_argument("--ci", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.set_defaults(handler=cmd_doctor)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="cf-lane")
    parser.add_argument("--project-root", default="")
    sub = parser.add_subparsers(dest="subcommand")
    _add_parser_new(sub)
    _add_parser_list(sub)
    _add_parser_status(sub)
    _add_parser_sync(sub)
    _add_parser_close(sub)
    _add_parser_cancel(sub)
    _add_parser_check_merge(sub)
    _add_parser_doctor(sub)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "subcommand", None):
        parser.print_help()
        return 0
    handler = getattr(args, "handler", None)
    if not handler:
        parser.print_help()
        return 1
    return int(handler(args))


if __name__ == "__main__":
    raise SystemExit(main())
