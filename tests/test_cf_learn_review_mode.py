#!/usr/bin/env python3
"""Regression tests for cf-learn --review mode semantics."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read_text(rel_path: str) -> str:
    return (ROOT / rel_path).read_text(encoding="utf-8")


def _assert_workspace_review_semantics(text: str) -> None:
    assert "当前工作区变更" in text
    assert "git diff --name-only" in text
    assert "git diff --cached --name-only" in text
    assert "--review --staged" in text

    assert "git log --oneline -N" not in text
    assert "从 git 历史挖掘人工修正模式" not in text


def test_cf_learn_docs_review_uses_workspace_changes() -> None:
    paths = [
        "src/adapters/codex/skills/cf-learn/SKILL.md",
        "src/adapters/claude/commands/cf-learn.md",
        "src/adapters/costrict/commands/cf-learn.md",
        "src/adapters/opencode/commands/cf-learn.md",
        ".agents/skills/cf-learn/SKILL.md",
        ".claude/commands/cf-learn.md",
        ".costrict/commands/cf-learn.md",
        ".opencode/commands/cf-learn.md",
    ]
    for path in paths:
        _assert_workspace_review_semantics(_read_text(path))


def test_usage_cf_learn_review_matches_workspace_flow() -> None:
    content = _read_text("docs/USAGE.md")
    assert "Review 模式（基于当前变更提炼规范）" in content
    assert "/cf-learn --review --staged" in content
    assert "从 git 历史中发现\"AI 写了但被人工修正\"的模式" not in content
