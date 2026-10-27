"""Collected plan skeletons for runtime boundary hardening.

Each acceptance command passes --runxfail, so a skeleton cannot be counted as
verified before its owning TASK replaces the failure with a real assertion.
"""
from pathlib import Path
import sys

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "src" / "core" / "code-flow" / "scripts"
sys.path.insert(0, str(SCRIPTS))


def test_s01_guard_detects_runtime_import_forms(tmp_path: Path) -> None:
    from test_runtime_consolidation import _import_edges, _private_imports, _script_modules

    package = tmp_path / "codeflow" / "spec"
    package.mkdir(parents=True)
    names = ("cf_type", "cf_else", "cf_peer", "cf_dynamic", "cf_builtin", "cf_dep", "cf_negative", "cf_member")
    for name in names:
        (package / f"{name}.py").write_text("", encoding="utf-8")
    actor = package / "cf_actor.py"
    actor.write_text(
        "from typing import TYPE_CHECKING\n"
        "if TYPE_CHECKING:\n"
        "    from codeflow.spec.cf_type import _OnlyType\n"
        "else:\n"
        "    from codeflow.spec.cf_else import live\n"
        "from . import cf_peer as peer\n"
        "import codeflow.spec.cf_dep as dep\n"
        "import importlib as loader\n"
        "from importlib import import_module as load\n"
        "import typing as t\n"
        "if not t.TYPE_CHECKING:\n"
        "    from .cf_negative import live\n"
        "else:\n"
        "    from .cf_type import _TypingOnly\n"
        "loader.import_module('codeflow.spec.cf_dynamic')\n"
        "loaded = load('codeflow.spec.cf_dynamic')\n"
        "__import__('codeflow.spec.cf_builtin')\n"
        "__import__('codeflow.spec', fromlist=['cf_member'])\n"
        "dep._hidden()\n"
        "peer._relative()\n"
        "loaded._dynamic_private()\n",
        encoding="utf-8",
    )
    modules = _script_modules(tmp_path)
    edges = _import_edges(actor, modules)
    assert edges == {("cf_actor", target) for target in names if target != "cf_type"}
    assert _private_imports(actor, modules) == {
        ("cf_actor", "cf_dep", "_hidden"), ("cf_actor", "cf_peer", "_relative"),
        ("cf_actor", "cf_dynamic", "_dynamic_private"),
    }

    actor.write_text("from typing import TYPE_CHECKING\nif TYPE_CHECKING and flag:\n    from .cf_type import X\n", encoding="utf-8")
    assert _import_edges(actor, modules) == set()
    actor.write_text("import importlib\nimportlib.import_module(name)\n", encoding="utf-8")
    with pytest.raises(ValueError, match="dynamic import"):
        _import_edges(actor, modules)


def test_b01_guard_distinguishes_shims_and_package_collisions(tmp_path: Path) -> None:
    from test_runtime_consolidation import (
        _import_edges, _layer_violations, _script_files, _script_modules,
        _strongly_connected_sizes,
    )

    core = tmp_path / "codeflow" / "core"
    task = tmp_path / "codeflow" / "task"
    core.mkdir(parents=True)
    task.mkdir(parents=True)
    (tmp_path / "cf_log.py").write_text(
        "import sys\nfrom codeflow.core import cf_log as _impl\n"
        "sys.modules[__name__] = _impl\n", encoding="utf-8"
    )
    (core / "cf_log.py").write_text("from codeflow.task import cf_task_doc\n", encoding="utf-8")
    (task / "cf_task_doc.py").write_text("from codeflow.core import cf_log\n", encoding="utf-8")
    modules = _script_modules(tmp_path)
    assert modules == frozenset({"cf_log", "cf_task_doc"})
    edges = set().union(*(_import_edges(path, modules) for path in _script_files(tmp_path)))
    assert _layer_violations(edges) == {("cf_log", "cf_task_doc")}
    assert _strongly_connected_sizes(edges) == [2]

    shim = tmp_path / "cf_log.py"
    good_shim = shim.read_text(encoding="utf-8")
    shim.write_text("from codeflow.core import cf_log as _impl\nvalue = _impl\n", encoding="utf-8")
    with pytest.raises(ValueError, match="ambiguous.*cf_log"):
        _script_modules(tmp_path)
    shim.write_text(good_shim, encoding="utf-8")

    extra = tmp_path / "codeflow" / "spec"
    extra.mkdir()
    (extra / "cf_log.py").write_text("", encoding="utf-8")
    with pytest.raises(ValueError, match="ambiguous.*cf_log"):
        _script_modules(tmp_path)


