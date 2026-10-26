"""Regressions for the 0.8 upgrade and multi-task workflow issue report."""
from __future__ import annotations

from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "src/core/code-flow/scripts"
sys.path.insert(0, str(SCRIPTS))

from codeflow.acceptance.cf_acceptance_plan import build_e2e_plan
from cf_acceptance_runner import run_manifest
from codeflow.spec.cf_rule_readiness import artifact_problem, referenced_item
from cf_spec_context import ContextError, _application_ref
from cf_stop_hook import _acceptance_gap
from codeflow.spec.cf_workflow_service import task_truth_issues
from test_cf_e2e_precision import _scenario
from test_audit_mainline_e2e import _repo


def test_artifact_is_resolved_only_in_its_requirement(tmp_path: Path) -> None:
    demand = tmp_path / ".code-flow/tasks/2026-10-26/one"
    other = demand.with_name("two")
    demand.mkdir(parents=True)
    other.mkdir()
    for base in (tmp_path, other):
        (base / "design.md").write_text("## Matrix\nRULE-api-001: wrong requirement\n")
    artifact = demand / "design.md"
    artifact.write_text("## Matrix\nRULE-api-001: resolved\n")
    sha = hashlib.sha256(artifact.read_bytes()).hexdigest()
    assert artifact_problem(str(tmp_path), "design.md", "Matrix", "RULE-api-001", sha,
                            task_dir=str(demand)) == ""
    artifact.unlink()
    assert artifact_problem(str(tmp_path), "design.md", "Matrix", "RULE-api-001",
                            task_dir=str(demand)) == "rule_artifact_missing"
    assert artifact_problem(str(tmp_path), "../two/design.md", "Matrix", "RULE-api-001",
                            task_dir=str(demand)) == "rule_artifact_outside_project"


def test_legacy_reference_aliases_resolve_without_substring_matches(tmp_path: Path) -> None:
    text = "## TASK-008: API\n- Implement endpoint\n## TASK-009: Later\n- TBD\n"
    assert referenced_item(text, "TASK-008", "task-008") == "- Implement endpoint"
    text = "## Matrix\n| app#RULE-api-002 | complete |\n"
    assert "complete" in referenced_item(text, "Matrix", "rule-api-002")
    assert referenced_item(text, "Matrix", "rule-api-00") == ""
    artifact = tmp_path / "design.md"
    artifact.write_text(text)
    with pytest.raises(ContextError, match="rule_artifact_reference_missing"):
        _application_ref(str(tmp_path), {"artifact": "design.md", "section_id": "Matrix", "item_id": "missing"})
    assert _application_ref(str(tmp_path), {"artifact": "design.md", "section_id": "Matrix",
                                          "item_id": "rule-api-002"}).artifact_sha256


def test_public_gate_resolves_application_from_requirement_directory(tmp_path: Path) -> None:
    from cf_spec_context import ArtifactRef, RuleStageStatus, load_context, save_context
    root, demand = _repo(tmp_path)
    artifact = demand / "design.md"
    artifact.write_text("## Matrix\nRULE-app-001: complete\n")
    (root / "design.md").write_text("## Matrix\nRULE-app-001: TBD\n")
    reference = ArtifactRef("design.md", "Matrix", "RULE-app-001", hashlib.sha256(artifact.read_bytes()).hexdigest())
    context = load_context(str(demand / "spec-context.yml"))
    binding = context.bindings[0]
    rule = replace(binding.rules[0], stage_status={"plan": RuleStageStatus("applied", (reference,), None, ())})
    save_context(str(demand / "spec-context.yml"), replace(context, bindings=(replace(binding, rules=(rule,)),)))
    result = subprocess.run([sys.executable, str(SCRIPTS / "cf_spec_gate.py"), "--task-dir", str(demand),
        "--stage", "plan", "--json"], cwd=root, capture_output=True, text=True, timeout=5)
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout)["decision"] == "pass"


