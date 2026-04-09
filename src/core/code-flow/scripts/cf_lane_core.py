#!/usr/bin/env python3
"""Core helpers for lane registry storage and locking."""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import time
import hashlib
from typing import Any

LANES_SCHEMA_VERSION = 1
_DEFAULT_TIMEOUT_SECONDS = 5.0
_DEFAULT_STALE_SECONDS = 120.0
_POLL_INTERVAL_SECONDS = 0.05


class LaneSchemaError(ValueError):
    """Raised when lanes.json does not match expected schema."""


def run_git(
    project_root: str,
    args: list[str],
    cwd: str | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    cmd = ["git", *args]
    run_cwd = cwd or project_root
    result = subprocess.run(cmd, cwd=run_cwd, capture_output=True, text=True, check=False)
    if check and result.returncode != 0:
        stderr = result.stderr.strip()
        raise RuntimeError(f"git command failed: {' '.join(args)} :: {stderr}")
    return result


def _run_git(project_root: str, args: list[str], check: bool = True) -> subprocess.CompletedProcess[str]:
    return run_git(project_root, args, check=check)


def _run_git_common_dir(project_root: str) -> str:
    result = _run_git(project_root, ["rev-parse", "--git-common-dir"], check=False)
    common_dir = result.stdout.strip()
    if result.returncode != 0 or not common_dir:
        stderr = result.stderr.strip()
        raise RuntimeError(f"failed to resolve git common dir: {stderr}")
    if os.path.isabs(common_dir):
        return common_dir
    return os.path.normpath(os.path.join(project_root, common_dir))


def _run_git_top_level(project_root: str) -> str:
    result = _run_git(project_root, ["rev-parse", "--show-toplevel"], check=False)
    top = result.stdout.strip()
    if result.returncode != 0 or not top:
        stderr = result.stderr.strip()
        raise RuntimeError(f"failed to resolve git top-level: {stderr}")
    return os.path.realpath(top)


def resolve_common_dir(project_root: str) -> str:
    """Resolve and create the shared code-flow directory in git common dir."""
    git_common_dir = _run_git_common_dir(project_root)
    lane_common_dir = os.path.join(git_common_dir, "code-flow")
    os.makedirs(lane_common_dir, exist_ok=True)
    return lane_common_dir


def compute_worktree_id(project_root: str) -> str:
    top = _run_git_top_level(project_root)
    digest = hashlib.sha1(top.encode("utf-8")).hexdigest()
    return digest[:12]


def resolve_inject_state_dir(project_root: str, worktree_id: str = "") -> str:
    wt_id = worktree_id or compute_worktree_id(project_root)
    base = os.path.join(resolve_common_dir(project_root), "inject-states", wt_id)
    os.makedirs(base, exist_ok=True)
    return base


def inject_state_file_path(
    project_root: str,
    session_id: str,
    worktree_id: str = "",
) -> str:
    sid = str(session_id or "").strip()
    if not sid:
        raise ValueError("session_id is required")
    return os.path.join(resolve_inject_state_dir(project_root, worktree_id), f"{sid}.json")


def legacy_inject_state_path(project_root: str) -> str:
    return os.path.join(project_root, ".code-flow", ".inject-state")


def lanes_file_path(project_root: str) -> str:
    return os.path.join(resolve_common_dir(project_root), "lanes.json")


def locks_dir_path(project_root: str) -> str:
    lock_dir = os.path.join(resolve_common_dir(project_root), "locks")
    os.makedirs(lock_dir, exist_ok=True)
    return lock_dir


def _empty_registry() -> dict[str, Any]:
    return {"version": LANES_SCHEMA_VERSION, "lanes": []}


def _is_optional_string(value: Any) -> bool:
    return value is None or isinstance(value, str)


def _validate_lane(lane: Any) -> None:
    if not isinstance(lane, dict):
        raise LaneSchemaError("lane item must be an object")
    required_fields = {
        "lane_id": str,
        "task_file": str,
        "branch": str,
        "worktree_path": str,
        "dep_type": str,
        "base_branch": str,
        "status": str,
        "last_sync_from": str,
        "last_sync_at": str,
        "blocked_reason": str,
        "created_at": str,
        "updated_at": str,
    }
    for field, expected_type in required_fields.items():
        if field not in lane:
            raise LaneSchemaError(f"lane missing required field: {field}")
        if not isinstance(lane[field], expected_type):
            raise LaneSchemaError(f"lane field {field} must be {expected_type.__name__}")
    if "dep_lane" not in lane:
        raise LaneSchemaError("lane missing required field: dep_lane")
    if not _is_optional_string(lane["dep_lane"]):
        raise LaneSchemaError("lane field dep_lane must be string or null")


def validate_registry(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise LaneSchemaError("lanes registry must be an object")
    version = payload.get("version")
    if version != LANES_SCHEMA_VERSION:
        raise LaneSchemaError(
            f"unsupported lanes schema version: {version}, expected {LANES_SCHEMA_VERSION}"
        )
    lanes = payload.get("lanes")
    if not isinstance(lanes, list):
        raise LaneSchemaError("lanes field must be a list")
    seen_ids: set[str] = set()
    for lane in lanes:
        _validate_lane(lane)
        lane_id = lane["lane_id"]
        if lane_id in seen_ids:
            raise LaneSchemaError(f"duplicated lane_id: {lane_id}")
        seen_ids.add(lane_id)
    return payload


def load_lanes(project_root: str) -> dict[str, Any]:
    path = lanes_file_path(project_root)
    if not os.path.exists(path):
        return _empty_registry()
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return validate_registry(data)


def _write_json(path: str, payload: dict[str, Any]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2, sort_keys=True)


def save_lanes(project_root: str, payload: dict[str, Any]) -> None:
    validated = validate_registry(payload)
    path = lanes_file_path(project_root)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp_path = f"{path}.tmp.{os.getpid()}"
    try:
        _write_json(tmp_path, validated)
        os.replace(tmp_path, path)
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)


def _lock_payload(command: str) -> dict[str, Any]:
    return {
        "pid": os.getpid(),
        "host": socket.gethostname(),
        "start_at": time.time(),
        "command": command,
    }


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def _load_lock(path: str) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise LaneSchemaError("lock payload must be an object")
    return data


def _state_pid(payload: dict[str, Any], default_pid: int) -> int:
    raw_pid = payload.get("pid")
    if isinstance(raw_pid, int):
        return raw_pid
    if isinstance(raw_pid, str) and raw_pid.isdigit():
        return int(raw_pid)
    sid = payload.get("session_id")
    if isinstance(sid, str) and sid.isdigit():
        return int(sid)
    return default_pid


def gc_inject_states(
    project_root: str,
    ttl_seconds: float = 24 * 3600,
    now_ts: float | None = None,
) -> list[str]:
    base = os.path.join(resolve_common_dir(project_root), "inject-states")
    if not os.path.isdir(base):
        return []
    now = now_ts if now_ts is not None else time.time()
    removed: list[str] = []
    for root, _, files in os.walk(base):
        for name in files:
            if not name.endswith(".json"):
                continue
            path = os.path.join(root, name)
            try:
                with open(path, "r", encoding="utf-8") as f:
                    payload = json.load(f)
            except (OSError, json.JSONDecodeError):
                continue
            if not isinstance(payload, dict):
                continue
            start_at = payload.get("start_at")
            if isinstance(start_at, (int, float)):
                created = float(start_at)
            else:
                try:
                    created = os.path.getmtime(path)
                except OSError:
                    continue
            age = now - created
            if age <= ttl_seconds:
                continue
            pid = _state_pid(payload, 0)
            if _pid_alive(pid):
                continue
            try:
                os.remove(path)
                removed.append(path)
            except OSError:
                continue
    return sorted(removed)


def is_stale_lock(lock_path: str, stale_seconds: float) -> bool:
    if not os.path.exists(lock_path):
        return False
    try:
        lock_data = _load_lock(lock_path)
    except (json.JSONDecodeError, OSError, LaneSchemaError):
        return True
    start_at = float(lock_data.get("start_at", 0.0))
    pid = int(lock_data.get("pid", 0))
    age = time.time() - start_at
    if age <= stale_seconds:
        return False
    return not _pid_alive(pid)


def _try_acquire(lock_path: str, command: str) -> bool:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    try:
        fd = os.open(lock_path, flags, 0o644)
    except FileExistsError:
        return False
    try:
        payload = _lock_payload(command)
        os.write(fd, json.dumps(payload, ensure_ascii=False).encode("utf-8"))
    finally:
        os.close(fd)
    return True


def acquire_lock(
    project_root: str,
    lock_name: str = "lanes.lock",
    timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS,
    stale_seconds: float = _DEFAULT_STALE_SECONDS,
    command: str = "",
) -> str:
    lock_path = os.path.join(locks_dir_path(project_root), lock_name)
    deadline = time.time() + timeout_seconds
    while time.time() <= deadline:
        if _try_acquire(lock_path, command):
            return lock_path
        if is_stale_lock(lock_path, stale_seconds):
            try:
                os.remove(lock_path)
            except FileNotFoundError:
                pass
            continue
        time.sleep(_POLL_INTERVAL_SECONDS)
    raise TimeoutError(f"failed to acquire lock within {timeout_seconds}s: {lock_path}")


def release_lock(lock_path: str) -> None:
    if not os.path.exists(lock_path):
        return
    lock_data = _load_lock(lock_path)
    owner_pid = int(lock_data.get("pid", 0))
    if owner_pid not in {0, os.getpid()}:
        raise RuntimeError(
            f"cannot release lock owned by another pid: {owner_pid} (self={os.getpid()})"
        )
    os.remove(lock_path)


def find_lane(payload: dict[str, Any], lane_id: str) -> dict[str, Any] | None:
    lanes = payload.get("lanes")
    if not isinstance(lanes, list):
        return None
    for lane in lanes:
        if lane.get("lane_id") == lane_id:
            return lane
    return None


def find_lane_by_task(payload: dict[str, Any], task_file: str) -> dict[str, Any] | None:
    lanes = payload.get("lanes")
    if not isinstance(lanes, list):
        return None
    for lane in lanes:
        if lane.get("task_file") == task_file:
            return lane
    return None


def build_dep_graph(lanes: list[dict[str, Any]]) -> dict[str, set[str]]:
    graph: dict[str, set[str]] = {}
    for lane in lanes:
        lane_id = lane.get("lane_id")
        if not isinstance(lane_id, str) or not lane_id:
            continue
        graph.setdefault(lane_id, set())
        dep_lane = lane.get("dep_lane")
        dep_type = lane.get("dep_type")
        if isinstance(dep_lane, str) and dep_lane and dep_type in {"soft", "hard"}:
            graph[lane_id].add(dep_lane)
            graph.setdefault(dep_lane, set())
    return graph


def _walk_cycle(
    node: str,
    graph: dict[str, set[str]],
    color: dict[str, int],
    stack: list[str],
) -> list[str]:
    color[node] = 1
    stack.append(node)
    for dep in sorted(graph.get(node, set())):
        dep_color = color.get(dep, 0)
        if dep_color == 0:
            cycle = _walk_cycle(dep, graph, color, stack)
            if cycle:
                return cycle
        elif dep_color == 1:
            start = stack.index(dep)
            return stack[start:] + [dep]
    stack.pop()
    color[node] = 2
    return []


def detect_cycle(graph: dict[str, set[str]], new_edge: tuple[str, str] | None = None) -> list[str]:
    graph_copy = {k: set(v) for k, v in graph.items()}
    if new_edge:
        src, dst = new_edge
        graph_copy.setdefault(src, set()).add(dst)
        graph_copy.setdefault(dst, set())
    color: dict[str, int] = {}
    for node in sorted(graph_copy.keys()):
        if color.get(node, 0) != 0:
            continue
        cycle = _walk_cycle(node, graph_copy, color, [])
        if cycle:
            return cycle
    return []


def topological_sort(graph: dict[str, set[str]]) -> list[str]:
    indegree = {node: len(deps) for node, deps in graph.items()}
    reverse: dict[str, set[str]] = {node: set() for node in graph}
    for node, deps in graph.items():
        for dep in deps:
            reverse.setdefault(dep, set()).add(node)
            indegree.setdefault(dep, 0)
    queue = sorted([node for node, deg in indegree.items() if deg == 0])
    ordered: list[str] = []
    while queue:
        node = queue.pop(0)
        ordered.append(node)
        for child in sorted(reverse.get(node, set())):
            indegree[child] -= 1
            if indegree[child] == 0:
                queue.append(child)
                queue.sort()
    if len(ordered) != len(indegree):
        raise ValueError("dependency graph contains cycle")
    return ordered


def get_task_owner(lanes: list[dict[str, Any]], task_file: str) -> dict[str, Any] | None:
    for lane in lanes:
        if lane.get("task_file") != task_file:
            continue
        if lane.get("status") == "active":
            return lane
    return None


def check_task_in_head(project_root: str, task_file: str) -> bool:
    result = _run_git(project_root, ["cat-file", "-e", f"HEAD:{task_file}"], check=False)
    return result.returncode == 0


def check_task_dirty(project_root: str, task_file: str) -> bool:
    result = _run_git(project_root, ["status", "--porcelain", "--", task_file], check=True)
    return bool(result.stdout.strip())


def sync_task_head_only(project_root: str, task_file: str) -> None:
    if not check_task_in_head(project_root, task_file):
        raise FileNotFoundError(f"task not found in HEAD: {task_file}")


def _has_staged_changes(project_root: str) -> bool:
    result = _run_git(project_root, ["diff", "--cached", "--quiet"], check=False)
    if result.returncode not in {0, 1}:
        stderr = result.stderr.strip()
        raise RuntimeError(f"failed to inspect staged changes: {stderr}")
    return result.returncode == 1


def _copy_task_file(src_root: str, dst_root: str, task_file: str) -> None:
    src_path = os.path.join(src_root, task_file)
    dst_path = os.path.join(dst_root, task_file)
    if not os.path.exists(src_path):
        raise FileNotFoundError(f"task source file does not exist: {task_file}")
    os.makedirs(os.path.dirname(dst_path), exist_ok=True)
    shutil.copy2(src_path, dst_path)


def sync_task_auto(project_root: str, task_file: str, worktree_path: str, branch: str) -> str:
    if check_task_in_head(project_root, task_file) and not check_task_dirty(project_root, task_file):
        return "head-only"
    _copy_task_file(project_root, worktree_path, task_file)
    _run_git(worktree_path, ["add", "--", task_file], check=True)
    if not _has_staged_changes(worktree_path):
        return "copied-no-commit"
    msg = f"chore(cf-lane): sync task snapshot {task_file}"
    _run_git(worktree_path, ["commit", "-m", msg], check=True)
    _run_git(worktree_path, ["rev-parse", "--verify", branch], check=True)
    return "snapshot-commit"
