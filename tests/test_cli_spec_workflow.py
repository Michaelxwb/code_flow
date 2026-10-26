#!/usr/bin/env python3
"""CLI dispatcher integration for the spec workflow migration."""

import hashlib
import json
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "src/cli.js"


SPEC = """---
id: app-rules
description: App rules
stages: [design, plan, code]
enforcement: required
verifiers:
  - rule: RULE-app-001
    type: test
    config:
      argv: [python3, -m, pytest]
---
# App
## Rules
- [RULE-app-001] Keep compatible.
"""


def _project(tmp_path: Path) -> None:
    flow = tmp_path / ".code-flow"
    (flow / "specs/app").mkdir(parents=True)
    (flow / "tasks/2026-07-18").mkdir(parents=True)
    (flow / ".version").write_text("0.5.2", encoding="utf-8")
    (flow / "config.yml").write_text("path_mapping:\n  app:\n    patterns: ['src/*']\n    specs:\n      - path: app/rules.md\n", encoding="utf-8")
    (flow / "specs/app/rules.md").write_text(SPEC, encoding="utf-8")
    (flow / "tasks/2026-07-18/demo.md").write_text("# Tasks\n", encoding="utf-8")


def _snapshot(root: Path) -> dict[str, str]:
    return {path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest() for path in root.rglob("*") if path.is_file()}


def _run(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["node", str(CLI), *args], cwd=root, text=True, capture_output=True, check=False)


def test_b_08_cli_dry_run_is_zero_write_single_json(tmp_path: Path) -> None:
    _project(tmp_path)
    before = _snapshot(tmp_path)
    result = _run(tmp_path, "migrate", "--spec-workflow", "--dry-run")
    assert result.returncode == 0
    assert json.loads(result.stdout)["ready"] is True
    assert result.stderr == ""
    assert _snapshot(tmp_path) == before


def test_cli_rejects_mixed_actions_and_init_old_schema_before_copy(tmp_path: Path) -> None:
    _project(tmp_path)
    sentinel = tmp_path / ".code-flow/scripts/user.py"
    sentinel.parent.mkdir()
    sentinel.write_text("user", encoding="utf-8")
    mixed = _run(tmp_path, "migrate", "--spec-workflow", "--dry-run", "--prepare")
    assert mixed.returncode != 0
    init = _run(tmp_path, "init", "--platform=codex")
    assert init.returncode == 3
    assert "migration_required" in init.stdout
    assert sentinel.read_text(encoding="utf-8") == "user"


def test_s_12_cli_prepare_apply_and_repeat(tmp_path: Path) -> None:
    _project(tmp_path)
    prepared = _run(tmp_path, "migrate", "--spec-workflow", "--prepare")
    payload = json.loads(prepared.stdout)
    applied = _run(tmp_path, "migrate", "--spec-workflow", "--apply", "--plan", payload["plan"])
    assert json.loads(applied.stdout)["status"] == "committed"
    repeated = _run(tmp_path, "migrate", "--spec-workflow", "--apply", "--plan", payload["plan"])
    assert json.loads(repeated.stdout)["status"] == "already_migrated"


def test_package_manifest_includes_migrator_without_new_dependency() -> None:
    package = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
    assert "src/migrate/**" in package["files"]
    assert "docs/migrations/spec-workflow-0.6.0.md" in package["files"]
    assert set(package["dependencies"]) == {"@ccusage/codex"}


# --- S-10: declarative platform install plan and runInit orchestration ---

import os  # noqa: E402
import shutil  # noqa: E402

import pytest  # noqa: E402

INSTALL_PLAN = ROOT / "src/adapters/install-plan.json"

PLATFORM_ARTIFACTS = {
    "claude": [
        "CLAUDE.md",
        ".claude/commands/cf-init.md",
        ".claude/settings.local.json",
        ".code-flow/scripts/cf_acceptance_runner.py",
    ],
    "codex": [
        "AGENTS.md",
        ".agents/skills/cf-init/SKILL.md",
        ".codex/hooks.json",
        ".codex/config.toml",
    ],
    "costrict": [
        "CLAUDE.md",
        ".costrict/commands/cf-init.md",
        ".costrict/settings.local.json",
    ],
    "opencode": [
        "AGENTS.md",
        ".opencode/plugins/code-flow/package.json",
        ".opencode/commands/cf-init.md",
        "opencode.json",
    ],
}


