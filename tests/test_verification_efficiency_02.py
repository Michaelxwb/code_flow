"""TASK-002 acceptance through scenario source, locking and real checks."""
from __future__ import annotations
import json
from pathlib import Path
import sys

import pytest
import yaml

SCRIPTS = Path(__file__).resolve().parents[1] / "src/core/code-flow/scripts"
sys.path.insert(0, str(SCRIPTS))
from codeflow.acceptance.cf_scenario_source import parse_scenarios, validate_e2e_quality
from codeflow.cli.cf_acceptance_manifest import write_manifest
from codeflow.cli.cf_acceptance_runner import run_manifest


def _fixture(root: Path) -> tuple[Path, Path, Path, list[str]]:
    (root / ".code-flow").mkdir()
    (root / "test_checks.py").write_text(
        "def test_contract(): assert True\n"
        "def test_component(): assert True\n"
        "def test_integration(): assert True\n", encoding="utf-8")
    task = root / "demo.md"
    rows = []
    for index, name in enumerate(("contract", "component", "integration"), 1):
        command = json.dumps([sys.executable, "-m", "pytest", "-q", f"test_checks.py::test_{name}"])
        rows.append(f"| S-0{index} | d#1 | integration | runtime | TASK-001 | planned | {command} |")
    task.write_text("# Tasks\n\n## Acceptance Coverage\n"
        "| 场景ID | 来源设计 | 测试层级 | 关键真实边界 | 负责任务 | 状态 | 执行命令 |\n"
        "|---|---|---|---|---|---|---|\n" + "\n".join(rows) +
        "\n\n## TASK-001: Demo\n- **Acceptance-Refs**: S-01, S-02, S-03\n", encoding="utf-8")
    manifest = root / ".acceptance-manifest.json"
    initial = write_manifest(str(task), str(manifest))
    ids = [row["check"] for row in initial["scenarios"]]
    source = root / "demo.scenarios.md"
    _write_source(source, ids)
    return task, manifest, source, ids


def _write_source(path: Path, ids: list[str], mapping: list[dict] | None = None) -> None:
    row = {"id": "S-01", "level": "integration", "expected": ["contract accepted", "component rendered", "transaction committed"],
           "checks": ids, "expected_checks": mapping if mapping is not None else
           [{"expected": index, "checks": [check]} for index, check in enumerate(ids, 1)]}
    path.write_text(yaml.safe_dump({"schema": 1, "scenarios": [row]}), encoding="utf-8")


def _registration(root: Path, ids: list[str], levels: list[str]) -> Path:
    config = root / "registration.json"
    config.write_text(json.dumps({"checks": {check: {"level": level}
                     for check, level in zip(ids, levels)}}), encoding="utf-8")
    return config


def test_s02_composed_checks_cover_one_scenario(tmp_path: Path) -> None:
    task, manifest, source, ids = _fixture(tmp_path)
    registration = _registration(tmp_path, ids, ["contract", "component", "integration"])
    locked = write_manifest(str(task), str(manifest), str(source), registration_file=str(registration))
    assert set(locked["registration"]["registered"]) == set(ids)
    assert locked["scenarios"][0]["expected_checks"] == [
        {"expected": index, "checks": [check]} for index, check in enumerate(ids, 1)]
    result = run_manifest(str(manifest), str(tmp_path), write_evidence=True, use_cache=False)
    row = next(item for item in result["results"] if item["id"] == "S-01")
    assert row["status"] == "passed"
    assert set(row["check_results"]) == set(ids)
    saved = json.loads(manifest.read_text(encoding="utf-8"))["scenarios"][0]
    assert set(saved["evidence"]["check_results"]) == set(ids)
    (tmp_path / "test_checks.py").write_text(
        "def test_contract(): assert True\ndef test_component(): assert False\ndef test_integration(): assert True\n", encoding="utf-8")
    result = run_manifest(str(manifest), str(tmp_path), write_evidence=True, use_cache=False)
    row = next(item for item in result["results"] if item["id"] == "S-01")
    assert row["status"] == "failed"
    assert row["check_results"][ids[1]]["status"] == "failed"


def test_s03_zero_e2e_plan_and_selection_guidance() -> None:
    source = {"scenarios": [{"id": "S-01", "level": "contract", "steps": ["submit CAS"],
              "expected": ["returns 409"], "expected_refs": [{"expected": 1, "steps": [1]}]}]}
    rows = parse_scenarios("case.scenarios.md", text=yaml.safe_dump(source))["scenarios"]
    report = validate_e2e_quality(rows)
    assert report["ok"] and report["e2e_count"] == 0
    browser = {"id": "S-02", "level": "e2e", "priority": "P0", "env": "browser",
               "components": ["browser"], "boundary": "browser and service", "why_e2e": "alpha",
               "steps": ["open"], "expected": ["result shown"],
               "expected_refs": [{"expected": 1, "steps": [1]}], "trigger_paths": ["app/**"]}
    assert validate_e2e_quality([browser])["ok"]
    template = (SCRIPTS.parent / "specs/shared/scenarios-template.md").read_text(encoding="utf-8")
    assert "CAS" in template and "contract" in template and "component" in template


def test_e02_missing_expected_coverage_blocks(tmp_path: Path) -> None:
    task, manifest, source, ids = _fixture(tmp_path)
    registration = _registration(tmp_path, ids, ["contract", "component", "integration"])
    write_manifest(str(task), str(manifest), str(source), registration_file=str(registration))
    result = run_manifest(str(manifest), str(tmp_path), write_evidence=True, use_cache=False)
    assert next(row for row in result["results"] if row["id"] == "S-01")["status"] == "passed"
    _write_source(source, ids, [{"expected": 1, "checks": [ids[0]]}])
    with pytest.raises(ValueError, match="expected_checks"):
        write_manifest(str(task), str(manifest), str(source))
    _write_source(source, [ids[0], ids[1], "unknown"])
    with pytest.raises(ValueError, match="unknown_check"):
        write_manifest(str(task), str(manifest), str(source))
    _write_source(source, ids, [{"expected": 1, "checks": ["unknown"]},
                               {"expected": 2, "checks": [ids[1]]}, {"expected": 3, "checks": [ids[2]]}])
    with pytest.raises(ValueError, match="expected_checks"):
        write_manifest(str(task), str(manifest), str(source))
    _write_source(source, ids)
    changed = _registration(tmp_path, ids, ["unit", "component", "integration"])
    relocked = write_manifest(str(task), str(manifest), str(source), registration_file=str(changed))
    row = relocked["scenarios"][0]
    assert row["status"] == "stale" and row["runs"] and row["evidence"]
    assert row["stale_reason"] == "scenario_or_check_contract_changed"
    assert "S-01" in relocked["relock"]["stale"]
