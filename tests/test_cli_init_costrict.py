#!/usr/bin/env python3
"""CLI integration tests for Costrict adapter deployment mode."""
import os
import shutil
import subprocess
from pathlib import Path

import pytest


if not shutil.which("node"):
    pytest.skip("node is required for CLI tests", allow_module_level=True)


ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "src" / "cli.js"


def run_cli(tmp_path: Path) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PIP_DISABLE_PIP_VERSION_CHECK"] = "1"
    return subprocess.run(
        ["node", str(CLI), "init", "--platform=costrict"],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def test_costrict_init_deploys_commands_and_settings(tmp_path: Path) -> None:
    first = run_cli(tmp_path)
    assert first.returncode == 0, first.stderr

    # L0 file
    costrict_md = tmp_path / "AGENTS.md"
    assert costrict_md.exists()

    # Commands directory
    cf_init_cmd = tmp_path / ".costrict" / "commands" / "cf-init.md"
    assert cf_init_cmd.exists()

    # Settings
    settings = tmp_path / ".costrict" / "settings.local.json"
    assert settings.exists()

    # Core files
    config_yml = tmp_path / ".code-flow" / "config.yml"
    assert config_yml.exists()

    # Task commands
    cf_task_plan = tmp_path / ".costrict" / "commands" / "cf-task" / "plan.md"
    assert cf_task_plan.exists()


def test_costrict_init_upgrade_overwrites_tool_files(tmp_path: Path) -> None:
    first = run_cli(tmp_path)
    assert first.returncode == 0, first.stderr

    cf_init_cmd = tmp_path / ".costrict" / "commands" / "cf-init.md"
    assert cf_init_cmd.exists()
    cf_init_cmd.write_text("SENTINEL\n", encoding="utf-8")

    version_file = tmp_path / ".code-flow" / ".version"
    version_file.write_text("0.0.0\n", encoding="utf-8")

    second = run_cli(tmp_path)
    assert second.returncode == 0, second.stderr
    # Tool files should be overwritten on upgrade
    assert cf_init_cmd.read_text(encoding="utf-8") != "SENTINEL\n"


def test_costrict_init_preserves_merge_files_on_upgrade(tmp_path: Path) -> None:
    first = run_cli(tmp_path)
    assert first.returncode == 0, first.stderr

    costrict_md = tmp_path / "AGENTS.md"
    original_content = costrict_md.read_text(encoding="utf-8")
    # Add user customization
    modified_content = original_content + "\n## Custom Section\n- My custom rule\n"
    costrict_md.write_text(modified_content, encoding="utf-8")

    version_file = tmp_path / ".code-flow" / ".version"
    version_file.write_text("0.0.0\n", encoding="utf-8")

    second = run_cli(tmp_path)
    assert second.returncode == 0, second.stderr
    # AGENTS.md should be merged, not overwritten
    current = costrict_md.read_text(encoding="utf-8")
    assert "## Custom Section" in current
    assert "- My custom rule" in current


def test_costrict_init_removes_legacy_claude_skills_dir(tmp_path: Path) -> None:
    legacy_skill_file = tmp_path / ".claude" / "skills" / "legacy" / "SKILL.md"
    legacy_skill_file.parent.mkdir(parents=True)
    legacy_skill_file.write_text("legacy\n", encoding="utf-8")

    result = run_cli(tmp_path)
    assert result.returncode == 0, result.stderr
    assert not (tmp_path / ".claude" / "skills").exists()
    assert "Removed (deprecated):" in result.stdout
    assert ".claude/skills/" in result.stdout


def test_costrict_settings_has_hooks(tmp_path: Path) -> None:
    result = run_cli(tmp_path)
    assert result.returncode == 0, result.stderr

    settings = tmp_path / ".costrict" / "settings.local.json"
    content = settings.read_text(encoding="utf-8")
    assert "PreToolUse" in content
    assert "SessionStart" in content
    assert "cf_inject_hook.py" in content
    assert "cf_session_hook.py" in content


def test_costrict_invalid_platform_fails(tmp_path: Path) -> None:
    env = os.environ.copy()
    env["PIP_DISABLE_PIP_VERSION_CHECK"] = "1"
    result = subprocess.run(
        ["node", str(CLI), "init", "--platform=invalid"],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert "invalid" in result.stderr
