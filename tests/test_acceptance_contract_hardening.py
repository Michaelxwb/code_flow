"""Regression probes for declared acceptance quality and executable plan gates."""
from __future__ import annotations

from dataclasses import replace
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src/core/code-flow/scripts"))

from cf_acceptance_manifest import main as manifest_main, validate_manifest
from cf_scenarios import ScenarioError, parse_scenarios, validate_e2e_quality
from cf_spec_context import ArtifactRef
from cf_spec_gate import validate_stage
from codeflow.spec.cf_spec_verify import VerificationScope, run_all_verifiers
from test_audit_mainline_e2e import _repo
from test_cf_spec_gate import _context
from test_cf_spec_verify import _metadata


def _scenario(**changes: object) -> dict[str, object]:
    return {"id": "S-01", "level": "e2e", "priority": "P0", "exec": "auto", "env": "browser",
            "components": ["frontend", "backend", "browser"], "boundary": "browser -> api -> db",
            "steps": ["submit order"], "expected": ["order appears"],
            "expected_refs": [{"expected": 1, "steps": [1]}],
            "why_e2e": "browser authentication wiring spans the real application",
            "trigger_paths": ["src/*"], **changes}


def _parse(tmp_path: Path, scenario: dict[str, object]) -> dict[str, object]:
    source = tmp_path / "demo.scenarios.md"
    source.write_text(yaml.safe_dump({"schema": 1, "scenarios": [scenario]}, allow_unicode=True))
    return parse_scenarios(source)


def _errors(scenario: dict[str, object]) -> set[str]:
    return {item["code"] for item in validate_e2e_quality([scenario])["errors"]}


def test_api_journey_requires_system_or_integration_instead_of_browser_e2e() -> None:
    assert "e2e_browser_boundary_missing" in _errors(_scenario(
        env="local-api", components=["backend"], boundary="api -> db"))


@pytest.mark.parametrize("expected", ["性能提升可观", "不回归", "若成功则不回归"])
def test_vague_expectations_do_not_count_as_acceptance(expected: str) -> None:
    assert "scenario_expected_nondeterministic" in _errors(_scenario(expected=[expected]))


@pytest.mark.parametrize("refs", [[], [{"expected": 1, "steps": [99]}]])
def test_every_expected_has_a_resolvable_step_or_assertion(refs: list[object]) -> None:
    assert "scenario_expected_reference_missing" in _errors(_scenario(expected_refs=refs))


@pytest.mark.parametrize("declared", [False, True])
def test_expected_assertion_refs_resolve_to_declared_assertions(tmp_path: Path, declared: bool) -> None:
    source = _parse(tmp_path, _scenario(assertions=["ASSERT-order"] if declared else [],
                    expected_refs=[{"expected": 1, "assertions": ["ASSERT-order"]}]))
    quality = validate_e2e_quality(source["scenarios"])
    assert quality["ok"] is declared, quality


def test_deterministic_conditional_expectation_is_allowed() -> None:
    quality = validate_e2e_quality([_scenario(
        preconditions=["order is rejected"], expected=["若订单被拒绝，则显示错误码 E-409"])])
    assert quality["ok"], quality


def test_extended_schema_preserves_defer_ownership_and_environment(tmp_path: Path) -> None:
    source = _parse(tmp_path, _scenario(level="system", env="staging", components=["api", "db"],
                    exec="deferred", defer_reason="staging approval", owner="ops", target_phase="review"))
    row = next(item for item in source["scenarios"] if item["id"] == "S-01")
    assert row["defer_reason"] == "staging approval"
    assert row["owner"] == "ops"
    assert row["target_phase"] == "review"
    assert row["expected_refs"] == [{"expected": 1, "steps": [1]}]


def test_unknown_environment_is_not_silently_accepted(tmp_path: Path) -> None:
    with pytest.raises(ScenarioError, match="env"):
        _parse(tmp_path, _scenario(env="invented-environment"))


def test_deferred_scenario_requires_reason_owner_and_target_phase() -> None:
    assert "scenario_defer_metadata_missing" in _errors(_scenario(exec="deferred"))


def test_code_gate_requires_execution_proof_instead_of_applied_reference(tmp_path: Path) -> None:
    context = _context("applied")
    binding = next(iter(context.bindings))
    rule = next(iter(binding.rules))
    ref = ArtifactRef("design.md", "3.5", rule.ref, "a" * 64)
    state = replace(rule.stage_status["design"], refs=(ref,))
    rule = replace(rule, stage_status={"code": state})
    context = replace(context, bindings=(replace(binding, stages=("code",), rules=(rule,)),))
    result = validate_stage(context, "code")
    assert result.decision == "block"
    assert "rule_execution_evidence_missing" in {item.code for item in result.errors}


@pytest.mark.parametrize("text, passes", [("待确认，需同步 spec 文本", False),
                                         ("禁止包含 TBD 占位值，当前验证已完成", True)])
def test_document_verifier_checks_referenced_resolution(tmp_path: Path, text: str, passes: bool) -> None:
    artifact = tmp_path / "design.md"
    artifact.write_text(f"## 3.5\nRULE-verify-001: {text}\n")
    metadata = _metadata(tmp_path, [{"rule": "RULE-verify-001", "type": "document", "config": {
        "artifact": "design.md", "section_id": "3.5", "item_id": "RULE-verify-001"}}],
        [("RULE-verify-001", "Document must be resolved")])
    result = run_all_verifiers(metadata, VerificationScope(str(tmp_path), (), "a" * 64))
    assert result.passed is passes


def test_verify_plan_rejects_manifest_drift_without_an_optional_flag(tmp_path: Path) -> None:
    root, demand = _repo(tmp_path)
    manifest = demand / ".acceptance-manifest.json"
    data = json.loads(manifest.read_text())
    next(row for row in data["scenarios"] if row["id"] == "S-01")["owner"] = "TASK-999"
    manifest.write_text(json.dumps(data))
    assert validate_manifest(str(demand / "work.md"), str(manifest))[0] is False
    output = io.StringIO()
    code = manifest_main(["--verify-plan", "--task-dir", str(demand),
                          "--task-file", str(demand / "work.md")], stdout=output)
    assert code == 3, output.getvalue()
    assert json.loads(output.getvalue())["decision"] == "block"
