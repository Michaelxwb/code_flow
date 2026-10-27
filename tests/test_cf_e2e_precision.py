#!/usr/bin/env python3
"""E2E precision gates for plan and start.

The expensive layer is only justified for critical journeys with an explicit
lower-layer gap and a change scope. These tests pin both the quality gate and
the scope projection that keeps a small diff from running every E2E.
"""

from __future__ import annotations

import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src/core/code-flow/scripts"))

from cf_acceptance_manifest import validate_manifest, write_manifest  # noqa: E402
from codeflow.acceptance.cf_acceptance_plan import build_e2e_plan  # noqa: E402
from cf_acceptance_runner import _select_profile, run_manifest  # noqa: E402
from codeflow.acceptance.cf_acceptance_schema import validate_checks  # noqa: E402
from cf_scenarios import parse_scenarios, validate_e2e_quality  # noqa: E402


def _scenario(**overrides: object) -> dict[str, object]:
    scenario: dict[str, object] = {
        "id": "S-01",
        "title": "create model and send message",
        "priority": "P0",
        "level": "e2e",
        "exec": "deferred",
        "env": "browser",
        "components": ["frontend", "browser", "backend"],
        "defer_reason": "requirement-level browser verification",
        "owner": "TASK-001",
        "target_phase": "review",
        "boundary": "browser -> API -> PG",
        "steps": ["open wizard", "create model"],
        "expected": ["model is visible", "agent replies"],
        "expected_refs": [{"expected": 1, "steps": [2]}, {"expected": 2, "steps": [2]}],
        "why_e2e": "only the real browser/API/DB stack exposes the wiring break",
        "trigger_paths": ["src/frontend/model/**"],
        "smoke": False,
    }
    scenario.update(overrides)
    return scenario


def test_valid_e2e_has_reason_scope_and_critical_priority() -> None:
    quality = validate_e2e_quality([_scenario()])
    assert quality["ok"] is True
    assert quality["e2e_count"] == 1


def test_e2e_without_lower_layer_justification_is_rejected() -> None:
    quality = validate_e2e_quality([_scenario(why_e2e="")])
    assert quality["ok"] is False
    assert "e2e_justification_missing" in {item["code"] for item in quality["errors"]}


def test_non_critical_e2e_is_rejected() -> None:
    quality = validate_e2e_quality([_scenario(priority="P2")])
    assert quality["ok"] is False
    assert "e2e_priority_not_critical" in {item["code"] for item in quality["errors"]}


def test_non_smoke_e2e_requires_trigger_paths() -> None:
    quality = validate_e2e_quality([_scenario(trigger_paths=[])])
    assert quality["ok"] is False
    assert "e2e_trigger_paths_missing" in {item["code"] for item in quality["errors"]}
    smoke = validate_e2e_quality([_scenario(trigger_paths=[], smoke=True)])
    assert smoke["ok"] is True


def test_scenario_source_accepts_component_and_contract_layers(tmp_path: Path) -> None:
    source = tmp_path / "demo.scenarios.md"
    source.write_text(
        "---\n"
        "schema: 1\n"
        "requirement: demo\n"
        "scenarios:\n"
        "  - id: S-01\n"
        "    priority: P0\n"
        "    level: component\n"
        "  - id: S-02\n"
        "    priority: P0\n"
        "    level: contract\n"
        "  - id: S-03\n"
        "    priority: P0\n"
        "    level: e2e\n"
        "    boundary: browser -> api\n"
        "    steps: [open]\n"
        "    expected: [reply]\n"
        "    why_e2e: lower layers cannot see browser wiring\n"
        "    trigger_paths: [src/frontend/**]\n"
        "---\n",
        encoding="utf-8",
    )
    parsed = parse_scenarios(source)
    assert [item["level"] for item in parsed["scenarios"]] == ["component", "contract", "e2e"]
    assert parsed["scenarios"][2]["trigger_paths"] == ["src/frontend/**"]


