#!/usr/bin/env python3
"""Regression tests for cf-learn scan exclusion rules in skill docs."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read_text(rel_path: str) -> str:
    return (ROOT / rel_path).read_text(encoding="utf-8")


def _assert_ignore_rules(text: str) -> None:
    assert ".gitignore" in text
    assert "统一排除集" in text
    assert "node_modules/**" in text
    assert ".codex_flow/**" in text
    assert "所有隐藏目录" in text
    assert ".github/workflows/**" in text
    assert "仅针对“未被排除”的路径执行" in text


def test_codex_cf_learn_declares_gitignore_based_scan_exclusions() -> None:
    content = _read_text("src/adapters/codex/skills/cf-learn/SKILL.md")
    _assert_ignore_rules(content)


def test_claude_cf_learn_declares_gitignore_based_scan_exclusions() -> None:
    content = _read_text("src/adapters/claude/commands/cf-learn.md")
    _assert_ignore_rules(content)


def test_project_codex_cf_learn_declares_gitignore_based_scan_exclusions() -> None:
    content = _read_text(".agents/skills/cf-learn/SKILL.md")
    _assert_ignore_rules(content)


def test_project_claude_cf_learn_declares_gitignore_based_scan_exclusions() -> None:
    content = _read_text(".claude/commands/cf-learn.md")
    _assert_ignore_rules(content)