@pytest.mark.parametrize("scope, kind, state, blocked", [
    (set(), "review_stage", "done", False),
    ({"app-runtime"}, "review_stage", "done", True),
    (set(), "budget", "done", True),
    (set(), "env", "done", True),
    (set(), "review_stage", "verified", True),
    (None, "review_stage", "done", True),
])
def test_truth_scope_only_accepts_recorded_done_deferrals(tmp_path: Path, scope: set[str] | None,
                                                        kind: str, state: str, blocked: bool) -> None:
    from cf_spec_context import RuleStageStatus, load_context
    root, demand = _repo(tmp_path)
    task = demand / "scope.md"
    task.write_text(f"## TASK-001: Work\n- **Status**: {state}\n")
    context = load_context(str(demand / "spec-context.yml"))
    binding = context.bindings[0]
    rule = binding.rules[0]
    status = RuleStageStatus("unverified", (), None, ({"error_code": "deferred_to_review",
                            "details": {"deferral_kind": kind}},))
    context = replace(context, bindings=(replace(binding, rules=(
        replace(rule, verifier_stage="code", stage_status={"code": status}),)),))
    issues = task_truth_issues(str(task), "TASK-001", context, spec_ids=scope)
    assert bool(issues) is blocked


def test_collect_honors_done_gate_deferrals_with_real_acceptance_proof(tmp_path: Path) -> None:
    from cf_spec_context import RuleStageStatus, load_context, save_context
    from cf_task_parallel import ParallelEvidenceError, _require_evidence
    from cf_task_workflow import finish_task
    from codeflow.spec.cf_workflow_service import start_task
    root, demand = _repo(tmp_path)
    task = demand / "work.md"
    assert start_task(str(root), str(demand), str(task), "TASK-001", ())["ok"]
    finished = finish_task(str(root), str(demand), str(task), "TASK-001")
    assert finished["decision"] == "pass", finished
    context = load_context(str(demand / "spec-context.yml"))
    binding = context.bindings[0]
    stage = RuleStageStatus("unverified", (), None, ({"error_code": "deferred_to_review",
                            "details": {"deferral_kind": "review_stage"}},))
    rule = replace(binding.rules[0], ref="RULE-other-001", stage_status={"code": stage})
    other = replace(binding, spec_id="other-runtime", path="other/rules.md", rules=(rule,))
    updated = replace(context, bindings=(*context.bindings, other))
    save_context(str(demand / "spec-context.yml"), updated)
    relative = str(task.relative_to(root))
    assert _require_evidence("TASK-001", root, relative)
    stage = replace(stage, evidence=({"error_code": "verifier_budget_exhausted"},))
    other = replace(other, rules=(replace(rule, stage_status={"code": stage}),))
    save_context(str(demand / "spec-context.yml"), replace(context, bindings=(*context.bindings, other)))
    with pytest.raises(ParallelEvidenceError) as failure:
        _require_evidence("TASK-001", root, relative)
    assert failure.value.code == "task_status_truth_mismatch"


def test_start_keeps_deferred_ownership_without_scheduling_collection(tmp_path: Path) -> None:
    task = tmp_path / "work.md"
    task.write_text("## TASK-001: Work\n- **Acceptance-Refs**: S-01\n")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"schema": 3, "e2e_gate": 1, "scenarios_file": "work.scenarios.md",
        "checks": [], "scenarios": [_scenario(id="S-01"),
        _scenario(id="S-02", owner="TASK-002", smoke=True)]}))
    plan = build_e2e_plan(str(manifest), str(task), "TASK-001")
    assert [row["id"] for row in plan["owned"]] == ["S-01"]
    assert plan["scheduled"] == []
    assert set(plan["deferred_ids"]) == {"S-01", "S-02"}
    assert plan["quality"]["ok"], plan


