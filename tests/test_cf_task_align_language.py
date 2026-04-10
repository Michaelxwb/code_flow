#!/usr/bin/env python3
"""Guardrails for cf-task-align language defaults and templates."""
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

CODEX_ALIGN_SKILL = ROOT / "src" / "adapters" / "codex" / "skills" / "cf-task-align" / "SKILL.md"
CLAUDE_ALIGN_COMMAND = ROOT / "src" / "adapters" / "claude" / "commands" / "cf-task" / "align.md"


def _assert_language_rules(content: str) -> None:
    assert "默认使用中文生成完整设计简报" in content
    assert "仅当用户明确要求英文" in content
    assert "输出语言默认与用户需求语言保持一致" in content


def _assert_chinese_template(content: str) -> None:
    assert "# 设计简报：<模块名称>" in content
    assert "## 目标" in content
    assert "## 非目标" in content
    assert "## 数据模型设计" in content
    assert "## 接口设计" in content
    assert "## 约束条件" in content
    assert "## 验收标准" in content
    assert "## Goal" not in content
    assert "## Non-goals" not in content
    assert "## Database Design" not in content
    assert "## API Design" not in content
    assert "## Acceptance Criteria" not in content


def test_codex_cf_task_align_uses_chinese_by_default() -> None:
    content = CODEX_ALIGN_SKILL.read_text(encoding="utf-8")
    _assert_language_rules(content)
    _assert_chinese_template(content)


def test_claude_cf_task_align_uses_chinese_by_default() -> None:
    content = CLAUDE_ALIGN_COMMAND.read_text(encoding="utf-8")
    _assert_language_rules(content)
    _assert_chinese_template(content)
