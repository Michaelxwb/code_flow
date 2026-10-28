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


def _real_check_conflict(directory: Path) -> None:
    import json

    from cf_task_parallel import merge, prepare
    from test_cf_task_merge import _REPO_TASK_FILE, _commit, _git, _manifest_path, _merge_repo, _set_status

    root = _merge_repo(directory)
    manifest = _manifest_path(root)
    data = json.loads(manifest.read_text(encoding="utf-8"))
    data["checks"][0]["id"] = "CHK-01"
    for row in data["scenarios"]:
        row["check"] = "CHK-01"
    manifest.write_text(json.dumps(data), encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "normalize check")
    prepared = prepare(root, _REPO_TASK_FILE, ["TASK-001", "TASK-002"], "conflict")
    assert prepared["ok"]
    for item, command in zip(prepared["worktrees"], (["pytest", "-q"], ["pytest", "-x"])):
        worktree = Path(item["path"])
        path = _manifest_path(worktree)
        data = json.loads(path.read_text(encoding="utf-8"))
        data["checks"][0]["command"] = command
        path.write_text(json.dumps(data), encoding="utf-8")
        _set_status(worktree, item["task"], "done")
        _commit(worktree, "change check")
    result = merge(root, "conflict", None)
    failure = result["results"][-1]
    assert not result["ok"] and failure["code"] == "check_conflict"
    assert failure["conflicts"][0]["check_id"] == "CHK-01"
    assert "command" in failure["conflicts"][0]["fields"]


def test_s06_parallel_conflicts_and_spec_scope_share_owner(tmp_path: Path) -> None:
    from codeflow.task.cf_task_runtime import task_spec_scope
    from test_cf_task_runtime import _repo
    from test_runtime_consolidation import _private_imports, _script_modules

    _real_check_conflict(tmp_path)
    scope_path = tmp_path / "scope"
    scope_path.mkdir()
    root, task_dir = _repo(scope_path, activate=False)
    (task_dir / "demo.md").write_text(
        "# Tasks\n## TASK-001: Demo\n- **Status**: draft\n"
        "- **Spec-Refs**: db-runtime#RULE-db-001\n", encoding="utf-8",
    )
    assert task_spec_scope(str(root), str(task_dir), "TASK-001", ("src/app.py",)) == {
        "app-runtime", "db-runtime",
    }
    task_file = task_dir / "demo.md"
    task_file.write_text(task_file.read_text(encoding="utf-8").replace(
        "db-runtime#RULE-db-001", "TBD, db-runtime#RULE-db-001"), encoding="utf-8")
    with pytest.raises(ValueError, match="spec_refs_unresolved"):
        task_spec_scope(str(root), str(task_dir), "TASK-001", ("src/app.py",))
    imports = _private_imports(SCRIPTS / "codeflow/cli/cf_task_parallel.py", _script_modules(SCRIPTS))
    assert not {entry for entry in imports if entry[1] in {"cf_task_merge", "cf_task_runtime"}}