TASK = """# Tasks

## Acceptance Coverage
| 场景ID | 来源设计 | 测试层级 | 关键真实边界 | 负责任务 | 状态 | 执行命令 | 优先级 | 执行方式 | 环境 | 输入 | E2E理由 | 触发路径 | 冒烟 |
|--------|---------|---------|-------------|---------|------|---------|--------|---------|------|------|--------|---------|------|
| S-01 | design#1 | E2E | browser -> API -> PG | TASK-001 | planned | ["python3", "-c", "pass"] | P0 | deferred | browser | | lower layers miss wiring | ["src/frontend/model/**"] | no |
| S-02 | design#1 | component | renderer | TASK-001 | planned | ["python3", "-c", "pass"] | P1 | auto | browser | | | | |

## TASK-001: Demo
- **Status**: draft
- **Acceptance-Refs**: S-01, S-02
"""


def test_scenario_source_level_overrides_table_to_prevent_e2e_downgrade(tmp_path: Path) -> None:
    task = tmp_path / "demo.md"
    manifest = tmp_path / ".acceptance-manifest.json"
    task.write_text(
        "# Tasks\n\n"
        "## Acceptance Coverage\n"
        "| 场景ID | 来源设计 | 测试层级 | 关键真实边界 | 负责任务 | 状态 | 执行命令 |\n"
        "|--------|---------|---------|-------------|---------|------|---------|\n"
        '| S-01 | design#1 | integration | browser -> API | TASK-001 | planned | ["python3", "-c", "pass"] |\n\n'
        "## TASK-001: Demo\n- **Status**: draft\n- **Acceptance-Refs**: S-01\n",
        encoding="utf-8",
    )
    (tmp_path / "demo.scenarios.md").write_text(
        "---\n"
        "schema: 1\n"
        "requirement: demo\n"
        "scenarios:\n"
        "  - id: S-01\n"
        "    priority: P0\n"
        "    level: e2e\n"
        "    boundary: browser -> api\n"
        "    steps: [open]\n"
        "    expected: [reply]\n"
        "    why_e2e: only the real stack catches the route wiring\n"
        "    trigger_paths: [src/frontend/**]\n"
        "---\n",
        encoding="utf-8",
    )
    locked = write_manifest(str(task), str(manifest))
    assert locked["scenarios"][0]["level"] == "e2e"
    assert locked["scenarios"][0]["kind"] == "e2e"
    assert validate_manifest(str(task), str(manifest)) == (True, "")


def test_source_explicit_false_clears_stale_smoke_and_paths(tmp_path: Path) -> None:
    task = tmp_path / "demo.md"
    manifest = tmp_path / ".acceptance-manifest.json"
    task.write_text(
        "# Tasks\n\n"
        "## Acceptance Coverage\n"
        "| 场景ID | 来源设计 | 测试层级 | 关键真实边界 | 负责任务 | 状态 | 执行命令 | 触发路径 | 冒烟 |\n"
        "|--------|---------|---------|-------------|---------|------|---------|---------|------|\n"
        '| S-01 | design#1 | E2E | browser -> API | TASK-001 | planned | ["python3", "-c", "pass"] | ["old/**"] | yes |\n\n'
        "## TASK-001: Demo\n- **Status**: draft\n- **Acceptance-Refs**: S-01\n",
        encoding="utf-8",
    )
    (tmp_path / "demo.scenarios.md").write_text(
        "---\n"
        "schema: 1\n"
        "requirement: demo\n"
        "scenarios:\n"
        "  - id: S-01\n"
        "    priority: P0\n"
        "    level: e2e\n"
        "    boundary: browser -> api\n"
        "    steps: [open]\n"
        "    expected: [reply]\n"
        "    why_e2e: real browser wiring\n"
        "    trigger_paths: []\n"
        "    smoke: false\n"
        "---\n",
        encoding="utf-8",
    )
    locked = write_manifest(str(task), str(manifest))
    row = locked["scenarios"][0]
    assert row["trigger_paths"] == []
    assert row["smoke"] is False
    check = next(item for item in locked["checks"] if item["id"] == row["check"])
    assert check["paths"] == []
    assert check["profile"] == "changed"


