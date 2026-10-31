"""TASK-003 acceptance at real Git, selection, validator and Done boundaries."""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

SCRIPTS = Path(__file__).resolve().parents[1] / "src/core/code-flow/scripts"
sys.path.insert(0, str(SCRIPTS))

from cf_acceptance_manifest import write_manifest
from codeflow.cli.cf_acceptance_runner import run_manifest
from cf_spec_context import new_context, save_context, start_active_task
from codeflow.acceptance.cf_acceptance_selection import select_profile
from codeflow.acceptance.cf_check_inputs import check_input_hash
from codeflow.task.cf_task_runtime import run_done_gate


def _git(root: Path, *args: str) -> None:
    subprocess.run(("git", *args), cwd=root, check=True, capture_output=True)


def _repo(root: Path) -> None:
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "test@example.invalid")
    _git(root, "config", "user.name", "Test")


def _write(root: Path, name: str, content: str = "initial\n") -> None:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _commit(root: Path) -> None:
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "baseline")


def _exercise_done_gate(tmp_path: Path) -> None:
    _repo(tmp_path)
    task_dir = tmp_path / ".code-flow/tasks/demand"
    task_dir.mkdir(parents=True)
    (tmp_path / ".code-flow/specs").mkdir()
    _write(tmp_path, ".code-flow/config.yml", "spec_workflow:\n  schema_version: 1\n  enforcement: required\nquality_loop:\n  enabled: true\n  finish_check: true\npath_mapping: {}\n")
    _write(tmp_path, ".code-flow/validation.yml", "validators:\n  - name: scoped\n    trigger: '*.py'\n    command: 'python3 validator.py'\n    timeout: 30000\n")
    _write(tmp_path, "validator.py", "from pathlib import Path\nPath('validator.count').write_text('ran')\n")
    _write(tmp_path, "owned.py", "VALUE = 1\n")
    def command(name: str) -> str:
        return json.dumps([sys.executable, "-c", f"from pathlib import Path; Path('{name}.count').write_text('ran')"])
    coverage = "\n".join(f"| S-0{i} | d#1 | {level} | boundary | TASK-00{owner} | planned | {command(name)} |"
                         for i, (level, owner, name) in enumerate([
                             ("integration", 1, "owned"), ("integration", 2, "other"),
                             ("e2e", 2, "browser"), ("capacity", 2, "capacity")], 1))
    task = task_dir / "work.md"
    task.write_text("## TASK-001: One\n- **Status**: draft\n- **Acceptance-Refs**: S-01\n"
        "## TASK-002: Two\n- **Status**: draft\n- **Acceptance-Refs**: S-02, S-03, S-04\n"
        "## Acceptance Coverage\n| 场景ID | 来源设计 | 测试层级 | 关键真实边界 | 负责任务 | 状态 | 执行命令 |\n"
        "|---|---|---|---|---|---|---|\n" + coverage + "\n", encoding="utf-8")
    save_context(str(task_dir / "spec-context.yml"), new_context("demo", (("test", "owner"),)))
    _commit(tmp_path)
    write_manifest(str(task), str(task_dir / ".acceptance-manifest.json"))
    start_active_task(str(tmp_path), ".code-flow/tasks/demand", "TASK-001", "ctx")
    _write(tmp_path, "owned.py", "VALUE = 2\n")
    marker = tmp_path / ".code-flow/.active-task.json"
    saved = json.loads(marker.read_text(encoding="utf-8"))
    for head in (None, "f" * 40):
        invalid = json.loads(json.dumps(saved))
        invalid["baseline"]["head"] = head
        marker.write_text(json.dumps(invalid), encoding="utf-8")
        unproven = run_done_gate(str(tmp_path), str(task_dir), task_id="TASK-001")
        assert unproven.decision == "block" and "baseline" in unproven.message
        assert not (tmp_path / "owned.count").exists()
    marker.write_text(json.dumps(saved), encoding="utf-8")
    outcome = run_done_gate(str(tmp_path), str(task_dir), task_id="TASK-001")
    assert outcome.decision == "pass", outcome.message
    assert (tmp_path / "owned.count").exists() and (tmp_path / "validator.count").exists()
    assert not any((tmp_path / f"{name}.count").exists() for name in ("other", "browser", "capacity"))


def test_s04_task_scope_starts_no_unrelated_stack(tmp_path: Path) -> None:
    _exercise_done_gate(tmp_path)


def _selection_fixture(root: Path) -> tuple[dict, dict]:
    _repo(root)
    for name in ("app/a.py", "app/b.py", "shared/auth.py", "contracts/api.json", "tests/test_api.py", "requirements.lock", "notes.txt"):
        _write(root, name)
    _commit(root)
    checks = {name: {"id": name, "command": ["true"], "inputs": [f"app/{name}.py", "shared/auth.py", "contracts/api.json", "tests/test_api.py", "requirements.lock"]} for name in ("a", "b")}
    scenarios = [{"id": f"S-0{i}", "kind": "functional", "priority": "P1", "checks": [name]} for i, name in enumerate(checks, 1)]
    return {"schema": 3, "checks": list(checks.values()), "scenarios": scenarios}, checks


