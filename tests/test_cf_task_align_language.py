#!/usr/bin/env python3
"""Guardrails for cf-task-align language defaults and template references."""
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

CODEX_ALIGN_SKILL = ROOT / "src" / "adapters" / "codex" / "skills" / "cf-task-align" / "SKILL.md"
CLAUDE_ALIGN_COMMAND = ROOT / "src" / "adapters" / "claude" / "commands" / "cf-task" / "align.md"
OPENCODE_ALIGN_COMMAND = ROOT / "src" / "adapters" / "opencode" / "commands" / "cf-task" / "align.md"


def _assert_language_rules(content: str) -> None:
    assert "默认使用中文生成完整设计简报" in content
    assert "仅当用户明确要求英文" in content
    assert "输出语言默认与用户需求语言保持一致" in content


def _assert_template_references(content: str) -> None:
    # Must reference the shared design templates rather than embedding a stale
    # in-line skeleton; align skills generate from design-lite/design-full.md.
    assert "design-lite.md" in content
    assert "design-full.md" in content
    assert ".code-flow/specs/shared/design/design-lite.md" in content
    assert ".code-flow/specs/shared/design/design-full.md" in content

    # Section-mapping headings (Chinese) must be present so generated briefs
    # stay aligned with the shared templates.
    for heading in (
        "2.1 需求概述",
        "2.4 验收条件",
        "3.1 技术选型",
        "3.3 接口设计",
    ):
        assert heading in content, f"missing section mapping: {heading}"

    # Stale English skeleton must not reappear.
    for forbidden in (
        "## Goal",
        "## Non-goals",
        "## Database Design",
        "## API Design",
        "## Acceptance Criteria",
    ):
        assert forbidden not in content, f"unexpected English heading: {forbidden}"


def test_codex_cf_task_align_uses_chinese_by_default() -> None:
    content = CODEX_ALIGN_SKILL.read_text(encoding="utf-8")
    _assert_language_rules(content)
    _assert_template_references(content)


def test_claude_cf_task_align_uses_chinese_by_default() -> None:
    content = CLAUDE_ALIGN_COMMAND.read_text(encoding="utf-8")
    _assert_language_rules(content)
    _assert_template_references(content)


def test_opencode_cf_task_align_uses_chinese_by_default() -> None:
    content = OPENCODE_ALIGN_COMMAND.read_text(encoding="utf-8")
    _assert_language_rules(content)
    _assert_template_references(content)