def test_s02_stop_ignores_moved_task_and_scenario_paths(tmp_path: Path) -> None:
    import json
    import subprocess

    from codeflow.core import cf_log

    flow = tmp_path / ".code-flow"
    flow.mkdir()
    (flow / "config.yml").write_text("quality_loop:\n  enabled: true\npath_mapping: {}\n")

    def stop(sid: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(SCRIPTS / "cf_stop_hook.py")], cwd=tmp_path,
            input=json.dumps({"session_id": sid}), text=True, capture_output=True,
            timeout=30, check=False,
        )

    scenario = flow / "tasks/2026-01-01/demo/demo.scenarios.md"
    scenario.parent.mkdir(parents=True)
    scenario.write_text("## Acceptance Coverage\n## TASK-001: a\n## TASK-001: b\n")
    assert cf_log.append_event(str(tmp_path), "edit", {"file": str(scenario.relative_to(tmp_path))}, "scenario")
    scenario_result = stop("scenario")

    original = scenario.with_name("demo.md")
    original.write_text("# Archived task\n")
    archive = flow / "tasks/archived/2026-01-01/demo/demo.md"
    archive.parent.mkdir(parents=True)
    original.rename(archive)
    assert cf_log.append_event(str(tmp_path), "edit", {"file": str(original.relative_to(tmp_path))}, "moved")
    moved_result = stop("moved")
    assert archive.is_file()
    assert (scenario_result.returncode, scenario_result.stdout, scenario_result.stderr) == (0, "", "") and (
        moved_result.returncode, moved_result.stdout, moved_result.stderr
    ) == (0, "", ""), f"scenario={scenario_result!r}; moved={moved_result!r}"

    original.write_text("## Acceptance Coverage\n## TASK-001: a\n- **Status**: done\n")
    assert cf_log.append_event(str(tmp_path), "edit", {"file": str(original.relative_to(tmp_path))}, "active")
    outcome = stop("active")
    assert outcome.returncode == 0 and json.loads(outcome.stdout)["decision"] == "block"


def test_e01_stop_preserves_real_error_diagnostics(tmp_path: Path) -> None:
    import json
    import subprocess

    from codeflow.core import cf_log

    flow = tmp_path / ".code-flow"
    flow.mkdir()
    (flow / "config.yml").write_text("quality_loop:\n  enabled: true\npath_mapping: {}\n")

    def stop(sid: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(SCRIPTS / "cf_stop_hook.py")], cwd=tmp_path,
            input=json.dumps({"session_id": sid}), text=True, capture_output=True,
            timeout=30, check=False,
        )

    marker = flow / ".active-task.json"
    marker.write_text("{")
    invalid = stop("invalid")
    payload = json.loads(invalid.stdout)
    assert invalid.returncode == 0 and payload["decision"] == "block"
    assert "SPEC_WORKFLOW_BLOCKED" in payload["reason"]

    marker.unlink()
    broken = flow / "tasks/2026-01-01/demo/unreadable.md"
    broken.mkdir(parents=True)
    assert cf_log.append_event(str(tmp_path), "edit", {"file": str(broken.relative_to(tmp_path))}, "io-error")
    failure = stop("io-error")
    assert failure.returncode == 0 and failure.stdout == ""
    assert "task read failed" in failure.stderr and "unreadable.md" in failure.stderr


