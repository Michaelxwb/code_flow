"""Behavioral regressions for acceptance integrity and workflow handoffs."""
import io
import json
import subprocess
import sys
from pathlib import Path
from unittest import mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src/core/code-flow/scripts"))
from cf_acceptance_manifest import write_manifest
from cf_acceptance_runner import run_manifest
from cf_spec_context import load_context, save_context, start_active_task
from cf_spec_session import context_sha256, project_task_session
from cf_spec_verify import VerificationScope, run_all_verifiers
from cf_task_runtime import run_done_gate
from cf_workflow_service import WorkflowError, check_startable, complete_task, start_task
from test_cf_injection_version import _repo, _ctx, _prompt
from test_cf_spec_verify import _metadata


def _manifest(root: Path, scenarios: list, **extra: object) -> Path:
    path = root / "manifest.json"
    path.write_text(json.dumps({"scenarios": scenarios, **extra}), encoding="utf-8")
    return path


def test_distinct_working_directories_never_share_success(tmp_path: Path) -> None:
    (tmp_path / "good").mkdir()
    (tmp_path / "bad").mkdir()
    command = [sys.executable, "-c", "from pathlib import Path; assert Path.cwd().name == 'good'"]
    path = _manifest(tmp_path, [{"id": "S-01", "command": command, "cwd": "good"},
                                {"id": "S-02", "command": command, "cwd": "bad"}])
    result = run_manifest(str(path), str(tmp_path))
    assert result["decision"] == "block"
    assert [row["status"] for row in result["results"]] == ["passed", "failed"]


def test_distinct_timeouts_never_share_success(tmp_path: Path) -> None:
    command = [sys.executable, "-c", "import time; time.sleep(.1)"]
    path = _manifest(tmp_path, [{"id": "S-01", "command": command, "timeout": 2},
                                {"id": "S-02", "command": command, "timeout": .01}])
    assert run_manifest(str(path), str(tmp_path))["decision"] == "block"


def test_owner_evidence_is_persisted_to_original_manifest(tmp_path: Path) -> None:
    path = _manifest(tmp_path, [{"id": "S-01", "owner": "TASK-001", "depends_on": [],
                                "command": [sys.executable, "-c", "pass"], "status": "planned"}])
    run_manifest(str(path), str(tmp_path), write_evidence=True, owner="TASK-001")
    row = json.loads(path.read_text())["scenarios"][0]
    assert row["status"] == "verified"
    assert row["evidence"]["status"] == "passed"


def test_evidence_adds_status_cell_without_merging_last_contract_cell(tmp_path: Path) -> None:
    from cf_acceptance_evidence import sync_task_evidence
    task = tmp_path / "task.md"
    task.write_text("## TASK-001: Demo\n### Acceptance Contract\n"
                    "| S-01 | real DB | assert persisted |\n")
    sync_task_evidence(task, "S-01", "runner", "passed", "TASK-001")
    assert "| S-01 | real DB | assert persisted | verified |" in task.read_text()


def test_failed_rerun_invalidates_status_and_preserves_contract_history(tmp_path: Path) -> None:
    task = tmp_path / "task.md"
    task.write_text("## TASK-001: Demo\n- **Acceptance-Refs**: S-01\n"
                    "### Acceptance Contract\n"
                    "| S-01 | integration | real API -> DB | assert row persisted | planned |\n"
                    "### Acceptance Evidence\n- S-01: RED assert row missing\n", encoding="utf-8")
    command = [sys.executable, "-c", "from pathlib import Path; assert not Path('fail').exists()"]
    path = _manifest(tmp_path, [{"id": "S-01", "command": command, "owner": "TASK-001"}], task_file="task.md")
    run_manifest(str(path), str(tmp_path), write_evidence=True)
    (tmp_path / "fail").touch()
    assert run_manifest(str(path), str(tmp_path), write_evidence=True)["decision"] == "block"
    row = json.loads(path.read_text())["scenarios"][0]
    assert row["status"] != "verified"
    assert len(row["runs"]) == 2
    text = task.read_text()
    assert "real API -> DB" in text and "assert row persisted" in text
    assert "RED assert row missing" in text
    from cf_stop_hook import _acceptance_gap
    section = text.replace("## TASK-001: Demo", "## TASK-001: Demo\n- **Status**: done")
    assert _acceptance_gap("TASK-001", section, "| S-01 | verified |")


