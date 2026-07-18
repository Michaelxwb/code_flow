#!/usr/bin/env python3
"""S-09/S-11 snapshots for schema-1 target templates and managed blocks."""

from pathlib import Path
import re

import yaml


ROOT = Path(__file__).resolve().parents[1]
CORE = ROOT / "src/core/code-flow"


def test_s_09_config_is_required_schema_one_without_legacy_routes() -> None:
    for path in (CORE / "config.yml", ROOT / ".code-flow/config.yml"):
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        assert data["spec_workflow"]["schema_version"] == 1
        assert data["spec_workflow"]["enforcement"] == "required"
        assert data["spec_workflow"]["catalog"]["dedup_window"] == 5
        assert "inject" not in data
        assert "dedup_window" not in data.get("quality_loop", {})


def test_frontend_template_routes_layered_javascript_files_to_frontend_specs() -> None:
    data = yaml.safe_load((CORE / "config.yml").read_text(encoding="utf-8"))
    patterns = data["path_mapping"]["frontend"]["patterns"]
    assert "src/composables/**" in patterns
    assert "src/services/**" in patterns


def test_s_11_gitignore_managed_block_covers_only_new_runtime_state() -> None:
    expected = (".active-task.json", ".active-task.lock", ".catalog-state.json", "migrations/", "specs/_session/")
    for path in (CORE / ".gitignore", ROOT / ".code-flow/.gitignore"):
        text = path.read_text(encoding="utf-8")
        assert "code-flow:runtime schema=1" in text
        assert all(item in text for item in expected)
        assert ".inject-state" not in text


def test_s_11_agent_templates_use_context_first_managed_protocol() -> None:
    paths = (
        ROOT / "AGENTS.md", ROOT / "CLAUDE.md",
        ROOT / "src/adapters/claude/CLAUDE.md", ROOT / "src/adapters/codex/AGENTS.md",
        ROOT / "src/adapters/costrict/CLAUDE.md", ROOT / "src/adapters/opencode/AGENTS.md",
    )
    for path in paths:
        text = path.read_text(encoding="utf-8")
        assert "<!-- code-flow:spec-loading schema=1 start -->" in text
        assert "active TASK" in text and "spec-context.yml" in text
        assert "inject.mode" not in text
        assert "Do NOT ask" in text or "不要询问" in text


def test_specs_allow_feature_modules_and_record_breaking_transaction() -> None:
    cli = (ROOT / ".code-flow/specs/cli/code-standards.md").read_text(encoding="utf-8")
    scripts = (ROOT / ".code-flow/specs/scripts/code-standards.md").read_text(encoding="utf-8")
    assert "事务 breaking migration" in cli
    assert "feature-scoped core module" in scripts
    assert "新增工具函数 → 放在 cf_core.py" not in scripts
    assert "cf_inject_hook.py" not in scripts


def _spec_contract(path: Path) -> tuple[set[str], list[dict[str, object]], str]:
    text = path.read_text(encoding="utf-8")
    frontmatter = yaml.safe_load(text.split("---", 2)[1])
    rule_ids = set(re.findall(r"\[(RULE-[a-z0-9-]+)\]", text))
    return rule_ids, frontmatter["verifiers"], text


def test_project_specs_use_atomic_automated_required_rules() -> None:
    cli_rules, cli_verifiers, cli_text = _spec_contract(ROOT / ".code-flow/specs/cli/code-standards.md")
    script_rules, script_verifiers, script_text = _spec_contract(ROOT / ".code-flow/specs/scripts/code-standards.md")
    assert cli_rules == {
        "RULE-cli-dependency-allowlist-001",
        "RULE-cli-user-content-preservation-001",
        "RULE-cli-platform-parity-001",
        "RULE-cli-hook-guard-001",
        "RULE-cli-migration-transaction-001",
    }
    assert script_rules == {
        "RULE-scripts-no-print-debug-001",
        "RULE-scripts-no-bare-except-001",
        "RULE-scripts-hook-protocol-001",
        "RULE-scripts-context-gate-001",
        "RULE-scripts-canonical-parity-001",
    }
    assert {item["rule"] for item in cli_verifiers} == cli_rules
    assert {item["rule"] for item in script_verifiers} == script_rules
    assert all(item["type"] != "manual" for item in (*cli_verifiers, *script_verifiers))
    assert "every applicable item" not in cli_text
    assert "every applicable item" not in script_text
