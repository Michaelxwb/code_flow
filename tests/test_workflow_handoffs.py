"""Real CLI, Git scope and crash-recovery regressions for command handoffs."""
import json
import subprocess
import sys
from pathlib import Path
from unittest import mock

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "src/core/code-flow/scripts"
sys.path.insert(0, str(SCRIPTS))

from cf_acceptance_manifest import write_manifest
from cf_validation import validation_scope
from cf_workflow_service import start_task
from cf_workflow_transaction import commit_transition, recover_transition
from test_audit_mainline_e2e import _git, _repo


def _cli(root: Path, script: str, *args: str, payload: str = "{}") -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(SCRIPTS / script), *args],
                          cwd=root, input=payload, text=True, capture_output=True, timeout=30)


def _transition_files(root: Path) -> tuple[Path, Path]:
    task = root / "task.md"
    task.write_text("in-progress")
    marker = root / ".code-flow/.active-task.json"
    marker.parent.mkdir()
    marker.write_text("active")
    return task, marker


def test_transition_write_failure_preserves_both_files(tmp_path: Path) -> None:
    import cf_workflow_transaction as transaction
    task, marker = _transition_files(tmp_path)
    original = transaction._write

    def fail_marker(path: Path, value: str) -> None:
        if path == marker and value is None:
            raise OSError("simulated full disk")
        original(path, value)

    with mock.patch.object(transaction, "_write", side_effect=fail_marker):
        with pytest.raises(OSError, match="full disk"):
            commit_transition(str(tmp_path), task, "in-progress", "done", "active", None)
    assert task.read_text() == "in-progress"
    assert marker.read_text() == "active"
    assert not (marker.parent / ".workflow-transition.json").exists()


def _interrupt_transition(root: Path, task: Path, marker: Path) -> None:
    import cf_workflow_transaction as transaction
    original = transaction._write

    def interrupt_marker(path: Path, value: str) -> None:
        if path == marker:
            raise KeyboardInterrupt()
        original(path, value)

    with mock.patch.object(transaction, "_write", side_effect=interrupt_marker):
        with pytest.raises(KeyboardInterrupt):
            commit_transition(str(root), task, "in-progress", "done", "active", None)


def test_interrupted_transition_rolls_forward_once(tmp_path: Path) -> None:
    task, marker = _transition_files(tmp_path)
    _interrupt_transition(tmp_path, task, marker)
    assert task.read_text() == "done" and marker.exists()
    assert recover_transition(str(tmp_path))
    assert task.read_text() == "done" and not marker.exists()
    assert not recover_transition(str(tmp_path))


def test_recovery_preserves_concurrent_user_edit(tmp_path: Path) -> None:
    task, marker = _transition_files(tmp_path)
    _interrupt_transition(tmp_path, task, marker)
    task.write_text("user changed this")
    with pytest.raises(ValueError, match="concurrent change"):
        recover_transition(str(tmp_path))
    assert task.read_text() == "user changed this"
    assert marker.read_text() == "active"
    assert (marker.parent / ".workflow-transition.json").exists()


def test_finish_cli_blocks_then_finishes_and_unlocks_next_task(tmp_path: Path) -> None:
    root, directory = _repo(tmp_path)
    task = directory / "work.md"
    start_task(str(root), str(directory), str(task), "TASK-001")
    # Regex verifiers reject matches; this fixture forbids VALUE = 2.
    (root / "src/app.py").write_text("VALUE = 2\n")
    args = ("finish", "--task-dir", str(directory), "--task", "TASK-001", "--json")
    failed = _cli(root, "cf_task_workflow.py", *args)
    assert failed.returncode == 3, failed.stderr + failed.stdout
    assert json.loads(failed.stdout)["decision"] == "block"
    assert (root / ".code-flow/.active-task.json").exists()
    (root / "src/app.py").write_text("VALUE = 1\n# valid implementation\n")
    passed = _cli(root, "cf_task_workflow.py", *args)
    assert passed.returncode == 0, passed.stderr + passed.stdout
    assert json.loads(passed.stdout)["decision"] == "pass"
    assert not (root / ".code-flow/.active-task.json").exists()
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "finish first")
    assert start_task(str(root), str(directory), str(task), "TASK-002")["ok"]