def test_owner_batch_does_not_run_draft_scenarios(tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.json"
    rows = [{"id": f"S-{number:02}", "kind": "e2e", "owner": f"TASK-{number:03}", "smoke": True,
             "command": [sys.executable, "-c", "pass" if number < 3 else "raise SystemExit(1)"]}
            for number in (1, 2, 3)]
    manifest.write_text(json.dumps({"schema": 3, "scenarios": rows, "checks": []}))
    result = run_manifest(str(manifest), str(tmp_path), include_e2e=True, owner="TASK-001,TASK-002",
                          profile="smoke", use_cache=False)
    assert result["decision"] == "pass", result
    assert {row["id"] for row in result["results"]} == {"S-01", "S-02"}


@pytest.mark.parametrize("task_state, blocked", [("done", False), ("verified", True)])
def test_stop_deferred_uses_named_columns(tmp_path: Path, task_state: str, blocked: bool) -> None:
    section = (f"## TASK-001: Work\n- **Status**: {task_state}\n- **Acceptance-Refs**: S-01\n"
               "### Acceptance Contract\n- S-01: e2e_deferred\n"
               "### Acceptance Evidence\n- S-01: e2e_deferred\n")
    coverage = ("| 场景ID | 执行方式 | 状态 | 测试层级 |\n|---|---|---|---|\n"
                "| S-01 | deferred | e2e_deferred | integration |\n")
    assert bool(_acceptance_gap("TASK-001", section, coverage)) is blocked


def test_old_quality_schema_warns_and_relock_enables_new_gate(tmp_path: Path) -> None:
    task = tmp_path / "work.md"
    task.write_text("## TASK-001: Work\n- **Acceptance-Refs**: S-01\n")
    row = _scenario(exec="auto")
    row.pop("expected_refs")
    manifest = tmp_path / "manifest.json"
    data = {"schema": 3, "e2e_gate": 1, "scenarios_file": "work.scenarios.md", "checks": [], "scenarios": [row]}
    manifest.write_text(json.dumps(data))
    legacy = build_e2e_plan(str(manifest), str(task), "TASK-001")
    assert legacy["quality"]["ok"] is True
    assert "legacy_quality_schema" in {item["code"] for item in legacy["quality"]["warnings"]}
    data["quality_schema"] = 2
    manifest.write_text(json.dumps(data))
    assert build_e2e_plan(str(manifest), str(task), "TASK-001")["quality"]["ok"] is False
    data["quality_schema"] = 3
    manifest.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="unsupported.*quality_schema"):
        build_e2e_plan(str(manifest), str(task), "TASK-001")


def _browser_plan(root: Path) -> tuple[Path, Path]:
    from test_design_and_registration_gates import _pytest_check
    check = _pytest_check(root)
    task = root / "work.md"
    task.write_text("## TASK-001: Browser\n- **Acceptance-Refs**: S-01\n"
        "## Acceptance Coverage\n"
        "| 场景ID | source | level | boundary | owner | status | command | smoke |\n"
        "|---|---|---|---|---|---|---|---|\n"
        f"| S-01 | design | e2e | browser -> API | TASK-001 | planned | {json.dumps(check['command'])} | yes |\n")
    return task, root / "manifest.json"


@pytest.mark.parametrize("pytest_addopts", ["", "-q"])
def test_manifest_registers_real_tests_without_editing_generated_json(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch, pytest_addopts: str) -> None:
    from cf_acceptance_manifest import write_manifest
    task, target = _browser_plan(tmp_path)
    monkeypatch.setenv("PYTEST_ADDOPTS", pytest_addopts)
    manifest = write_manifest(str(task), str(target), register_checks=True)
    check = manifest["checks"][0]
    assert check["test_ids"] == ["test_probe.py::test_browser_order"]
    assert check["suite"] == "browser"
    assert set(check["markers"]) == {"browser", "smoke"}
    assert check["collect"]["format"] == "pytest"
    assert manifest["registration"]["registered"] == [check["id"]]


