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


@pytest.mark.xfail(strict=True, reason="S-03 is planned for TASK-003")
def test_s03_manifest_scenario_and_schema_dependencies_are_acyclic() -> None:
    pytest.fail("Implement S-03: scenario parsing, manifest extraction and schema validation form a directed graph")


@pytest.mark.xfail(strict=True, reason="E-02 is planned for TASK-003")
def test_e02_manifest_legacy_healing_and_drift_behavior() -> None:
    pytest.fail("Implement E-02: real legacy lock healing and malformed or changed inputs keep their outcomes")


@pytest.mark.xfail(strict=True, reason="S-04 is planned for TASK-004")
def test_s04_check_registration_uses_shared_public_contract() -> None:
    pytest.fail("Implement S-04: real pytest collection and registration use the same check semantics")


@pytest.mark.xfail(strict=True, reason="S-05 is planned for TASK-004")
def test_s05_acceptance_selection_and_risk_are_consistent() -> None:
    pytest.fail("Implement S-05: owner and profile selection and accepted risk agree across consumers")


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
