"""Collectable TASK-008 acceptance skeletons; replace during implementation.

Actual acceptance uses --runxfail, so placeholders cannot count as passes.
"""
import json
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "src" / "core" / "code-flow" / "scripts"
sys.path.insert(0, str(SCRIPTS))

def _prepare_project_pilot(root: Path) -> Path:
    """Use a real code-flow test and runtime in an isolated Git project."""
    repo = Path(__file__).resolve().parents[1]
    scripts = root / "src/core/code-flow/scripts"
    scripts.parent.mkdir(parents=True)
    shutil.copytree(repo / "src/core/code-flow/scripts", scripts, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    (root / "tests").mkdir()
    shutil.copy2(repo / "tests/test_verification_efficiency_01.py", root / "tests")
    for args in (("init", "-q"), ("config", "user.name", "Pilot"),
                 ("config", "user.email", "pilot@example.invalid"), ("add", "."),
                 ("commit", "-qm", "pilot inputs")):
        subprocess.run(("git", *args), cwd=root, check=True, capture_output=True)
    (root / ".code-flow").mkdir()
    check = {"id": "CHK-PILOT", "cwd": ".", "env": "none", "timeout": 60,
             "inputs": ["tests/test_verification_efficiency_01.py", "src/core/code-flow/scripts/**/*.py"],
             "evidence_ttl_seconds": 3600,
             "command": [sys.executable, "-m", "pytest", "-q", "--runxfail",
                         "tests/test_verification_efficiency_01.py::test_s01_timing_and_selection_report"]}
    scenario = {"id": "S-PILOT", "kind": "functional", "checks": ["CHK-PILOT"], "status": "planned"}
    path = root / ".code-flow/manifest.json"
    path.write_text(json.dumps({"schema": 3, "checks": [check], "scenarios": [scenario]}), encoding="utf-8")
    return path


def test_s11_pilot_replacements_detect_seeded_defects(tmp_path: Path) -> None:
    """Exercise actual project tests and evidence when inputs or results change."""
    from codeflow.cli.cf_acceptance_runner import run_manifest

    manifest = _prepare_project_pilot(tmp_path)
    run = lambda **kwargs: run_manifest(str(manifest), str(tmp_path), write_evidence=True, **kwargs)
    assert run()["executed"] == 1
    assert run()["reused"] == 1
    case = tmp_path / "tests/test_verification_efficiency_01.py"
    original = case.read_text(encoding="utf-8")
    case.write_text(original.replace("    demand = _project(tmp_path)\n", "    assert False, 'injected failure'\n", 1), encoding="utf-8")
    failed = run()
    assert failed["decision"] == "block" and failed["executed"] == 1
    case.write_text(original, encoding="utf-8")
    recovered = run()
    assert recovered["decision"] == "pass" and recovered["executed"] == 1
    data = json.loads(manifest.read_text(encoding="utf-8"))
    data["scenarios"][0]["evidence"]["executed_at"] = "2000-01-01T00:00:00+00:00"
    manifest.write_text(json.dumps(data), encoding="utf-8")
    assert run()["executed"] == 1


@pytest.mark.xfail(strict=True, reason="TASK-008: complete measurements not yet available")
def test_s12_pilot_report_has_reproducible_measurements() -> None:
    """Require actual, validated measurements before reporting a complete pilot."""
    from pilot_report_validation import validate_report

    path = Path(__file__).resolve().parents[1] / "docs/verification-efficiency/benchmark.json"
    assert path.is_file(), "S-12: benchmark report with real old/new measurements is missing"
    report = json.loads(path.read_text(encoding="utf-8"))
    result = validate_report(report)
    assert result["performance_pass"], result["errors"]
    assert result["coverage_pass"], result["errors"]


def test_e08_unmeasured_pilot_is_not_reported_passed() -> None:
    """缺少实测或把合成数据标为真实 fluxion 时拒绝给出性能达标/覆盖通过结论。"""
    from pilot_report_validation import validate_report

    for report in (
        {},
        {"source": "synthetic", "claimed_source": "fluxion"},
        {"source": "fluxion", "origin": "synthetic", "measurements": [1],
         "coverage_evidence": ["claimed"]},
    ):
        result = validate_report(report)
        assert result["performance_pass"] is False
        assert result["coverage_pass"] is False
        assert result["errors"]


def test_fluxion_raw_sample_validation_recomputes_medians() -> None:
    """Audit actual partial fluxion measurements without declaring S-12 complete."""
    from pilot_report_validation import validate_raw_comparison

    reports = Path(__file__).resolve().parents[1] / "docs/verification-efficiency"
    old = json.loads((reports / "fluxion-old-cache-runs.json").read_text(encoding="utf-8"))
    new = json.loads((reports / "fluxion-new-cache-runs.json").read_text(encoding="utf-8"))
    result = validate_raw_comparison(old, new)
    assert result["errors"] == []
    assert result["medians_ms"]["old"]["cold"] == 1397.633
    assert result["medians_ms"]["new"]["reuse"] == 250.233
    altered = json.loads(json.dumps(new))
    altered["manifest_sha256"] = "different"
    assert validate_raw_comparison(old, altered)["errors"]
    altered = json.loads(json.dumps(new))
    altered["runs"][0]["exit_code"] = 1
    assert validate_raw_comparison(old, altered)["errors"]
    altered = json.loads(json.dumps(new))
    altered["runs"] = altered["runs"][:-1]
    assert validate_raw_comparison(old, altered)["errors"]
    altered = json.loads(json.dumps(new))
    altered["runs"][0]["result"]["results"][0]["check_config"]["command"][-1] = "tests/other.py"
    assert validate_raw_comparison(old, altered)["errors"]
    altered = json.loads(json.dumps(new))
    altered["origin"] = "synthetic"
    assert validate_raw_comparison(old, altered)["errors"]


def test_archive_raw_records_preserve_failure_and_check_counts() -> None:
    """The partial archive comparison must not conceal the old blocked result."""
    reports = Path(__file__).resolve().parents[1] / "docs/verification-efficiency"
    old = json.loads((reports / "code-flow-archive-old-raw.json").read_text(encoding="utf-8"))
    new = json.loads((reports / "code-flow-archive-new-raw.json").read_text(encoding="utf-8"))
    assert old["test_sha256"] == new["test_sha256"]
    assert old["platform"] == new["platform"] and old["python"] == new["python"]
    for report, phase in ((old, "old"), (new, "new")):
        assert report["source"] == "code-flow-real-cli-synthetic-fixture"
        assert report["phase"] == phase and len(report["runs"]) == 6
        for mode in ("missing", "reuse"):
            runs = [item for item in report["runs"] if item["mode"] == mode]
            assert {item["repeat"] for item in runs} == {1, 2, 3}
            expected = "block" if phase == "old" and mode == "missing" else "pass"
            delta = [1, 1] if phase == "new" and mode == "missing" else [0, 0]
            for item in runs:
                assert item["elapsed_ms"] > 0 and item["result"]["decision"] == expected
                assert [after - before for before, after in zip(
                    item["check_count_before"], item["check_count_after"])] == delta


def test_real_task_raw_records_cover_same_checks() -> None:
    reports = Path(__file__).resolve().parents[1] / "docs/verification-efficiency"
    old = json.loads((reports / "code-flow-task-old-raw.json").read_text(encoding="utf-8"))
    new = json.loads((reports / "code-flow-task-new-raw.json").read_text(encoding="utf-8"))
    for key in ("commit", "manifest_sha256", "input_sha256", "platform", "python"):
        assert old[key] == new[key]
    for report, phase in ((old, "old"), (new, "new")):
        assert report["phase"] == phase and report["source"] == "code-flow-real-requirement"
        for mode in ("forced", "prime", "reuse"):
            runs = [item for item in report["runs"] if item["mode"] == mode]
            assert {item["repeat"] for item in runs} == {1, 2, 3}
            for item in runs:
                result = item["result"]
                assert item["exit_code"] == 0 and result["decision"] == "pass"
                assert {row["id"] for row in result["results"]} == {"S-01", "B-01"}
                assert (result["executed"], result["reused"]) == ((0, 2) if mode == "reuse" else (2, 0))