def _assert_promotion_requires_acceptance(
    root: Path, task_dir: Path, task: Path, tasks: list[tuple[Path, str, str]], result: dict[str, object],
) -> None:
    import json

    from cf_acceptance_runner import run_manifest
    from cf_task_workflow import _complete_requirement_verification

    manifest = task_dir / ".acceptance-manifest.json"
    data = {
        "schema": 3, "task_file": task.name,
        "checks": [{"id": "CHK-1", "command": [sys.executable, "-c", "pass"], "cwd": ".", "timeout": 30,
                    "inputs": ["src/app.py"]}],
        "scenarios": [{"id": "S-01", "owner": "TASK-001", "kind": "functional", "check": "CHK-1",
                       "command": [sys.executable, "-c", "pass"],
                       "status": "verified", "evidence": {"status": "failed", "exit_code": 1}}],
    }
    manifest.write_text(json.dumps(data), encoding="utf-8")
    blocked = _complete_requirement_verification(str(root), str(task_dir), tasks, result)
    assert blocked["reason"] == "requirement_acceptance_unverified"
    assert "**Status**: verified" not in task.read_text(encoding="utf-8")
    wrong_owner = {**data["scenarios"][0], "owner": "TASK-002",
                   "evidence": {"status": "passed", "exit_code": 0}}
    for scenarios in ([], [wrong_owner]):
        manifest.write_text(json.dumps({**data, "scenarios": scenarios}), encoding="utf-8")
        missing = _complete_requirement_verification(str(root), str(task_dir), tasks, result)
        assert missing["reason"] == "requirement_acceptance_unverified"
        assert any("TASK-001" in issue and "S-01" in issue for issue in missing["issues"])
        assert "**Status**: verified" not in task.read_text(encoding="utf-8")
    manifest.write_text(json.dumps(data), encoding="utf-8")
    executed = run_manifest(str(manifest), str(root), owner="TASK-001", write_evidence=True)
    assert executed["decision"] == "pass", executed
    app = root / "src/app.py"
    original = app.read_text(encoding="utf-8")
    app.write_text("VALUE = 3\n", encoding="utf-8")
    stale = _complete_requirement_verification(str(root), str(task_dir), tasks, result)
    assert stale["reason"] == "requirement_acceptance_unverified"
    assert "**Status**: verified" not in task.read_text(encoding="utf-8")
    app.write_text(original, encoding="utf-8")
    passed = _complete_requirement_verification(str(root), str(task_dir), tasks, result)
    assert passed["decision"] == "pass"
    assert task.read_text(encoding="utf-8").count("**Status**: verified") == 2


def test_e03_evidence_and_task_transitions_preserve_guards(tmp_path: Path) -> None:
    from cf_spec_context import complete_active_task, load_context, start_active_task
    from cf_spec_session import context_sha256
    from cf_task_workflow import _complete_requirement_verification
    from codeflow.spec.cf_workflow_service import WorkflowError, complete_task
    from codeflow.task.cf_task_runtime import run_done_gate
    from test_cf_task_runtime import _git, _repo
    from test_runtime_consolidation import _private_imports, _script_modules

    root, task_dir = _repo(tmp_path, activate=False)
    task = task_dir / "demo.md"
    task.write_text(
        "# Tasks\n## TASK-001: One\n- **Status**: done\n"
        "- **Spec-Refs**: app-runtime#RULE-app-001\n"
        "## TASK-002: Two\n- **Status**: done\n", encoding="utf-8",
    )
    _git(root, "add", ".")
    _git(root, "commit", "-qm", "task fixture")
    context = load_context(str(task_dir / "spec-context.yml"))
    start_active_task(str(root), str(task_dir), "TASK-001", context_sha256(context))
    (root / "src/app.py").write_text("print('bad')\n", encoding="utf-8")
    result = run_done_gate(str(root), str(task_dir))
    assert result.decision == "block" and result.evidence[0]["error_code"] == "regex_violation"
    with pytest.raises(WorkflowError, match="active_mismatch"):
        complete_task(str(root), str(task_dir), str(task), "TASK-002", True)
    (root / ".code-flow/.active-task.json").unlink()
    layers = {name: {"decision": "pass"} for name in ("validators", "review", "e2e")}
    forged = {"decision": "pass", "profile": "full", "selected_layers": list(layers), "layers": layers}
    tasks = [(task, "TASK-001", "done"), (task, "TASK-002", "done")]
    verified = _complete_requirement_verification(str(root), str(task_dir), tasks, forged)
    assert verified["reason"] == "task_status_truth_mismatch"
    assert "**Status**: done" in task.read_text(encoding="utf-8")

    current = load_context(str(task_dir / "spec-context.yml"))
    start_active_task(str(root), str(task_dir), "TASK-001", context_sha256(current), ("src/app.py",))
    (root / "src/app.py").write_text("VALUE = 2\n", encoding="utf-8")
    passed = run_done_gate(str(root), str(task_dir))
    assert passed.decision == "pass"
    complete_active_task(str(root), passed.decision == "pass")
    task.write_text(task.read_text(encoding="utf-8").replace(
        "- **Spec-Refs**: app-runtime#RULE-app-001", "- **Acceptance-Refs**: S-01\n- **Spec-Refs**: app-runtime#RULE-app-001"
    ), encoding="utf-8")
    verified = _complete_requirement_verification(str(root), str(task_dir), tasks, forged)
    assert verified["reason"] == "requirement_acceptance_unverified"
    assert "**Status**: verified" not in task.read_text(encoding="utf-8")
    _assert_promotion_requires_acceptance(root, task_dir, task, tasks, forged)
    imports = _private_imports(SCRIPTS / "codeflow/cli/cf_task_workflow.py", _script_modules(SCRIPTS))
    assert not {entry for entry in imports if entry[1] in {"cf_task_runtime", "cf_workflow_service"}}