def test_s05_shared_dependency_expands_scope(tmp_path: Path) -> None:
    data, checks = _selection_fixture(tmp_path)
    manifest = tmp_path / "evidence.json"
    manifest.write_text(json.dumps(data), encoding="utf-8")
    first = run_manifest(str(manifest), str(tmp_path), write_evidence=True)
    assert first["executed"] == 2
    original = {key: check_input_hash(str(tmp_path), check, "baseline")["input_hash"] for key, check in checks.items()}
    for name in ("shared/auth.py", "contracts/api.json", "tests/test_api.py", "requirements.lock"):
        _write(tmp_path, name, "changed\n")
        selected = select_profile(data, str(tmp_path), "changed")
        assert {row["id"] for row in selected["scenarios"]} == {"S-01", "S-02"}
        assert all(check_input_hash(str(tmp_path), check, "baseline")["input_hash"] != original[key] for key, check in checks.items())
        _git(tmp_path, "checkout", "--", name)
    _write(tmp_path, "notes.txt", "unrelated\n")
    assert not select_profile(data, str(tmp_path), "changed")["scenarios"]
    assert all(check_input_hash(str(tmp_path), check, "baseline")["input_hash"] == original[key] for key, check in checks.items())
    second = run_manifest(str(manifest), str(tmp_path), write_evidence=True)
    assert second["executed"] == 0 and second["reused"] == 2


def test_e03_unknown_inputs_remain_conservative(tmp_path: Path) -> None:
    data, checks = _selection_fixture(tmp_path)
    checks["a"]["inputs"].append("missing/*.py")
    _write(tmp_path, "notes.txt", "unrelated\n")
    outcome = select_profile(data, str(tmp_path), "changed")
    assert "S-01" in {row["id"] for row in outcome["scenarios"]}
    assert outcome["selection_reason"] == "incomplete_inputs_conservative"
    assert outcome["missing_input_patterns"]["a"] == ["missing/*.py"]
    manifest = tmp_path / "standalone.json"
    manifest.write_text(json.dumps(data), encoding="utf-8")
    result = run_manifest(str(manifest), str(tmp_path), profile="changed", use_cache=False)
    assert result["selection_reason"] == "incomplete_inputs_conservative"
    assert result["scope"]["missing_input_patterns"]["a"] == ["missing/*.py"]
    assert check_input_hash(str(tmp_path), checks["a"], "repo-fingerprint")["scope"] != "inputs"
    (tmp_path / "app/b.py").unlink()
    _git(tmp_path, "mv", "app/a.py", "app/renamed.py")
    _write(tmp_path, "app/new.py")
    assert {row["id"] for row in select_profile(data, str(tmp_path), "changed")["scenarios"]} == {"S-01", "S-02"}
    baseline = check_input_hash(str(tmp_path), checks["a"], "repo-fingerprint")
    assert baseline["missing_patterns"] == ["app/a.py", "missing/*.py"]
    gate_root = tmp_path / "gate-project"
    gate_root.mkdir()
    _exercise_done_gate(gate_root)
    from codeflow.spec.cf_spec_metadata import load_spec_metadata
    from codeflow.spec.cf_spec_verify import VerificationScope, run_all_verifiers
    spec = tmp_path / "rules.md"
    spec.write_text("---\nid: example\ndescription: test\nstages: [code]\nenforcement: required\n"
                    "verifiers:\n  - rule: RULE-example-001\n    type: regex\n"
                    "    config: {pattern: forbidden, files: '*.py'}\n---\n"
                    "## Rules\n- [RULE-example-001] No forbidden text\n", encoding="utf-8")
    report = run_all_verifiers(load_spec_metadata(str(spec)), VerificationScope(str(tmp_path), ("notes.txt",), "diff"))
    assert not report.passed and report.evidence[0].status == "unverified"


def test_empty_validator_scope_does_not_expand_to_changed_files(tmp_path: Path) -> None:
    from codeflow.task.cf_validation_service import validate_files
    _repo(tmp_path)
    _write(tmp_path, ".code-flow/validation.yml", "validators:\n  - name: scope\n    trigger: '*.py'\n    command: 'python3 check.py'\n")
    _write(tmp_path, "check.py", "from pathlib import Path\nPath('ran').touch()\n")
    _commit(tmp_path)
    _write(tmp_path, "check.py", "from pathlib import Path\nPath('ran').touch()\n# changed\n")
    result = validate_files(str(tmp_path), ())
    assert result["reason"] == "no_changes" and not (tmp_path / "ran").exists()
