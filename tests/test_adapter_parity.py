#!/usr/bin/env python3
"""跨平台命令对等性守门：防止任一平台拿到降级/走样版命令。

策略（见 .code-flow/specs/cli/code-standards.md「canonical 源 + 适配白名单」）：
- claude 是 cf-* 命令的内容 canonical 源。
- costrict 与 claude 架构相同（CLAUDE.md / `/project:` / 同一套工具），平台中立命令
  必须与 claude 逐字相同；只有 cf-init / cf-inject 含合法平台路径差异（白名单排除）。
- 部署副本必须与适配器源同步。
"""

import json
import re
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "src/adapters/commands.json"

CF_TASK = ["align", "archive", "block", "graph", "note", "plan", "prd", "start", "status", "verify-e2e"]

# 平台中立命令：costrict 必须与 claude 逐字相同（无任何合法平台 token 差异）
COSTRICT_IDENTICAL = [
    "cf-learn.md",
    "cf-stats.md",
    "cf-spec.md",
    "cf-sync.md",
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
    "cf-task/verify-e2e.md",
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


def test_four_platform_spec_workflow_entrypoints_and_deploy_copies() -> None:
    source_deploy = (
        ("src/adapters/claude/commands/cf-spec.md", ".claude/commands/cf-spec.md"),
        ("src/adapters/costrict/commands/cf-spec.md", ".costrict/commands/cf-spec.md"),
        ("src/adapters/opencode/commands/cf-spec.md", ".opencode/commands/cf-spec.md"),
        ("src/adapters/codex/skills/cf-spec/SKILL.md", ".agents/skills/cf-spec/SKILL.md"),
    )
    required = ("migrate --plan", "spec-context.yml", "refresh", "doctor", "prepared")
    for source, deployed in source_deploy:
        source_text = _read(source)
        assert source_text == _read(deployed)
        assert all(item in source_text for item in required)
    for root in ("src/adapters", ".claude", ".costrict", ".opencode", ".agents"):
        assert not [path for path in (ROOT / root).rglob("*cf-inject*") if path.is_file()]


def _catalog() -> dict:
    return json.loads(CATALOG.read_text(encoding="utf-8"))


def _surface_ids(platform: str, installed: bool = False) -> set[str]:
    if platform == "codex":
        base = ROOT / (".agents/skills" if installed else "src/adapters/codex/skills")
        return {path.parent.name for path in base.glob("*/SKILL.md")}
    base = ROOT / (f".{platform}/commands" if installed else f"src/adapters/{platform}/commands")
    ids: set[str] = set()
    for path in base.rglob("*.md"):
        relative = path.relative_to(base).as_posix()
        if relative.startswith("cf-task/"):
            ids.add(f"cf-task-{Path(relative).stem}")
        elif "/" not in relative:
            ids.add(Path(relative).stem)
    return ids


def test_s11_command_surface_converges_to_9_to_11_user_commands() -> None:
    """[S-11] 用户命令 9-11 条；note/block/graph/validate 保留为别名，sync 为 internal。"""
    entries = _catalog()["commands"]
    users = [item["id"] for item in entries if item["kind"] == "user"]
    aliases = {item["id"]: item for item in entries if item["kind"] == "alias"}
    internal = [item["id"] for item in entries if item["kind"] == "internal"]
    assert 9 <= len(users) <= 11, f"用户命令应为 9-11 条，实际 {len(users)}"
    assert set(users) == {
        "cf-init", "cf-learn", "cf-spec", "cf-stats", "cf-task-prd", "cf-task-align",
        "cf-task-plan", "cf-task-start", "cf-task-status", "cf-task-archive",
        "cf-task-verify-e2e",
    }
    assert set(aliases) == {"cf-task-note", "cf-task-block", "cf-task-graph", "cf-validate"}
    assert aliases["cf-task-note"]["alias_of"] == "cf-task-status"
    assert aliases["cf-validate"]["alias_of"] == "cf-task-verify-e2e"
    assert internal == ["cf-sync"]
    assert len(entries) == len(users) + len(aliases) + len(internal) == 16


def test_s11_four_platform_install_surface_matches_catalog() -> None:
    """[S-11] 四平台安装产物命令集一致；旧别名文件仍可调用。"""
    expected = {item["id"] for item in _catalog()["commands"]}
    for platform in ("claude", "codex", "costrict", "opencode"):
        assert _surface_ids(platform) == expected, f"{platform} 源命令集漂移"
        assert _surface_ids(platform, installed=True) == expected, f"{platform} 部署命令集漂移"
    for platform in ("claude", "codex", "costrict", "opencode"):
        for alias in ("cf-task-note", "cf-task-block", "cf-task-graph", "cf-validate"):
            if platform == "codex":
                path = ROOT / f".agents/skills/{alias}/SKILL.md"
            else:
                name = alias.removeprefix("cf-task-")
                relative = f"cf-task/{name}.md" if alias.startswith("cf-task-") else f"{alias}.md"
                path = ROOT / f".{platform}/commands/{relative}"
            assert path.is_file(), f"{platform} 缺旧别名 {alias}"
            assert "0.9.0" in path.read_text(encoding="utf-8")


def test_opencode_core_task_workflow_has_all_context_gates() -> None:
    phrases = {
        "prd": ("catalog --stage prd", "PRD Gate"),
        "align": ("refresh --task-dir", "Design Gate"),
        "plan": ("--stage plan --artifact", "Context Plan"),
        "start": ("code-flow task start", "Context hash"),
        "archive": ("code-flow spec gate", "spec-context.yml"),
    }
    for command, required in phrases.items():
        text = _read(f"src/adapters/opencode/commands/cf-task/{command}.md")
        assert all(item in text for item in required), f"opencode {command} 缺 Context/Gate 步骤"


GENERATOR = ROOT / "src/render-runtime-contract.js"


def _run_generator(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["node", str(GENERATOR), *args], capture_output=True, text=True, timeout=30)


def _minimal_generator_repo(tmp_path: Path) -> Path:
    """复制生成器所需的最小真实输入：四平台正文 + 运行时命令注册表。"""
    root = tmp_path / "repo"
    shutil.copytree(ROOT / "src/adapters", root / "src/adapters")
    registry = root / "src/core/code-flow/runtime-commands.json"
    registry.parent.mkdir(parents=True)
    shutil.copy(ROOT / "src/core/code-flow/runtime-commands.json", registry)
    return root


def _adapter_bytes(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in (root / "src/adapters").rglob("*.md")
    }


def test_s09_generated_platform_bodies_have_no_drift() -> None:
    """Codex/Costrict/OpenCode 正文由 canonical Claude 生成；仓库内生成物不得手工漂移。"""
    result = _run_generator("--check")
    assert result.returncode == 0, result.stdout + result.stderr


def test_s09_generator_check_detects_body_drift(tmp_path: Path) -> None:
    root = _minimal_generator_repo(tmp_path)
    target = root / "src/adapters/opencode/commands/cf-task/prd.md"
    target.write_text(target.read_text(encoding="utf-8") + "\n<!-- injected drift -->\n", encoding="utf-8")
    result = _run_generator("--check", "--root", str(root))
    assert result.returncode != 0, result.stdout + result.stderr
    assert "cf-task/prd.md" in result.stdout + result.stderr


def test_s09_generator_is_idempotent_and_preserves_bodies(tmp_path: Path) -> None:
    root = _minimal_generator_repo(tmp_path)
    expected = _adapter_bytes(root)
    tampered = root / "src/adapters/codex/skills/cf-task-prd/SKILL.md"
    tampered.write_text("tampered\n", encoding="utf-8")

    regenerated = _run_generator("--root", str(root))
    assert regenerated.returncode == 0, regenerated.stdout + regenerated.stderr
    assert _adapter_bytes(root) == expected, "生成结果必须与当前正文逐字一致"

    second = _run_generator("--root", str(root))
    assert second.returncode == 0, second.stdout + second.stderr
    assert _adapter_bytes(root) == expected, "生成必须幂等"
    assert _run_generator("--check", "--root", str(root)).returncode == 0


def test_s09_generator_preserves_examples_errors_and_steps(tmp_path: Path) -> None:
    """适配不得借生成删掉示例块、错误信息或步骤说明。"""
    root = _minimal_generator_repo(tmp_path)
    assert _run_generator("--root", str(root)).returncode == 0
    checks = {
        "src/adapters/codex/skills/cf-task-start/SKILL.md": ("code-flow:runtime-commands start", "#NOTES"),
        "src/adapters/opencode/commands/cf-task/prd.md": ("code-flow:runtime-commands start", "PRD"),
        "src/adapters/costrict/commands/cf-task/verify-e2e.md": ("code-flow:runtime-commands start", "deferred E2E"),
        "src/adapters/opencode/commands/cf-init.md": ("### 6. 生成 OpenCode 插件配置", "opencode.json"),
        "src/adapters/codex/skills/cf-init/SKILL.md": ("### 6. 生成 .codex/hooks.json 和 .codex/config.toml", "apply_patch"),
    }
    for relative, markers in checks.items():
        text = (root / relative).read_text(encoding="utf-8")
        for marker in markers:
            assert marker in text, f"{relative} 丢失内容 {marker!r}"


def test_s09_generator_uses_only_node_builtins() -> None:
    text = GENERATOR.read_text(encoding="utf-8")
    requires = re.findall(r"""require\(['"]([^'"]+)['"]\)""", text)
    assert requires, "生成器应声明所需模块"
    for name in requires:
        assert name.startswith(".") or name in {"fs", "path", "assert", "os", "crypto"}, name