def test_s07_gate_and_session_use_domain_owners(tmp_path: Path) -> None:
    from cf_spec_context import load_context
    from cf_spec_gate import validate_stage
    from cf_spec_session import project_task_session
    from test_cf_spec_session import _project
    from test_runtime_consolidation import _import_edges, _script_modules

    task_dir, task_file, _ = _project(tmp_path, 2)
    context = load_context(str(task_dir / "spec-context.yml"))
    projection = project_task_session(context, str(task_file), "TASK-001")
    plan = validate_stage(context, "plan")
    code = validate_stage(context, "code")
    refs = {f"session-rules#RULE-session-{index:03d}" for index in (1, 2)}
    assert plan.decision == "pass" and code.decision == "block"
    assert set(code.affected_refs) == refs
    assert projection.included_rules == projection.total_rules == len(refs)
    assert all(ref in projection.text for ref in refs)
    assert validate_stage.__module__ == "codeflow.spec.cf_stage_gate"
    assert type(projection).__module__ == "codeflow.spec.cf_task_projection"
    modules = _script_modules(SCRIPTS)
    for relative in ("acceptance/cf_plan_quality.py", "spec/cf_workflow_service.py"):
        edges = _import_edges(SCRIPTS / "codeflow" / relative, modules)
        assert not {edge for edge in edges if edge[1] == "cf_spec_gate"}
    for relative in ("cli/cf_spec_gate.py", "cli/cf_spec_session.py"):
        edges = _import_edges(SCRIPTS / "codeflow" / relative, modules)
        assert not {edge for edge in edges if edge[1] == "cf_spec_context"}
    service_edges = _import_edges(SCRIPTS / "codeflow/spec/cf_workflow_service.py", modules)
    assert ("cf_workflow_service", "cf_spec_session") not in service_edges


def test_e04_gate_deferral_kinds_keep_fail_closed_policy() -> None:
    from cf_spec_gate import evidence_deferral_kind, validate_stage
    from test_cf_spec_gate import _context

    for kind, error in (("review_stage", "deferred_to_review"), ("heavy", "deferred_to_review"),
                        ("budget", "verifier_budget_exhausted"), ("env", "env_blocked")):
        evidence = {"status": "unverified", "error_code": error, "details": {"deferral_kind": kind}}
        context = _context("unverified", evidence=(evidence,))
        assert evidence_deferral_kind(evidence) == kind
        assert validate_stage(context, "design").decision == "block"
        allowed = validate_stage(context, "design", allow_deferred_skips=True)
        assert allowed.decision == ("pass" if kind in {"review_stage", "heavy"} else "block")
    for error, expected in (("verifier_budget_exhausted", "budget"), ("env_blocked", "env")):
        evidence = {"error_code": error, "details": {"deferral_kind": "review_stage"}}
        assert evidence_deferral_kind(evidence) == expected
        assert validate_stage(_context("unverified", evidence=(evidence,)), "design",
                              allow_deferred_skips=True).decision == "block"
    unknown = {"error_code": "deferred_to_review"}
    assert evidence_deferral_kind(unknown) == "unknown"
    assert validate_stage(_context("unverified", evidence=(unknown,)), "design",
                          allow_deferred_skips=True).decision == "block"