@pytest.mark.parametrize("data", [[], {"scenarios": [None]}, {"scenarios": [{"id": "S-01"}, {"id": "S-01"}]}])
def test_malformed_or_duplicate_manifest_rejected(tmp_path: Path, data: object) -> None:
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        run_manifest(str(path), str(tmp_path))


def test_duplicate_coverage_rejected_at_lock(tmp_path: Path) -> None:
    task = tmp_path / "task.md"
    row = "| S-01 | design#1 | integration | real | TASK-001 | planned |\n"
    task.write_text("## Acceptance Coverage\n" + row + row)
    with pytest.raises(ValueError, match="duplicate"):
        write_manifest(str(task), str(tmp_path / "manifest.json"))


@pytest.mark.parametrize("state,kind,task_status,blocked", [
    ("unverified", "integration", "done", True),
    ("verified", "integration", "done", False),
    ("e2e_deferred", "E2E", "done", False),
    ("e2e_deferred", "E2E", "verified", True),
    ("e2e_deferred", "integration", "done", True),
])
def test_stop_checks_exact_state_and_allows_only_e2e_deferral(state: str, kind: str, task_status: str, blocked: bool) -> None:
    from cf_stop_hook import _acceptance_gap
    section = (f"## TASK-001: Demo\n- **Status**: {task_status}\n- **Acceptance-Refs**: S-01\n"
               f"### Acceptance Contract\n| S-01 | {kind} | real | assertion | {state} |\n"
               f"### Acceptance Evidence\n- S-01: {state}\n")
    coverage = f"| S-01 | design | {kind} | real | TASK-001 | {state} |"
    assert bool(_acceptance_gap("TASK-001", section, coverage)) == blocked


def test_stop_corrupt_manifest_blocks_with_json(tmp_path: Path) -> None:
    import cf_stop_hook
    root = _repo(tmp_path)
    start_active_task(str(root), ".code-flow/tasks/demo", "TASK-001", _ctx(root))
    (root / ".code-flow/tasks/demo/.acceptance-manifest.json").write_text("[]")
    output = io.StringIO()
    with mock.patch("sys.stdin", io.StringIO('{"session_id":"audit"}')), mock.patch("sys.stdout", output), mock.patch("os.getcwd", return_value=str(root)):
        cf_stop_hook.main()
    assert json.loads(output.getvalue())["decision"] == "block"


@pytest.mark.parametrize("damage", ["missing", "command"])
def test_done_revalidates_manifest(tmp_path: Path, damage: str) -> None:
    from test_audit_mainline_e2e import _repo as mainline_repo
    root, directory = mainline_repo(tmp_path)
    task = directory / "work.md"
    start_task(str(root), str(directory), str(task), "TASK-001")
    path = directory / ".acceptance-manifest.json"
    if damage == "missing":
        path.unlink()
    else:
        data = json.loads(path.read_text())
        data["scenarios"][0]["command"] = [sys.executable, "-c", "print('changed')"]
        path.write_text(json.dumps(data))
    assert run_done_gate(str(root), str(directory)).decision == "block"