def test_final_e2e_cli_requires_functional_evidence_and_promotes_only_on_success(tmp_path: Path) -> None:
    root, directory = _repo(tmp_path)
    task = directory / "work.md"
    text = task.read_text().replace("**Status**: draft", "**Status**: done")
    text = text.replace("**Acceptance-Refs**: S-02", "**Acceptance-Refs**: S-02, E-01")
    command = json.dumps([sys.executable, "-c", "from pathlib import Path; assert Path('ready').exists()"])
    task.write_text(text + f"|E-01|src|E2E|real process|TASK-002|planned|{command}|\n")
    manifest = directory / ".acceptance-manifest.json"
    write_manifest(str(task), str(manifest))
    args = ("verify-e2e", "--task-dir", str(directory), "--json")
    missing = _cli(root, "cf_task_workflow.py", *args)
    assert json.loads(missing.stdout)["reason"] == "functional_or_manual_evidence_missing"
    from cf_acceptance_runner import run_manifest
    assert run_manifest(str(manifest), str(root), write_evidence=True)["decision"] == "pass"
    failed = _cli(root, "cf_task_workflow.py", *args)
    assert failed.returncode == 3, failed.stderr + failed.stdout
    assert "**Status**: verified" not in task.read_text()
    (root / "ready").touch()
    passed = _cli(root, "cf_task_workflow.py", *args)
    assert passed.returncode == 0, passed.stderr + passed.stdout
    assert task.read_text().count("**Status**: verified") == 2
    assert json.loads(manifest.read_text())["scenarios"][-1]["status"] == "verified"


def test_validation_includes_untracked_and_committed_active_changes(tmp_path: Path) -> None:
    root, directory = _repo(tmp_path)
    start_task(str(root), str(directory), str(directory / "work.md"), "TASK-001")
    (root / "src/app.py").write_text("VALUE = 2\n")
    _git(root, "add", "src/app.py")
    _git(root, "commit", "-qm", "implementation")
    (root / "src/new file.py").write_text("VALUE = 2\n")
    assert {"src/app.py", "src/new file.py"} <= set(validation_scope(str(root)))


def test_validation_cli_catches_untracked_syntax_error_with_quoted_filename(tmp_path: Path) -> None:
    root, _ = _repo(tmp_path)
    (root / ".code-flow/validation.yml").write_text(
        'validators:\n  - name: syntax\n    trigger: "*.py"\n'
        '    command: "python3 -m py_compile {files}"\n')
    (root / "src/new ' file.py").write_text("invalid python!\n")
    result = _cli(root, "cf_validation.py", "--json")
    assert result.returncode == 3, result.stderr + result.stdout
    assert json.loads(result.stdout)["decision"] == "block"
    with pytest.raises(ValueError, match="outside"):
        validation_scope(str(root), ("../outside.py",))


def test_validation_deletions_trigger_global_tests_not_file_compiler(tmp_path: Path) -> None:
    root, _ = _repo(tmp_path)
    (root / ".code-flow/validation.yml").write_text(
        'validators:\n  - name: syntax\n    trigger: "*.py"\n'
        '    command: "python3 -m py_compile {files}"\n'
        '  - name: global\n    trigger: "*.py"\n'
        '    command: "python3 -c pass"\n')
    (root / "src/app.py").unlink()
    result = _cli(root, "cf_validation.py", "--json")
    assert result.returncode == 0, result.stderr + result.stdout
    assert "src/app.py" in json.loads(result.stdout)["files"]


def test_validation_missing_executable_is_not_success(tmp_path: Path) -> None:
    root, _ = _repo(tmp_path)
    (root / "src/new.py").touch()
    (root / ".code-flow/validation.yml").write_text(
        'validators:\n  - name: absent\n    trigger: "*.py"\n'
        '    command: "cf-executable-that-does-not-exist"\n')
    result = _cli(root, "cf_validation.py", "--json")
    assert result.returncode == 3, result.stderr + result.stdout
    assert json.loads(result.stdout)["failures"]


def test_draft_block_resume_cli_does_not_create_active_marker(tmp_path: Path) -> None:
    root, directory = _repo(tmp_path)
    args = ("--task-dir", str(directory), "--task", "TASK-001", "--json")
    blocked = _cli(root, "cf_task_workflow.py", "block", *args, "--reason", "await answer")
    assert blocked.returncode == 0, blocked.stderr + blocked.stdout
    resumed = _cli(root, "cf_task_workflow.py", "resume", *args)
    assert resumed.returncode == 0, resumed.stderr + resumed.stdout
    assert "**Status**: blocked" not in (directory / "work.md").read_text()
    assert not (root / ".code-flow/.active-task.json").exists()


