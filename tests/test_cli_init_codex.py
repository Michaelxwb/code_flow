#!/usr/bin/env python3
"""CLI integration tests for Codex skill deployment mode."""
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
        ["node", str(CLI), "init", "--platform=codex"],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def test_codex_init_deploys_skills_and_upgrade_overwrites_tool_files(tmp_path: Path) -> None:
    first = run_cli(tmp_path)
    assert first.returncode == 0, first.stderr

    cf_init_skill = tmp_path / ".agents" / "skills" / "cf-init" / "SKILL.md"
    assert cf_init_skill.exists()
    lane_skills = [
        "cf-lane-new",
        "cf-lane-list",
        "cf-lane-status",
        "cf-lane-sync",
        "cf-lane-close",
        "cf-lane-cancel",
        "cf-lane-check-merge",
        "cf-lane-doctor",
    ]
    for skill in lane_skills:
        assert (tmp_path / ".agents" / "skills" / skill / "SKILL.md").exists()
    assert not (tmp_path / ".codex" / "prompts").exists()

    cf_init_skill.write_text("SENTINEL\n", encoding="utf-8")
    lane_new_skill = tmp_path / ".agents" / "skills" / "cf-lane-new" / "SKILL.md"
    lane_new_skill.write_text("SENTINEL_LANE\n", encoding="utf-8")
    version_file = tmp_path / ".code-flow" / ".version"
    version_file.write_text("0.0.0\n", encoding="utf-8")

    second = run_cli(tmp_path)
    assert second.returncode == 0, second.stderr
    assert cf_init_skill.read_text(encoding="utf-8") != "SENTINEL\n"
    assert lane_new_skill.read_text(encoding="utf-8") != "SENTINEL_LANE\n"


def test_codex_init_removes_non_empty_legacy_claude_skills_dir(tmp_path: Path) -> None:
    legacy_skill_file = tmp_path / ".claude" / "skills" / "legacy" / "SKILL.md"
    legacy_skill_file.parent.mkdir(parents=True)
    legacy_skill_file.write_text("legacy\n", encoding="utf-8")

    result = run_cli(tmp_path)
    assert result.returncode == 0, result.stderr
    assert not (tmp_path / ".claude" / "skills").exists()
    assert "Removed (deprecated):" in result.stdout
    assert ".claude/skills/" in result.stdout