def test_failed_registration_does_not_replace_existing_lock(tmp_path: Path) -> None:
    from cf_acceptance_manifest import write_manifest
    from codeflow.acceptance.cf_acceptance_registration import RegistrationError
    task, target = _browser_plan(tmp_path)
    write_manifest(str(task), str(target))
    previous = target.read_bytes()
    (tmp_path / "test_probe.py").write_text("def test_browser_order(): pass\n")
    with pytest.raises(RegistrationError) as failure:
        write_manifest(str(task), str(target), register_checks=True)
    assert failure.value.report["errors"]
    assert target.read_bytes() == previous


def test_registration_file_is_validated_and_applied_through_cli(tmp_path: Path) -> None:
    from cf_acceptance_manifest import write_manifest
    task, target = _browser_plan(tmp_path)
    check = write_manifest(str(task), str(target))["checks"][0]
    config = tmp_path / "registration.json"
    config.write_text(json.dumps({"checks": {check["id"]: {"test_ids": ["test_probe.py::test_browser_order"]}}}))
    result = subprocess.run([sys.executable, str(SCRIPTS / "cf_acceptance_manifest.py"),
        "--task-file", str(task), "--output", str(target), "--registration-file", str(config)],
        cwd=tmp_path, capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout)["registration"]["ok"] is True


def test_relock_retains_history_and_marks_only_changed_scenarios_stale(tmp_path: Path) -> None:
    from cf_acceptance_manifest import write_manifest
    root, demand = _repo(tmp_path)
    target, task = demand / ".acceptance-manifest.json", demand / "work.md"
    result = run_manifest(str(target), str(root), write_evidence=True)
    assert result["decision"] == "pass", result
    old = json.loads(target.read_text())
    task.write_text(task.read_text().replace("|S-02|src|integration|real|", "|S-02|src|integration|new boundary|"))
    relocked = write_manifest(str(task), str(target))
    first, second = relocked["scenarios"]
    assert first["status"] == "verified"
    assert first["evidence"] == old["scenarios"][0]["evidence"]
    assert second["status"] == "stale"
    assert second["runs"] == old["scenarios"][1]["runs"]
    assert relocked["relock"]["stale"] == ["S-02"]


def test_new_file_proof_survives_commit_and_invalidates_on_content_change(tmp_path: Path) -> None:
    root, demand = _repo(tmp_path)
    source = root / "src/new.py"
    source.write_text("VALUE = 1\n")
    target = demand / ".acceptance-manifest.json"
    first = run_manifest(str(target), str(root), write_evidence=True, owner="TASK-001")
    assert first["decision"] == "pass", first
    for command in (("add", "-A"), ("commit", "-qm", "new source")):
        subprocess.run(["git", *command], cwd=root, check=True, capture_output=True)
    second = run_manifest(str(target), str(root), write_evidence=True, owner="TASK-001")
    assert second["results"][0].get("cache_reused") is True, second
    source.write_text("VALUE = 2\n")
    third = run_manifest(str(target), str(root), write_evidence=True, owner="TASK-001")
    assert not third["results"][0].get("cache_reused"), third


