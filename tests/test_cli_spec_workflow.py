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