def _lifecycle_project(root: Path) -> tuple[Path, Path]:
    import json
    import subprocess

    import yaml

    from cf_acceptance_manifest import write_manifest
    from test_cf_task_runtime import _git, _repo

    root, directory = _repo(root, activate=False)
    initialized = subprocess.run(("node", str(SCRIPTS.parents[2] / "cli.js"), "init", "--platform=codex"),
                                 cwd=root, text=True, capture_output=True, check=False)
    assert initialized.returncode == 0, initialized.stderr
    config_path = root / ".code-flow/config.yml"
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    specs = root / ".code-flow/specs"
    config["path_mapping"]["shared"] = {"specs": [
        {"path": path.relative_to(specs).as_posix(), "tags": []} for path in (specs / "shared").rglob("*.md")
    ]}
    config_path.write_text(yaml.safe_dump(config), encoding="utf-8")
    test_file = root / "tests/test_demo.py"
    test_file.parent.mkdir()
    test_file.write_text("from pathlib import Path\n\ndef test_app_value():\n"
                         "    assert 'VALUE' in (Path(__file__).parents[1] / 'src/app.py').read_text()\n",
                         encoding="utf-8")
    task = directory / "demo.md"
    command = json.dumps([sys.executable, "-c", "pass"])
    task.write_text(
        "# Tasks\n\n## Acceptance Coverage\n\n"
        "| 场景ID | 来源设计 | 测试层级 | 关键真实边界 | 负责任务 | 状态 | 执行命令 |\n"
        "|--------|---------|---------|-------------|---------|------|---------|\n"
        f"| S-01 | demo.design.md#2 | integration | real process | TASK-001 | planned | {command} |\n\n"
        "## TASK-001: Demo\n- **Status**: draft\n- **Spec-Refs**: app-runtime#RULE-app-001\n"
        "- **Acceptance-Refs**: S-01\n### Checklist\n- [x] Verify the real boundary\n"
        "### Acceptance Contract\n| S-01 | integration | real process | succeeds | planned |\n"
        "### Acceptance Evidence\n\n### Log\n- [2026-01-01] created (draft)\n", encoding="utf-8",
    )
    write_manifest(str(task), str(directory / ".acceptance-manifest.json"))
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "lifecycle fixture")
    return directory, task


def _lifecycle_cli(root: Path, *args: str) -> dict[str, object]:
    import json
    import subprocess

    result = subprocess.run(("node", str(SCRIPTS.parents[2] / "cli.js"), *args), cwd=root,
                            input='{"owned_paths":[]}', text=True, capture_output=True, timeout=60, check=False)
    assert result.returncode == 0, result.stderr + result.stdout
    return json.loads(result.stdout)


def _reachable(edges: set[tuple[str, str]], source: str, target: str) -> bool:
    pending, seen = [source], set()
    while pending:
        node = pending.pop()
        if node == target:
            return True
        if node not in seen:
            seen.add(node)
            pending.extend(to for start, to in edges if start == node and to not in seen)
    return False


