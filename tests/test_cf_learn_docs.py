#!/usr/bin/env python3
"""Regression tests for cf-learn command/skill documentation contracts."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

TEMPLATE_TO_INSTALLED = {
    "src/adapters/codex/skills/cf-learn/SKILL.md": ".agents/skills/cf-learn/SKILL.md",
    "src/adapters/claude/commands/cf-learn.md": ".claude/commands/cf-learn.md",
    "src/adapters/costrict/commands/cf-learn.md": ".costrict/commands/cf-learn.md",
    "src/adapters/opencode/commands/cf-learn.md": ".opencode/commands/cf-learn.md",
}


def _read_text(rel_path: str) -> str:
    return (ROOT / rel_path).read_text(encoding="utf-8")


def _assert_core_learning_contract(text: str) -> None:
    required = [
        "证据优先",
        "禁止编造",
        "用户确认",
        "置信度",
        "低置信度不自动写入",
        "来源文件",
        "证据片段",
        ".code-flow/config.yml",
        "path_mapping",
        "directory-structure.md",
        "component-specs.md",
        "quality-standards.md",
        "database.md",
        "logging.md",
        "platform-rules.md",
        "code-quality-performance.md",
        "不要创建猜测文件",
        "已有人工内容要保留",
    ]
    for phrase in required:
        assert phrase in text


def test_cf_learn_templates_require_evidence_backed_candidates() -> None:
    for template_path in TEMPLATE_TO_INSTALLED:
        _assert_core_learning_contract(_read_text(template_path))


def test_installed_cf_learn_docs_match_adapter_templates() -> None:
    for template_path, installed_path in TEMPLATE_TO_INSTALLED.items():
        assert _read_text(installed_path) == _read_text(template_path)


def test_cf_learn_platform_global_targets_are_correct() -> None:
    codex = _read_text("src/adapters/codex/skills/cf-learn/SKILL.md")
    claude = _read_text("src/adapters/claude/commands/cf-learn.md")
    costrict = _read_text("src/adapters/costrict/commands/cf-learn.md")
    opencode = _read_text("src/adapters/opencode/commands/cf-learn.md")

    assert "写入 `AGENTS.md`" in codex
    assert "写入 `AGENTS.md`" in opencode
    assert "写入 `CLAUDE.md`" in claude
    assert "写入 `CLAUDE.md`" in costrict

    assert "`/project:cf-learn`" in claude
    assert "`/project:cf-learn`" in costrict
    assert "`/project:cf-learn`" in opencode
    assert "`cf-learn`" in codex

    # apply_patch 是 codex 的编辑机制；opencode 用自身编辑工具，不应残留 apply_patch
    assert "apply_patch" not in opencode