def test_user_confirmed_pending_design_plan_can_still_start(tmp_path: Path) -> None:
    from test_audit_mainline_e2e import _repo as mainline_repo
    from cf_spec_context import BindingInput, bind_specs, new_context
    from cf_spec_resolver import resolve_candidates
    root, directory = mainline_repo(tmp_path)
    spec = root / ".code-flow/specs/app/rules.md"
    spec.write_text(spec.read_text().replace("stages: [code]", "stages: [design, plan, code]"))
    candidate = resolve_candidates(str(root), "code", ["src/app.py"])[0]
    context = bind_specs(new_context("demo", (("user", "confirmed"),)), (BindingInput(candidate, "plan", "confirmed"),))
    save_context(str(directory / "spec-context.yml"), context)
    result = start_task(str(root), str(directory), str(directory / "work.md"), "TASK-001", (".code-flow/specs/app/rules.md",))
    assert result["ok"] is True


def test_complete_rejects_same_id_from_other_demand(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    directory = root / ".code-flow/tasks/demo"
    start_active_task(str(root), str(directory), "TASK-001", _ctx(root))
    wrong = root / ".code-flow/tasks/other/other.md"
    wrong.parent.mkdir()
    wrong.write_text("## TASK-001: Other\n- **Status**: draft\n")
    with pytest.raises(WorkflowError):
        complete_task(str(root), str(wrong.parent), str(wrong), "TASK-001", True)
    assert (root / ".code-flow/.active-task.json").exists()
    assert "draft" in wrong.read_text()


def test_verified_dependency_is_startable(tmp_path: Path) -> None:
    task = tmp_path / "task.md"
    task.write_text("## TASK-001: First\n- **Status**: verified\n"
                    "## TASK-002: Second\n- **Status**: draft\n- **Depends**: TASK-001\n")
    assert check_startable(str(task), "TASK-002") == []


def test_document_cache_invalidates_when_artifact_changes(tmp_path: Path) -> None:
    metadata = _metadata(tmp_path, [{"rule": "RULE-verify-001", "type": "document", "config": {
        "artifact": "design.md", "section_id": "SECTION", "item_id": "RULE-verify-001"}}], [("RULE-verify-001", "Document")])
    artifact = tmp_path / "design.md"
    artifact.write_text("SECTION RULE-verify-001")
    scope = VerificationScope(str(tmp_path), (), "a" * 64)
    assert run_all_verifiers(metadata, scope).passed
    artifact.write_text("required content removed")
    assert not run_all_verifiers(metadata, scope).passed


def test_duplicate_verifier_commands_run_once_per_gate(tmp_path: Path) -> None:
    command = [sys.executable, "-c", "from pathlib import Path; p=Path('count'); p.write_text(p.read_text()+'x' if p.exists() else 'x')"]
    rules = [(f"RULE-verify-{i:03d}", "Same suite") for i in range(1, 4)]
    metadata = _metadata(tmp_path, [{"rule": rule, "type": "test", "config": {"argv": command}} for rule, _ in rules], rules)
    scope = VerificationScope(str(tmp_path), (), "a" * 64)
    assert run_all_verifiers(metadata, scope).passed
    assert (tmp_path / "count").read_text() == "x"
    assert run_all_verifiers(metadata, scope).passed
    assert (tmp_path / "count").read_text() == "xx", "do not cache commands across runs"


def test_oversized_acceptance_without_rules_reports_truncation(tmp_path: Path) -> None:
    from cf_spec_context import new_context
    task = tmp_path / "task.md"
    task.write_text("## TASK-001: Demo\n- **Spec-Refs**:\n### Acceptance Contract\n" + "x" * 13000)
    result = project_task_session(new_context("demo", (("audit", "budget"),)), str(task), "TASK-001")
    assert result.truncated


def test_long_contract_tail_change_reinjects(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    task = root / ".code-flow/tasks/demo/demo.md"
    task.write_text(task.read_text().replace("first contract", "x" * 3500 + " ASSERT_A"))
    start_active_task(str(root), ".code-flow/tasks/demo", "TASK-001", _ctx(root))
    assert "ASSERT_A" in _prompt(root)
    task.write_text(task.read_text().replace("ASSERT_A", "ASSERT_B"))
    assert "ASSERT_B" in _prompt(root)
