#!/usr/bin/env python3
"""跨平台命令对等性守门：防止任一平台拿到降级/走样版命令。

策略（见 .code-flow/specs/cli/code-standards.md「canonical 源 + 适配白名单」）：
- claude 是 cf-* 命令的内容 canonical 源。
- costrict 与 claude 架构相同（CLAUDE.md / `/project:` / 同一套工具），平台中立命令
  必须与 claude 逐字相同；只有 cf-init / cf-inject 含合法平台路径差异（白名单排除）。
- 部署副本必须与适配器源同步。
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

CF_TASK = ["align", "archive", "block", "graph", "note", "plan", "prd", "start", "status"]

# 平台中立命令：costrict 必须与 claude 逐字相同（无任何合法平台 token 差异）
COSTRICT_IDENTICAL = [
    "cf-learn.md",
    "cf-stats.md",
    "cf-validate.md",
    "cf-task/align.md",
    "cf-task/archive.md",
    "cf-task/block.md",
    "cf-task/graph.md",
    "cf-task/note.md",
    "cf-task/plan.md",
    "cf-task/prd.md",
    "cf-task/start.md",
    "cf-task/status.md",
]

# 含合法平台路径差异（.claude↔.costrict / --platform）的命令，仅做内容存在性回归
COSTRICT_PRESENCE = {
    "cf-init.md": ["permissions、settings"],  # 曾漏 permissions 导致 hook 合并丢配置
}


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_costrict_neutral_commands_identical_to_claude() -> None:
    for cmd in COSTRICT_IDENTICAL:
        claude = _read(f"src/adapters/claude/commands/{cmd}")
        costrict = _read(f"src/adapters/costrict/commands/{cmd}")
        assert claude == costrict, f"{cmd}: costrict 与 claude 不一致（疑似平台降级/走样）"


def test_costrict_path_commands_retain_key_content() -> None:
    for cmd, phrases in COSTRICT_PRESENCE.items():
        text = _read(f"src/adapters/costrict/commands/{cmd}")
        for phrase in phrases:
            assert phrase in text, f"{cmd}: costrict 缺失关键内容 {phrase!r}"


def test_costrict_deploy_copies_match_source() -> None:
    for cmd in COSTRICT_IDENTICAL + list(COSTRICT_PRESENCE):
        src = _read(f"src/adapters/costrict/commands/{cmd}")
        deploy = _read(f".costrict/commands/{cmd}")
        assert src == deploy, f"{cmd}: costrict 部署副本与源不同步"


def _nonblank(text: str) -> int:
    return len([ln for ln in text.splitlines() if ln.strip()])


def _strip_frontmatter(text: str) -> str:
    return re.sub(r"^---\n.*?\n---\n", "", text, count=1, flags=re.DOTALL)


def test_codex_cf_task_not_content_degraded() -> None:
    """codex cf-task skill 从 claude(canonical) 适配而来，只许做平台适配、不许借适配删内容。

    codex 仅去掉 H1+一行描述并加 frontmatter，正文应与 claude 基本等量；
    显著偏短 = 平台降级（曾经 cf-task 系列被砍掉示例块/输出块/说明）。
    """
    for c in CF_TASK:
        claude = _nonblank(_read(f"src/adapters/claude/commands/cf-task/{c}.md"))
        codex = _nonblank(_strip_frontmatter(_read(f"src/adapters/codex/skills/cf-task-{c}/SKILL.md")))
        ratio = codex / claude
        assert ratio >= 0.85, f"cf-task-{c}: codex 正文仅为 claude 的 {ratio:.0%}，疑似平台降级"
