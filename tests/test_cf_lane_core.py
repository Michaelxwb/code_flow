#!/usr/bin/env python3
"""Tests for cf_lane_core.py."""

import json
import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "core", "code-flow", "scripts"))

from cf_lane_core import (
    LaneSchemaError,
    acquire_lock,
    build_dep_graph,
    check_task_dirty,
    check_task_in_head,
    compute_worktree_id,
    detect_cycle,
    find_lane,
    find_lane_by_task,
    gc_inject_states,
    get_task_owner,
    inject_state_file_path,
    lanes_file_path,
    legacy_inject_state_path,
    load_lanes,
    release_lock,
    resolve_common_dir,
    resolve_inject_state_dir,
    save_lanes,
    sync_task_auto,
    sync_task_head_only,
    topological_sort,
)


def _init_git_repo(path: str) -> None:
    subprocess.run(["git", "init"], cwd=path, check=True, capture_output=True, text=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=path,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test User"],
        cwd=path,
        check=True,
        capture_output=True,
        text=True,
    )


def _sample_lane() -> dict:
    return {
        "lane_id": "lane_order_abc123",
        "task_file": ".code-flow/tasks/2026-04-08/order.md",
        "branch": "feat/order",
        "worktree_path": "/tmp/codeflow-order",
        "dep_lane": None,
        "dep_type": "none",
        "base_branch": "main",
        "status": "active",
        "last_sync_from": "main",
        "last_sync_at": "2026-04-08T10:00:00Z",
        "blocked_reason": "",
        "created_at": "2026-04-08T10:00:00Z",
        "updated_at": "2026-04-08T10:00:00Z",
    }


def test_resolve_common_dir_creates_code_flow_dir() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        _init_git_repo(tmpdir)
        common_dir = resolve_common_dir(tmpdir)
        assert os.path.isdir(common_dir)
        assert common_dir.endswith("code-flow")


def test_save_and_load_lanes_roundtrip() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        _init_git_repo(tmpdir)
        payload = {"version": 1, "lanes": [_sample_lane()]}
        save_lanes(tmpdir, payload)

        loaded = load_lanes(tmpdir)
        assert loaded["version"] == 1
        assert loaded["lanes"][0]["lane_id"] == "lane_order_abc123"
        assert find_lane(loaded, "lane_order_abc123") is not None
        assert find_lane_by_task(loaded, ".code-flow/tasks/2026-04-08/order.md") is not None


def test_load_lanes_schema_validation_failure() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        _init_git_repo(tmpdir)
        path = lanes_file_path(tmpdir)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"version": 2, "lanes": []}, f)

        try:
            load_lanes(tmpdir)
        except LaneSchemaError as exc:
            assert "unsupported lanes schema version" in str(exc)
        else:
            assert False, "expected LaneSchemaError"


def test_lock_competition_times_out() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        _init_git_repo(tmpdir)
        lock_path = acquire_lock(tmpdir, timeout_seconds=0.5, command="task-a")
        try:
            try:
                acquire_lock(tmpdir, timeout_seconds=0.2, stale_seconds=9999, command="task-b")
            except TimeoutError as exc:
                assert "failed to acquire lock" in str(exc)
            else:
                assert False, "expected TimeoutError"
        finally:
            release_lock(lock_path)


def test_stale_lock_is_recovered() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        _init_git_repo(tmpdir)
        common_dir = resolve_common_dir(tmpdir)
        lock_dir = os.path.join(common_dir, "locks")
        os.makedirs(lock_dir, exist_ok=True)
        lock_path = os.path.join(lock_dir, "lanes.lock")
        with open(lock_path, "w", encoding="utf-8") as f:
            json.dump({"pid": 999999, "host": "test", "start_at": 1.0, "command": "old"}, f)

        recovered = acquire_lock(tmpdir, timeout_seconds=0.5, stale_seconds=0.1, command="task-new")
        assert recovered == lock_path
        release_lock(recovered)


def test_dep_graph_and_topological_sort_chain() -> None:
    lanes = [
        {"lane_id": "lane-b", "dep_lane": None, "dep_type": "none"},
        {"lane_id": "lane-a", "dep_lane": "lane-b", "dep_type": "hard"},
    ]
    graph = build_dep_graph(lanes)
    assert graph == {"lane-b": set(), "lane-a": {"lane-b"}}
    assert detect_cycle(graph) == []
    assert topological_sort(graph) == ["lane-b", "lane-a"]


def test_dep_graph_cycle_detection() -> None:
    graph = {
        "lane-a": {"lane-b"},
        "lane-b": {"lane-c"},
        "lane-c": set(),
    }
    cycle = detect_cycle(graph, new_edge=("lane-c", "lane-a"))
    assert cycle[0] == "lane-a"
    assert cycle[-1] == "lane-a"


def test_topological_sort_multi_branch_and_single_node() -> None:
    graph = {
        "lane-base": set(),
        "lane-a": {"lane-base"},
        "lane-b": {"lane-base"},
        "lane-c": set(),
    }
    order = topological_sort(graph)
    assert order.index("lane-base") < order.index("lane-a")
    assert order.index("lane-base") < order.index("lane-b")
    assert "lane-c" in order


