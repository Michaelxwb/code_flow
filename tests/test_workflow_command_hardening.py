"""Exercise public task commands against real installations, Git and processes."""
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import shutil
import subprocess
import sys

import pytest
import yaml

from test_audit_mainline_e2e import _repo
from test_cf_acceptance_consumers import Project, project as acceptance_project


ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "src/cli.js"


def _cli(root: Path, *args: str, input_text: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.run(["node", str(CLI), *args], cwd=root, input=input_text,
                          capture_output=True, text=True, timeout=40)


def _install(root: Path) -> None:
    result = _cli(root, "init", "--platform=codex")
    assert result.returncode == 0, result.stdout + result.stderr


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)


@dataclass(frozen=True)
class ActiveProject:
    root: Path
    demand: Path
    task: Path
    validation_log: Path

    def state(self) -> dict[str, bytes]:
        paths = (self.task, self.demand / "spec-context.yml",
                 self.root / ".code-flow/.active-task.json")
        return {str(path): path.read_bytes() for path in paths}


@pytest.fixture()
def active_project(tmp_path: Path) -> ActiveProject:
    root = tmp_path / "project"
    root.mkdir()
    _install(root)
    shutil.rmtree(root / ".code-flow/specs")
    validation_log = tmp_path / "validation.json"
    code = ("import json, sys; from pathlib import Path; "
            f"Path({str(validation_log)!r}).write_text(json.dumps(sys.argv[1:]))")
    import shlex
    command = shlex.join([sys.executable, "-c", code]) + " {files}"
    (root / ".code-flow/validation.yml").write_text(yaml.safe_dump({"validators": [
        {"name": "record-inputs", "trigger": "*.py", "command": command, "timeout": 5000}]}))
    root, demand = _repo(root)
    (root / "src/untouched.py").write_text("VALUE = 0\n")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "prepare command probe")
    task = demand / "work.md"
    result = _cli(root, "task", "start", "--root", str(root), "--task-dir", str(demand), "--task-file", str(task),
                  "--task", "TASK-001", "--json", input_text='{"owned_paths":[]}')
    assert result.returncode == 0, result.stdout + result.stderr
    (root / "src/app.py").write_text("VALUE = 1\n# committed task change\n")
    _git(root, "add", "src/app.py")
    _git(root, "commit", "-qm", "task implementation")
    (root / "src/extra.py").write_text("VALUE = 2\n")
    return ActiveProject(root, demand, task, validation_log)


@pytest.mark.parametrize("action", ["verify", "verify-e2e"])
@pytest.mark.parametrize("selector", [("--checks",), ("--layers", "validators")])
def test_validator_commands_work_during_coding_without_advancing_state(
    active_project: ActiveProject, action: str, selector: tuple[str, ...],
) -> None:
    project = active_project
    before = project.state()
    completed = _cli(project.root, "task", action, "--task-dir", str(project.demand),
                     *selector, "--profile", "full", "--json")
    result = json.loads(completed.stdout)
    assert completed.returncode == 0, result
    assert result["selected_layers"] == ["validators"]
    assert result["executed"] == 1
    assert set(json.loads(project.validation_log.read_text())) == {"src/app.py", "src/extra.py"}
    assert project.state() == before


def test_requirement_gate_still_rejects_unfinished_tasks(active_project: ActiveProject) -> None:
    project = active_project
    before = project.state()
    completed = _cli(project.root, "task", "verify", "--task-dir", str(project.demand),
                     "--profile", "full", "--json")
    assert completed.returncode == 3
    assert json.loads(completed.stdout)["reason"] == "unfinished_tasks"
    assert not project.validation_log.exists()
    assert project.state() == before


@pytest.mark.parametrize("fault", ["corrupt_marker", "context_hash", "wrong_requirement"])
def test_validator_commands_preserve_active_context_guards(active_project: ActiveProject,
                                                           fault: str) -> None:
    project = active_project
    marker = project.root / ".code-flow/.active-task.json"
    demand = project.demand
    if fault == "corrupt_marker":
        marker.write_text("{")
    elif fault == "context_hash":
        data = json.loads(marker.read_text())
        data["context_sha256"] = "f" * 64
        marker.write_text(json.dumps(data))
    else:
        demand = project.demand.parent / "other"
        demand.mkdir()
    before = project.state()
    completed = _cli(project.root, "task", "verify", "--checks", "--task-dir", str(demand), "--json")
    assert completed.returncode != 0
    assert json.loads(completed.stdout)["decision"] == "block"
    assert not project.validation_log.exists()
    assert project.state() == before


