#!/usr/bin/env python3
"""[S-11] Canonical command surface, four-platform parity and 0.8 release docs.

真实边界：真实 adapters/部署副本、真实 `code-flow init` 安装产物、真实运行时事务迁移。
"""

import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "src/cli.js"
CATALOG = ROOT / "src/adapters/commands.json"

USER_COMMANDS = {
    "cf-init",
    "cf-learn",
    "cf-spec",
    "cf-stats",
    "cf-task-prd",
    "cf-task-align",
    "cf-task-plan",
    "cf-task-start",
    "cf-task-status",
    "cf-task-archive",
    "cf-task-verify-e2e",
}
ALIASES = {
    "cf-task-note": ("cf-task-status", "--notes"),
    "cf-task-block": ("cf-task-status", "--block"),
    "cf-task-graph": ("cf-task-status", "--graph"),
    "cf-validate": ("cf-task-verify-e2e", "--checks"),
}
INTERNAL = {"cf-sync"}


def _catalog() -> dict:
    return json.loads(CATALOG.read_text(encoding="utf-8"))


def _entry_file(platform: str, entry: dict) -> str:
    relative = entry["file"]
    if platform == "codex":
        return f"src/adapters/codex/skills/{relative[:-3].replace('/', '-')}/SKILL.md"
    return f"src/adapters/{platform}/commands/{relative}"


def _deploy_file(platform: str, entry: dict) -> str:
    relative = entry["file"]
    if platform == "codex":
        return f".agents/skills/{relative[:-3].replace('/', '-')}/SKILL.md"
    return f".{platform}/commands/{relative}"


def _command_ids(platform: str, install: bool = False) -> set[str]:
    base = (ROOT / (f".{platform}/commands" if install else f"src/adapters/{platform}/commands"))
    if platform == "codex":
        base = ROOT / (".agents/skills" if install else "src/adapters/codex/skills")
        return {path.parent.name for path in base.glob("*/SKILL.md")}
    ids = set()
    for path in base.rglob("*.md"):
        relative = path.relative_to(base).as_posix()
        if relative.startswith("cf-task/"):
            ids.add(f"cf-task-{Path(relative).stem}")
        elif "/" not in relative:
            ids.add(Path(relative).stem)
    return ids


def test_command_surface_catalog_has_9_to_11_user_commands() -> None:
    catalog = _catalog()
    assert catalog["schema_version"] == 1
    assert catalog["content_canonical"] == "claude"
    entries = catalog["commands"]
    by_kind = {kind: {item["id"] for item in entries if item["kind"] == kind}
               for kind in ("user", "alias", "internal")}
    assert by_kind["user"] == USER_COMMANDS
    assert 9 <= len(by_kind["user"]) <= 11, f"用户命令应为 9-11 条，实际 {len(by_kind['user'])}"
    assert by_kind["alias"] == set(ALIASES)
    assert by_kind["internal"] == INTERNAL
    assert len(entries) == 16, "0.8 仅收敛用户命令面，不丢弃兼容文件"

    aliases = {item["id"]: item for item in entries if item["kind"] == "alias"}
    for command, (target, flag) in ALIASES.items():
        assert aliases[command]["alias_of"] == target
        assert aliases[command]["alias_flag"] == flag

    status = next(item for item in entries if item["id"] == "cf-task-status")
    assert status["subactions"] == ["--notes", "--block", "--graph"]


def test_four_platform_sources_match_canonical_catalog() -> None:
    entries = _catalog()["commands"]
    for platform in ("claude", "codex", "costrict", "opencode"):
        expected = {item["id"] for item in entries}
        assert _command_ids(platform) == expected, f"{platform} 源命令集与 canonical 目录不一致"
        for item in entries:
            assert (ROOT / _entry_file(platform, item)).is_file(), (
                f"{platform} 缺 {item['id']} 的命令文件")


def test_four_platform_deploy_copies_match_canonical_catalog() -> None:
    entries = _catalog()["commands"]
    for platform in ("claude", "codex", "costrict", "opencode"):
        expected = {item["id"] for item in entries}
        assert _command_ids(platform, install=True) == expected, (
            f"{platform} 部署副本命令集与 canonical 目录不一致；请运行 code-flow init")
        for item in entries:
            source = (ROOT / _entry_file(platform, item)).read_text(encoding="utf-8")
            deployed = (ROOT / _deploy_file(platform, item)).read_text(encoding="utf-8")
            assert source == deployed, f"{platform}/{item['id']}: 部署副本与源不同步"


