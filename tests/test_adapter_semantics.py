#!/usr/bin/env python3
"""[S-11] 跨平台命令语义绑定守门：行数相近≠行为一致。

逐平台断言关键语义绑定存在（canonical claude 定义 + 三平台适配 + 四部署副本）。
"""
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

PLATFORMS = ("claude", "costrict", "opencode", "codex")

SRC = {
    "claude": ROOT / "src/adapters/claude/commands/cf-task",
    "costrict": ROOT / "src/adapters/costrict/commands/cf-task",
    "opencode": ROOT / "src/adapters/opencode/commands/cf-task",
    "codex": ROOT / "src/adapters/codex/skills",
}
DEPLOY = {
    "claude": ROOT / ".claude/commands/cf-task",
    "costrict": ROOT / ".costrict/commands/cf-task",
    "opencode": ROOT / ".opencode/commands/cf-task",
    "codex": ROOT / ".agents/skills",
}


def _path(platform: str, base: Path, command: str) -> Path:
    if platform == "codex":
        return base / f"cf-task-{command}" / "SKILL.md"
    return base / f"{command}.md"


# command -> ((platforms sharing one binding phrase), phrase)
BINDINGS = {
    "start": (PLATFORMS, "workflow service"),
    "block": (PLATFORMS, "active block"),
    "verify-e2e": (PLATFORMS, "--only-e2e"),
    "archive": (PLATFORMS, "verified"),
    "graph": (PLATFORMS, "cf_task_index"),
}


def test_semantic_bindings_present_in_source_and_deploy() -> None:
    for command, (platforms, phrase) in BINDINGS.items():
        for platform in platforms:
            for base in (SRC[platform], DEPLOY[platform]):
                path = _path(platform, base, command)
                assert path.is_file(), f"{platform} 缺命令: {path}"
                assert phrase in path.read_text(encoding="utf-8"), (
                    f"{path} 缺语义绑定 {phrase!r}（疑似平台降级/走样）"
                )


def test_verify_e2e_present_on_all_platforms() -> None:
    for platform in PLATFORMS:
        for base in (SRC[platform], DEPLOY[platform]):
            assert _path(platform, base, "verify-e2e").is_file()