def test_s08_context_and_workflow_are_acyclic_and_preserve_lifecycle(tmp_path: Path) -> None:
    from test_runtime_consolidation import _import_edges, _script_files, _script_modules

    directory, task = _lifecycle_project(tmp_path)
    refresh = _lifecycle_cli(tmp_path, "spec", "refresh", "--task-dir", str(directory), "--root", str(tmp_path), "--json")
    assert refresh["ok"]
    started = _lifecycle_cli(tmp_path, "task", "start", "--task-dir", str(directory), "--task-file", str(task),
                             "--task", "TASK-001", "--root", str(tmp_path), "--json")
    assert started["active"]["status"] == "active"
    assert "RULE-app-001" in Path(started["session_output"]).read_text(encoding="utf-8")
    (tmp_path / "src/app.py").write_text("VALUE = 2\n", encoding="utf-8")
    finished = _lifecycle_cli(tmp_path, "task", "finish", "--task-dir", str(directory),
                              "--task", "TASK-001", "--root", str(tmp_path), "--json")
    assert finished["decision"] == "pass" and not (tmp_path / ".code-flow/.active-task.json").exists()
    verified = _lifecycle_cli(tmp_path, "task", "verify", "--task-dir", str(directory),
                              "--profile", "full", "--root", str(tmp_path), "--json")
    assert verified["decision"] == "pass" and "**Status**: verified" in task.read_text(encoding="utf-8")
    modules = _script_modules(SCRIPTS)
    edges = set().union(*(_import_edges(path, modules) for path in _script_files(SCRIPTS)))
    assert not (_reachable(edges, "cf_spec_context", "cf_workflow_service")
                and _reachable(edges, "cf_workflow_service", "cf_spec_context"))


def test_e05_failed_start_preserves_context_and_marker(tmp_path: Path) -> None:
    from codeflow.spec.cf_active_task import acquire_active_lock, release_active_lock
    from codeflow.spec.cf_workflow_service import WorkflowError, start_task
    from test_cf_task_runtime import _git, _repo

    for name, refs, coverage in (("manifest", "app-runtime#RULE-app-001", "## Acceptance Coverage\n"),
                                 ("projection", "missing#RULE-missing-001", ""),
                                 ("output", "app-runtime#RULE-app-001", ""),
                                 ("invalid_owned", "app-runtime#RULE-app-001", ""),
                                 ("lock", "app-runtime#RULE-app-001", ""),
                                 ("unowned", "app-runtime#RULE-app-001", "")):
        root = tmp_path / name
        root.mkdir()
        root, directory = _repo(root, activate=False)
        task = directory / "demo.md"
        task.write_text(f"# Tasks\n{coverage}\n## TASK-001: Demo\n- **Status**: draft\n"
                        f"- **Spec-Refs**: {refs}\n### Acceptance Contract\n| S-01 | integration | real | pass |\n",
                        encoding="utf-8")
        spec = root / ".code-flow/specs/app/rules.md"
        spec.write_text(spec.read_text(encoding="utf-8").replace("Runtime constraint.", "Updated constraint."), encoding="utf-8")
        _git(root, "add", ".code-flow/specs/app/rules.md")
        _git(root, "commit", "-qm", "change spec without refreshing context")
        if name == "unowned":
            (root / "src/app.py").write_text("VALUE = 9\n", encoding="utf-8")
        context = directory / "spec-context.yml"
        before = context.read_bytes()
        output = str(root / "src/app.py/session.md") if name == "output" else ""
        owned = (123,) if name == "invalid_owned" else ()
        lock = acquire_active_lock(str(root)) if name == "lock" else None
        try:
            with pytest.raises(WorkflowError) as error:
                start_task(str(root), str(directory), str(task), "TASK-001", owned_paths=owned,  # type: ignore[arg-type]
                           session_output=output)
        finally:
            if lock is not None:
                release_active_lock(lock)
        assert error.value.code == {"manifest": "acceptance_manifest_missing", "projection": "task_projection_failed",
                                    "output": "session_write_failed", "invalid_owned": "invalid_owned_paths",
                                    "lock": "transition_failed",
                                    "unowned": "unowned_changes"}[name]
        assert context.read_bytes() == before
        assert not (root / ".code-flow/.active-task.json").exists()
        assert "**Status**: draft" in task.read_text(encoding="utf-8")


