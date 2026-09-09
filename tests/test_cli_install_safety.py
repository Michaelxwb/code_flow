#!/usr/bin/env python3
"""[S-01][E-01][B-01] 安装内容保护与平台版本分离回归测试。

真实边界：真实 FS + 真实 `node src/cli.js init` 子进程（无 mock）。
"""
import os
import shutil
import subprocess
from pathlib import Path

import pytest


if not shutil.which("node"):
    pytest.skip("node is required for CLI tests", allow_module_level=True)


ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "src" / "cli.js"


def run_cli(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PIP_DISABLE_PIP_VERSION_CHECK"] = "1"
    return subprocess.run(
        ["node", str(CLI), *args],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def test_fresh_init_preserves_user_claude_skills(tmp_path: Path) -> None:
    """[S-01] fresh init 不得删除用户自建 skill。"""
    custom = tmp_path / ".claude" / "skills" / "my-custom-skill" / "SKILL.md"
    custom.parent.mkdir(parents=True)
    custom.write_text("# my skill\n", encoding="utf-8")

    result = run_cli(tmp_path, "init", "--platform=claude")
    assert result.returncode == 0, result.stderr
    assert custom.is_file(), "用户自建 skill 在 fresh init 后必须保留"
    assert custom.read_text(encoding="utf-8") == "# my skill\n"


def test_upgrade_and_cross_platform_init_preserve_user_skills(tmp_path: Path) -> None:
    """[S-01] upgrade 与跨平台 init 同样不得删除用户 skill。"""
    custom = tmp_path / ".claude" / "skills" / "my-custom-skill" / "SKILL.md"
    custom.parent.mkdir(parents=True)
    custom.write_text("# my skill\n", encoding="utf-8")
    assert run_cli(tmp_path, "init", "--platform=claude").returncode == 0

    (tmp_path / ".code-flow" / ".version").write_text("0.0.1\n", encoding="utf-8")
    upgrade = run_cli(tmp_path, "init", "--platform=claude")
    assert upgrade.returncode == 0, upgrade.stderr
    assert custom.is_file(), "用户自建 skill 在 upgrade 后必须保留"

    cross = run_cli(tmp_path, "init", "--platform=codex")
    assert cross.returncode == 0, cross.stderr
    assert custom.is_file(), "跨平台 init（codex）不得删除 .claude 下用户 skill"


def test_managed_legacy_skill_removed_with_backup_user_kept(tmp_path: Path) -> None:
    """[E-01] 受管旧文件删除并备份，用户文件保留。"""
    legacy = tmp_path / ".claude" / "skills" / "cf-stats.md"
    legacy.parent.mkdir(parents=True)
    legacy.write_text("# legacy managed\n", encoding="utf-8")
    custom = tmp_path / ".claude" / "skills" / "my-custom-skill" / "SKILL.md"
    custom.parent.mkdir(parents=True)
    custom.write_text("# mine\n", encoding="utf-8")

    result = run_cli(tmp_path, "init", "--platform=claude")
    assert result.returncode == 0, result.stderr
    assert not legacy.exists(), "受管旧文件应被清理"
    assert custom.is_file(), "用户文件必须保留"
    backups = list((tmp_path / ".code-flow" / "backups").rglob("cf-stats.md"))
    assert backups, "受管旧文件删除前必须进备份"
    assert backups[0].read_text(encoding="utf-8") == "# legacy managed\n"


def test_nested_user_skill_dirs_preserved(tmp_path: Path) -> None:
    """[B-01] 深嵌套用户 skill 目录保留。"""
    deep = tmp_path / ".claude" / "skills" / "team" / "nested" / "SKILL.md"
    deep.parent.mkdir(parents=True)
    deep.write_text("# deep\n", encoding="utf-8")

    result = run_cli(tmp_path, "init", "--platform=claude")
    assert result.returncode == 0, result.stderr
    assert deep.is_file()


def test_per_platform_upgrade_updates_stale_codex_command(tmp_path: Path) -> None:
    """[S-01] 先升 Claude 再 init Codex，旧 Codex 命令必须更新（平台版本分离）。"""
    import json

    assert run_cli(tmp_path, "init", "--platform=claude").returncode == 0
    assert run_cli(tmp_path, "init", "--platform=codex").returncode == 0
    skill = tmp_path / ".agents" / "skills" / "cf-init" / "SKILL.md"
    skill.write_text("SENTINEL\n", encoding="utf-8")
    # 模拟旧版 Codex 安装：全局版本已最新，但 codex adapter 记录停留在旧版
    adapter_versions = tmp_path / ".code-flow" / ".adapter-versions.json"
    data = json.loads(adapter_versions.read_text(encoding="utf-8"))
    data["adapters"]["codex"] = "0.0.1"
    adapter_versions.write_text(json.dumps(data), encoding="utf-8")

    result = run_cli(tmp_path, "init", "--platform=codex")
    assert result.returncode == 0, result.stderr
    assert skill.read_text(encoding="utf-8") != "SENTINEL\n"