def test_deletion_fingerprint_survives_commit(tmp_path: Path) -> None:
    from codeflow.core.cf_exec_base import worktree_fingerprint
    root, _ = _repo(tmp_path)
    (root / "src/app.py").unlink()
    before = worktree_fingerprint(str(root))
    subprocess.run(["git", "add", "-A"], cwd=root, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-qm", "delete source"], cwd=root, check=True, capture_output=True)
    assert worktree_fingerprint(str(root)) == before


def test_requirement_smoke_filters_draft_owners_before_execution(tmp_path: Path) -> None:
    from cf_acceptance_manifest import write_manifest
    from cf_task_workflow import verify_layers
    root, demand = _repo(tmp_path)
    task = demand / "work.md"
    text = task.read_text().replace("- **Status**: draft", "- **Status**: done", 1)
    text = text.replace("|integration|", "|e2e|")
    lines = [line.replace('"pass"', '"raise SystemExit(1)"') if line.startswith("|S-02|") else line
             for line in text.splitlines()]
    task.write_text("\n".join(lines) + "\n")
    write_manifest(str(task), str(demand / ".acceptance-manifest.json"))
    result = verify_layers(str(root), str(demand), layers="e2e", profile="smoke", only_tasks=["TASK-001"])
    assert result["decision"] == "pass", result
    assert {item["id"] for item in result["layers"]["e2e"]["results"]} == {"S-01"}
    assert verify_layers(str(root), str(demand), layers="e2e", profile="full")["decision"] == "block"


def test_plan_reports_explicit_refresh_for_stale_artifact(tmp_path: Path) -> None:
    from codeflow.acceptance.cf_plan_quality import verify_plan
    from cf_spec_context import ArtifactRef, RuleStageStatus, apply_artifact_ref, load_context, save_context
    root, demand = _repo(tmp_path)
    artifact = demand / "design.md"
    artifact.write_text("## Matrix\nRULE-app-001: complete\n")
    context = load_context(str(demand / "spec-context.yml"))
    binding = context.bindings[0]
    rule = replace(binding.rules[0], stage_status={**binding.rules[0].stage_status,
                                                 "plan": RuleStageStatus("pending", (), None, ())})
    context = replace(context, bindings=(replace(binding, rules=(rule,)),))
    context = apply_artifact_ref(context, "app-runtime", "RULE-app-001", "plan",
        ArtifactRef("design.md", "Matrix", "RULE-app-001", hashlib.sha256(artifact.read_bytes()).hexdigest()))
    save_context(str(demand / "spec-context.yml"), context)
    artifact.write_text(artifact.read_text() + "\nupdated\n")
    result = verify_plan(str(demand), str(demand / "work.md"))
    assert result["decision"] == "block"
    assert any("spec refresh --task-dir" in value for value in result["next"])


def test_stop_concurrency_returns_owner_and_recovers_after_kill(tmp_path: Path) -> None:
    from cf_stop_hook import build_stop_result
    from codeflow.core.cf_stop_guard import stop_guard
    flow = tmp_path / ".code-flow"
    flow.mkdir()
    (flow / "config.yml").write_text("quality_loop:\n  enabled: true\n")
    script = ("from codeflow.core.cf_stop_guard import stop_guard; import sys\n"
              f"with stop_guard({str(tmp_path)!r}, 'holder'):\n print('ready', flush=True)\n sys.stdin.read()\n")
    holder = subprocess.Popen([sys.executable, "-u", "-c", script], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, text=True, env={**os.environ, "PYTHONPATH": str(SCRIPTS)})
    try:
        assert holder.stdout.readline().strip() == "ready"
        started = time.monotonic()
        result = build_stop_result(str(tmp_path), "second")
        assert result["decision"] == "block" and str(holder.pid) in result["reason"], result
        assert time.monotonic() - started < 1
    finally:
        holder.kill()
        holder.communicate(timeout=3)
    with stop_guard(str(tmp_path), "recovered"):
        assert True


@pytest.mark.skipif(os.name == "nt", reason="POSIX process-group regression")
def test_command_timeout_terminates_descendants_holding_output_pipes(tmp_path: Path) -> None:
    from codeflow.core.cf_exec_base import run_command
    marker = tmp_path / "orphan-output.txt"
    child = f"import time; from pathlib import Path; time.sleep(0.5); Path({str(marker)!r}).write_text('orphan')"
    command = [sys.executable, "-c", "import subprocess,sys,time; "
        f"subprocess.Popen([sys.executable,'-c',{child!r}]); time.sleep(6)"]
    started = time.monotonic()
    result = run_command(command, str(tmp_path), 0.1)
    assert result["status"] == "timeout", result
    assert time.monotonic() - started < 2
    time.sleep(0.7)
    assert not marker.exists(), "timed-out check must not leave descendants running"
