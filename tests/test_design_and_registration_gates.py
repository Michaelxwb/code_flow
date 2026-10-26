"""Real design graphs, pytest collection and rule-readiness regressions."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src/core/code-flow/scripts"))

from codeflow.acceptance.cf_check_registration import _parse_collection, validate_registration
from cf_design_lint import lint_designs
from codeflow.spec.cf_rule_readiness import artifact_problem
from cf_spec_context import ArtifactRef, _doctor_command, apply_artifact_ref, load_context, save_context
from cf_acceptance_manifest import write_manifest
from codeflow.acceptance.cf_check_inputs import check_input_hash
from codeflow.core.cf_exec_base import worktree_fingerprint
from codeflow.acceptance.cf_plan_quality import verify_plan
from test_audit_mainline_e2e import _repo


DESIGN = """# Demo
## 功能方案
| 功能ID | 名称 |
|---|---|
| FEAT-01 | 创建订单 |
## 接口设计
| 接口ID | 名称 |
|---|---|
| API-01 | 创建订单 |
## 验收条件
| 场景ID | 功能ID | 接口引用 |
|---|---|---|
| S-01 | FEAT-01 | API-01 |
## 非功能指标
| 指标ID | 名称 |
|---|---|
| NFR-01 | 延迟 |
"""


@pytest.mark.parametrize("addition, code", [
    ("调用 API-05..08", "traceability_undefined_id"),
    ("参照 NFR-07", "nfr_id_mismatch"),
    ("| FEAT-02 | 未覆盖功能 |", "feature_without_scenario"),
])
def test_design_lint_rejects_unclosed_ids(tmp_path: Path, addition: str, code: str) -> None:
    design = tmp_path / "demo.design.md"
    design.write_text(DESIGN + addition)
    report = lint_designs([str(design)])
    assert report["decision"] == "block"
    assert code in {item["code"] for item in report["findings"]}


def test_valid_design_ids_pass_without_requiring_unrelated_template_sections(tmp_path: Path) -> None:
    design = tmp_path / "demo.design.md"
    design.write_text(DESIGN)
    assert lint_designs([str(design)])["decision"] == "pass"
    strict = lint_designs([str(design)], template="frontend")
    assert "template_section_missing" in {item["code"] for item in strict["findings"]}


def test_frontend_template_headings_allow_normal_whitespace_variations(tmp_path: Path) -> None:
    design = tmp_path / "frontend.design.md"
    design.write_text("\n".join(f"## {title}" for title in (
        "需求概述", "功能方案", "范围与边界", "验收条件", "页面与路由结构", "组件设计", "UI状态")))
    assert lint_designs([str(design)], template="frontend")["decision"] == "pass"


def test_scenario_design_refs_are_checked_against_design_definitions(tmp_path: Path) -> None:
    design = tmp_path / "demo.design.md"
    design.write_text(DESIGN)
    source = tmp_path / "demo.scenarios.md"
    source.write_text(yaml.safe_dump({"scenarios": [{"id": "S-01", "features": ["FEAT-01"],
                                                   "design_refs": ["API-05"]}]}))
    report = lint_designs([str(design)], str(source))
    assert "traceability_undefined_id" in {item["code"] for item in report["findings"]}


def test_scenario_feature_mapping_cannot_disagree_with_design(tmp_path: Path) -> None:
    design = tmp_path / "demo.design.md"
    design.write_text(DESIGN + "\n| FEAT-02 | 另一功能 |\n")
    source = tmp_path / "demo.scenarios.md"
    source.write_text(yaml.safe_dump({"schema": 1, "scenarios": [
        {"id": "S-01", "features": ["FEAT-02"], "level": "integration"}]}))
    report = lint_designs([str(design)], str(source))
    assert "scenario_feature_mismatch" in {item["code"] for item in report["findings"]}


def _pytest_check(root: Path) -> dict[str, object]:
    (root / "test_probe.py").write_text(
        "import pytest\n@pytest.mark.browser\n@pytest.mark.smoke\n"
        "def test_browser_order():\n    assert True\n\n"
        "@pytest.mark.capacity\ndef test_capacity():\n    assert True\n")
    (root / "pytest.ini").write_text("[pytest]\nmarkers =\n browser: browser suite\n smoke: smoke suite\n capacity: capacity suite\n")
    return {"id": "CHK-BROWSER", "suite": "browser", "cwd": ".", "markers": ["browser", "smoke"],
            "test_ids": ["test_probe.py::test_browser_order"],
            "command": [sys.executable, "-m", "pytest", "-q", "test_probe.py::test_browser_order"],
            "collect": {"argv": [sys.executable, "-m", "pytest", "--collect-only", "-q", "-m", "browser and smoke"],
                        "format": "pytest", "timeout": 10}}


def test_browser_and_smoke_registration_use_real_collected_test_ids(tmp_path: Path) -> None:
    check = _pytest_check(tmp_path)
    row = {"id": "S-01", "level": "e2e", "smoke": True, "check": check["id"]}
    result = validate_registration(str(tmp_path), [row], [check])
    assert result["ok"], result
    assert result["runnable_smoke_count"] == 1
    assert result["runnable_browser_count"] == 1
    check["test_ids"] = ["test_probe.py::does_not_exist"]
    result = validate_registration(str(tmp_path), [row], [check])
    assert result["ok"] is False
    assert result["runnable_smoke_count"] == 0
    assert "check_test_not_collected" in {item["code"] for item in result["errors"]}


def test_collection_does_not_prove_an_unrelated_execution_command(tmp_path: Path) -> None:
    check = _pytest_check(tmp_path)
    check["command"] = [sys.executable, "-c", "pass"]
    row = {"id": "S-01", "level": "e2e", "smoke": True, "check": check["id"]}
    result = validate_registration(str(tmp_path), [row], [check])
    assert result["ok"] is False
    assert "check_execution_selection_mismatch" in {item["code"] for item in result["errors"]}


def test_collection_failure_retains_command_exit_and_output(tmp_path: Path) -> None:
    check = _pytest_check(tmp_path)
    command = [sys.executable, "-c", 'import sys; sys.stderr.write("collector unavailable"); sys.exit(7)']
    check["collect"] = {"argv": command, "format": "json"}
    result = validate_registration(str(tmp_path), [{"id": "S-01", "level": "e2e", "check": check["id"]}], [check])
    error = next(item for item in result["errors"] if item["code"] == "check_collection_failed")
    assert error["command"] == command
    assert error["exit_code"] == 7
    assert error["output"] == "collector unavailable"


def test_playwright_collection_uses_report_root_and_project_metadata(tmp_path: Path) -> None:
    report = {"config": {"rootDir": str(tmp_path / "tests"), "projects": [
        {"name": "Desktop Chrome", "metadata": {"capabilities": ["browser"]}}]}, "suites": [
        {"file": "orders.spec.ts", "specs": [{"file": "orders.spec.ts", "line": 8,
          "tags": ["smoke"], "tests": [{"projectName": "Desktop Chrome"}]}]}]}
    tests = _parse_collection(json.dumps(report), {"format": "playwright"}, str(tmp_path))
    assert tests == [{"id": "tests/orders.spec.ts:8@Desktop Chrome", "markers": ["smoke"], "capabilities": ["browser"]}]


@pytest.mark.parametrize("report", [{"config": []}, {"suites": None}, {"suites": [None]},
                                   {"suites": [{"specs": [None]}]}])
def test_malformed_playwright_collection_is_an_explicit_failure(tmp_path: Path, report: dict[str, object]) -> None:
    with pytest.raises(ValueError, match="check_collection_invalid"):
        _parse_collection(json.dumps(report), {"format": "playwright"}, str(tmp_path))


@pytest.mark.parametrize("explicit_inputs", [True, False])
def test_registration_changes_invalidate_previous_input_proof(tmp_path: Path, explicit_inputs: bool) -> None:
    root, _ = _repo(tmp_path)
    check = _pytest_check(root)
    if explicit_inputs:
        check["inputs"] = ["src/app.py"]
    fallback = worktree_fingerprint(str(root), include_untracked=False)
    before = check_input_hash(str(root), check, fallback)["input_hash"]
    check["suite"] = "system"
    assert check_input_hash(str(root), check, fallback)["input_hash"] != before


def test_complete_plan_aggregates_real_collection_quality_and_context(tmp_path: Path) -> None:
    root, demand = _repo(tmp_path)
    check = _pytest_check(root)
    task = demand / "work.md"
    text = task.read_text().replace(json.dumps([sys.executable, "-c", "pass"]), json.dumps(check["command"]))
    task.write_text(text)
    source = demand / "demo.scenarios.md"
    common = {"priority": "P0", "env": "browser", "exec": "auto", "components": ["frontend", "backend"],
              "boundary": "browser -> api -> db", "steps": ["submit order"], "expected": ["order exists"],
              "expected_refs": [{"expected": 1, "steps": [1]}]}
    source.write_text(yaml.safe_dump({"schema": 1, "scenarios": [
        {**common, "id": "S-01", "level": "e2e", "why_e2e": "real browser session wiring",
         "trigger_paths": ["src/*"], "smoke": True}, {**common, "id": "S-02", "level": "integration"}]}))
    target = demand / ".acceptance-manifest.json"
    manifest = write_manifest(str(task), str(target), str(source))
    for registered in manifest["checks"]:
        registered.update({key: check[key] for key in ("suite", "test_ids", "markers", "collect")})
    target.write_text(json.dumps(manifest))
    result = verify_plan(str(demand), str(task))
    assert result["decision"] == "pass", result
    assert result["e2e_quality"]["e2e_browser_count"] == 1
    assert result["e2e_quality"]["runnable_smoke_count"] == 1


@pytest.mark.parametrize("fault, expected", [("suite", "e2e_check_not_browser"),
                                            ("smoke", "smoke_check_not_registered"),
                                            ("capacity", "capacity_check_not_marked")])
def test_suite_and_markers_cannot_be_claimed_without_collection(tmp_path: Path, fault: str, expected: str) -> None:
    check = _pytest_check(tmp_path)
    row = {"id": "S-01", "level": "e2e", "smoke": True, "check": check["id"]}
    if fault == "suite":
        check["suite"] = "integration"
    elif fault == "smoke":
        check["markers"] = ["browser"]
    else:
        row.update(level="capacity", smoke=False)
    result = validate_registration(str(tmp_path), [row], [check])
    assert expected in {item["code"] for item in result["errors"]}


def test_doctor_reports_unresolved_application_and_unenforced_conventions(tmp_path: Path) -> None:
    root, demand = _repo(tmp_path)
    artifact = demand / "design.md"
    artifact.write_text("## 3.5\nRULE-app-001: 待确认，需同步 spec 文本\n")
    context = load_context(str(demand / "spec-context.yml"))
    context = apply_artifact_ref(context, "app-runtime", "RULE-app-001", "code",
        ArtifactRef("design.md", "3.5", "RULE-app-001", hashlib.sha256(artifact.read_bytes()).hexdigest()))
    save_context(str(demand / "spec-context.yml"), context)
    spec = root / ".code-flow/specs/app/rules.md"
    spec.write_text(spec.read_text() + "\n## Conventions\n- single Pod only\n")
    report = _doctor_command(argparse.Namespace(task_dir=str(demand), root=str(root)))
    assert report["decision"] == "block"
    assert {"rule_applied_unresolved", "convention_review_required"} <= {
        item["code"] for item in report["findings"]}
    assert report["readiness"]["code"]["decision"] == "block"


def test_rule_id_in_a_different_section_does_not_prove_application(tmp_path: Path) -> None:
    (tmp_path / "design.md").write_text("## 3.5\nresolved\n## 3.6\nRULE-demo-001 is finalized\n")
    assert artifact_problem(str(tmp_path), "design.md", "3.5", "RULE-demo-001") == "rule_artifact_reference_missing"


def test_old_cli_reports_upgrade_for_a_new_project_command_family(tmp_path: Path) -> None:
    project, old = tmp_path / "project", tmp_path / "old-cli"
    project.mkdir()
    old.mkdir()
    installed = subprocess.run(["node", str(ROOT / "src/cli.js"), "init", "--platform=codex"],
                               cwd=project, capture_output=True, text=True, timeout=40)
    assert installed.returncode == 0, installed.stderr
    shutil.copytree(ROOT / "src", old / "src", ignore=shutil.ignore_patterns("__pycache__"))
    package = json.loads((ROOT / "package.json").read_text())
    package["version"] = "0.7.0"
    (old / "package.json").write_text(json.dumps(package))
    registry = old / "src/core/code-flow/runtime-commands.json"
    data = json.loads(registry.read_text())
    data["commands"] = {key: value for key, value in data["commands"].items() if not key.startswith("scenarios ")}
    registry.write_text(json.dumps(data))
    result = subprocess.run(["node", str(old / "src/cli.js"), "scenarios", "parse", "--help"],
                            cwd=project, capture_output=True, text=True, timeout=40)
    assert result.returncode == 3, result.stdout + result.stderr
    assert "0.7.0" in result.stderr and "0.8.0" in result.stderr
    assert "npm install --global" in result.stderr
    assert "migrate --runtime --dry-run" not in result.stderr