def _parallel_smoke_repo(tmp_path: Path, command: list[str]) -> tuple[Path, list[str]]:
    import json

    from cf_acceptance_manifest import write_manifest
    from test_cf_task_parallel import BATCH_TASK_FILE, _batch_repo, _git, _shared_marker_command

    tasks = ["TASK-001", "TASK-002", "TASK-003"]
    root = _batch_repo(tmp_path, tasks, command)
    task_file = root / BATCH_TASK_FILE
    text = task_file.read_text(encoding="utf-8")
    draft_command = _shared_marker_command(tmp_path / "draft-check.log")
    rows = (
        f"| E-02 | demo.design.md#2.5 | e2e | 真实 shared env | TASK-002 | planned | {json.dumps(command)} |\n"
        f"| E-03 | demo.design.md#2.5 | e2e | 真实 shared env | TASK-003 | planned | {json.dumps(draft_command)} |"
    )
    text = text.replace("\n\n---\n\n## TASK-001", f"\n{rows}\n\n---\n\n## TASK-001", 1)
    text = text.replace("**Acceptance-Refs**: S-02", "**Acceptance-Refs**: S-02, E-02", 1)
    text = text.replace("**Acceptance-Refs**: S-03", "**Acceptance-Refs**: S-03, E-03", 1)
    task_file.write_text(text, encoding="utf-8")
    write_manifest(str(task_file), str(task_file.parent / ".acceptance-manifest.json"))
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "register shared and draft checks")
    return root, tasks[:2]


def _prepare_smoke_batch(root: Path, tasks: list[str], run_id: str) -> dict[str, object]:
    from cf_task_parallel import collect, prepare
    from test_cf_task_parallel import BATCH_TASK_FILE, _run_batch_worker

    prepared = prepare(root, BATCH_TASK_FILE, tasks, run_id)
    assert prepared["ok"] is True, prepared
    for task in tasks:
        outcome = _run_batch_worker(root, run_id, task)
        assert outcome["decision"] == "pass", outcome
    collected = collect(root, run_id, None)
    assert collected["ok"] is True and collected["batch_smoke"] == "pending", collected
    return prepared


def test_s09_parallel_smoke_uses_shared_verification(tmp_path: Path) -> None:
    import json

    from cf_task_parallel import merge
    from test_cf_task_parallel import BATCH_TASK_FILE, _shared_marker_command
    from test_runtime_consolidation import _import_edges, _script_modules

    marker = tmp_path / "shared-check.log"
    root, tasks = _parallel_smoke_repo(tmp_path, _shared_marker_command(marker))
    _prepare_smoke_batch(root, tasks, "shared-smoke")
    merged = merge(root, "shared-smoke", None)
    assert merged["ok"] is True, merged
    assert [item["status"] for item in merged["results"]] == ["merged", "merged"]
    assert merged["batch_smoke"]["status"] == "passed"
    assert marker.read_text(encoding="utf-8") == "x", "shared check must execute once"
    assert not (tmp_path / "draft-check.log").exists(), "draft owner's check must not run"
    data = json.loads((root / Path(BATCH_TASK_FILE).parent / ".acceptance-manifest.json").read_text())
    rows = {row["id"]: row for row in data["scenarios"]}
    assert rows["E-01"]["status"] == rows["E-02"]["status"] == "verified"
    assert rows["E-03"]["status"] == "planned"
    edges = _import_edges(SCRIPTS / "codeflow/cli/cf_task_parallel.py", _script_modules(SCRIPTS))
    assert ("cf_task_parallel", "cf_task_workflow") not in edges