@pytest.mark.parametrize("action", ["verify", "verify-e2e"])
def test_both_verify_entries_reject_conflicting_checks_layers(active_project: ActiveProject,
                                                             action: str) -> None:
    project = active_project
    completed = _cli(project.root, "task", action, "--checks", "--layers", "e2e",
                     "--task-dir", str(project.demand), "--json")
    assert completed.returncode == 2, completed.stdout + completed.stderr
    assert "--checks" in completed.stdout + completed.stderr
    assert not project.validation_log.exists()


@pytest.mark.parametrize("action, flags", [
    ("verify", ("--scenarios", "S-01")),
    ("archive", ("--checks",)),
    ("finish", ("--profile", "full")),
])
def test_task_actions_reject_irrelevant_options(tmp_path: Path, action: str,
                                               flags: tuple[str, ...]) -> None:
    _install(tmp_path)
    completed = _cli(tmp_path, "task", action, "--task-dir", ".code-flow/tasks/missing", *flags)
    assert completed.returncode == 2, completed.stdout + completed.stderr
    assert "unrecognized arguments" in completed.stderr
    assert flags[0] in completed.stderr


@pytest.fixture()
def diagnostic_project(tmp_path: Path) -> Project:
    _install(tmp_path)
    return acceptance_project.__wrapped__(tmp_path)


@pytest.mark.parametrize("entry", ["acceptance", "verify"])
def test_multicheck_preflight_exposes_the_failed_check_and_dependency(diagnostic_project: Project,
                                                                    entry: str) -> None:
    project = diagnostic_project
    data = project.data()
    check = next(item for item in data["checks"] if item["id"] == "CHK-B")
    probe = [sys.executable, "-c", 'import sys; sys.stderr.write("database unavailable"); sys.exit(7)']
    check["preflight"] = [probe]
    if entry == "verify":
        next(row for row in data["scenarios"] if row["id"] == "S-01")["kind"] = "e2e"
    project.manifest.write_text(json.dumps(data))
    arguments = (("acceptance", "run", "--manifest", str(project.manifest), "--write-evidence")
                 if entry == "acceptance" else ("task", "verify", "--task-dir", str(project.demand),
                                                "--layers", "e2e", "--profile", "full", "--json"))
    completed = _cli(project.root, *arguments, "--root", str(project.root))
    result = json.loads(completed.stdout)
    assert completed.returncode == 3, result
    detail = next(item for item in result["env_blocked_details"] if item["check_id"] == "CHK-B")
    assert detail["owner"] == "TASK-001"
    assert detail["command"] == check["command"]
    missing = next(item for item in detail["missing"] if item["command"] == probe)
    assert missing["exit_code"] == 7
    assert missing["output"] == "database unavailable"
    evidence = next(row for row in project.data()["scenarios"] if row["id"] == "S-01")["evidence"]
    assert evidence["check_results"]["CHK-B"]["missing"] == detail["missing"]
    assert project.store().read_latest("CHK-A")["status"] == "passed"


def test_multicheck_assertion_output_is_preserved_in_result_and_evidence(diagnostic_project: Project) -> None:
    project = diagnostic_project
    data = project.data()
    check = next(item for item in data["checks"] if item["id"] == "CHK-B")
    check["command"] = [sys.executable, "-c", 'import sys; sys.stderr.write("B assertion failed"); sys.exit(9)']
    project.manifest.write_text(json.dumps(data))
    completed = _cli(project.root, "acceptance", "run", "--manifest", str(project.manifest),
                     "--root", str(project.root), "--write-evidence")
    result = json.loads(completed.stdout)
    assert completed.returncode == 3, result
    outcome = next(row for row in result["results"] if row["id"] == "S-01")["check_results"]["CHK-B"]
    assert outcome["exit_code"] == 9
    assert outcome["output"] == "B assertion failed"
    evidence = next(row for row in project.data()["scenarios"] if row["id"] == "S-01")["evidence"]
    assert evidence["check_results"]["CHK-B"]["output"] == outcome["output"]