def _run_init(root: Path, platform: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PIP_DISABLE_PIP_VERSION_CHECK"] = "1"
    return subprocess.run(
        ["node", str(CLI), "init", f"--platform={platform}"],
        cwd=root, env=env, text=True, capture_output=True, check=False,
    )


def _function_line_span(source: str, name: str) -> int:
    start = source.index(f"function {name}(")
    opening = source.index("{", start)
    depth = 0
    for index in range(opening, len(source)):
        char = source[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return source.count("\n", start, index) + 1
    raise AssertionError(f"unterminated function {name}")


def test_install_plan_declaration_covers_platforms_and_is_packaged() -> None:
    plan = json.loads(INSTALL_PLAN.read_text(encoding="utf-8"))
    assert set(plan["platforms"]) == {"claude", "codex", "costrict", "opencode"}
    for platform, spec in plan["platforms"].items():
        assert spec["markers"], f"{platform} needs platform markers"
        assert spec["entries"], f"{platform} needs install entries"
        assert spec["next_steps"]["fresh"] and spec["next_steps"]["upgrade"]
        for entry in spec["entries"]:
            assert entry["kind"] in {"file", "dir", "stamp"}, entry
            if entry["kind"] == "file":
                assert entry["category"] in {"tool", "merge", "user"}, entry
                assert entry["merger"], entry
            else:
                assert entry["category"] in {"tool", "merge", "user"}, entry
    assert [group["key"] for group in plan["summary"]] == [
        "updated", "merged", "created", "skipped", "removed"]
    package = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
    assert any(item.startswith("src/adapters") for item in package["files"])


def test_run_init_is_orchestration_only_and_under_two_hundred_lines() -> None:
    source = (ROOT / "src/cli.js").read_text(encoding="utf-8")
    assert _function_line_span(source, "runInit") < 200
    assert "installPlatform(" in source
    assert "PLATFORM_INSTALL_PLAN" in source or "installPlan" in source


def test_four_platform_fresh_and_upgrade_keep_install_and_summary(tmp_path: Path) -> None:
    if not shutil.which("node"):
        pytest.skip("node is required for CLI tests")
    for platform, artifacts in PLATFORM_ARTIFACTS.items():
        root = tmp_path / platform
        root.mkdir()
        fresh = _run_init(root, platform)
        assert fresh.returncode == 0, fresh.stderr
        assert "Created:" in fresh.stdout
        assert "Next steps:" in fresh.stdout
        for relative in artifacts:
            assert (root / relative).is_file(), f"{platform} fresh missing {relative}"

        version = root / ".code-flow/.version"
        version.write_text("0.0.1\n", encoding="utf-8")
        upgrade = _run_init(root, platform)
        assert upgrade.returncode == 0, upgrade.stderr
        assert "Updated (tool-managed):" in upgrade.stdout, upgrade.stdout
        assert "Removed (deprecated):" not in upgrade.stdout
        for relative in artifacts:
            assert (root / relative).is_file(), f"{platform} upgrade missing {relative}"


def test_upgrade_summary_groups_merge_and_skip_separately(tmp_path: Path) -> None:
    root = tmp_path
    fresh = _run_init(root, "claude")
    assert fresh.returncode == 0, fresh.stderr
    (root / ".code-flow/.version").write_text("0.0.1\n", encoding="utf-8")
    upgrade = _run_init(root, "claude")
    assert upgrade.returncode == 0, upgrade.stderr
    assert "Updated (tool-managed):" in upgrade.stdout
    assert "Skipped (user-customized):" in upgrade.stdout
    assert upgrade.stdout.index("Updated (tool-managed):") < upgrade.stdout.index(
        "Skipped (user-customized):")
