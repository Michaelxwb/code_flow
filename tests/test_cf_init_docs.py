#!/usr/bin/env python3
"""Regression tests for cf-init command/skill guidance."""
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CF_INIT_DOCS = {
    "claude": ROOT / "src" / "adapters" / "claude" / "commands" / "cf-init.md",
    "costrict": ROOT / "src" / "adapters" / "costrict" / "commands" / "cf-init.md",
    "codex": ROOT / "src" / "adapters" / "codex" / "skills" / "cf-init" / "SKILL.md",
    "opencode": ROOT / "src" / "adapters" / "opencode" / "commands" / "cf-init.md",
}
INSTALLED_CF_INIT_DOCS = {
    "claude": ROOT / ".claude" / "commands" / "cf-init.md",
    "costrict": ROOT / ".costrict" / "commands" / "cf-init.md",
    "codex": ROOT / ".agents" / "skills" / "cf-init" / "SKILL.md",
    "opencode": ROOT / ".opencode" / "commands" / "cf-init.md",
}


def _read(platform: str) -> str:
    return CF_INIT_DOCS[platform].read_text(encoding="utf-8")


def test_cf_init_docs_share_core_initialization_quality_rules() -> None:
    required = [
        "不要只因为 `package.json` 存在就判定为前端",
        "不要复制或手写旧版 YAML",
        "`inject.compress: true`",
        "`inject.dedup_window: 5`",
        "`path_mapping.shared`",
        "shared/design/design-lite.md",
        "shared/design/design-frontend.md",
        "动态补 `frontend.patterns`",
        "证据优先",
        "禁止编造项目规范",
        'python3 -c "import yaml"',
    ]

    for platform in CF_INIT_DOCS:
        content = _read(platform)
        for phrase in required:
            assert phrase in content, f"{platform} missing {phrase!r}"


def test_cf_init_docs_do_not_contain_old_or_inconsistent_guidance() -> None:
    forbidden = [
        "读取 manually",
        "模板内容：",
        "直接写入",
        "只因为 `package.json` 存在 → 前端",
        "python3 -m pip install pyyaml\n```\n\n成功 → 继续",
        "|| stack",
    ]

    for platform in CF_INIT_DOCS:
        content = _read(platform)
        for phrase in forbidden:
            assert phrase not in content, f"{platform} still contains {phrase!r}"


def test_platform_specific_cf_init_sections_match_adapter_contracts() -> None:
    assert ".claude/settings.local.json" in _read("claude")
    assert "UserPromptSubmit" in _read("claude")
    assert "不得整文件覆盖" in _read("claude")

    assert ".costrict/settings.local.json" in _read("costrict")
    assert "UserPromptSubmit" in _read("costrict")
    assert "不得整文件覆盖" in _read("costrict")

    codex = _read("codex")
    assert ".codex/hooks.json" in codex
    assert ".codex/config.toml" in codex
    assert "hooks = true" in codex
    assert "codex_hooks = true" in codex
    assert "/hooks" in codex
    assert "不得整文件覆盖" in codex

    opencode = _read("opencode")
    assert "opencode.json" in opencode
    assert ".opencode/plugins/code-flow/" in opencode
    assert ".claude/settings.local.json" not in opencode
    assert "CLAUDE.md" not in opencode


def test_installed_cf_init_docs_match_adapter_templates() -> None:
    for platform, template_path in CF_INIT_DOCS.items():
        installed_path = INSTALLED_CF_INIT_DOCS[platform]
        template = template_path.read_text(encoding="utf-8")
        installed = installed_path.read_text(encoding="utf-8")
        assert installed == template, platform


def test_cf_init_docs_do_not_embed_full_l0_template() -> None:
    # L0 (CLAUDE.md / AGENTS.md) content has a single source of truth: the adapter
    # root template that `code-flow init` deploys. cf-init must only *reference* it,
    # never embed a copy — an embedded copy is exactly what drifts out of sync.
    for platform in CF_INIT_DOCS:
        assert "# Project Guidelines" not in _read(platform), platform


def test_costrict_adapter_docs_use_claude_md_for_l0() -> None:
    # Costrict is a Claude-compatible host: its L0 instruction file is CLAUDE.md,
    # so adapter command docs must never reference AGENTS.md (".agents/" paths are
    # a different token and unaffected).
    cmd_dir = ROOT / "src" / "adapters" / "costrict" / "commands"
    for md in sorted(cmd_dir.rglob("*.md")):
        assert "AGENTS.md" not in md.read_text(encoding="utf-8"), str(md.relative_to(ROOT))


def test_opencode_adapter_docs_use_agents_md_and_plugin() -> None:
    # OpenCode's L0 is AGENTS.md and injection runs through the code-flow plugin;
    # it has no PreToolUse Hook. Docs copied from the claude adapter must not
    # carry CLAUDE.md or PreToolUse over.
    cmd_dir = ROOT / "src" / "adapters" / "opencode" / "commands"
    for md in sorted(cmd_dir.rglob("*.md")):
        text = md.read_text(encoding="utf-8")
        rel = str(md.relative_to(ROOT))
        assert "CLAUDE.md" not in text, rel
        assert "PreToolUse" not in text, rel
