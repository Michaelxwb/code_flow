"""TASK-004 acceptance skeletons and real identity regression."""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

import pytest
import yaml

SCRIPTS = Path(__file__).resolve().parents[1] / "src/core/code-flow/scripts"
sys.path.insert(0, str(SCRIPTS))
from codeflow.cli.cf_acceptance_runner import run_manifest


def _repo(root: Path) -> None:
    for args in (("init", "-q"), ("config", "user.email", "test@example.invalid"),
                 ("config", "user.name", "Test")):
        subprocess.run(("git", *args), cwd=root, check=True, capture_output=True)
    (root / ".code-flow").mkdir()
    (root / "source.py").write_text("value = 1\n", encoding="utf-8")
    script = ("from pathlib import Path\nimport time\np=Path('.code-flow/count')\n"
              "p.write_text(p.read_text()+'x' if p.exists() else 'x')\n"
              "if Path('.code-flow/slow').exists(): time.sleep(1)\n"
              "assert not Path('.code-flow/fail').exists()\n")
    (root / "check.py").write_text(script, encoding="utf-8")
    subprocess.run(("git", "add", "source.py", "check.py"), cwd=root, check=True, capture_output=True)
    subprocess.run(("git", "commit", "-qm", "baseline"), cwd=root, check=True, capture_output=True)


def _manifest(root: Path) -> Path:
    command = [sys.executable, "check.py"]
    check = {"id": "CHK-1", "command": command, "cwd": ".", "timeout": 30,
             "inputs": ["source.py", "check.py"], "env": "external"}
    row = {"id": "S-01", "kind": "functional", "checks": ["CHK-1"], "owner": "TASK-001", "status": "planned"}
    path = root / ".code-flow/manifest.json"
    path.write_text(json.dumps({"schema": 3, "checks": [check], "scenarios": [row]}), encoding="utf-8")
    return path


def _edit_check(path: Path, **changes: object) -> None:
    data = json.loads(path.read_text(encoding="utf-8"))
    data["checks"][0].update(changes)
    path.write_text(json.dumps(data), encoding="utf-8")


def test_s06_equivalent_execution_is_deduplicated(tmp_path: Path) -> None:
    from codeflow.core.cf_exec_base import execution_session
    from codeflow.spec.cf_spec_metadata import load_spec_metadata
    from codeflow.spec.cf_spec_verify import VerificationScope, run_all_verifiers
    from codeflow.task.cf_validation_service import validate_files

    _repo(tmp_path)
    command = [sys.executable, "check.py"]
    spec = tmp_path / ".code-flow/review.md"
    spec.write_text("---\nid: review-test\ndescription: review\nstages: [review]\nenforcement: required\n"
        "verifiers:\n  - rule: RULE-review-001\n    type: test\n    stage: review\n"
        f"    config: {{argv: {json.dumps(command)}, timeout: 30}}\n---\n"
        "## Rules\n- [RULE-review-001] Review result\n", encoding="utf-8")
    config = {"validators": [{"name": "same", "trigger": "*.py", "command": f"{sys.executable} check.py", "timeout": 30000}]}
    (tmp_path / ".code-flow/validation.yml").write_text(yaml.safe_dump(config), encoding="utf-8")
    manifest = _manifest(tmp_path)
    _edit_check(manifest, env="none")
    with execution_session():
        validator = validate_files(str(tmp_path), ["source.py"], use_cache=False)
        review = run_all_verifiers(load_spec_metadata(str(spec)), VerificationScope(str(tmp_path), ("source.py",), "diff"), stage="review")
        acceptance = run_manifest(str(manifest), str(tmp_path), write_evidence=True, use_cache=False)
        assert (tmp_path / ".code-flow/count").read_text(encoding="utf-8") == "x"
        (tmp_path / "source.py").write_text("value = 2\n", encoding="utf-8")
        changed = run_manifest(str(manifest), str(tmp_path), write_evidence=True, use_cache=False)
        _edit_check(manifest, test_ids=["first"])
        run_manifest(str(manifest), str(tmp_path), write_evidence=True, use_cache=False)
        _edit_check(manifest, test_ids=["second"])
        run_manifest(str(manifest), str(tmp_path), write_evidence=True, use_cache=False)
    assert validator["decision"] == "pass" and review.passed and acceptance["decision"] == "pass"
    assert changed["executed"] == 1
    assert (tmp_path / ".code-flow/count").read_text(encoding="utf-8") == "xxxx"
    data = json.loads(manifest.read_text(encoding="utf-8"))
    data["checks"][0]["command"].append("different")
    manifest.write_text(json.dumps(data), encoding="utf-8")
    assert run_manifest(str(manifest), str(tmp_path), write_evidence=True, use_cache=False)["executed"] == 1
    assert (tmp_path / ".code-flow/count").read_text(encoding="utf-8") == "xxxxx"


