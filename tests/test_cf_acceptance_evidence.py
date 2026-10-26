"""Acceptance evidence writer must update the Coverage status cell in place."""
from __future__ import annotations

import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "src/core/code-flow/scripts"
sys.path.insert(0, str(SCRIPTS))

from codeflow.acceptance.cf_acceptance_evidence import (  # noqa: E402
    _status_line, line_status, sync_task_evidence,
)


def test_status_line_replaces_designed_in_place() -> None:
    line = (
        "| S-01 | design | unit | boundary | TASK-001 | designed | [\"pytest\"] | "
        "P1 | auto | none | tests/x.py | - | - | no |"
    )
    updated = _status_line(line, "S-01", "verified")
    assert updated.count("|") == line.count("|")
    assert "designed" not in updated
    assert line_status(updated, "S-01") == "verified"


def test_status_line_appends_only_when_no_status_cell() -> None:
    line = "| S-01 | design | unit | boundary | TASK-001 | | [\"pytest\"] |"
    updated = _status_line(line, "S-01", "verified")
    assert line_status(updated, "S-01") == "verified"


def test_sync_task_evidence_updates_status_column_only(tmp_path: Path) -> None:
    task = tmp_path / "work.md"
    task.write_text(
        "## TASK-001: demo\n"
        "- **Acceptance-Refs**: S-01\n"
        "### Checklist\n"
        "- [ ] [S-01] ok\n"
        "### Acceptance Contract\n"
        "| 场景ID | 测试层级 | 不得 Mock 的真实边界 | 关键断言 | 测试文件 / 用例 | 执行命令 | 状态 |\n"
        "|---|---|---|---|---|---|---|\n"
        "| S-01 | unit | boundary | assert | tests/x.py | pytest | planned |\n"
        "## Acceptance Coverage\n"
        "| 场景ID | 来源设计 | 测试层级 | 关键真实边界 | 负责任务 | 状态 | 执行命令 |\n"
        "|---|---|---|---|---|---|---|\n"
        "| S-01 | designed | unit | boundary | TASK-001 | | [\"pytest\"] |\n",
        encoding="utf-8",
    )
    assert sync_task_evidence(task, "S-01", "tester", "evidence", owner="TASK-001") == "synced"
    text = task.read_text(encoding="utf-8")
    coverage = text.split("## Acceptance Coverage", 1)[1]
    row = next(line for line in coverage.splitlines() if line.startswith("| S-01"))
    cells = [cell.strip() for cell in row.strip().strip("|").split("|")]
    assert cells[1] == "designed", "来源设计列不得被改写"
    assert cells[5] == "verified", "状态列必须原位更新"
    contract = text.split("### Acceptance Contract", 1)[1].split("## Acceptance Coverage", 1)[0]
    contract_row = next(line for line in contract.splitlines() if line.startswith("| S-01"))
    assert "verified" in contract_row