def test_new_manifest_without_quality_columns_still_opts_into_gate(tmp_path: Path) -> None:
    task = tmp_path / "demo.md"
    manifest = tmp_path / ".acceptance-manifest.json"
    task.write_text(
        "# Tasks\n\n"
        "## Acceptance Coverage\n"
        "| 场景ID | 来源设计 | 测试层级 | 关键真实边界 | 负责任务 | 状态 | 执行命令 | 优先级 |\n"
        "|--------|---------|---------|-------------|---------|------|---------|--------|\n"
        '| S-01 | design#1 | E2E | browser -> API | TASK-001 | planned | ["python3", "-c", "pass"] | P2 |\n\n'
        "## TASK-001: Demo\n- **Status**: draft\n- **Acceptance-Refs**: S-01\n",
        encoding="utf-8",
    )
    locked = write_manifest(str(task), str(manifest))
    assert locked["e2e_gate"] == 1
    plan = build_e2e_plan(str(manifest), str(task), "TASK-001")
    assert plan["quality"]["gate"] == "required"
    assert plan["quality"]["ok"] is False
    assert "e2e_priority_not_critical" in {
        item["code"] for item in plan["quality"]["errors"]
    }


def test_manifest_remembers_explicit_scenarios_source_path(tmp_path: Path) -> None:
    task = tmp_path / "tasks.md"
    task.write_text(
        "# Tasks\n\n"
        "## Acceptance Coverage\n"
        "| 场景ID | 来源设计 | 测试层级 | 关键真实边界 | 负责任务 | 状态 | 执行命令 |\n"
        "|--------|---------|---------|-------------|---------|------|---------|\n"
        '| S-01 | design#1 | E2E | browser -> API | TASK-001 | planned | ["python3", "-c", "pass"] |\n\n'
        "## TASK-001: Demo\n- **Status**: draft\n- **Acceptance-Refs**: S-01\n",
        encoding="utf-8",
    )
    source = tmp_path / "demo.scenarios.md"
    source.write_text(
        "---\n"
        "schema: 1\n"
        "requirement: demo\n"
        "scenarios:\n"
        "  - id: S-01\n"
        "    priority: P0\n"
        "    level: e2e\n"
        "    boundary: browser -> api\n"
        "    steps: [open]\n"
        "    expected: [reply]\n"
        "    why_e2e: real browser wiring\n"
        "    trigger_paths: [src/frontend/**]\n"
        "---\n",
        encoding="utf-8",
    )
    manifest = tmp_path / ".acceptance-manifest.json"
    write_manifest(str(task), str(manifest), str(source))
    locked = json.loads(manifest.read_text(encoding="utf-8"))
    assert locked["scenarios_file"] == "demo.scenarios.md"
    assert validate_manifest(str(task), str(manifest)) == (True, "")
    relocked = write_manifest(str(task), str(manifest))
    assert relocked["scenarios_file"] == "demo.scenarios.md"
    assert relocked["scenarios"][0]["why_e2e"] == "real browser wiring"
    assert validate_manifest(str(task), str(manifest)) == (True, "")


def test_manifest_projects_e2e_scope_and_quality_fields(tmp_path: Path) -> None:
    task = tmp_path / "demo.md"
    manifest = tmp_path / ".acceptance-manifest.json"
    task.write_text(TASK, encoding="utf-8")
    locked = write_manifest(str(task), str(manifest))
    by_id = {row["id"]: row for row in locked["scenarios"]}
    assert by_id["S-01"]["why_e2e"] == "lower layers miss wiring"
    assert by_id["S-01"]["trigger_paths"] == ["src/frontend/model/**"]
    assert by_id["S-01"]["smoke"] is False
    check = next(item for item in locked["checks"] if item["id"] == by_id["S-01"]["check"])
    assert check["paths"] == ["src/frontend/model/**"]
    assert validate_manifest(str(task), str(manifest)) == (True, "")


def test_relock_refreshes_trigger_paths_and_smoke_profile(tmp_path: Path) -> None:
    task = tmp_path / "demo.md"
    manifest = tmp_path / ".acceptance-manifest.json"
    task.write_text(TASK, encoding="utf-8")
    first = write_manifest(str(task), str(manifest))
    check = next(item for item in first["checks"] if item["id"] == first["scenarios"][0]["check"])
    assert check["paths"] == ["src/frontend/model/**"]
    updated = TASK.replace(
        '["src/frontend/model/**"] | no |', '["src/frontend/agent/**"] | yes |'
    )
    task.write_text(updated, encoding="utf-8")
    second = write_manifest(str(task), str(manifest))
    check = next(item for item in second["checks"] if item["id"] == second["scenarios"][0]["check"])
    assert check["profile"] == "smoke"
    assert check["paths"] == ["src/frontend/agent/**"]