def test_s07_ci_and_local_evidence_reuse(tmp_path: Path) -> None:
    from codeflow.cli.cf_evidence_import import EvidenceImportError, import_report
    repo = tmp_path / "repo"
    repo.mkdir()
    _repo(repo)
    manifest = _manifest(repo)
    data = json.loads(manifest.read_text(encoding="utf-8"))
    data["checks"][0]["env"] = "none"
    second = {**data["checks"][0], "id": "CHK-2", "command": [sys.executable, "check.py", "second"]}
    data["checks"].append(second)
    data["scenarios"][0]["checks"].append("CHK-2")
    manifest.write_text(json.dumps(data), encoding="utf-8")
    subprocess.run(("git", "add", "-f", ".code-flow/manifest.json"), cwd=repo, check=True, capture_output=True)
    subprocess.run(("git", "commit", "-qm", "plan"), cwd=repo, check=True, capture_output=True)
    clone = tmp_path / "checkout"
    subprocess.run(("git", "clone", "-q", str(repo), str(clone)), check=True, capture_output=True)
    head = subprocess.run(("git", "rev-parse", "HEAD"), cwd=clone, check=True, capture_output=True, text=True).stdout.strip()
    locked = clone / ".code-flow/manifest.json"
    report = tmp_path / "ci.xml"
    report.write_text('<testsuite><testcase name="CHK-1"/></testsuite>', encoding="utf-8")
    with pytest.raises(EvidenceImportError, match="scenario"):
        import_report(clone, report=report, fmt="junit", commit=head, run_url="https://ci.example/run/1", manifest=str(locked))
    assert json.loads(locked.read_text(encoding="utf-8"))["scenarios"][0]["status"] == "planned"
    report.write_text('<testsuite><testcase name="CHK-1"/><testcase name="CHK-2"/></testsuite>', encoding="utf-8")
    result = import_report(clone, report=report, fmt="junit", commit=head, run_url="https://ci.example/run/2", manifest=str(locked))
    assert result["decision"] == "pass"
    reused = run_manifest(str(locked), str(clone), write_evidence=True)
    assert reused["executed"] == 0 and reused["reused"] == 2
    report.write_text('<testsuite><testcase name="CHK-1"><skipped/></testcase><testcase name="CHK-2"/></testsuite>', encoding="utf-8")
    skipped = import_report(clone, report=report, fmt="junit", commit=head, run_url="https://ci.example/run/3", manifest=str(locked))
    assert skipped["decision"] == "block"
    retry = run_manifest(str(locked), str(clone), write_evidence=True)
    assert retry["executed"] >= 1
    (clone / "source.py").write_text("value = 2\n", encoding="utf-8")
    assert run_manifest(str(locked), str(clone), write_evidence=True)["executed"] == 2


def test_e04_identity_and_failure_invalidate_reuse(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _repo(tmp_path)
    manifest = _manifest(tmp_path)
    first = run_manifest(str(manifest), str(tmp_path), write_evidence=True)
    second = run_manifest(str(manifest), str(tmp_path), write_evidence=True)
    assert first["executed"] == second["executed"] == 1, "external without environment identity must not persistently reuse"
    _edit_check(manifest, environment_revision="env-v1", evidence_ttl_seconds=3600)
    assert run_manifest(str(manifest), str(tmp_path), write_evidence=True, resume=True)["executed"] == 1
    assert run_manifest(str(manifest), str(tmp_path), write_evidence=True)["reused"] == 1
    monkeypatch.setenv("TASK004_ENV", "changed")
    assert run_manifest(str(manifest), str(tmp_path), write_evidence=True)["executed"] == 1
    _edit_check(manifest, environment_revision="env-v2")
    assert run_manifest(str(manifest), str(tmp_path), write_evidence=True)["executed"] == 1
    data = json.loads(manifest.read_text(encoding="utf-8"))
    data["scenarios"][0]["evidence"]["executed_at"] = "2000-01-01T00:00:00+00:00"
    manifest.write_text(json.dumps(data), encoding="utf-8")
    assert run_manifest(str(manifest), str(tmp_path), write_evidence=True, resume=True)["executed"] == 1
    (tmp_path / "source.py").write_text("value = 2\n", encoding="utf-8")
    assert run_manifest(str(manifest), str(tmp_path), write_evidence=True)["executed"] == 1
    data = json.loads(manifest.read_text(encoding="utf-8"))
    data["checks"][0].pop("evidence_ttl_seconds")
    manifest.write_text(json.dumps(data), encoding="utf-8")
    assert run_manifest(str(manifest), str(tmp_path), write_evidence=True, resume=True)["decision"] == "pass"
    (tmp_path / ".code-flow/fail").touch()
    failed = run_manifest(str(manifest), str(tmp_path), write_evidence=True, use_cache=False)
    assert failed["decision"] == "block"
    (tmp_path / ".code-flow/fail").unlink()
    retried = run_manifest(str(manifest), str(tmp_path), write_evidence=True, resume=True)
    assert retried["executed"] == 1 and retried["reused"] == 0
    (tmp_path / ".code-flow/slow").touch()
    _edit_check(manifest, timeout=0.05)
    timed_out = run_manifest(str(manifest), str(tmp_path), write_evidence=True, use_cache=False)
    assert timed_out["decision"] == "block"
    (tmp_path / ".code-flow/slow").unlink()
    _edit_check(manifest, timeout=30)
    assert run_manifest(str(manifest), str(tmp_path), write_evidence=True, resume=True)["executed"] == 1
