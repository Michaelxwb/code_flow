#!/usr/bin/env python3
"""Acceptance guards for the demand-directory task workflow."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TASK_COMMANDS = ROOT / "src/adapters/claude/commands/cf-task"


def _command(name: str) -> str:
    return (TASK_COMMANDS / f"{name}.md").read_text(encoding="utf-8")


def test_s_01_prd_is_written_inside_its_demand_directory() -> None:
    text = _command("prd")
    assert ".code-flow/tasks/<YYYY-MM-DD>/<name>/" in text
    assert ".code-flow/tasks/<日期>/<name>/<name>.prd.md" in text


def test_s_02_b_01_align_names_full_stack_and_single_domain_designs() -> None:
    text = _command("align")
    assert "<需求>.frontend.design.md" in text
    assert "<需求>.backend.design.md" in text
    assert "纯后端/通用单域时 `<需求>.design.md`" in text
    assert "全栈需求" in text and "前后端各写一份" in text


def test_s_03_plan_merges_all_designs_into_one_task_file() -> None:
    text = _command("plan")
    assert "<目录>/*.design.md" in text
    assert "目录内**全部设计简报**" in text
    assert "多份 design 合并拆解为**一份**任务文件" in text
    assert ".code-flow/tasks/<日期>/<需求>/<需求>.md" in text


def test_s_04_e_03_archive_supports_directory_and_flat_layouts() -> None:
    text = _command("archive")
    assert "**A. 需求目录布局**" in text
    assert "整个需求目录一并归档" in text
    assert "**B. 旧扁平布局**" in text
    assert "向后兼容" in text and "逐文件归档" in text