def test_quality_manifest_cannot_drop_the_e2e_gate_marker(tmp_path: Path) -> None:
    task = tmp_path / "demo.md"
    manifest = tmp_path / ".acceptance-manifest.json"
    task.write_text(TASK, encoding="utf-8")
    write_manifest(str(task), str(manifest))
    data = json.loads(manifest.read_text(encoding="utf-8"))
    assert data["e2e_gate"] == 1
    data.pop("e2e_gate")
    manifest.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    assert validate_manifest(str(task), str(manifest)) == (
        False, "acceptance_manifest_e2e_gate_missing"
    )


def test_scenario_source_supplies_e2e_fields_missing_from_table(tmp_path: Path) -> None:
    task = tmp_path / "demo.md"
    manifest = tmp_path / ".acceptance-manifest.json"
    task.write_text(
        "# Tasks\n\n"
        "## Acceptance Coverage\n"
        "| 场景ID | 来源设计 | 测试层级 | 关键真实边界 | 负责任务 | 状态 | 执行命令 |\n"
        "|--------|---------|---------|-------------|---------|------|---------|\n"
        '| S-01 | design#1 | E2E | browser -> API | TASK-001 | planned | ["python3", "-c", "pass"] |\n\n'
        "## TASK-001: Demo\n- **Status**: draft\n- **Acceptance-Refs**: S-01\n",
        encoding="utf-8",
    )
    (tmp_path / "demo.scenarios.md").write_text(
        "---\n"
        "schema: 1\n"
        "requirement: demo\n"
        "scenarios:\n"
        "  - id: S-01\n"
        "    priority: P0\n"
        "    level: e2e\n"
        "    boundary: browser -> api\n"
        "    steps: [open]\n"
        "    expected: [reply]\n"
        "    why_e2e: only the real stack catches the route wiring\n"
        "    trigger_paths: [src/frontend/**]\n"
        "---\n",
        encoding="utf-8",
    )
    locked = write_manifest(str(task), str(manifest))
    row = locked["scenarios"][0]
    assert row["why_e2e"] == "only the real stack catches the route wiring"
    assert row["trigger_paths"] == ["src/frontend/**"]
    assert validate_manifest(str(task), str(manifest)) == (True, "")


def test_start_plan_keeps_owned_and_smoke_but_defers_the_rest(tmp_path: Path) -> None:
    task = tmp_path / "demo.md"
    task.write_text(
        "# Tasks\n\n## TASK-001: One\n- **Acceptance-Refs**: S-01\n\n"
        "## TASK-002: Two\n- **Acceptance-Refs**: S-02, S-03\n",
        encoding="utf-8",
    )
    rows = [
        _scenario(id="S-01", owner="TASK-001", exec="auto"),
        _scenario(id="S-02", owner="TASK-002", smoke=True, trigger_paths=[], exec="auto"),
        _scenario(id="S-03", owner="TASK-002", trigger_paths=["src/other/**"]),
    ]
    manifest = tmp_path / ".acceptance-manifest.json"
    manifest.write_text(json.dumps({"schema": 3, "checks": [], "scenarios": rows}), encoding="utf-8")

    plan = build_e2e_plan(str(manifest), str(task), "TASK-001")

    assert [item["id"] for item in plan["owned"]] == ["S-01"]
    assert [item["id"] for item in plan["smoke"]] == ["S-02"]
    assert [item["id"] for item in plan["scheduled"]] == ["S-01", "S-02"]
    assert plan["deferred_count"] == 1
    assert plan["quality"]["ok"] is True


def test_start_plan_uses_owner_not_acceptance_reference(tmp_path: Path) -> None:
    task = tmp_path / "demo.md"
    task.write_text(
        "# Tasks\n\n## TASK-001: One\n- **Acceptance-Refs**: S-01\n\n"
        "## TASK-002: Two\n- **Acceptance-Refs**: S-01\n",
        encoding="utf-8",
    )
    manifest = tmp_path / ".acceptance-manifest.json"
    manifest.write_text(
        json.dumps({"schema": 3, "e2e_gate": 1, "checks": [], "scenarios": [
            _scenario(id="S-01", owner="TASK-002")
        ]}),
        encoding="utf-8",
    )

    first = build_e2e_plan(str(manifest), str(task), "TASK-001")
    second = build_e2e_plan(str(manifest), str(task), "TASK-002")

    assert first["owned"] == []
    assert first["deferred_count"] == 1
    assert [item["id"] for item in second["owned"]] == ["S-01"]