def _manifest_fixture(directory: Path, level: str = "integration") -> tuple[Path, Path, Path]:
    task = directory / "demo.md"
    source = directory / "demo.scenarios.md"
    manifest = directory / ".acceptance-manifest.json"
    task.write_text(
        "# Tasks\n\n## Acceptance Coverage\n"
        "| 场景ID | 来源设计 | 测试层级 | 关键真实边界 | 负责任务 | 状态 | 执行命令 |\n"
        "|--------|---------|---------|-------------|---------|------|---------|\n"
        f'| S-01 | design#1 | {level} | service -> store | TASK-001 | planned | ["python3", "-c", "pass"] |\n'
        f'| S-02 | design#1 | {level} | service -> store | TASK-001 | planned | ["python3", "-c", "pass"] |\n\n'
        "## TASK-001: Demo\n- **Status**: draft\n- **Acceptance-Refs**: S-01, S-02\n",
        encoding="utf-8",
    )
    source.write_text(
        "---\nschema: 1\nrequirement: demo\nscenarios:\n"
        "- id: S-01\n  priority: P1\n  level: integration\n  boundary: service -> store\n"
        "- id: S-02\n  priority: P1\n  level: integration\n  boundary: service -> store\n---\n",
        encoding="utf-8",
    )
    return task, source, manifest


def _reachable(edges: set[tuple[str, str]], start: str, end: str) -> bool:
    pending, seen = [start], set()
    while pending:
        node = pending.pop()
        if node == end:
            return True
        if node not in seen:
            seen.add(node)
            pending.extend(target for source, target in edges if source == node)
    return False


