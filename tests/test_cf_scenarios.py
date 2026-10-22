"""Scenario-first acceptance source model (TASK-001)."""

from __future__ import annotations

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