def test_start_plan_blocks_owned_e2e_without_trigger_scope(tmp_path: Path) -> None:
    task = tmp_path / "demo.md"
    task.write_text("# Tasks\n\n## TASK-001: One\n- **Acceptance-Refs**: S-01\n", encoding="utf-8")
    manifest = tmp_path / ".acceptance-manifest.json"
    manifest.write_text(
        json.dumps({"schema": 3, "e2e_gate": 1, "checks": [], "scenarios": [
            _scenario(id="S-01", owner="TASK-001", trigger_paths=[], why_e2e="-", exec="auto")
        ]}),
        encoding="utf-8",
    )

    plan = build_e2e_plan(str(manifest), str(task), "TASK-001")

    assert plan["quality"]["ok"] is False
    assert "e2e_trigger_paths_missing" in {
        item["code"] for item in plan["quality"]["errors"]
    }
    assert "e2e_justification_missing" in {
        item["code"] for item in plan["quality"]["errors"]
    }


def test_check_paths_must_be_string_globs() -> None:
    with pytest.raises(ValueError, match="invalid check CHK-1:paths"):
        validate_checks([{
            "id": "CHK-1", "command": ["true"], "paths": ["src/a.ts", 1],
        }])
    with pytest.raises(ValueError, match="invalid check CHK-1:paths"):
        validate_checks([{"id": "CHK-1", "command": ["true"], "paths": "src/a.ts"}])


def test_duplicate_e2e_journey_warns_even_with_new_titles() -> None:
    first = _scenario()
    second = _scenario(id="S-02", title="another title")
    quality = validate_e2e_quality([first, second])
    assert quality["ok"] is True
    assert "duplicate_e2e_journey" in {
        item["code"] for item in quality["warnings"]
    }


def test_start_plan_rejects_aspirational_e2e(tmp_path: Path) -> None:
    task = tmp_path / "demo.md"
    task.write_text("# Tasks\n\n## TASK-001: One\n- **Acceptance-Refs**: S-01\n", encoding="utf-8")
    manifest = tmp_path / ".acceptance-manifest.json"
    manifest.write_text(
        json.dumps({"schema": 3, "e2e_gate": 1, "checks": [], "scenarios": [
            _scenario(id="S-01", owner="TASK-001", exec="aspirational")
        ]}),
        encoding="utf-8",
    )
    plan = build_e2e_plan(str(manifest), str(task), "TASK-001")
    assert plan["quality"]["ok"] is False
    assert "e2e_aspirational" in {item["code"] for item in plan["quality"]["errors"]}


def test_relock_preserves_evidence_when_only_gate_marker_is_missing(tmp_path: Path) -> None:
    task = tmp_path / "demo.md"
    manifest = tmp_path / ".acceptance-manifest.json"
    task.write_text(TASK, encoding="utf-8")
    first = write_manifest(str(task), str(manifest))
    data = json.loads(manifest.read_text(encoding="utf-8"))
    data["scenarios"][0]["status"] = "verified"
    data["scenarios"][0]["evidence"] = {"status": "passed", "exit_code": 0}
    data.pop("e2e_gate")
    manifest.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    second = write_manifest(str(task), str(manifest))
    assert second["scenarios"][0]["status"] == "verified"
    assert second["scenarios"][0]["evidence"]["exit_code"] == 0
    assert second["e2e_gate"] == 1
    assert first["scenarios"][0]["id"] == second["scenarios"][0]["id"]


def test_relock_preserves_legacy_check_profile_without_scenario_smoke(tmp_path: Path) -> None:
    task = tmp_path / "demo.md"
    manifest = tmp_path / ".acceptance-manifest.json"
    task.write_text(
        "# Tasks\n\n"
        "## Acceptance Coverage\n"
        "| 场景ID | 来源设计 | 测试层级 | 关键真实边界 | 负责任务 | 状态 | 执行命令 |\n"
        "|--------|---------|---------|-------------|---------|------|---------|\n"
        '| S-01 | design#1 | E2E | browser -> API | TASK-001 | planned | ["python3", "-c", "pass"] |\n\n'
        "## TASK-001: Demo\n- **Status**: draft\n- **Acceptance-Refs**: S-01\n",
        encoding="utf-8",
    )
    first = write_manifest(str(task), str(manifest))
    data = json.loads(manifest.read_text(encoding="utf-8"))
    data["checks"][0]["profile"] = "smoke"
    manifest.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    second = write_manifest(str(task), str(manifest))
    assert second["checks"][0]["profile"] == "smoke"
    assert first["scenarios"][0]["id"] == second["scenarios"][0]["id"]