def test_e06_failed_parallel_smoke_preserves_worktrees(tmp_path: Path) -> None:
    import json

    from cf_task_parallel import cleanup, merge
    from test_cf_task_parallel import _git

    root, tasks = _parallel_smoke_repo(tmp_path, [sys.executable, "-c", "raise SystemExit(3)"])
    prepared = _prepare_smoke_batch(root, tasks, "failed-smoke")
    merged = merge(root, "failed-smoke", None)
    assert merged["ok"] is False and merged["code"] == "batch_smoke_failed", merged
    assert merged["batch_smoke"]["status"] == "failed"
    ledger = json.loads((root / ".code-flow/worktrees/failed-smoke/run.json").read_text())
    assert ledger["merge"]["status"] == "blocked"
    cleaned = cleanup(root, "failed-smoke", force=False)
    assert cleaned["ok"] is False
    assert {item["code"] for item in cleaned["results"]} == {"batch_smoke_failed"}
    for entry in prepared["worktrees"]:
        assert Path(entry["path"]).is_dir()
        assert entry["branch"] in _git(root, "branch", "--list", entry["branch"])


def _synthetic_graph(tmp_path: Path, modules: dict[str, str]) -> Path:
    package = tmp_path / "codeflow" / "task"
    package.mkdir(parents=True)
    for name, source in modules.items():
        (package / f"{name}.py").write_text(source, encoding="utf-8")
    return tmp_path


