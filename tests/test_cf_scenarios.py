"""Scenario-first acceptance source model (TASK-001)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "src/core/code-flow/scripts"
sys.path.insert(0, str(SCRIPTS))

from cf_scenarios import ScenarioError, merge_scenarios, parse_scenarios, scenario_status  # noqa: E402


def _source(tmp_path: Path, body: str, name: str = "demo.scenarios.md") -> Path:
    path = tmp_path / name
    path.write_text("---\n" + body + "\n---\n", encoding="utf-8")
    return path


def test_parse_scenarios_reads_frontmatter(tmp_path: Path) -> None:
    path = _source(tmp_path, """
schema: 1
requirement: demo
scenarios:
  - id: S-01
    title: full-stack journey
    priority: P0
    level: E2E
    exec: deferred
    env: browser
    components: [frontend, backend]
    boundary: browser -> api -> db
    steps: [open, send]
    expected: [message delivered]
    design_refs: [backend §3.2, frontend §3.5]
    checks: [CHK-API, CHK-BROWSER]
""")
    result = parse_scenarios(path)
    assert result["schema"] == 1
    assert result["scenarios"][0]["id"] == "S-01"
    assert result["scenarios"][0]["checks"] == ["CHK-API", "CHK-BROWSER"]
    assert result["scenarios"][0]["components"] == ["frontend", "backend"]


def test_duplicate_scenario_id_in_one_source_is_rejected(tmp_path: Path) -> None:
    path = _source(tmp_path, """
schema: 1
scenarios:
  - id: S-01
    priority: P0
  - id: S-01
    priority: P0
""")
    with pytest.raises(ScenarioError) as error:
        parse_scenarios(path)
    assert error.value.code == "duplicate_scenario_id"


def test_merge_conflict_unions_identical_definitions(tmp_path: Path) -> None:
    backend = parse_scenarios(_source(tmp_path, """
schema: 1
scenarios:
  - id: S-01
    title: journey
    priority: P0
    level: E2E
    design_refs: [backend §3.2]
    checks: [CHK-API]
""", "backend.scenarios.md"))
    frontend = parse_scenarios(_source(tmp_path, """
schema: 1
scenarios:
  - id: S-01
    title: journey
    priority: P0
    level: E2E
    design_refs: [frontend §3.5]
    checks: [CHK-BROWSER]
""", "frontend.scenarios.md"))
    merged = merge_scenarios([backend, frontend])
    assert len(merged) == 1
    assert merged[0]["design_refs"] == ["backend §3.2", "frontend §3.5"]
    assert merged[0]["checks"] == ["CHK-API", "CHK-BROWSER"]


def test_definition_conflict_fails_closed(tmp_path: Path) -> None:
    first = parse_scenarios(_source(tmp_path, """
schema: 1
scenarios:
  - id: S-01
    title: one
    priority: P0
""", "a.scenarios.md"))
    second = parse_scenarios(_source(tmp_path, """
schema: 1
scenarios:
  - id: S-01
    title: two
    priority: P0
""", "b.scenarios.md"))
    with pytest.raises(ScenarioError) as error:
        merge_scenarios([first, second])
    assert error.value.code == "design_scenario_conflict"
    assert "title" in error.value.details["fields"]


def test_multi_check_status_is_and_semantics() -> None:
    scenario = {"id": "S-01", "checks": ["CHK-API", "CHK-BROWSER"], "exec": "auto"}
    assert scenario_status(scenario, {"CHK-API": "verified", "CHK-BROWSER": "verified"}) == "verified"
    assert scenario_status(scenario, {"CHK-API": "verified", "CHK-BROWSER": "failed"}) == "failed"
    assert scenario_status(scenario, {"CHK-API": "env_blocked", "CHK-BROWSER": "verified"}) == "env_blocked"


def test_single_domain_scenario_source_is_valid(tmp_path: Path) -> None:
    path = _source(tmp_path, """
schema: 1
scenarios:
  - id: S-01
    title: backend only
    priority: P1
    level: integration
    components: [backend]
    checks: [CHK-API]
