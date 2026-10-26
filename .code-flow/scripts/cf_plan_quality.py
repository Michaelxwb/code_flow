"""One executable plan gate for manifest identity, semantics and design closure."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from shlex import quote
from typing import Mapping, Optional


@dataclass(frozen=True)
class FileSnapshot:
    """One file read once, with a stat fingerprint for drift detection."""

    path: str
    text: str
    size: int
    mtime_ns: int

    def drift(self) -> bool:
        try:
            stat = Path(self.path).stat()
        except OSError:
            return True
        return stat.st_size != self.size or stat.st_mtime_ns != self.mtime_ns


@dataclass(frozen=True)
class PlanSnapshot:
    """Verified inputs of one verify_plan operation; no persistent cache."""

    task: FileSnapshot
    manifest: FileSnapshot
    scenario_file: str
    scenario: Optional[FileSnapshot]

    def drift(self) -> bool:
        if self.task.drift() or self.manifest.drift():
            return True
        return self.scenario is not None and self.scenario.drift()


def _read_snapshot(path: Path) -> FileSnapshot:
    stat = path.stat()
    return FileSnapshot(str(path), path.read_text(encoding="utf-8"), stat.st_size, stat.st_mtime_ns)


def load_plan_snapshot(directory: str, task_file: str,
                       require_scenarios: bool = False) -> PlanSnapshot:
    """Read TASK, manifest and scenario source at most once for one operation."""
    from cf_scenarios import ScenarioError
    base = Path(directory)
    manifest = _read_snapshot(base / ".acceptance-manifest.json")
    task = _read_snapshot(Path(task_file))
    try:
        data = json.loads(manifest.text)
    except ValueError:
        data = {}
    try:
        source_file = _source(base, data if isinstance(data, Mapping) else {}, require_scenarios)
    except ScenarioError:
        source_file = ""
    source = _read_snapshot(Path(source_file)) if source_file and Path(source_file).is_file() else None
    return PlanSnapshot(task, manifest, source_file, source)


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


def _scenario_snapshot(snapshot: PlanSnapshot, source_file: str) -> Optional[FileSnapshot]:
    scenario = snapshot.scenario
    if not source_file:
        return None
    if scenario is not None and Path(scenario.path).resolve() == Path(source_file).resolve():
        return scenario
    return _read_snapshot(Path(source_file)) if Path(source_file).is_file() else None


def verify_plan(directory: str, task_file: str, require_scenarios: bool = False,
                *, snapshot: Optional[PlanSnapshot] = None) -> dict[str, object]:
    from cf_acceptance_manifest import validate_manifest
    from cf_acceptance_schema import load_manifest
    from cf_check_registration import validate_registration
    from cf_design_lint import lint_requirement
    from cf_scenarios import parse_scenarios, validate_e2e_quality
    from cf_spec_context import load_context
    from cf_spec_gate import result_to_data, validate_plan_coverage, validate_stage
    base = Path(directory)
    path = base / ".acceptance-manifest.json"
    if not path.is_file():
        return {"decision": "block", "reason": "acceptance_manifest_missing"}
    plan = snapshot if snapshot is not None else load_plan_snapshot(directory, task_file, require_scenarios)
    if plan.drift():
        return {"decision": "block", "reason": "plan_snapshot_drift"}
    try:
        manifest = load_manifest(path, text=plan.manifest.text)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return {"decision": "block", "reason": f"acceptance_manifest_invalid: {exc}"}
    source_file = _source(base, manifest, require_scenarios)
    scenario = _scenario_snapshot(plan, source_file)
    valid, reason = validate_manifest(task_file, str(path), task_text=plan.task.text,
                                      manifest=manifest, scenario_file=source_file,
                                      scenario_text=scenario.text if scenario is not None else None)
    if not valid:
        return {"decision": "block", "reason": reason}
    if scenario is not None:
        source = parse_scenarios(scenario.path, text=scenario.text)
    elif source_file:
        source = parse_scenarios(source_file)
    else:
        source = {"scenarios": manifest["scenarios"]}
    quality = validate_e2e_quality(source["scenarios"])
    projection = _projection(source, manifest)
    registration = validate_registration(str(_root(base)), manifest["scenarios"], manifest.get("checks", []))
    quality.update({"runnable_smoke_count": registration["runnable_smoke_count"],
                    "runnable_browser_count": registration["runnable_browser_count"],
                    "registration_status": "passed" if registration["ok"] else "failed"})
    design = lint_requirement(task_file, source_file, task_text=plan.task.text,
                              scenarios=source["scenarios"] if source_file else None)
    context = load_context(str(base / "spec-context.yml"))
    gate = validate_stage(context, "plan", root=str(_root(base)), task_dir=directory)
    coverage = validate_plan_coverage(context, task_file, text=plan.task.text)
    blocked = (not quality["ok"] or projection or not registration["ok"] or
               design["decision"] != "pass" or gate.decision != "pass" or coverage.decision != "pass")
    recovery = (["code-flow spec refresh --task-dir " + quote(str(base)) +
                 " --root " + quote(str(_root(base))) + " --json"]
                if any(issue.code == "rule_artifact_stale" for issue in gate.errors) else [])
    return {"decision": "block" if blocked else "pass", "gate": result_to_data(gate), "next": recovery,
            "coverage": result_to_data(coverage), "e2e_quality": quality,
            "registration": registration, "design_lint": design, "projection": projection}