def test_manifest_rejects_check_scope_tampering(tmp_path: Path) -> None:
    task = tmp_path / "demo.md"
    manifest = tmp_path / ".acceptance-manifest.json"
    task.write_text(TASK, encoding="utf-8")
    write_manifest(str(task), str(manifest))
    data = json.loads(manifest.read_text(encoding="utf-8"))
    data["checks"][0]["paths"] = []
    manifest.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    assert validate_manifest(str(task), str(manifest)) == (
        False, "acceptance_manifest_check_scope_changed"
    )


def test_legacy_manifest_warns_instead_of_blocking_start(tmp_path: Path) -> None:
    task = tmp_path / "demo.md"
    task.write_text("# Tasks\n\n## TASK-001: One\n- **Acceptance-Refs**: S-01\n", encoding="utf-8")
    manifest = tmp_path / ".acceptance-manifest.json"
    manifest.write_text(
        json.dumps({"schema": 3, "checks": [], "scenarios": [
            _scenario(id="S-01", owner="TASK-001", trigger_paths=[], why_e2e="", exec="auto")
        ]}),
        encoding="utf-8",
    )

    plan = build_e2e_plan(str(manifest), str(task), "TASK-001")

    assert plan["quality"]["ok"] is True
    assert plan["quality"]["gate"] == "legacy"
    assert "legacy_e2e_plan" in {item["code"] for item in plan["quality"]["warnings"]}


def test_changed_profile_scopes_e2e_by_trigger_paths(monkeypatch) -> None:
    data = {
        "schema": 3,
        "checks": [
            {"id": "CHK-A", "command": ["true"], "cwd": ".", "timeout": 30,
             "paths": ["src/frontend/a/**"]},
            {"id": "CHK-B", "command": ["true"], "cwd": ".", "timeout": 30,
             "paths": ["src/frontend/b/**"]},
        ],
        "scenarios": [
            {"id": "S-01", "kind": "e2e", "check": "CHK-A", "priority": "P0"},
            {"id": "S-02", "kind": "e2e", "check": "CHK-B", "priority": "P0"},
        ],
    }
    monkeypatch.setattr("codeflow.acceptance.cf_acceptance_selection.changed_paths", lambda root: {"src/frontend/a/View.tsx"})
    selected = _select_profile(data, "/tmp", "changed")
    assert [item["id"] for item in selected["scenarios"]] == ["S-01"]


def test_changed_profile_does_not_run_unscoped_smoke_e2e() -> None:
    data = {
        "schema": 3,
        "checks": [
            {"id": "CHK-SMOKE", "command": ["true"], "cwd": ".", "timeout": 30,
             "profile": "smoke"},
        ],
        "scenarios": [
            {"id": "S-01", "kind": "e2e", "check": "CHK-SMOKE", "priority": "P0",
             "smoke": True},
        ],
    }
    selected = _select_profile(data, "/tmp", "changed")
    assert [item["id"] for item in selected["scenarios"]] == []


def test_changed_profile_uses_scenario_trigger_paths_even_if_check_has_none(monkeypatch) -> None:
    data = {
        "schema": 3,
        "checks": [
            {"id": "CHK-A", "command": ["true"], "cwd": ".", "timeout": 30},
        ],
        "scenarios": [
            {"id": "S-01", "kind": "e2e", "check": "CHK-A", "priority": "P0",
             "trigger_paths": ["src/frontend/a/**"]},
            {"id": "S-02", "kind": "e2e", "check": "CHK-A", "priority": "P0",
             "trigger_paths": ["src/frontend/b/**"]},
        ],
    }
    monkeypatch.setattr("codeflow.acceptance.cf_acceptance_selection.changed_paths", lambda root: {"src/frontend/a/View.tsx"})
    selected = _select_profile(data, "/tmp", "changed")
    assert [item["id"] for item in selected["scenarios"]] == ["S-01"]


