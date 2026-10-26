#!/usr/bin/env python3
"""[TASK-012] 能力级 plan 与计划预算（真实模板 + 真实任务文件，无 mock）。"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "src/core/code-flow/scripts"
sys.path.insert(0, str(SCRIPTS))

from codeflow.task.cf_task_plan import evaluate_plan, parse_estimate_hours  # noqa: E402

PLAN_SOURCES = (
    ROOT / "src/adapters/claude/commands/cf-task/plan.md",
    ROOT / "src/adapters/costrict/commands/cf-task/plan.md",
    ROOT / "src/adapters/opencode/commands/cf-task/plan.md",
    ROOT / "src/adapters/codex/skills/cf-task-plan/SKILL.md",
)
def _requirement_dir(name: str) -> Path:
    live = ROOT / ".code-flow/tasks/2026-10-22" / name
    if live.is_dir():
        return live
    archived = sorted((ROOT / ".code-flow/tasks/archived").glob(f"*/{name}"))
    if not archived:
        raise RuntimeError(f"requirement not found: {name}")
    return archived[-1]


REAL_TASK_FILE = (
    _requirement_dir("code-flow-0.8-optimization")
    / "code-flow-0.8-optimization.md"
)


def _task_block(
    task_id: str,
    title: str,
    estimate: str,
    capability: str,
    refs: str = "S-01",
) -> str:
    return (
        f"## {task_id}: {title}\n"
        "- **Status**: draft\n"
        "- **Priority**: P0\n"
        "- **Depends**:\n"
        "- **Source**: design.md#2.3 功能方案\n"
        "- **Spec-Refs**:\n"
        f"- **Acceptance-Refs**: {refs}\n"
        f"- **Estimate**: {estimate}\n"
        f"- **Capability**: {capability}\n"
        "\n"
        "### Description\n"
        f"\n交付 {capability}，用户可以独立演示。\n"
        "\n"
        "### Checklist\n"
        f"- [ ] 演示 {capability}\n"
        "- [ ] 运行验收命令并填写 Acceptance Evidence\n"
        "\n"
        "### Acceptance Contract\n"
        "\n"
        "| 场景ID | 测试层级 | 不得 Mock 的真实边界 | 关键断言 | 测试文件 / 用例 | 执行命令 | 状态 |\n"
        "|--------|---------|--------------------|---------|----------------|---------|------|\n"
        f"| {refs.split(',')[0]} | integration | CLI | 能力可演示 | x | - | planned |\n"
    )


def _task_file(tmp_path: Path, blocks: list[str]) -> str:
    path = tmp_path / "capability-plan.md"
    path.write_text(
        "# Tasks: capability fixture\n\n## Proposal\n\n演示能力级拆分。\n\n"
        + "\n".join(blocks),
        encoding="utf-8",
    )
    return str(path)


def test_capability_budget_defaults_in_real_plan_template() -> None:
    for source in PLAN_SOURCES:
        text = source.read_text(encoding="utf-8")
        assert "--task-size capability" in text, f"{source}: 缺少默认 capability 粒度"
        assert "1-2 天" in text, f"{source}: 缺少 1-2 天能力粒度"
        assert "task index" in text and "--budget" in text, f"{source}: 缺少 task index --budget 预算入口"
        assert "25" in text and "2h" in text, f"{source}: 缺少预算阈值"
        assert "**Capability**" in text, f"{source}: 模板缺少 Capability 字段"
        assert "**Estimate**" in text, f"{source}: 模板缺少 Estimate 字段"


def test_capability_budget_passes_balanced_capability_plan(tmp_path: Path) -> None:
    path = _task_file(
        tmp_path,
        [
            _task_block("TASK-001", "导入能力", "1d", "用户可以导入一份配置并看到成功摘要", "S-01"),
            _task_block("TASK-002", "校验能力", "1.5d", "用户可以触发校验并看到逐项结果", "S-02"),
            _task_block("TASK-003", "导出能力", "2d", "用户可以导出结果并在外部打开", "S-03"),
        ],
    )
    budget = evaluate_plan(path)
    assert budget["decision"] == "pass"
    assert budget["requires_merge"] is False
    assert budget["task_count"] == 3
    assert budget["estimated_task_count"] == 3
    assert budget["total_hours"] == 36.0
    assert budget["average_hours"] == 12.0
    assert budget["warnings"] == []
    assert all(task["capability"] for task in budget["tasks"])
    assert all(task["scenario_count"] >= 1 for task in budget["tasks"])


def test_capability_budget_requires_merge_above_task_count(tmp_path: Path) -> None:
    blocks = [
        _task_block(f"TASK-{index:03d}", f"能力 {index}", "2d", f"用户可以演示能力 {index}", "S-01")
        for index in range(1, 27)
    ]
    budget = evaluate_plan(_task_file(tmp_path, blocks))
    assert budget["task_count"] == 26
    assert budget["decision"] == "merge_required"
    assert budget["requires_merge"] is True
    warning = next(item for item in budget["warnings"] if item["code"] == "task_count_exceeds_budget")
    assert "26" in warning["message"] and "25" in warning["message"]


def test_capability_budget_requires_merge_below_average_hours(tmp_path: Path) -> None:
    path = _task_file(
        tmp_path,
        [
            _task_block("TASK-001", "小改动一", "1h", "用户可以运行一个命令", "S-01"),
            _task_block("TASK-002", "小改动二", "1h", "用户可以运行另一个命令", "S-02"),
            _task_block("TASK-003", "小改动三", "1h", "用户可以再运行一个命令", "S-03"),
        ],
    )
    budget = evaluate_plan(path)
    assert budget["average_hours"] == 1.0
    assert budget["requires_merge"] is True
    warning = next(item for item in budget["warnings"] if item["code"] == "average_task_too_small")
    assert "1.0" in warning["message"] and "2" in warning["message"]


def test_capability_budget_file_mode_keeps_legacy_granularity(tmp_path: Path) -> None:
    path = _task_file(
        tmp_path,
        [
            _task_block("TASK-001", "文件修改一", "30m", "用户可以运行一个命令", "S-01"),
            _task_block("TASK-002", "文件修改二", "30m", "用户可以运行另一个命令", "S-02"),
        ],
    )
    legacy = evaluate_plan(path, task_size="file")
    assert legacy["task_size"] == "file"
    assert legacy["requires_merge"] is False
    assert legacy["warnings"] == []


def test_capability_budget_parses_estimate_units() -> None:
    assert parse_estimate_hours("1.5d") == 12.0
    assert parse_estimate_hours("1d") == 8.0
    assert parse_estimate_hours("90m") == 1.5
    assert parse_estimate_hours("4h") == 4.0
    assert parse_estimate_hours("2-3d") == 24.0
    assert parse_estimate_hours("") is None


def test_capability_budget_reads_real_requirement_task_file() -> None:
    if not REAL_TASK_FILE.is_file():
        pytest.skip("needs the code-flow 0.8 task file")
    budget = evaluate_plan(str(REAL_TASK_FILE))
    assert budget["task_count"] == 17
    assert budget["estimated_task_count"] == 17
    assert budget["total_hours"] == 244.0
    assert budget["average_hours"] == pytest.approx(14.35)
    assert budget["task_count"] <= 25 or budget["warnings"]
    assert all(task["capability"] for task in budget["tasks"])


def test_capability_budget_cli_reports_json_and_exit_code(tmp_path: Path) -> None:
    path = _task_file(
        tmp_path,
        [
            _task_block("TASK-001", "导入能力", "1d", "用户可以导入配置", "S-01"),
            _task_block("TASK-002", "导出能力", "2d", "用户可以导出结果", "S-02"),
        ],
    )
    passing = subprocess.run(
        [sys.executable, str(SCRIPTS / "cf_task_index.py"), "--task-file", path, "--budget", "--json"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert passing.returncode == 0, passing.stderr
    payload = json.loads(passing.stdout)
    assert payload["budget"]["decision"] == "pass"
    assert payload["budget"]["task_count"] == 2

    blocked_path = _task_file(
        tmp_path,
        [_task_block(f"TASK-{index:03d}", f"能力 {index}", "1h", "小改动", "S-01") for index in range(1, 27)],
    )
    blocked = subprocess.run(
        [sys.executable, str(SCRIPTS / "cf_task_index.py"), "--task-file", blocked_path, "--budget", "--json"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert blocked.returncode == 1
    blocked_payload = json.loads(blocked.stdout)
    assert blocked_payload["budget"]["requires_merge"] is True


def test_scenario_owner_reconciliation_requires_unique_owner() -> None:
    from cf_scenarios import reconcile_coverage
    scenarios = [{"id": "S-01"}, {"id": "S-02"}]
    report = reconcile_coverage(scenarios, [
        {"scenario_id": "S-01", "owner": "TASK-001"},
        {"scenario_id": "S-02", "owner": "TASK-002"},
    ])
    assert report["ok"] is True


def test_missing_scenarios_source_blocks_plan(tmp_path: Path) -> None:
    from cf_scenarios import ScenarioError, require_source
    with pytest.raises(ScenarioError) as error:
        require_source(tmp_path)
    assert error.value.code == "scenario_source_missing"
