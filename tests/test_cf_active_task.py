#!/usr/bin/env python3
"""S-15/E-13/B-09 coverage for Active Task Git ownership."""

from dataclasses import replace
import json
from pathlib import Path
import subprocess
import sys

import pytest


SCRIPTS = Path(__file__).resolve().parents[1] / "src" / "core" / "code-flow" / "scripts"
sys.path.insert(0, str(SCRIPTS))

from cf_spec_context import (
    ContextError,
    complete_active_task,
    current_owned_paths,
    doctor_active_task,
    load_active_task,
    pause_active_task,
    resume_active_task,
    save_active_task,
    start_active_task,
)


def _git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ("git", *args), cwd=root, text=True, capture_output=True, check=True
    )
    return result.stdout.strip()


def _repository(tmp_path: Path) -> Path:
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "test@example.com")
    _git(tmp_path, "config", "user.name", "Test User")
    source = tmp_path / "src" / "app.py"
    source.parent.mkdir()
    source.write_text("VALUE = 1\n", encoding="utf-8")
    _git(tmp_path, "add", "src/app.py")
    _git(tmp_path, "commit", "-qm", "initial")
    return tmp_path


def test_s_15_dirty_baseline_requires_ownership_and_tracks_delta(tmp_path: Path) -> None:
    root = _repository(tmp_path)
    source = root / "src" / "app.py"
    source.write_text("VALUE = 2\n", encoding="utf-8")

    with pytest.raises(ContextError) as unowned:
        start_active_task(str(root), ".code-flow/tasks/demo", "TASK-007", "ctx-1")
    assert unowned.value.code == "unowned_changes"

    active = start_active_task(
        str(root),
        ".code-flow/tasks/demo",
        "TASK-007",
        "ctx-1",
        ("src/app.py",),
    )
    assert active.baseline.head == _git(root, "rev-parse", "HEAD")
    assert active.baseline.preexisting_changes["src/app.py"].status == "modified"
    # content_sha256 是历史字段、无 Gate 消费，start 不再逐文件哈希，保持空串
    assert active.baseline.preexisting_changes["src/app.py"].content_sha256 == ""

    (root / "src" / "new.py").write_text("NEW = True\n", encoding="utf-8")
    assert current_owned_paths(str(root), active) == ("src/app.py", "src/new.py")

    paused = pause_active_task(str(root))
    assert paused.status == "paused"
    with pytest.raises(ContextError) as duplicate:
        start_active_task(str(root), ".code-flow/tasks/other", "TASK-001", "ctx-2")
    assert duplicate.value.code == "active_exists"
    assert resume_active_task(str(root)).status == "active"
    assert complete_active_task(str(root), gate_passed=True).status == "completed"
    assert not (root / ".code-flow" / ".active-task.json").exists()


def test_e_13_active_marker_is_fail_closed(tmp_path: Path) -> None:
    root = _repository(tmp_path)
    active = start_active_task(
        str(root), ".code-flow/tasks/demo", "TASK-007", "ctx-1"
    )
    with pytest.raises(ContextError) as duplicate:
        start_active_task(str(root), ".code-flow/tasks/demo", "TASK-008", "ctx-1")
    assert duplicate.value.code == "active_exists"

    marker = root / ".code-flow" / ".active-task.json"
    marker.write_text("{broken", encoding="utf-8")
    with pytest.raises(ContextError) as corrupt:
        load_active_task(str(root))
    assert corrupt.value.code == "invalid_active_marker"
    with pytest.raises(ContextError) as doctor:
        doctor_active_task(str(root), active.context_sha256)
    assert doctor.value.code == "recovery_required"
    assert marker.exists()


def test_b_09_doctor_repairs_only_hash_proven_interrupted_activation(tmp_path: Path) -> None:
    root = _repository(tmp_path)
    active = start_active_task(
        str(root), ".code-flow/tasks/demo", "TASK-007", "ctx-1"
    )
    save_active_task(str(root), replace(active, status="activating"))
    lock = root / ".code-flow" / ".active-task.lock"
    lock.write_text("stale", encoding="utf-8")

    result = doctor_active_task(str(root), "ctx-1")

    assert result.action == "resumed"
    assert result.active.status == "active"
    assert load_active_task(str(root)).status == "active"
    assert not lock.exists()


def test_active_cli_emits_one_json_object(tmp_path: Path) -> None:
    root = _repository(tmp_path)
    task_dir = root / ".code-flow" / "tasks" / "demo"
    task_dir.mkdir(parents=True)
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPTS / "cf_spec_context.py"),
            "active",
            "start",
            "--root",
            str(root),
            "--task-dir",
            str(task_dir),
            "--task",
            "TASK-007",
            "--context-sha256",
            "ctx-1",
            "--json",
        ],
        input=json.dumps({"owned_paths": []}),
        text=True,
        capture_output=True,
        check=False,
    )

    payload = json.loads(result.stdout)
    assert result.returncode == 0
    assert payload["ok"] is True
    assert payload["active"]["status"] == "active"
    assert result.stdout.count("{") >= 1
    assert result.stderr == ""