def test_s03_manifest_scenario_and_schema_dependencies_are_acyclic(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    import json
    import subprocess

    from cf_acceptance_manifest import validate_manifest, write_manifest
    from cf_scenarios import parse_scenarios
    from test_runtime_consolidation import _import_edges, _script_files, _script_modules

    task, source, manifest = _manifest_fixture(tmp_path)
    source_reads = [0]
    original_read = Path.read_text

    def observe_read(path: Path, *args: object, **kwargs: object) -> str:
        if path == source:
            source_reads[0] += 1
        return original_read(path, *args, **kwargs)

    with monkeypatch.context() as observer:
        observer.setattr(Path, "read_text", observe_read)
        locked = write_manifest(str(task), str(manifest), str(source))
    assert 0 < source_reads[0] <= 3, "locking must not add scenario-source reads"
    parsed = parse_scenarios(source)
    assert {item["id"] for item in parsed["scenarios"]} == {"S-01", "S-02"}
    checks = {item["id"]: item["check"] for item in locked["scenarios"]}
    assert checks["S-01"] == checks["S-02"] == locked["checks"][0]["id"]
    assert validate_manifest(str(task), str(manifest)) == (True, "")
    migrated = subprocess.run(
        [sys.executable, str(SCRIPTS / "cf_scenarios.py"), "migrate", "--task-file", str(task)],
        capture_output=True, text=True, timeout=30, check=False,
    )
    assert migrated.returncode == 0, migrated.stderr
    assert {row["id"] for row in json.loads(migrated.stdout)["scenarios"]} == {"S-01", "S-02"}

    modules = _script_modules(SCRIPTS)
    edges = set().union(*(_import_edges(path, modules) for path in _script_files(SCRIPTS)))
    owners = ("cf_acceptance_manifest_core", "cf_acceptance_schema", "cf_scenarios")
    for index, left in enumerate(owners):
        for right in owners[index + 1:]:
            assert not (_reachable(edges, left, right) and _reachable(edges, right, left)), (left, right)


def test_e02_manifest_legacy_healing_and_drift_behavior(tmp_path: Path) -> None:
    import json

    from cf_acceptance_manifest import _legacy_kind, extract_manifest, validate_manifest

    task, source, manifest = _manifest_fixture(tmp_path, "E2E（Playwright）")
    original = task.read_text(encoding="utf-8")
    legacy = extract_manifest(str(task), _legacy_kind, contract_fallback=False, merge_source=False)
    legacy["task_file"] = task.name
    legacy["scenarios_file"] = source.name
    legacy["e2e_gate"] = 1
    legacy["scenarios"][0]["evidence"] = {"status": "passed", "exit_code": 0}
    manifest.write_text(json.dumps(legacy, ensure_ascii=False), encoding="utf-8")
    assert validate_manifest(str(task), str(manifest)) == (True, "")
    healed = json.loads(manifest.read_text(encoding="utf-8"))
    assert healed["scenarios"][0]["evidence"]["exit_code"] == 0
    assert healed["task_sha256"] != legacy["task_sha256"]

    task.write_text(original.replace("design#1", "design#changed"), encoding="utf-8")
    assert validate_manifest(str(task), str(manifest)) == (False, "acceptance_manifest_drift")
    task.write_text(original, encoding="utf-8")
    source.write_text("---\nscenarios: [\n---\n", encoding="utf-8")
    valid, reason = validate_manifest(str(task), str(manifest))
    assert not valid and reason.startswith("acceptance_manifest_invalid: scenario_source_invalid:")


def test_s04_check_registration_uses_shared_public_contract(tmp_path: Path) -> None:
    import json

    from codeflow.acceptance.cf_acceptance_registration import RegistrationError, register_checks
    from codeflow.acceptance.cf_check_registration import validate_registration
    from test_runtime_consolidation import _private_imports, _script_modules

    (tmp_path / "pytest.ini").write_text("[pytest]\nmarkers =\n    smoke: smoke test\n", encoding="utf-8")
    (tmp_path / "test_sample.py").write_text(
        "import pytest\n@pytest.mark.smoke\ndef test_selected(): pass\n"
        "@pytest.mark.smoke\ndef test_other(): pass\n", encoding="utf-8",
    )
    check = {"id": "CHK-1", "command": [sys.executable, "-m", "pytest", "-q",
                                        "test_sample.py::test_selected", "-m", "smoke"]}
    row = {"id": "S-01", "kind": "functional", "smoke": True, "check": "CHK-1"}
    manifest = {"checks": [check], "scenarios": [row]}
    assert register_checks(manifest, str(tmp_path))["ok"]
    assert check["test_ids"] == ["test_sample.py::test_selected"] and "smoke" in check["markers"]
    assert validate_registration(str(tmp_path), [row], [check])["ok"]

    override = tmp_path / "registration.json"
    override.write_text(json.dumps({"checks": {"CHK-1": {
        "test_ids": ["test_sample.py::test_other"],
        "collect": {"argv": [sys.executable, "-m", "pytest", "--collect-only", "--verbosity=-1",
                               "test_sample.py", "-m", "smoke"], "format": "pytest", "timeout": 10},
    }}}), encoding="utf-8")
    wrong = {"checks": [{"id": "CHK-1", "command": check["command"]}], "scenarios": [row]}
    with pytest.raises(RegistrationError) as error:
        register_checks(wrong, str(tmp_path), str(override))
    assert "check_execution_selection_mismatch" in str(error.value.report)

    imports = _private_imports(SCRIPTS / "codeflow/acceptance/cf_acceptance_registration.py", _script_modules(SCRIPTS))
    assert not {entry for entry in imports if entry[1] == "cf_check_registration"}


def _selection_manifest_fixture(directory: Path) -> tuple[Path, Path]:
    import json

    task = directory / "demo.md"
    task.write_text("# Legacy tasks\n## TASK-001: One\n## TASK-002: Two\n", encoding="utf-8")
    manifest = directory / ".acceptance-manifest.json"
    check = {"id": "CHK-1", "command": [sys.executable, "-c", "raise SystemExit(1)"],
             "cwd": ".", "timeout": 30}
    rows = [
        {"id": "S-01", "kind": "functional", "owner": "TASK-001", "check": "CHK-1",
         "depends_on": ["S-02"], "status": "accepted_risk"},
        {"id": "S-02", "kind": "functional", "owner": "TASK-002", "check": "CHK-1",
         "status": "accepted_risk"},
    ]
    manifest.write_text(json.dumps({"schema": 3, "task_file": task.name,
                                    "checks": [check], "scenarios": rows}), encoding="utf-8")
    return task, manifest


def test_s05_acceptance_selection_and_risk_are_consistent(tmp_path: Path) -> None:
    import json

    from cf_acceptance_manifest import record_accepted_risk
    from cf_acceptance_runner import _prepare_manifest, run_manifest
    from cf_task_workflow import _e2e_preflight
    from test_runtime_consolidation import _private_imports, _script_modules

    task, manifest = _selection_manifest_fixture(tmp_path)
    record_accepted_risk(str(manifest), "CHK-1", "TASK-001", "known failure",
                         "2999-01-01", "user", "confirmed in fixture")
    for profile in ("smoke", "changed", "full"):
        _, _, runner_rows, _ = _prepare_manifest(str(manifest), str(tmp_path), profile, (), "TASK-001")
        workflow, failure = _e2e_preflight(manifest, [(task, "TASK-001", "done")], True, profile, str(tmp_path))
        assert failure is None and workflow is not None
        assert [row["id"] for row in runner_rows] == [row["id"] for row in workflow["scenarios"]] == ["S-01"]
        assert runner_rows[0]["depends_on"] == workflow["scenarios"][0]["depends_on"] == []
    assert run_manifest(str(manifest), str(tmp_path), owner="TASK-001")["results"][0]["status"] == "accepted_risk"
    assert run_manifest(str(manifest), str(tmp_path), owner="TASK-002")["results"][0]["status"] == "failed"
    _, _, both, _ = _prepare_manifest(str(manifest), str(tmp_path), "full", (), "TASK-001,TASK-002")
    assert [row["id"] for row in both] == ["S-01", "S-02"] and both[0]["depends_on"] == ["S-02"]
    data = json.loads(manifest.read_text(encoding="utf-8"))
    data["scenarios"][0]["status"] = "planned"
    data["scenarios"][1]["priority"] = "P1"
    manifest.write_text(json.dumps(data), encoding="utf-8")
    _, _, smoke_rows, _ = _prepare_manifest(str(manifest), str(tmp_path), "smoke", (), "TASK-001")
    _, failure = _e2e_preflight(manifest, [(task, "TASK-001", "done")], True, "smoke", str(tmp_path))
    assert smoke_rows == [] and failure is None, "preflight must use the same manifest-wide profile"
    imports = _private_imports(SCRIPTS / "codeflow/cli/cf_task_workflow.py", _script_modules(SCRIPTS))
    assert not {entry for entry in imports if entry[1] == "cf_acceptance_runner"}


@pytest.mark.xfail(strict=True, reason="S-06 is planned for TASK-005")
def test_s06_parallel_conflicts_and_spec_scope_share_owner() -> None:
    pytest.fail("Implement S-06: merge conflicts and Spec-Refs plus path-mapping scope stay consistent")


@pytest.mark.xfail(strict=True, reason="E-03 is planned for TASK-005")
def test_e03_evidence_and_task_transitions_preserve_guards() -> None:
    pytest.fail("Implement E-03: evidence updates and marker mismatches cannot promote an unverified TASK")


@pytest.mark.xfail(strict=True, reason="S-07 is planned for TASK-006")
def test_s07_gate_and_session_use_domain_owners() -> None:
    pytest.fail("Implement S-07: gate and session share model and policy owners without CLI back edges")


@pytest.mark.xfail(strict=True, reason="E-04 is planned for TASK-006")
def test_e04_gate_deferral_kinds_keep_fail_closed_policy() -> None:
    pytest.fail("Implement E-04: review and heavy deferrals differ from budget and environment failures")


@pytest.mark.xfail(strict=True, reason="S-08 is planned for TASK-007")
def test_s08_context_and_workflow_are_acyclic_and_preserve_lifecycle() -> None:
    pytest.fail("Implement S-08: Context refresh, marker, TASK and session projection preserve lifecycle behavior")


@pytest.mark.xfail(strict=True, reason="E-05 is planned for TASK-007")
def test_e05_failed_start_preserves_context_and_marker() -> None:
    pytest.fail("Implement E-05: real failed start checks leave Context and active marker in their prior states")


@pytest.mark.xfail(strict=True, reason="S-09 is planned for TASK-008")
def test_s09_parallel_smoke_uses_shared_verification() -> None:
    pytest.fail("Implement S-09: batch smoke selects merged owners and executes a shared check once")


@pytest.mark.xfail(strict=True, reason="E-06 is planned for TASK-008")
def test_e06_failed_parallel_smoke_preserves_worktrees() -> None:
    pytest.fail("Implement E-06: a real failed batch smoke blocks cleanup and preserves worktrees")


@pytest.mark.xfail(strict=True, reason="S-10 is planned for TASK-009")
def test_s10_final_dependency_ratchet_rejects_new_cycles() -> None:
    pytest.fail("Implement S-10: batch seven has no allowed reverse edges, private imports or multi-module SCC")


@pytest.mark.xfail(strict=True, reason="S-11 is planned for TASK-009")
def test_s11_packaged_runtime_and_canonical_copies_match() -> None:
    pytest.fail("Implement S-11: real package installation and canonical/deployed runtime contracts agree")