""")
    result = parse_scenarios(path)
    assert result["scenarios"][0]["components"] == ["backend"]


def test_scenario_owner_reconciliation_requires_unique_owner() -> None:
    from cf_scenarios import reconcile_coverage
    scenarios = [{"id": "S-01"}, {"id": "S-02"}]
    report = reconcile_coverage(scenarios, [
        {"scenario_id": "S-01", "owner": "TASK-001"},
        {"scenario_id": "S-02", "owner": "TASK-002"},
    ])
    assert report["ok"] is True
    duplicate = reconcile_coverage(scenarios, [
        {"scenario_id": "S-01", "owner": "TASK-001"},
        {"scenario_id": "S-01", "owner": "TASK-002"},
        {"scenario_id": "S-02", "owner": "TASK-002"},
    ])
    assert duplicate["ok"] is False
    assert duplicate["duplicate_owner"] == ["S-01"]


def test_missing_scenarios_source_blocks_plan(tmp_path: Path) -> None:
    from cf_scenarios import require_source
    with pytest.raises(ScenarioError) as error:
        require_source(tmp_path)
    assert error.value.code == "scenario_source_missing"


def test_scenario_source_three_way_audit() -> None:
    from cf_scenarios import audit_scenario_source
    scenarios = [{"id": "S-01"}, {"id": "S-02"}]
    coverage = [{"scenario_id": "S-01", "owner": "TASK-001"},
                {"scenario_id": "S-02", "owner": "TASK-002"}]
    report = audit_scenario_source(scenarios, coverage, ["S-01", "S-02"])
    assert report["ok"] is True
    assert report["manifest_missing"] == []


def test_fallback_marks_legacy_without_scenarios_file(tmp_path: Path) -> None:
    from cf_scenarios import load_requirement_scenarios
    result = load_requirement_scenarios(tmp_path, allow_legacy=True)
    assert result["deprecated"] is True
    assert result["scenarios"] == []


def test_unknown_scenario_is_reported() -> None:
    from cf_scenarios import audit_scenario_source
    report = audit_scenario_source([{"id": "S-01"}], [
        {"scenario_id": "S-01", "owner": "TASK-001"},
        {"scenario_id": "S-99", "owner": "TASK-002"},
    ])
    assert report["ok"] is False
    assert report["unknown"] == ["S-99"]


def test_migrate_legacy_coverage_to_scenarios() -> None:
    from cf_scenarios import migrate_from_coverage
    result = migrate_from_coverage([{"scenario_id": "S-01", "boundary": "api"}])
    assert result["migrated"] is True
    assert result["scenarios"][0]["id"] == "S-01"
    assert result["scenarios"][0]["sources"] == ["legacy-coverage"]


def test_traceability_from_scenarios_source(tmp_path: Path) -> None:
    from codeflow.acceptance.cf_traceability import build_traceability_from_scenarios
    source = _source(tmp_path, """
schema: 1
scenarios:
  - id: S-01
    title: journey
    priority: P0
    level: E2E
    checks: [CHK-1]
""")
    manifest = tmp_path / ".acceptance-manifest.json"
    manifest.write_text(json.dumps({
        "schema": 3,
        "checks": [{"id": "CHK-1", "command": ["true"], "cwd": ".", "timeout": 30}],
        "scenarios": [{"id": "S-01", "kind": "functional", "check": "CHK-1",
                       "owner": "TASK-001", "status": "verified"}],
    }), encoding="utf-8")
    trace = build_traceability_from_scenarios(str(source), str(manifest))
    assert trace["decision"] == "pass"
    assert trace["summary"]["bound"] == 1


def test_multi_check_missing_check_blocks(tmp_path: Path) -> None:
    from codeflow.acceptance.cf_traceability import build_traceability_from_scenarios
    source = _source(tmp_path, """
schema: 1
scenarios:
  - id: S-01
    title: journey
    checks: [CHK-1, CHK-2]
""")
    manifest = tmp_path / ".acceptance-manifest.json"
    manifest.write_text(json.dumps({
        "schema": 3,
        "checks": [{"id": "CHK-1", "command": ["true"], "cwd": ".", "timeout": 30}],
        "scenarios": [{"id": "S-01", "kind": "functional", "check": "CHK-1",
                       "owner": "TASK-001", "status": "verified"}],
    }), encoding="utf-8")
    trace = build_traceability_from_scenarios(str(source), str(manifest))
    assert trace["decision"] == "block"
    assert any(item["code"] == "missing_check" for item in trace["violations"])


def test_design_scenario_duplicate_is_reported(tmp_path: Path) -> None:
    from cf_audit import _scenario_source_findings
    source = _source(tmp_path, """
