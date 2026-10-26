"""One executable plan gate for manifest identity, semantics and design closure."""
from __future__ import annotations

from pathlib import Path
from shlex import quote
from typing import Mapping


def _root(directory: Path) -> Path:
    return next((parent.parent for parent in (directory, *directory.parents)
                 if parent.name == ".code-flow"), directory)


def _source(directory: Path, manifest: Mapping[str, object], required: bool) -> str:
    from cf_scenarios import require_source
    named = manifest.get("scenarios_file")
    if isinstance(named, str) and named:
        return str(directory / named)
    candidates = sorted(directory.glob("*.scenarios.md"))
    if required or candidates:
        return str(require_source(directory))
    return ""


def _projection(source: Mapping[str, object], manifest: Mapping[str, object]) -> list[dict[str, object]]:
    from cf_acceptance_schema import scenario_check_ids
    rows = {str(row["id"]): row for row in manifest.get("scenarios", [])}
    checks = {str(check["id"]) for check in manifest.get("checks", [])}
    findings: list[dict[str, object]] = []
    for row in source["scenarios"]:
        required = scenario_check_ids(row)
        current = rows.get(str(row["id"]), {})
        unknown = set(required) - checks
        if unknown:
            findings.append({"code": "unknown_check", "scenario": row["id"], "checks": sorted(unknown)})
        if required and set(required) != set(scenario_check_ids(current)):
            findings.append({"code": "scenario_checks_not_projected", "scenario": row["id"]})
    return findings


def verify_plan(directory: str, task_file: str, require_scenarios: bool = False) -> dict[str, object]:
    from cf_acceptance_manifest import validate_manifest
    from cf_acceptance_schema import load_manifest
    from cf_check_registration import validate_registration
    from cf_design_lint import lint_requirement
    from cf_scenarios import parse_scenarios, validate_e2e_quality
    from cf_spec_context import load_context
    from cf_spec_gate import result_to_data, validate_plan_coverage, validate_stage
    path = Path(directory) / ".acceptance-manifest.json"
    if not path.is_file():
        return {"decision": "block", "reason": "acceptance_manifest_missing"}
    valid, reason = validate_manifest(task_file, str(path))
    if not valid:
        return {"decision": "block", "reason": reason}
    manifest = load_manifest(path)
    source_file = _source(Path(directory), manifest, require_scenarios)
    source = parse_scenarios(source_file) if source_file else {"scenarios": manifest["scenarios"]}
    quality = validate_e2e_quality(source["scenarios"])
    projection = _projection(source, manifest)
    registration = validate_registration(str(_root(Path(directory))), manifest["scenarios"], manifest.get("checks", []))
    quality.update({"runnable_smoke_count": registration["runnable_smoke_count"],
                    "runnable_browser_count": registration["runnable_browser_count"],
                    "registration_status": "passed" if registration["ok"] else "failed"})
    design = lint_requirement(task_file, source_file)
    context = load_context(str(Path(directory) / "spec-context.yml"))
    gate = validate_stage(context, "plan", root=str(_root(Path(directory))), task_dir=directory)
    coverage = validate_plan_coverage(context, task_file)
    blocked = (not quality["ok"] or projection or not registration["ok"] or
               design["decision"] != "pass" or gate.decision != "pass" or coverage.decision != "pass")
    recovery = (["code-flow spec refresh --task-dir " + quote(str(Path(directory))) +
                 " --root " + quote(str(_root(Path(directory)))) + " --json"]
                if any(issue.code == "rule_artifact_stale" for issue in gate.errors) else [])
    return {"decision": "block" if blocked else "pass", "gate": result_to_data(gate), "next": recovery,
            "coverage": result_to_data(coverage), "e2e_quality": quality,
            "registration": registration, "design_lint": design, "projection": projection}
