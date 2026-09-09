#!/usr/bin/env python3
"""[TASK-011] 任务索引/DAG 程序化回归测试（真实解析，无 mock）。"""
import json
import subprocess
import sys
from pathlib import Path


SCRIPTS = Path(__file__).resolve().parents[1] / "src/core/code-flow/scripts"
sys.path.insert(0, str(SCRIPTS))

import pytest  # noqa: E402

from cf_task_index import independent_groups, parse_task_file, task_batches  # noqa: E402


def _file(tmp_path: Path, body: str) -> str:
    task = tmp_path / "work.md"
    task.write_text(body, encoding="utf-8")
    return str(task)


def test_batches_follow_depends_and_skip_finished(tmp_path: Path) -> None:
    path = _file(
        tmp_path,
        "## TASK-001: A\n- **Status**: done\n- **Depends**: \n"
        "## TASK-002: B\n- **Status**: draft\n- **Depends**: TASK-001\n"
        "## TASK-003: C\n- **Status**: draft\n- **Depends**: TASK-001\n"
        "## TASK-004: D\n- **Status**: draft\n- **Depends**: TASK-002\n",
    )
    nodes = parse_task_file(path)
    assert task_batches(nodes) == [["TASK-002", "TASK-003"], ["TASK-004"]]
    assert ["TASK-002", "TASK-003"] == sorted(task_batches(nodes)[0])


def test_verified_counts_as_finished_and_unknown_status_preserved(tmp_path: Path) -> None:
    path = _file(
        tmp_path,
        "## TASK-001: A\n- **Status**: verified\n- **Depends**: \n"
        "## TASK-002: B\n- **Status**: draft\n- **Depends**: TASK-001\n",
    )
    nodes = parse_task_file(path)
    assert nodes[0].status == "verified"
    assert task_batches(nodes) == [["TASK-002"]]


def test_unknown_depends_and_cycles_raise(tmp_path: Path) -> None:
    missing = _file(tmp_path, "## TASK-001: A\n- **Status**: draft\n- **Depends**: TASK-999\n")
    with pytest.raises(ValueError, match="unknown depends"):
        task_batches(parse_task_file(missing))
    cycle = _file(
        tmp_path,
        "## TASK-001: A\n- **Status**: draft\n- **Depends**: TASK-002\n"
        "## TASK-002: B\n- **Status**: draft\n- **Depends**: TASK-001\n",
    )
    with pytest.raises(ValueError, match="cycle"):
        task_batches(parse_task_file(cycle))


def test_cli_json_batches_real_task_file() -> None:
    root = Path(__file__).resolve().parents[1]
    task = root / ".code-flow/tasks/2026-09-09/audit-remediation/audit-remediation.md"
    if not task.is_file():
        pytest.skip("needs the audit-remediation task file")
    result = subprocess.run(
        [sys.executable, str(root / "src/core/code-flow/scripts/cf_task_index.py"),
         "--task-file", str(task), "--dag", "--json"],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert len(data["tasks"]) == 13
    order = [task for batch in data["batches"] for task in batch]
    by_id = {item["id"]: item for item in data["tasks"]}
    finished = {item["id"] for item in data["tasks"] if item["status"] in ("done", "verified")}
    assert set(order) == set(by_id) - finished
    position = {task: index for index, task in enumerate(order)}
    for item in data["tasks"]:
        for dep in item["depends"]:
            if dep in position:
                assert position[dep] < position[item["id"]], f"{dep} 必须排在 {item['id']} 之前"