def test_s10_final_dependency_ratchet_rejects_new_cycles(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import test_runtime_consolidation as guard

    assert guard.CURRENT_BATCH == 7
    assert not guard.DEPENDENCY_EDGE_ALLOWLIST and not guard.PRIVATE_SYMBOL_ALLOWLIST
    guard.test_dependency_direction()
    guard.test_private_symbol_guard()
    guard.test_allowlist_ratchet()
    guard.test_scc_budget()
    modules = guard._script_modules(SCRIPTS)
    edges = set().union(*(guard._import_edges(path, modules) for path in guard._script_files(SCRIPTS)))
    assert guard._strongly_connected_sizes(edges) == []

    reverse = _synthetic_graph(tmp_path / "reverse", {
        "cf_log": "from codeflow.spec import cf_spec_context\n", "cf_spec_context": "",
    })
    monkeypatch.setattr(guard, "SCRIPTS", reverse)
    with pytest.raises(AssertionError, match="new reverse dependencies"):
        guard.test_dependency_direction()
    private = _synthetic_graph(tmp_path / "private", {
        "cf_log": "from codeflow.task.cf_task_doc import _hidden\n", "cf_task_doc": "",
    })
    monkeypatch.setattr(guard, "SCRIPTS", private)
    with pytest.raises(AssertionError, match="new private cross-module imports"):
        guard.test_private_symbol_guard()
    cycle = _synthetic_graph(tmp_path / "cycle", {
        "cf_task_doc": "from codeflow.task import cf_task_plan\n",
        "cf_task_plan": "from codeflow.task import cf_task_doc\n",
    })
    monkeypatch.setattr(guard, "SCRIPTS", cycle)
    with pytest.raises(AssertionError, match="dependency SCC"):
        guard.test_scc_budget()
    monkeypatch.setattr(guard, "DEPENDENCY_EDGE_ALLOWLIST", frozenset({("cf_log", "cf_task_doc", 7)}))
    with pytest.raises(AssertionError, match="past their cleanup batch"):
        guard.test_allowlist_ratchet()


def _assert_packed_platform(cli: Path, project: Path, platform: str) -> None:
    import json
    import subprocess

    from test_runtime_consolidation import _flat_entry_modules, _hook_probe, _script_py_files

    project.mkdir()
    result = subprocess.run(["node", str(cli), "init", f"--platform={platform}"], cwd=project,
                            text=True, capture_output=True, timeout=120, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
    scripts = project / ".code-flow/scripts"
    canonical = _script_py_files(SCRIPTS)
    assert _script_py_files(scripts) == canonical
    for relative in canonical:
        assert (scripts / relative).read_bytes() == (SCRIPTS / relative).read_bytes(), relative
    manifest = json.loads((project / ".code-flow/.runtime-install.json").read_text())
    for relative in canonical:
        assert f".code-flow/scripts/{relative}" in manifest["files"], relative
    modules = sorted(_flat_entry_modules())
    probe = ("import importlib, sys\n"
             f"sys.path.insert(0, {str(scripts)!r})\n"
             f"[importlib.import_module(name) for name in {modules!r}]\n")
    loaded = subprocess.run([sys.executable, "-c", probe], cwd=project, text=True,
                            capture_output=True, timeout=120, check=False)
    assert loaded.returncode == 0, loaded.stderr
    verify = subprocess.run(["node", str(cli), "task", "verify", "--help"], cwd=project,
                            text=True, capture_output=True, timeout=120, check=False)
    assert verify.returncode == 0, verify.stdout + verify.stderr
    _hook_probe(project, "cf_stop_hook.py", {"session_id": "s11", "hook_event_name": "Stop"})
    if platform == "codex":
        _hook_probe(project, "cf_codex_hook.py", {"cwd": str(project), "session_id": "s11",
                    "hook_event_name": "UserPromptSubmit", "prompt": "explain the architecture"})
    if platform == "opencode":
        _hook_probe(project, "cf_opencode_event.py", {"kind": "session.prompt", "directory": str(project),
                    "event": {"sessionID": "s11", "prompt": {"text": "explain the architecture"}}})


def test_s11_packaged_runtime_and_canonical_copies_match(tmp_path: Path) -> None:
    import json
    import subprocess

    from test_runtime_consolidation import PLATFORMS, ROOT, _extract_tarball

    packed = subprocess.run(["npm", "pack", "--pack-destination", str(tmp_path), "--silent"], cwd=ROOT,
                            text=True, capture_output=True, timeout=180, check=False)
    assert packed.returncode == 0, packed.stdout + packed.stderr
    tarballs = list(tmp_path.glob("*.tgz"))
    assert len(tarballs) == 1
    extracted = tmp_path / "extracted"
    _extract_tarball(tarballs[0], extracted)
    package = extracted / "package"
    source = json.loads((ROOT / "package.json").read_text())
    packed_config = json.loads((package / "package.json").read_text())
    assert packed_config.get("dependencies", {}) == source.get("dependencies", {})
    assert set(source.get("dependencies", {})) == {"@ccusage/codex"}
    for platform in PLATFORMS:
        _assert_packed_platform(package / "src/cli.js", tmp_path / platform, platform)
    synced = subprocess.run(["node", str(ROOT / "src/cli.js"), "sync", "check"], cwd=ROOT,
                            text=True, capture_output=True, timeout=120, check=False)
    assert synced.returncode == 0, synced.stdout + synced.stderr


def test_s12_workflow_shim_preserves_bindings_import(tmp_path: Path) -> None:
    import subprocess

    empty = tmp_path / "empty"
    corrupt = tmp_path / "corrupt"
    empty.mkdir()
    corrupt.mkdir()
    (corrupt / "spec-context.yml").write_text("invalid: [\n", encoding="utf-8")
    probe = (
        "import sys\n"
        "from pathlib import Path\n"
        "sys.path.insert(0, sys.argv[1])\n"
        "from cf_task_workflow import collect_requirement_bindings\n"
        "assert collect_requirement_bindings(Path(sys.argv[2])) == {}\n"
        "try:\n"
        "    collect_requirement_bindings(Path(sys.argv[3]))\n"
        "except ValueError as exc:\n"
        "    assert 'review_context_unreadable' in str(exc)\n"
        "else:\n"
        "    raise AssertionError('corrupt context was silently accepted')\n"
    )
    deployed = Path(__file__).resolve().parents[1] / ".code-flow/scripts"
    for scripts in (SCRIPTS, deployed):
        result = subprocess.run([sys.executable, "-c", probe, str(scripts), str(empty), str(corrupt)],
                                cwd=tmp_path, text=True, capture_output=True, timeout=30, check=False)
        assert result.returncode == 0, f"{scripts}: {result.stderr}"
