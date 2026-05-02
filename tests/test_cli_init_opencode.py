#!/usr/bin/env python3
"""CLI integration tests for OpenCode adapter deployment mode."""
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest


if not shutil.which("node"):
    pytest.skip("node is required for CLI tests", allow_module_level=True)


ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "src" / "cli.js"


def run_cli(tmp_path: Path, extra_args: list = None) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PIP_DISABLE_PIP_VERSION_CHECK"] = "1"
    args = ["node", str(CLI), "init", "--platform=opencode"]
    if extra_args:
        args.extend(extra_args)
    return subprocess.run(
        args,
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def test_opencode_init_deploys_agents_md_and_plugin(tmp_path: Path) -> None:
    """Fresh init must create AGENTS.md, opencode.json, plugin files, and commands."""
    result = run_cli(tmp_path)
    assert result.returncode == 0, result.stderr

    agents_md = tmp_path / "AGENTS.md"
    assert agents_md.exists()
    content = agents_md.read_text(encoding="utf-8")
    assert "code-flow" in content
    assert "Spec Loading" in content

    opencode_json = tmp_path / "opencode.json"
    assert opencode_json.exists()
    cfg = json.loads(opencode_json.read_text(encoding="utf-8"))
    assert "plugin" in cfg
    assert ".opencode/plugins/code-flow" in cfg["plugin"]

    plugin_dir = tmp_path / ".opencode" / "plugins" / "code-flow"
    assert plugin_dir.is_dir()
    assert (plugin_dir / "index.js").exists()
    assert (plugin_dir / "package.json").exists()

    # Command files
    commands_dir = tmp_path / ".opencode" / "commands"
    assert commands_dir.is_dir()
    assert (commands_dir / "cf-init.md").exists()
    assert (commands_dir / "cf-learn.md").exists()
    assert (commands_dir / "cf-scan.md").exists()
    assert (commands_dir / "cf-stats.md").exists()
    assert (commands_dir / "cf-validate.md").exists()
    assert (commands_dir / "cf-task" / "align.md").exists()
    assert (commands_dir / "cf-task" / "plan.md").exists()

    # Frontmatter present
    cf_init = (commands_dir / "cf-init.md").read_text(encoding="utf-8")
    assert cf_init.startswith("---\n")
    assert "description:" in cf_init

    assert "Created:" in result.stdout
    assert "AGENTS.md" in result.stdout
    assert "opencode.json" in result.stdout


def test_opencode_init_already_up_to_date(tmp_path: Path) -> None:
    """Second init without version change should report up to date."""
    first = run_cli(tmp_path)
    assert first.returncode == 0, first.stderr

    second = run_cli(tmp_path)
    assert second.returncode == 0, second.stderr
    assert "already up to date" in second.stdout


def test_opencode_upgrade_overwrites_tool_files(tmp_path: Path) -> None:
    """Upgrade must overwrite plugin and command files (tool category) but preserve user data."""
    first = run_cli(tmp_path)
    assert first.returncode == 0, first.stderr

    # Downgrade version to force upgrade path
    version_file = tmp_path / ".code-flow" / ".version"
    version_file.write_text("0.0.0\n", encoding="utf-8")

    # Modify a tool file — should be overwritten on upgrade
    plugin_index = tmp_path / ".opencode" / "plugins" / "code-flow" / "index.js"
    plugin_index.write_text("// user edited\n", encoding="utf-8")

    # Modify a command file — should be overwritten on upgrade (tool category)
    cmd_init = tmp_path / ".opencode" / "commands" / "cf-init.md"
    cmd_init.write_text("stale content\n", encoding="utf-8")

    # Modify AGENTS.md — should be merge-skipped (user content preserved)
    agents_md = tmp_path / "AGENTS.md"
    original = agents_md.read_text(encoding="utf-8")
    agents_md.write_text(original + "\n## My Custom Section\ncustom content\n", encoding="utf-8")

    second = run_cli(tmp_path)
    assert second.returncode == 0, second.stderr

    # Tool files were overwritten
    assert plugin_index.read_text(encoding="utf-8") != "// user edited\n"
    assert "import {" in plugin_index.read_text(encoding="utf-8")
    assert cmd_init.read_text(encoding="utf-8") != "stale content\n"
    assert cmd_init.read_text(encoding="utf-8").startswith("---\n")

    # User section in merge file was preserved
    final_agents = agents_md.read_text(encoding="utf-8")
    assert "My Custom Section" in final_agents


def test_opencode_init_invalid_platform_rejected(tmp_path: Path) -> None:
    """Invalid platform must fail with clear error."""
    env = os.environ.copy()
    result = subprocess.run(
        ["node", str(CLI), "init", "--platform=invalid"],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert "opencode" in result.stderr  # shows valid options


def test_opencode_init_force_overwrites_all(tmp_path: Path) -> None:
    """--force must overwrite all files including merge-typed ones."""
    first = run_cli(tmp_path)
    assert first.returncode == 0, first.stderr

    agents_md = tmp_path / "AGENTS.md"
    agents_md.write_text("# completely different\n", encoding="utf-8")

    opencode_json = tmp_path / "opencode.json"
    opencode_json.write_text('{"$schema": "https://opencode.ai/config.json", "plugin": ["other"]}\n', encoding="utf-8")

    result = run_cli(tmp_path, extra_args=["--force"])
    assert result.returncode == 0, result.stderr

    assert "# completely different" not in agents_md.read_text(encoding="utf-8")
    cfg = json.loads(opencode_json.read_text(encoding="utf-8"))
    assert ".opencode/plugins/code-flow" in cfg["plugin"]