def test_get_task_owner_prefers_active_lane() -> None:
    lanes = [
        {"lane_id": "lane-old", "task_file": "task.md", "status": "closed"},
        {"lane_id": "lane-new", "task_file": "task.md", "status": "active"},
    ]
    owner = get_task_owner(lanes, "task.md")
    assert owner is not None
    assert owner["lane_id"] == "lane-new"


def test_task_in_head_and_dirty_checks() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        _init_git_repo(tmpdir)
        task_file = ".code-flow/tasks/2026-04-08/t1.md"
        abs_path = os.path.join(tmpdir, task_file)
        os.makedirs(os.path.dirname(abs_path), exist_ok=True)
        with open(abs_path, "w", encoding="utf-8") as f:
            f.write("v1\\n")
        subprocess.run(["git", "add", "--", task_file], cwd=tmpdir, check=True, capture_output=True, text=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=tmpdir, check=True, capture_output=True, text=True)

        assert check_task_in_head(tmpdir, task_file) is True
        assert check_task_dirty(tmpdir, task_file) is False
        with open(abs_path, "a", encoding="utf-8") as f:
            f.write("dirty\\n")
        assert check_task_dirty(tmpdir, task_file) is True


def test_sync_task_head_only_fails_if_missing_in_head() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        _init_git_repo(tmpdir)
        task_file = ".code-flow/tasks/2026-04-08/missing.md"
        try:
            sync_task_head_only(tmpdir, task_file)
        except FileNotFoundError as exc:
            assert task_file in str(exc)
        else:
            assert False, "expected FileNotFoundError"


def test_sync_task_auto_head_only_fast_path() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        _init_git_repo(tmpdir)
        task_file = ".code-flow/tasks/2026-04-08/t2.md"
        abs_path = os.path.join(tmpdir, task_file)
        os.makedirs(os.path.dirname(abs_path), exist_ok=True)
        with open(abs_path, "w", encoding="utf-8") as f:
            f.write("v1\\n")
        subprocess.run(["git", "add", "--", task_file], cwd=tmpdir, check=True, capture_output=True, text=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=tmpdir, check=True, capture_output=True, text=True)

        mode = sync_task_auto(tmpdir, task_file, tmpdir, "main")
        assert mode == "head-only"


def test_sync_task_auto_creates_snapshot_commit() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        repo = os.path.join(tmpdir, "repo")
        worktree = os.path.join(tmpdir, "wt")
        os.makedirs(repo, exist_ok=True)
        _init_git_repo(repo)
        task_file = ".code-flow/tasks/2026-04-08/t3.md"
        src_path = os.path.join(repo, task_file)
        os.makedirs(os.path.dirname(src_path), exist_ok=True)
        with open(src_path, "w", encoding="utf-8") as f:
            f.write("v1\\n")
        subprocess.run(["git", "add", "--", task_file], cwd=repo, check=True, capture_output=True, text=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=repo, check=True, capture_output=True, text=True)

        with open(src_path, "w", encoding="utf-8") as f:
            f.write("v2-dirty\\n")
        subprocess.run(
            ["git", "worktree", "add", "-b", "feat/t3", worktree],
            cwd=repo,
            check=True,
            capture_output=True,
            text=True,
        )
        mode = sync_task_auto(repo, task_file, worktree, "feat/t3")
        assert mode == "snapshot-commit"
        result = subprocess.run(
            ["git", "-C", worktree, "log", "-1", "--pretty=%s"],
            check=True,
            capture_output=True,
            text=True,
        )
        assert "chore(cf-lane): sync task snapshot" in result.stdout.strip()


def test_inject_state_paths_and_worktree_id() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        _init_git_repo(tmpdir)
        wt_id = compute_worktree_id(tmpdir)
        assert len(wt_id) == 12
        state_dir = resolve_inject_state_dir(tmpdir, wt_id)
        assert state_dir.endswith(f"inject-states/{wt_id}")
        state_file = inject_state_file_path(tmpdir, "12345", wt_id)
        assert state_file.endswith(f"inject-states/{wt_id}/12345.json")
        legacy = legacy_inject_state_path(tmpdir)
        assert legacy.endswith(".code-flow/.inject-state")


def test_gc_inject_states_removes_stale_dead_sessions() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        _init_git_repo(tmpdir)
        wt_id = compute_worktree_id(tmpdir)
        state_dir = resolve_inject_state_dir(tmpdir, wt_id)

        old_state = os.path.join(state_dir, "old.json")
        with open(old_state, "w", encoding="utf-8") as f:
            json.dump({"session_id": "999999", "pid": 999999, "start_at": 1.0}, f)

        active_state = os.path.join(state_dir, "active.json")
        with open(active_state, "w", encoding="utf-8") as f:
            json.dump({"session_id": str(os.getpid()), "pid": os.getpid(), "start_at": 1.0}, f)

        removed = gc_inject_states(tmpdir, ttl_seconds=0.1, now_ts=100000.0)
        assert old_state in removed
        assert os.path.exists(active_state)


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