schema: 1
scenarios:
  - id: S-01
    title: journey
""")
    design = tmp_path / "demo.design.md"
    design.write_text(
        "# Demo\n\n## 2.5 验收条件\n\n"
        "| 场景ID | 功能ID | 优先级 | 测试层级 | 关键真实边界 |\n"
        "|---|---|---|---|---|\n"
        "| S-01 | FEAT-01 | P0 | integration | runner |\n",
        encoding="utf-8",
    )
    manifest = tmp_path / ".acceptance-manifest.json"
    manifest.write_text(json.dumps({"schema": 3, "checks": [], "scenarios": [
        {"id": "S-01", "kind": "functional", "owner": "TASK-001", "status": "planned"},
    ]}), encoding="utf-8")
    findings = _scenario_source_findings(str(source), manifest, design, json.loads(manifest.read_text()))
    assert any(item["code"] == "design_scenario_duplicate" for item in findings)


def test_multi_check_runner_and_semantics(tmp_path: Path) -> None:
    from cf_acceptance_runner import run_manifest
    passing = [sys.executable, "-c", "pass"]
    failing = [sys.executable, "-c", "raise SystemExit(3)"]
    manifest = tmp_path / ".acceptance-manifest.json"
    manifest.write_text(json.dumps({
        "schema": 3,
        "checks": [
            {"id": "CHK-A", "command": passing, "cwd": ".", "timeout": 30},
            {"id": "CHK-B", "command": failing, "cwd": ".", "timeout": 30},
        ],
        "scenarios": [
            {"id": "S-01", "kind": "functional", "checks": ["CHK-A", "CHK-B"],
             "owner": "TASK-001", "status": "planned"},
        ],
    }), encoding="utf-8")
    result = run_manifest(str(manifest), str(tmp_path))
    assert result["decision"] == "block"
    assert result["results"][0]["status"] == "failed"


def test_write_manifest_projects_scenario_checks(tmp_path: Path) -> None:
    from cf_acceptance_manifest import write_manifest
    task = tmp_path / "demo.md"
    task.write_text(
        "# Demo\n\n## Acceptance Coverage\n"
        "| 场景ID | 来源设计 | 测试层级 | 关键真实边界 | 负责任务 | 状态 | 执行命令 |\n"
        "|---|---|---|---|---|---|---|\n"
        '| S-01 | d#2.5 | integration | runner | TASK-001 | planned | ["python3", "-c", "pass"] |\n\n'
        "## TASK-001: A\n- **Status**: draft\n- **Acceptance-Refs**: S-01\n",
        encoding="utf-8",
    )
    manifest = tmp_path / ".acceptance-manifest.json"
    base = write_manifest(str(task), str(manifest))
    check_id = base["checks"][0]["id"]
    source = _source(tmp_path, f"""
schema: 1
scenarios:
  - id: S-01
    title: journey
    checks: ["{check_id}"]
""")
    projected = write_manifest(str(task), str(manifest), str(source))
    assert projected["scenarios"][0]["checks"] == [check_id]


def test_write_manifest_auto_detects_sibling_scenarios_file(tmp_path: Path) -> None:
    from cf_acceptance_manifest import write_manifest
    task = tmp_path / "demo.md"
    task.write_text(
        "# Demo\n\n## Acceptance Coverage\n"
        "| 场景ID | 来源设计 | 测试层级 | 关键真实边界 | 负责任任务 | 状态 | 执行命令 |\n"
        "|---|---|---|---|---|---|---|\n"
        '| S-01 | d#2.5 | integration | runner | TASK-001 | planned | ["python3", "-c", "pass"] |\n\n'
        "## TASK-001: A\n- **Status**: draft\n- **Acceptance-Refs**: S-01\n",
        encoding="utf-8",
    )
    manifest = tmp_path / ".acceptance-manifest.json"
    check_id = write_manifest(str(task), str(manifest))["checks"][0]["id"]
    _source(tmp_path, f"""
schema: 1
scenarios:
  - id: S-01
    title: journey
    checks: ["{check_id}"]
""")
    projected = write_manifest(str(task), str(manifest))
    assert projected["scenarios"][0]["checks"] == [check_id]