def test_done_rejects_wrong_demand_before_mutating_context(tmp_path: Path) -> None:
    from cf_task_runtime import run_done_gate
    root, directory = _repo(tmp_path)
    start_task(str(root), str(directory), str(directory / "work.md"), "TASK-001")
    other = root / ".code-flow/tasks/other"
    other.mkdir()
    result = run_done_gate(str(root), str(other), task_id="TASK-001")
    assert result.decision == "block" and "active_mismatch" in result.message
    assert not (other / "spec-context.yml").exists()


def test_legacy_active_cli_rejects_wrong_demand_without_task_file(tmp_path: Path) -> None:
    from cf_spec_context import load_active_task
    root, directory = _repo(tmp_path)
    start_task(str(root), str(directory), str(directory / "work.md"), "TASK-001")
    active = load_active_task(str(root))
    result = _cli(root, "cf_spec_context.py", "active", "complete", "--root", str(root),
                  "--task-dir", ".code-flow/tasks/missing", "--task", "TASK-001",
                  "--context-sha256", active.context_sha256, "--json", payload='{"gate_passed": true}')
    assert result.returncode != 0
    assert "active_mismatch" in result.stdout
    assert (root / ".code-flow/.active-task.json").exists()


def test_unconfigured_rerun_clears_stale_verified(tmp_path: Path) -> None:
    from cf_acceptance_runner import run_manifest
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"scenarios": [
        {"id": "S-01", "kind": "functional", "status": "verified"}]}))
    assert run_manifest(str(manifest), str(tmp_path), write_evidence=True)["decision"] == "block"
    assert json.loads(manifest.read_text())["scenarios"][0]["status"] == "not_configured"


def test_manifest_cannot_redirect_evidence_to_another_task_file(tmp_path: Path) -> None:
    from cf_acceptance_manifest import validate_manifest
    root, directory = _repo(tmp_path)
    other = root / ".code-flow/tasks/other/work.md"
    other.parent.mkdir()
    other.write_text((directory / "work.md").read_text())
    manifest = directory / ".acceptance-manifest.json"
    data = json.loads(manifest.read_text())
    data["task_file"] = str(other)
    manifest.write_text(json.dumps(data))
    assert validate_manifest(str(directory / "work.md"), str(manifest)) == (
        False, "acceptance_manifest_task_mismatch")


@pytest.mark.parametrize("evidence", [{}, {"status": "failed", "exit_code": 1},
                                     {"status": "passed", "exit_code": 1}])
def test_verified_label_alone_does_not_close_acceptance(evidence: dict) -> None:
    from cf_acceptance_schema import verified_evidence
    assert not verified_evidence({"status": "verified", "kind": "functional", "evidence": evidence})


def test_stats_counts_selected_platform_and_excludes_session(tmp_path: Path) -> None:
    from cf_core import project_instruction_file
    from cf_scan import build_report
    (tmp_path / "AGENTS.md").write_text("Project rules\n" * 30)
    session = tmp_path / ".code-flow/specs/_session/task-demo.md"
    session.parent.mkdir(parents=True)
    before = build_report(str(tmp_path))
    session.write_text("temporary injection\n" * 100)
    after = build_report(str(tmp_path))
    assert after["total_tokens"] == before["total_tokens"] > 0
    assert all("_session" not in item["path"] for item in after["files"])
    result = _cli(tmp_path, "cf_stats.py", "--json")
    assert json.loads(result.stdout)["l0"]["file"] == "AGENTS.md"
    assert "L0 (AGENTS.md)" in _cli(tmp_path, "cf_stats.py", "--human").stdout
    (tmp_path / "CLAUDE.md").write_text("Claude-specific rules")
    assert project_instruction_file(str(tmp_path), "claude") == "CLAUDE.md"
    assert project_instruction_file(str(tmp_path), "codex") == "AGENTS.md"


def test_graph_distinguishes_batches_from_dependency_components(tmp_path: Path) -> None:
    from cf_task_index import index_data
    task = tmp_path / "work.md"
    task.write_text("## TASK-001: A\n- **Status**: draft\n"
                    "## TASK-002: B\n- **Status**: draft\n- **Depends**: TASK-001\n"
                    "## TASK-003: C\n- **Status**: draft\n")
    data = index_data(str(task))
    assert data["batches"] == [["TASK-001", "TASK-003"], ["TASK-002"]]
    assert data["dependency_components"] == [["TASK-001", "TASK-002"], ["TASK-003"]]
    assert data["independent_groups"] == data["dependency_components"]