def test_changed_preflight_ignores_unaffected_unverified_functional(
    tmp_path: Path, monkeypatch
) -> None:
    from cf_acceptance_manifest import write_manifest
    from cf_task_workflow import _e2e_preflight

    task = tmp_path / "demo.md"
    task.write_text(
        "# Tasks\n\n"
        "## Acceptance Coverage\n"
        "| 场景ID | 来源设计 | 测试层级 | 关键真实边界 | 负责任务 | 状态 | 执行命令 | 优先级 |\n"
        "|--------|---------|---------|-------------|---------|------|---------|--------|\n"
        '| S-01 | design#1 | integration | service -> store | TASK-001 | planned | ["python3", "-c", "pass"] | P1 |\n\n'
        "## TASK-001: Demo\n- **Status**: done\n- **Acceptance-Refs**: S-01\n",
        encoding="utf-8",
    )
    manifest = tmp_path / ".acceptance-manifest.json"
    data = write_manifest(str(task), str(manifest))
    data["checks"][0]["inputs"] = ["src/a.py"]
    manifest.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr("codeflow.acceptance.cf_acceptance_selection.changed_paths", lambda root: {"docs/unrelated.md"})

    loaded, failure = _e2e_preflight(
        manifest, [(task, "TASK-001", "done")], True, "changed", str(tmp_path)
    )
    assert failure is None, failure
    assert loaded is not None


def test_changed_profile_with_no_matching_scenario_is_a_clean_noop(
    tmp_path: Path, monkeypatch
) -> None:
    manifest = tmp_path / ".acceptance-manifest.json"
    manifest.write_text(json.dumps({
        "schema": 3,
        "checks": [{
            "id": "CHK-A", "command": ["python3", "-c", "pass"], "cwd": ".", "timeout": 30,
            "paths": ["src/frontend/a/**"],
        }],
        "scenarios": [{
            "id": "S-01", "kind": "e2e", "check": "CHK-A", "priority": "P0",
            "trigger_paths": ["src/frontend/a/**"],
        }],
    }), encoding="utf-8")
    monkeypatch.setattr("codeflow.acceptance.cf_acceptance_selection.changed_paths", lambda root: {"docs/unrelated.md"})
    result = run_manifest(str(manifest), str(tmp_path), profile="changed")
    assert result["decision"] == "pass"
    assert result["reason"] == "no_affected_scenarios"


def test_smoke_profile_uses_marked_e2e_instead_of_every_e2e() -> None:
    data = {
        "schema": 3,
        "checks": [
            {"id": "CHK-SMOKE", "command": ["true"], "cwd": ".", "timeout": 30, "profile": "smoke"},
            {"id": "CHK-FULL", "command": ["true"], "cwd": ".", "timeout": 30},
        ],
        "scenarios": [
            {"id": "S-01", "kind": "e2e", "check": "CHK-SMOKE", "priority": "P0", "smoke": True},
            {"id": "S-02", "kind": "e2e", "check": "CHK-FULL", "priority": "P0"},
        ],
    }
    selected = _select_profile(data, "/tmp", "smoke")
    assert [item["id"] for item in selected["scenarios"]] == ["S-01"]


def test_all_platform_commands_carry_the_e2e_contract() -> None:
    root = Path(__file__).resolve().parents[1]
    plans = (
        root / "src/adapters/claude/commands/cf-task/plan.md",
        root / "src/adapters/costrict/commands/cf-task/plan.md",
        root / "src/adapters/opencode/commands/cf-task/plan.md",
        root / "src/adapters/codex/skills/cf-task-plan/SKILL.md",
    )
    starts = (
        root / "src/adapters/claude/commands/cf-task/start.md",
        root / "src/adapters/costrict/commands/cf-task/start.md",
        root / "src/adapters/opencode/commands/cf-task/start.md",
        root / "src/adapters/codex/skills/cf-task-start/SKILL.md",
    )
    for path in plans:
        text = path.read_text(encoding="utf-8")
        assert "E2E 精度" in text, path
        assert "why_e2e" in text and "trigger_paths" in text, path
        assert "--quality" in text or "quality.ok=false" in text, path
        assert "acceptance project" in text, path
        assert "--scenarios-file" in text, path
        assert "acceptance manifest" in text and "--verify-plan" in text, path
        assert "--require-scenarios" in text, path
    for path in starts:
        text = path.read_text(encoding="utf-8")
        assert "e2e_plan" in text and "owned" in text and "deferred" in text, path
