#!/usr/bin/env python3
"""Regression tests for cf-learn generated spec constraints."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(rel_path: str) -> str:
    return (ROOT / rel_path).read_text(encoding="utf-8")


def test_cli_specs_include_non_blocking_optional_init_ops() -> None:
    content = _read(".code-flow/specs/cli/code-standards.md")
    assert "可选操作" in content
    assert "不能阻塞 init 主流程" in content
    assert "recursive + force + retry" in content


def test_scripts_specs_include_hook_noop_and_prompt_path_extraction_rules() -> None:
    content = _read(".code-flow/specs/scripts/code-standards.md")
    assert "no-op 场景" in content
    assert "不输出额外 stdout 噪音" in content
    assert "支持裸路径、`@path`、反引号路径" in content


def test_scripts_specs_include_effective_mapping_and_domain_fallback_rules() -> None:
    content = _read(".code-flow/specs/scripts/code-standards.md")
    assert "优先基于磁盘实际存在的 `.code-flow/specs` 构建有效映射" in content
    assert "SessionStart 必须重写 `.inject-state`" in content
    assert "域解析回退顺序固定：路径 pattern 命中 → 上下文 tag 命中域名 → 全域回退" in content
    assert "Codex Hook、Claude Hook、Stats 三类回归测试" in content