def test_alias_commands_declare_one_minor_compatibility_window() -> None:
    entries = [item for item in _catalog()["commands"] if item["kind"] == "alias"]
    for platform in ("claude", "codex", "costrict", "opencode"):
        for item in entries:
            text = (ROOT / _entry_file(platform, item)).read_text(encoding="utf-8")
            assert "命令面状态（0.8）" in text, f"{platform}/{item['id']}: 缺命令面状态标注"
            assert "0.9.0" in text, f"{platform}/{item['id']}: 缺移除版本"
            assert item["alias_of"] in text, f"{platform}/{item['id']}: 缺等价命令"
            assert item["alias_flag"] in text, f"{platform}/{item['id']}: 缺别名参数"


def test_user_command_docs_describe_subactions_and_internal_scope() -> None:
    status = (ROOT / "src/adapters/claude/commands/cf-task/status.md").read_text(encoding="utf-8")
    for flag in ("--notes", "--block", "--graph"):
        assert flag in status, f"task status 缺子动作 {flag}"
    sync = (ROOT / "src/adapters/claude/commands/cf-sync.md").read_text(encoding="utf-8")
    assert "命令面状态（0.8）" in sync
    assert "internal" in sync.lower(), "cf-sync 必须标注 internal/dev-only"


def test_usage_and_migration_docs_cover_0_8_surface() -> None:
    usage = (ROOT / "docs/USAGE.md").read_text(encoding="utf-8")
    for command in sorted(USER_COMMANDS | set(ALIASES)):
        assert command in usage or command.replace("cf-task-", "cf-task:") in usage, (
            f"USAGE 缺命令 {command}")
    assert "cf-sync" in usage
    assert "migrations/runtime-0.8.0.md" in usage

    migration = ROOT / "docs/migrations/runtime-0.8.0.md"
    text = migration.read_text(encoding="utf-8")
    for keyword in ("0.8.0", "manifest v3", "evidence sidecar", "状态机", "回滚", "别名",
                    "provisional", "env_blocked", "migrate --runtime --dry-run",
                    "migrate --runtime --rollback"):
        assert keyword in text, f"迁移指南缺 {keyword!r}"

    package = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
    assert package["version"] == "0.8.0"
    assert "docs/migrations/runtime-0.8.0.md" in package["files"]
    assert set(package["dependencies"]) == {"@ccusage/codex"}, "不得新增 npm 运行时依赖"


def _cli(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["node", str(CLI), *args], cwd=root, text=True,
                          capture_output=True, timeout=120, env=dict(os.environ))


def test_runtime_migration_dry_run_apply_and_rollback(tmp_path: Path) -> None:
    result = _cli(tmp_path, "init", "--platform=claude")
    assert result.returncode == 0, result.stderr + result.stdout
    version_file = tmp_path / ".code-flow/.version"
    manifest_file = tmp_path / ".code-flow/.runtime-install.json"
    version_file.write_text("0.7.0\n", encoding="utf-8")
    manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    manifest["version"] = "0.7.0"
    manifest_file.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    preview = _cli(tmp_path, "migrate", "--runtime", "--dry-run")
    assert preview.returncode == 0, preview.stderr + preview.stdout
    previewed = json.loads(preview.stdout)
    assert previewed["status"] == "previewed"
    assert version_file.read_text(encoding="utf-8").strip() == "0.7.0", "dry-run 不得写入目标"

    applied = _cli(tmp_path, "migrate", "--runtime", "--apply")
    assert applied.returncode == 0, applied.stderr + applied.stdout
    committed = json.loads(applied.stdout)
    assert committed["status"] == "committed"
    assert version_file.read_text(encoding="utf-8").strip() == "0.8.0"

    rolled_back = _cli(tmp_path, "migrate", "--runtime", "--rollback", committed["migration_id"])
    assert rolled_back.returncode == 4, rolled_back.stderr + rolled_back.stdout
    assert json.loads(rolled_back.stdout)["status"] == "rolled_back"
    assert version_file.read_text(encoding="utf-8").strip() == "0.7.0"


def test_spec_doctor_help_is_served_by_real_parser(tmp_path: Path) -> None:
    # 使用真实安装产物，确认 spec doctor 已进入运行时命令契约。
    result = _cli(tmp_path, "init", "--platform=codex")
    assert result.returncode == 0, result.stderr + result.stdout
    doctor = _cli(tmp_path, "spec", "doctor", "--help")
    assert doctor.returncode == 0, doctor.stderr + doctor.stdout
    assert doctor.stdout.lower().startswith("usage: code-flow spec")
