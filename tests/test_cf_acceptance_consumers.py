"""Cross-consumer acceptance probes using real Git, commands and evidence.

The application is deliberately tiny: A/B assert independent input files and
append execution counters. Faults change inputs or remove temporary evidence;
no runner, hash, checkpoint, audit or collect result is mocked.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Mapping
import xml.etree.ElementTree as ET

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src/core/code-flow/scripts"))

from codeflow.acceptance.cf_acceptance_evidence import stale_scenario_checks
from cf_acceptance_manifest import record_accepted_risk
from cf_acceptance_runner import run_manifest
from codeflow.acceptance.cf_acceptance_schema import load_manifest
from cf_audit import build_audit
from codeflow.acceptance.cf_check_inputs import check_input_hashes
from codeflow.evidence.cf_evidence_store import EvidenceStore, requirement_key
from cf_evidence_import import import_report
from codeflow.core.cf_exec_base import worktree_fingerprint
from cf_task_parallel import _missing_evidence
from cf_task_workflow import _stale_functional_rows, verify_layers


@dataclass(frozen=True)
class Project:
    root: Path
    demand: Path
    manifest: Path
    design: Path
    task: Path

    def store(self) -> EvidenceStore:
        return EvidenceStore(self.root, requirement_key(self.demand))

    def data(self) -> dict[str, object]:
        return load_manifest(self.manifest)

    def counts(self) -> dict[str, int]:
        return {name: len((self.root / f"{name}.runs").read_text()) for name in ("A", "B")}


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)


def _check(name: str) -> dict[str, object]:
    code = ("from pathlib import Path; "
            f"p = Path('{name}.runs'); p.write_text((p.read_text() if p.exists() else '') + 'x'); "
            f"assert Path('src/{name}.txt').read_text() == 'ok'")
    return {"id": f"CHK-{name}", "command": [sys.executable, "-c", code],
            "cwd": ".", "timeout": 30, "inputs": [f"src/{name}.txt"]}


@pytest.fixture()
def project(tmp_path: Path) -> Project:
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "consumer@test.invalid")
    _git(tmp_path, "config", "user.name", "consumer test")
    (tmp_path / ".gitignore").write_text("*.runs\n")
    (tmp_path / "src").mkdir()
    for name in ("A", "B"):
        (tmp_path / f"src/{name}.txt").write_text("ok")
    demand = tmp_path / ".code-flow/tasks/demo"
    demand.mkdir(parents=True)
    design = demand / "demo.design.md"
    design.write_text("## 2.5 验收条件\n\n"
                      "| 场景ID | 测试层级 | 执行方式(exec) |\n|---|---|---|\n"
                      "| S-01 | integration | auto |\n")
    task = demand / "demo.md"
    task.write_text("# Demo\n\n## TASK-001: A and B\n"
                    "- **Status**: done\n- **Acceptance-Refs**: S-01\n")
    manifest = demand / ".acceptance-manifest.json"
    manifest.write_text(json.dumps({"schema": 3, "task_file": "demo.md", "checks": [_check("A"), _check("B")],
        "scenarios": [{"id": "S-01", "kind": "functional", "owner": "TASK-001",
                       "check": "CHK-A", "checks": ["CHK-A", "CHK-B"], "status": "planned"}]}))
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-qm", "acceptance baseline")
    return Project(tmp_path, demand, manifest, design, task)


def _run(project: Project, resume: bool = False) -> dict[str, object]:
    return run_manifest(str(project.manifest), str(project.root), write_evidence=True, resume=resume)


def _scenario(data: Mapping[str, object], field: str = "scenarios") -> dict[str, object]:
    return next(row for row in data[field] if row["id"] == "S-01")


def _audit(project: Project) -> dict[str, object]:
    return build_audit(str(project.design), str(project.manifest), str(project.root))


def _collect_missing(project: Project, data: Mapping[str, object]) -> list[str]:
    missing, required = _missing_evidence(
        project.root, "TASK-001", data, project.task.relative_to(project.root).as_posix())
    assert required == ["CHK-A", "CHK-B"]
    return [str(item["check_id"]) for item in missing]


def _merge_stale(project: Project, data: Mapping[str, object]) -> list[str]:
    fingerprint = worktree_fingerprint(str(project.root), include_untracked=False)
    checks = {item["id"]: item for item in data["checks"]}
    hashes = check_input_hashes(str(project.root), checks, fingerprint)
    scenario = next(row for row in data["scenarios"] if row["id"] == "S-01")
    return stale_scenario_checks(scenario, hashes, fingerprint)


def _run_second_check(project: Project) -> dict[str, object]:
    data = project.data()
    check = next(item for item in data["checks"] if item["id"] == "CHK-B")
    partial = project.demand / "partial.json"
    partial.write_text(json.dumps({"schema": 3, "checks": [check], "scenarios": [
        {"id": "S-01", "kind": "functional", "owner": "TASK-001", "check": "CHK-B"}]}))
    return run_manifest(str(partial), str(project.root), write_evidence=True,
                        use_cache=False, resume=False)


@pytest.mark.parametrize("primary_alias", [True, False])
def test_all_consumers_accept_both_checks_and_cache_is_observable(project: Project,
                                                                 primary_alias: bool) -> None:
    if not primary_alias:
        data = project.data()
        _scenario(data).pop("check")
        project.manifest.write_text(json.dumps(data))
    assert _run(project)["decision"] == "pass"
    assert project.counts() == {"A": 1, "B": 1}
    assert _scenario(_run(project), "results")["cache_reused"] is True
    assert project.counts() == {"A": 1, "B": 1}
    before = project.manifest.read_bytes()
    report = _audit(project)
    assert report["decision"] == "pass", report
    assert _scenario(report)["checks"] == ["CHK-A", "CHK-B"]
    assert project.manifest.read_bytes() == before
    assert _collect_missing(project, project.data()) == []
    assert _merge_stale(project, project.data()) == []
    assert _stale_functional_rows(project.data(), str(project.root)) == []


def test_second_check_failure_cannot_hide_behind_first_pass(project: Project) -> None:
    assert _run(project)["decision"] == "pass"
    (project.root / "src/B.txt").write_text("broken")
    assert _run_second_check(project)["decision"] == "block"
    assert project.store().read_latest("CHK-B")["status"] == "failed"
    assert _collect_missing(project, project.data()) == ["CHK-B"]
    assert _merge_stale(project, project.data()) == ["CHK-B"]
    assert _stale_functional_rows(project.data(), str(project.root)) == ["S-01"]
    report = _audit(project)
    assert report["decision"] == "block", report
    assert {item["check_id"] for item in report["findings"]} == {"CHK-B"}


def test_partial_sidecar_loss_cannot_fall_back_to_aggregate_pass(project: Project) -> None:
    assert _run(project)["decision"] == "pass"
    shutil.rmtree(project.store().check_directory("CHK-B"))
    assert _collect_missing(project, project.data()) == ["CHK-B"]
    report = _audit(project)
    assert report["decision"] == "block", report
    assert {item["check_id"] for item in report["findings"]} == {"CHK-B"}


def test_changed_input_is_stale_and_requirement_verify_runs_the_assertion(project: Project) -> None:
    assert _run(project)["decision"] == "pass"
    (project.root / "src/B.txt").write_text("broken")
    assert _merge_stale(project, project.data()) == ["CHK-B"]
    assert _stale_functional_rows(project.data(), str(project.root)) == ["S-01"]
    assert _collect_missing(project, project.data()) == ["CHK-B"]
    result = verify_layers(str(project.root), str(project.demand), profile="full")
    assert result["decision"] == "block", result
    assert project.counts() == {"A": 1, "B": 2}, result


@pytest.mark.parametrize("resume", [False, True])
def test_partial_failure_keeps_individual_outcomes_and_resumes_only_missing_work(project: Project,
                                                                                resume: bool) -> None:
    (project.root / "src/B.txt").write_text("broken")
    result = _run(project)
    assert result["decision"] == "block"
    assert {item["id"]: item["status"] for item in result["checks"]} == {
        "CHK-A": "passed", "CHK-B": "failed"}
    assert project.store().read_latest("CHK-A")["status"] == "passed"
    assert project.store().read_latest("CHK-B")["status"] == "failed"
    (project.root / "src/B.txt").write_text("ok")
    assert _run(project, resume=resume)["decision"] == "pass"
    assert project.counts() == {"A": 1, "B": 2}
    assert _collect_missing(project, project.data()) == []
    assert _audit(project)["decision"] == "pass"


def test_risk_on_second_check_does_not_relabel_first_check(project: Project) -> None:
    (project.root / "src/B.txt").write_text("broken")
    record_accepted_risk(str(project.manifest), "CHK-B", "TASK-001", "fixture waiver",
                         "2999-12-31", "user", "explicit fixture confirmation")
    result = _run(project)
    assert result["decision"] == "pass", result
    assert _scenario(result, "results")["status"] == "accepted_risk"
    assert project.store().read_latest("CHK-A")["status"] == "passed"
    assert project.store().read_latest("CHK-B")["status"] == "accepted_risk"
    assert _collect_missing(project, project.data()) == []
    (project.root / "src/A.txt").write_text("broken")
    assert _run(project)["decision"] == "block"
    assert _collect_missing(project, project.data()) == ["CHK-A"]


def test_audit_keeps_findings_for_each_failed_check(project: Project) -> None:
    assert _run(project)["decision"] == "pass"
    for check in project.data()["checks"]:
        name = check["id"].removeprefix("CHK-")
        (project.root / f"src/{name}.txt").write_text("broken")
        partial = project.demand / "partial.json"
        partial.write_text(json.dumps({"checks": [check], "scenarios": [
            {"id": "S-01", "check": check["id"], "kind": "functional"}]}))
        assert run_manifest(str(partial), str(project.root), write_evidence=True,
                            use_cache=False)["decision"] == "block"
    findings = _audit(project)["findings"]
    assert {item["check_id"] for item in findings} == {"CHK-A", "CHK-B"}


@pytest.mark.parametrize("missing_field", ["", "check_hashes", "check_results", "empty_outcome"])
def test_legacy_fallback_requires_explicit_proof_for_every_check(project: Project,
                                                               missing_field: str) -> None:
    assert _run(project)["decision"] == "pass"
    shutil.rmtree(project.store().directory)
    if missing_field:
        data = project.data()
        evidence = _scenario(data)["evidence"]
        if missing_field == "empty_outcome":
            evidence["check_results"]["CHK-B"] = {}
        else:
            evidence[missing_field].pop("CHK-B")
        project.manifest.write_text(json.dumps(data))
    report = _audit(project)
    assert report["decision"] == ("block" if missing_field else "pass"), report
    if missing_field:
        assert {item["check_id"] for item in report["findings"]} == {"CHK-B"}


def _real_junit(project: Project, target: Path) -> None:
    suite = ET.Element("testsuite")
    for check in project.data()["checks"]:
        result = subprocess.run(check["command"], cwd=project.root, capture_output=True, text=True)
        case = ET.SubElement(suite, "testcase", name=check["id"])
        if result.returncode:
            ET.SubElement(case, "failure").text = result.stderr
    ET.ElementTree(suite).write(target, encoding="utf-8")


@pytest.mark.parametrize("second_input", ["ok", "broken"])
def test_ci_import_preserves_real_per_check_outcomes(project: Project, second_input: str) -> None:
    (project.root / "src/B.txt").write_text(second_input)
    _git(project.root, "add", "-A")
    _git(project.root, "commit", "--allow-empty", "-qm", "CI input snapshot")
    report = project.root.parent / f"{project.root.name}-junit.xml"
    _real_junit(project, report)
    imported = import_report(project.root, report=report, fmt="junit", commit="HEAD",
                             run_url="https://ci.example.test/runs/1", manifest=str(project.manifest))
    assert imported["decision"] == ("pass" if second_input == "ok" else "block")
    assert project.store().read_latest("CHK-A")["status"] == "passed"
    expected_b = "passed" if second_input == "ok" else "failed"
    assert project.store().read_latest("CHK-B")["status"] == expected_b
    assert project.counts() == {"A": 1, "B": 1}
