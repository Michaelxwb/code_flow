#!/usr/bin/env python3
"""S-09/B-03 real Node CLI + Python transformer migration E2E."""

import hashlib
import json
from pathlib import Path
import subprocess
from typing import Optional

import yaml


ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "src/cli.js"

SPEC = """---
id: app-rules
description: App rules
stages: [prd, design, plan, code]
enforcement: required
verifiers:
  - rule: RULE-app-001
    type: regex
    config:
      pattern: SAFE
---
# App
## Rules
- [RULE-app-001] Keep SAFE behavior.
"""


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _fixture(root: Path, version: Optional[str] = "0.5.2", demands: tuple[str, ...] = ("alpha", "beta")) -> None:
    flow = root / ".code-flow"
    _write(flow / "config.yml", "inject:\n  mode: catalog\nquality_loop:\n  dedup_window: 5\npath_mapping:\n  app:\n    patterns: ['src/*']\n    specs:\n      - path: app/rules.md\n")
    if version is not None:
        _write(flow / ".version", version)
    _write(flow / "specs/app/rules.md", SPEC)
    _write(flow / ".inject-state", json.dumps({"injected_specs": ["app/rules.md"]}))
    for demand in demands:
        date = flow / "tasks/2026-07-18"
        _write(date / f"{demand}.prd.md", f"# {demand} PRD\n")
        _write(date / f"{demand}.design.md", f"# {demand} Design\n")
        _write(date / f"{demand}.md", f"# {demand} Tasks\n\n## TASK-001: Work\n- **Spec-Refs**: `app/rules.md`\n")
    archived = flow / "tasks/archived/2025-01-01/old.md"
    archived.parent.mkdir(parents=True)
    archived.write_bytes(b"ARCHIVED\x00BYTES")
    _write(root / "src/user.txt", "USER-BYTES\n")
    _write(root / "AGENTS.md", "# User Project\n\n## Spec Loading\nold catalog instructions\n\n## User Rules\nKEEP-ME\n")
    for command in (root / ".claude/commands/cf-inject.md", root / ".costrict/commands/cf-inject.md", root / ".opencode/commands/cf-inject.md", root / ".agents/skills/cf-inject/SKILL.md"):
        _write(command, "legacy inject\n")
    settings = {
        "permissions": {"allow": ["Bash(user-command)"]},
        "hooks": {"PreToolUse": [{"matcher": "Edit", "hooks": [
            {"type": "command", "command": "echo user-custom"},
            {"type": "command", "command": "python3 cf_inject_hook.py"},
        ]}]},
    }
    _write(root / ".claude/settings.local.json", json.dumps(settings))


def _run(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(("node", str(CLI), *args), cwd=root, text=True, capture_output=True, check=False)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_s_09_full_project_migrates_once_with_user_and_archive_bytes(tmp_path: Path) -> None:
    _fixture(tmp_path)
    user_hash = _sha(tmp_path / "src/user.txt")
    archive_hash = _sha(tmp_path / ".code-flow/tasks/archived/2025-01-01/old.md")
    prepared = json.loads(_run(tmp_path, "migrate", "--spec-workflow", "--prepare").stdout)
    applied = _run(tmp_path, "migrate", "--spec-workflow", "--apply", "--plan", prepared["plan"])
    assert applied.returncode == 0, applied.stdout + applied.stderr
    assert json.loads(applied.stdout)["status"] == "committed"
    config = yaml.safe_load((tmp_path / ".code-flow/config.yml").read_text(encoding="utf-8"))
    assert config["spec_workflow"]["schema_version"] == 1 and "inject" not in config
    assert all((tmp_path / f".code-flow/tasks/2026-07-18/{name}/spec-context.yml").is_file() for name in ("alpha", "beta"))
    alpha_context = yaml.safe_load((tmp_path / ".code-flow/tasks/2026-07-18/alpha/spec-context.yml").read_text(encoding="utf-8"))
    assert alpha_context["bindings"][0]["spec_id"] == "app-rules"
    alpha_task = (tmp_path / ".code-flow/tasks/2026-07-18/alpha/alpha.md").read_text(encoding="utf-8")
    assert "app-rules#RULE-app-001" in alpha_task and "app/rules.md" not in alpha_task
    assert (tmp_path / ".code-flow/.version").read_text(encoding="utf-8") == "0.6.0"
    assert _sha(tmp_path / "src/user.txt") == user_hash
    assert _sha(tmp_path / ".code-flow/tasks/archived/2025-01-01/old.md") == archive_hash
    assert "KEEP-ME" in (tmp_path / "AGENTS.md").read_text(encoding="utf-8")
    settings_text = (tmp_path / ".claude/settings.local.json").read_text(encoding="utf-8")
    assert "Bash(user-command)" in settings_text and "echo user-custom" in settings_text
    assert "cf_inject_hook.py" not in settings_text and "cf_pre_tool_hook.py" in settings_text
    for path in (".claude/commands/cf-spec.md", ".costrict/commands/cf-spec.md", ".opencode/commands/cf-spec.md", ".agents/skills/cf-spec/SKILL.md"):
        assert (tmp_path / path).is_file()
    residue = [path for path in tmp_path.rglob("*cf-inject*") if ".code-flow/migrations/" not in path.as_posix()]
    assert residue == []
    assert (tmp_path / ".code-flow/scripts/cf_spec_router.py").is_file()


def test_b_03_any_unresolved_demand_blocks_whole_project(tmp_path: Path) -> None:
    _fixture(tmp_path, demands=("alpha",))
    demand = tmp_path / ".code-flow/tasks/2026-07-18/existing"
    _write(demand / "one.md", "# one\n")
    _write(demand / "two.md", "# two\n")
    before = _sha(tmp_path / ".code-flow/.version")
    prepared_result = _run(tmp_path, "migrate", "--spec-workflow", "--prepare")
    prepared = json.loads(prepared_result.stdout)
    assert prepared["status"] == "prepared_blocked"
    applied = _run(tmp_path, "migrate", "--spec-workflow", "--apply", "--plan", prepared["plan"])
    assert applied.returncode == 3
    assert _sha(tmp_path / ".code-flow/.version") == before
    assert not (demand / "spec-context.yml").exists()


def test_supported_042_and_missing_version_preview_without_writes(tmp_path: Path) -> None:
    for version in ("0.4.2", None):
        root = tmp_path / (version or "missing")
        root.mkdir()
        _fixture(root, version=version, demands=("alpha",))
        before = {p.relative_to(root).as_posix(): _sha(p) for p in root.rglob("*") if p.is_file()}
        result = _run(root, "migrate", "--spec-workflow", "--dry-run")
        assert result.returncode == 0
        assert json.loads(result.stdout)["ready"] is True
        after = {p.relative_to(root).as_posix(): _sha(p) for p in root.rglob("*") if p.is_file()}
        assert after == before
