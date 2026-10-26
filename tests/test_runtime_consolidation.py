"""Architecture guards and plan skeletons for runtime consolidation.

The three implemented tests are the TASK-001 acceptance contract (S-15, S-16,
B-03). The remaining skeletons are registered during plan and replaced by their
implementing tasks; no production import belongs at module scope so collection
stays independent of unimplemented modules.
"""
from __future__ import annotations

import ast
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path
from typing import Iterable, Optional

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "src" / "core" / "code-flow" / "scripts"
CLI = ROOT / "src" / "cli.js"
CANONICAL_IGNORE = ROOT / "src" / "core" / "code-flow" / ".gitignore"
RUNTIME_IGNORE_START = "# >>> code-flow:runtime schema=1"
RUNTIME_IGNORE_END = "# <<< code-flow:runtime schema=1"
RUNTIME_IGNORE_ENTRIES = 20
sys.path.insert(0, str(SCRIPTS))

CURRENT_BATCH = 1

LAYERS: dict[str, int] = {
    "cf_acceptance_evidence": 1,
    "cf_acceptance_manifest": 2,
    "cf_acceptance_plan": 1,
    "cf_acceptance_registration": 2,
    "cf_acceptance_risk": 1,
    "cf_acceptance_runner": 2,
    "cf_acceptance_schema": 1,
    "cf_audit": 3,
    "cf_check_inputs": 1,
    "cf_check_registration": 1,
    "cf_checks": 1,
    "cf_codex_hook": 3,
    "cf_context_cache": 1,
    "cf_core": 1,
    "cf_design_lint": 1,
    "cf_edit_service": 2,
    "cf_evidence_import": 2,
    "cf_evidence_store": 1,
    "cf_exec_base": 0,
    "cf_feedback": 3,
    "cf_fs": 0,
    "cf_git": 0,
    "cf_injection": 2,
    "cf_log": 0,
    "cf_markdown": 1,
    "cf_native_paths": 0,
    "cf_opencode_event": 3,
    "cf_patch": 0,
    "cf_plan_quality": 1,
    "cf_post_hook": 3,
    "cf_pre_tool_hook": 3,
    "cf_rule_readiness": 1,
    "cf_runtime_install": 0,
    "cf_scan": 3,
    "cf_scenario_quality": 1,
    "cf_scenarios": 1,
    "cf_session_state": 0,
    "cf_spec_context": 2,
    "cf_spec_gate": 2,
    "cf_spec_metadata": 1,
    "cf_spec_migrate": 3,
    "cf_spec_resolver": 1,
    "cf_spec_router": 2,
    "cf_spec_session": 2,
    "cf_spec_verify": 2,
    "cf_stats": 3,
    "cf_stop_guard": 0,
    "cf_stop_hook": 3,
    "cf_sync": 3,
    "cf_task_doc": 1,
    "cf_task_index": 1,
    "cf_task_merge": 2,
    "cf_task_parallel": 2,
    "cf_task_plan": 1,
    "cf_task_runtime": 2,
    "cf_task_state": 0,
    "cf_task_workflow": 3,
    "cf_traceability": 3,
    "cf_user_prompt_hook": 3,
    "cf_validation": 3,
    "cf_validators": 1,
    "cf_workflow_service": 2,
    "cf_workflow_transaction": 2,
    "cf_worktree_env": 0,
}

# (importer, imported module, batch after which the edge must be gone)
DEPENDENCY_EDGE_ALLOWLIST = frozenset({
    ("cf_acceptance_schema", "cf_acceptance_manifest", 4),
    ("cf_context_cache", "cf_spec_context", 4),
    ("cf_evidence_store", "cf_spec_context", 4),
    ("cf_plan_quality", "cf_acceptance_manifest", 4),
    ("cf_plan_quality", "cf_spec_context", 4),
    ("cf_plan_quality", "cf_spec_gate", 6),
    ("cf_scenarios", "cf_acceptance_manifest", 4),
    ("cf_task_parallel", "cf_task_workflow", 6),
})

# (importer, source module, private symbol, batch after which it must be gone)
PRIVATE_SYMBOL_ALLOWLIST = frozenset({
    ("cf_acceptance_registration", "cf_check_registration", "_collected", 6),
    ("cf_acceptance_registration", "cf_check_registration", "_execution_argv", 6),
    ("cf_acceptance_registration", "cf_check_registration", "_pytest_markers", 6),
    ("cf_acceptance_registration", "cf_check_registration", "_registration_issues", 6),
    ("cf_acceptance_registration", "cf_check_registration", "_requirements", 6),
    ("cf_task_parallel", "cf_task_merge", "_check_conflicts", 6),
    ("cf_task_parallel", "cf_task_runtime", "_task_scope_specs", 6),
    ("cf_task_runtime", "cf_spec_session", "_refs", 3),
    ("cf_task_runtime", "cf_spec_session", "_task_section", 3),
    ("cf_task_workflow", "cf_acceptance_runner", "_accepted_risk", 6),
    ("cf_task_workflow", "cf_acceptance_runner", "_owned", 6),
    ("cf_task_workflow", "cf_acceptance_runner", "_select_profile", 6),
    ("cf_task_workflow", "cf_task_runtime", "_NON_EXECUTION_ERRORS", 6),
    ("cf_task_workflow", "cf_task_runtime", "_apply_evidence", 6),
    ("cf_task_workflow", "cf_task_runtime", "_evidence_data", 6),
    ("cf_task_workflow", "cf_workflow_service", "_require_marker_task", 7),
    ("cf_task_workflow", "cf_workflow_service", "_sync_markdown", 7),
    ("cf_workflow_service", "cf_spec_context", "_active_data", 7),
    ("cf_workflow_service", "cf_spec_context", "_new_active", 7),
    ("cf_workflow_transaction", "cf_spec_context", "_acquire_active_lock", 7),
    ("cf_workflow_transaction", "cf_spec_context", "_release_active_lock", 7),
})


def _type_checking_lines(tree: ast.Module) -> frozenset[int]:
    lines: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.If):
            continue
        test = node.test
        name = test.id if isinstance(test, ast.Name) else (test.attr if isinstance(test, ast.Attribute) else "")
        if name != "TYPE_CHECKING":
            continue
        for child in ast.walk(node):
            line = getattr(child, "lineno", None)
            if isinstance(line, int):
                lines.add(line)
    return frozenset(lines)


def _import_edges(path: Path, modules: frozenset[str]) -> set[tuple[str, str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    skip = _type_checking_lines(tree)
    source = path.stem
    edges: set[tuple[str, str]] = set()
    for node in ast.walk(tree):
        if getattr(node, "lineno", 0) in skip:
            continue
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name in modules and alias.name != source:
                    edges.add((source, alias.name))
        elif isinstance(node, ast.ImportFrom) and node.module in modules and node.module != source:
            edges.add((source, node.module))
    return edges


def _private_imports(path: Path, modules: frozenset[str]) -> set[tuple[str, str, str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    source = path.stem
    found: set[tuple[str, str, str]] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom) or node.module not in modules or node.module == source:
            continue
        for alias in node.names:
            if alias.name.startswith("_") and not alias.name.startswith("__"):
                found.add((source, node.module, alias.name))
    return found


def _layer_violations(edges: Iterable[tuple[str, str]]) -> set[tuple[str, str]]:
    return {(source, target) for source, target in edges if LAYERS[source] < LAYERS[target]}


def _expired(entries: Iterable[tuple[object, ...]], current_batch: int) -> list[tuple[object, ...]]:
    return sorted(entry for entry in entries
                  if isinstance(entry[-1], int) and entry[-1] <= current_batch)


def test_dependency_direction() -> None:
    modules = frozenset(path.stem for path in SCRIPTS.glob("*.py"))
    missing = sorted(modules - LAYERS.keys())
    assert not missing, f"add layer mapping for: {missing}"
    edges: set[tuple[str, str]] = set()
    for path in sorted(SCRIPTS.glob("*.py")):
        edges |= _import_edges(path, modules)
    violations = _layer_violations(edges)
    allowed = {(source, target) for source, target, _ in DEPENDENCY_EDGE_ALLOWLIST}
    unexpected = sorted(violations - allowed)
    stale = sorted(allowed - violations)
    assert not unexpected, f"new reverse dependencies: {unexpected}"
    assert not stale, f"allowlist entries no longer violate; remove them: {stale}"
    synthetic = {("cf_log", "cf_spec_context")}
    assert _layer_violations(synthetic) == synthetic, "guard must flag L0 -> L2 imports"


def test_private_symbol_guard() -> None:
    modules = frozenset(path.stem for path in SCRIPTS.glob("*.py"))
    actual: set[tuple[str, str, str]] = set()
    for path in sorted(SCRIPTS.glob("*.py")):
        actual |= _private_imports(path, modules)
    allowed = {(importer, source, symbol) for importer, source, symbol, _ in PRIVATE_SYMBOL_ALLOWLIST}
    unexpected = sorted(actual - allowed)
    stale = sorted(allowed - actual)
    assert not unexpected, f"new private cross-module imports: {unexpected}"
    assert not stale, f"allowlist entries no longer imported; remove them: {stale}"


def test_allowlist_ratchet() -> None:
    expired_edges = _expired(DEPENDENCY_EDGE_ALLOWLIST, CURRENT_BATCH)
    expired_symbols = _expired(PRIVATE_SYMBOL_ALLOWLIST, CURRENT_BATCH)
    assert not expired_edges, f"edges past their cleanup batch: {expired_edges}"
    assert not expired_symbols, f"symbols past their cleanup batch: {expired_symbols}"
    synthetic = [("cf_log", "cf_spec_context", CURRENT_BATCH)]
    assert _expired(synthetic, CURRENT_BATCH) == synthetic


def _ignore_entries(text: str) -> list[str]:
    return [line for line in text.splitlines() if line and not line.startswith("#")]


def _node_binary() -> str:
    node = shutil.which("node")
    assert node is not None, "node is required for runtime ignore integration tests"
    return node


def _run_cli_init(cli: Path, project: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [_node_binary(), str(cli), "init", "--platform=claude"],
        cwd=project,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )


def _extract_tarball(tarball: Path, dest: Path) -> None:
    """Extract a locally built tarball, rejecting traversal and links."""
    dest.mkdir(parents=True, exist_ok=True)
    root = dest.resolve()
    with tarfile.open(tarball) as archive:
        for member in archive.getmembers():
            target = (dest / member.name).resolve()
            assert str(target).startswith(str(root) + os.sep) or target == root, (
                f"unsafe tarball member: {member.name}"
            )
            assert not (member.issym() or member.islnk()), f"unexpected link: {member.name}"
        archive.extractall(dest)


def test_packed_install_ignore() -> None:
    npm = shutil.which("npm")
    assert npm is not None, "npm is required for the real tarball install probe"
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        pack_dir = tmp_path / "pack"
        pack_dir.mkdir()
        packed = subprocess.run(
            [npm, "pack", "--pack-destination", str(pack_dir), "--silent"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=180,
            check=False,
        )
        assert packed.returncode == 0, f"npm pack failed:\n{packed.stdout}{packed.stderr}"
        tarballs = list(pack_dir.glob("*.tgz"))
        assert len(tarballs) == 1, f"expected one tarball, got {tarballs}"

        extracted = tmp_path / "extracted"
        _extract_tarball(tarballs[0], extracted)
        packed_cli = extracted / "package" / "src" / "cli.js"
        assert packed_cli.is_file(), "tarball must ship src/cli.js"
        # The published tarball never carries .gitignore; init must recreate it.
        assert not (extracted / "package" / "src" / "core" / "code-flow" / ".gitignore").exists()

        project = tmp_path / "project"
        project.mkdir()
        result = _run_cli_init(packed_cli, project)
        assert result.returncode == 0, f"init failed:\n{result.stdout}{result.stderr}"

        ignore = project / ".code-flow" / ".gitignore"
        assert ignore.is_file(), "packed install must create .code-flow/.gitignore"
        entries = _ignore_entries(ignore.read_text())
        assert len(entries) == RUNTIME_IGNORE_ENTRIES, (
            f"expected {RUNTIME_IGNORE_ENTRIES} runtime entries, got {entries}"
        )
        assert ".stop.lock" in entries, "packed install is missing .stop.lock"
        assert ".context-state.json" in entries, "packed install is missing .context-state.json"
        assert entries == _ignore_entries(CANONICAL_IGNORE.read_text())


def test_upgrade_preserves_user_ignore() -> None:
    canonical_entries = _ignore_entries(CANONICAL_IGNORE.read_text())
    assert len(canonical_entries) == RUNTIME_IGNORE_ENTRIES
    removed_entries = (".stop.lock", ".debug.log")
    stale_managed = [entry for entry in canonical_entries if entry not in removed_entries]
    user_lines = ["# user-managed entries", "my-local-notes.txt"]
    stale_text = (
        RUNTIME_IGNORE_START + "\n"
        + "\n".join(stale_managed) + "\n"
        + RUNTIME_IGNORE_END + "\n"
        + "\n".join(user_lines) + "\n"
    )

    with tempfile.TemporaryDirectory() as tmp:
        project = Path(tmp)
        (project / ".code-flow").mkdir()
        (project / ".code-flow" / ".version").write_text("0.7.0\n")
        (project / ".code-flow" / "runtime-commands.json").write_text("{}\n")
        ignore = project / ".code-flow" / ".gitignore"
        ignore.write_text(stale_text)

        result = _run_cli_init(CLI, project)
        assert result.returncode == 0, f"upgrade failed:\n{result.stdout}{result.stderr}"

        upgraded = ignore.read_text()
        managed_block = upgraded.split(RUNTIME_IGNORE_START, 1)[1].split(RUNTIME_IGNORE_END, 1)[0]
        managed_entries = _ignore_entries(managed_block)
        assert sorted(managed_entries) == sorted(canonical_entries), (
            "upgrade must leave exactly the canonical managed entries in the block"
        )
        assert len(managed_entries) == len(set(managed_entries)), "managed entries must not duplicate"
        for entry in removed_entries:
            assert entry in managed_entries, f"managed entry not restored: {entry}"
        assert upgraded.split(RUNTIME_IGNORE_END, 1)[1] == "\n" + "\n".join(user_lines) + "\n", (
            "user-owned lines after the managed block must stay byte-identical"
        )


def test_user_owned_ignore_untouched() -> None:
    user_text = "# my project ignores\nnode_modules/\ncoverage/\n"
    with tempfile.TemporaryDirectory() as tmp:
        project = Path(tmp)
        (project / ".code-flow").mkdir()
        ignore = project / ".code-flow" / ".gitignore"
        ignore.write_bytes(user_text.encode("utf-8"))
        before = ignore.read_bytes()

        result = _run_cli_init(CLI, project)
        assert result.returncode == 0, f"init failed:\n{result.stdout}{result.stderr}"
        assert ignore.read_bytes() == before, "a user-owned ignore file must not be rewritten"


def test_canonical_ignore_drift() -> None:
    node = _node_binary()
    with tempfile.TemporaryDirectory() as tmp:
        shadow = Path(tmp)
        shutil.copytree(ROOT / "src", shadow / "src")
        shutil.copy2(ROOT / "package.json", shadow / "package.json")
        (shadow / "tests").mkdir()
        suite = shadow / "tests" / "test_cli_merge_helpers.js"
        shutil.copy2(ROOT / "tests" / "test_cli_merge_helpers.js", suite)

        def run_guard() -> subprocess.CompletedProcess[str]:
            return subprocess.run(
                [node, str(suite)],
                cwd=shadow,
                capture_output=True,
                text=True,
                timeout=120,
                check=False,
            )

        baseline = run_guard()
        assert baseline.returncode == 0, (
            "canonical .gitignore and cli.js already drifted:\n"
            + baseline.stdout + baseline.stderr
        )

        # Simulate a release that adds a managed entry to the canonical template
        # without updating the embedded RUNTIME_GITIGNORE.
        drift_entry = ".drift-probe-cache.json"
        canonical = shadow / "src" / "core" / "code-flow" / ".gitignore"
        canonical.write_text(
            canonical.read_text().replace(
                RUNTIME_IGNORE_END, drift_entry + "\n" + RUNTIME_IGNORE_END
            )
        )
        drifted = run_guard()
        output = drifted.stdout + drifted.stderr
        assert drifted.returncode != 0, "drift guard must fail when canonical gains an entry"
        assert drift_entry in output, f"drift failure must name the missing entry:\n{output}"


def _validator_project(tmp_path: Path, validation: Optional[str]) -> Path:
    root = tmp_path / "project"
    (root / ".code-flow").mkdir(parents=True)
    (root / ".code-flow" / "config.yml").write_text(
        "quality_loop:\n  enabled: true\n"
        "spec_workflow:\n  schema_version: 1\n  enforcement: required\n"
        "path_mapping: {}\n",
        encoding="utf-8",
    )
    if validation is not None:
        (root / ".code-flow" / "validation.yml").write_text(validation, encoding="utf-8")
    return root


def _edit_event(root: Path, rel: str = "src/a.py", sid: str = "sid-1") -> None:
    import cf_log

    cf_log.append_event(str(root), "edit", {"file": rel, "tool": "Edit"}, sid)


def _heavy_validation(marker: Path) -> str:
    return yaml.safe_dump({
        "validators": [{
            "name": "HeavySuite",
            "trigger": "**/*.py",
            "command": f"python3 -c \"open({str(marker)!r}, 'a').write('x')\"",
            "timeout": 5000,
            "heavy": True,
            "on_fail": "fix",
        }],
    })


def test_validator_corrupt_consistent(tmp_path: Path) -> None:
    """[S-03] 同一份坏 YAML 在 validate / Stop / finish 三入口一致 block。"""
    from cf_stop_hook import build_stop_result
    from cf_task_runtime import _run_finish_validation
    from cf_validation import validate_files

    root = _validator_project(tmp_path, "validators: [")
    _edit_event(root)

    validated = validate_files(str(root), ["src/a.py"])
    stop = build_stop_result(str(root), "sid-1")
    issue, deferred_heavy = _run_finish_validation(str(root), ("src/a.py",))

    assert validated["decision"] == "block"
    assert validated["reason"] == "invalid_validation_config", validated
    assert stop.get("decision") == "block", stop
    assert "invalid_validation_config" in stop.get("reason", "")
    assert issue.startswith("finish validation blocked"), issue
    assert "invalid_validation_config" in issue
    assert deferred_heavy == 0


def test_validator_missing_policy(tmp_path: Path) -> None:
    """[S-04] 缺失/空配置保持既有策略：validate 阻断，finish 放行。"""
    from cf_task_runtime import _run_finish_validation
    from cf_validation import validate_files
    from cf_validators import load_validators

    root = _validator_project(tmp_path, None)
    assert load_validators(str(root)).state == "missing"
    validated = validate_files(str(root), ["src/a.py"])
    assert validated["decision"] == "block"
    assert validated["reason"] == "no_validators_configured"
    issue, deferred_heavy = _run_finish_validation(str(root), ("src/a.py",))
    assert issue == "", issue
    assert deferred_heavy == 0

    empty_root = _validator_project(tmp_path / "empty", "validators: []\n")
    assert load_validators(str(empty_root)).state == "empty"
    empty_validated = validate_files(str(empty_root), ["src/a.py"])
    assert empty_validated["decision"] == "block"
    assert empty_validated["reason"] == "no_validators_configured"
    empty_issue, empty_deferred = _run_finish_validation(str(empty_root), ("src/a.py",))
    assert empty_issue == "", empty_issue
    assert empty_deferred == 0


def test_heavy_deferral(tmp_path: Path) -> None:
    """[S-05] heavy validator 在 finish 默认延期且 deferred_heavy 计数为 1。"""
    from cf_task_runtime import _run_finish_validation

    marker = tmp_path / "heavy-ran"
    root = _validator_project(tmp_path / "deferred", _heavy_validation(marker))

    issue, deferred_heavy = _run_finish_validation(str(root), ("src/a.py",))

    assert issue == "", issue
    assert deferred_heavy == 1
    assert not marker.exists(), "heavy validator 默认不得在 finish 执行"


def test_stop_json_protocol(tmp_path: Path) -> None:
    """[E-02] Stop stdout 是单个 JSON 对象，decision/reason 明确。"""
    root = _validator_project(tmp_path, "validators: [")
    _edit_event(root)

    completed = subprocess.run(
        [sys.executable, str(SCRIPTS / "cf_stop_hook.py")],
        cwd=str(root),
        input=json.dumps({"session_id": "sid-1", "hook_event_name": "Stop"}),
        text=True,
        capture_output=True,
        timeout=30,
    )

    assert completed.returncode == 0, completed.stderr
    output = completed.stdout.strip()
    assert output, "blocked Stop must emit one JSON object"
    payload = json.loads(output)
    assert isinstance(payload, dict)
    assert payload["decision"] == "block"
    assert "invalid_validation_config" in payload["reason"]


def test_task_heading_edges() -> None:
    """[S-06] 行内示例、缩进/引用示例与围栏代码块中的标题都不参与解析。"""
    from cf_task_doc import parse_task_document

    text = (
        "# Tasks\n\n"
        "普通段落提到 ## TASK-999: inline example 不算标题\n"
        "  ## TASK-998: indented example\n"
        "```markdown\n"
        "## TASK-002: fenced with backticks\n"
        "```\n"
        "~~~\n"
        "## TASK-003: fenced with tildes\n"
        "~~~\n"
        "> ## TASK-997: quoted example\n"
        "## TASK-001: first real\n"
        "- **Status**: draft\n\n"
        "## TASK-004: second real\n"
        "- **Status**: done\n"
    )

    document = parse_task_document(text)

    assert [task.id for task in document.tasks] == ["TASK-001", "TASK-004"]
    assert [task.title for task in document.tasks] == ["first real", "second real"]


def test_duplicate_task_id(tmp_path: Path) -> None:
    """[S-07] 五个消费者对重复 TASK ID 一致拒绝，禁止择一。"""
    from cf_spec_context import SpecContext
    from cf_spec_gate import validate_plan_coverage
    from cf_spec_session import _task_section
    from cf_task_index import parse_task_file
    from cf_task_plan import parse_plan_tasks
    from cf_workflow_service import WorkflowError, read_task_section

    text = (
        "## TASK-001: first\n"
        "- **Status**: draft\n\n"
        "## TASK-001: second\n"
        "- **Status**: done\n"
    )
    task_file = tmp_path / "tasks.md"
    task_file.write_text(text, encoding="utf-8")

    with pytest.raises(WorkflowError) as workflow_error:
        read_task_section(str(task_file), "TASK-001")
    assert workflow_error.value.code == "duplicate_task_id"

    with pytest.raises(ValueError, match="duplicate_task_id"):
        _task_section(text, "TASK-001")

    with pytest.raises(ValueError, match="duplicate_task_id"):
        parse_task_file(str(task_file))

    with pytest.raises(ValueError, match="duplicate_task_id"):
        parse_plan_tasks(str(task_file))

    context = SpecContext(
        version=1, task="duplicate", enforcement="required", updated_at="",
        sources=(), bindings=(),
    )
    gate = validate_plan_coverage(context, str(task_file))
    assert gate.decision == "block"
    assert [issue.code for issue in gate.errors] == ["duplicate_task_id"]


def test_missing_status_draft() -> None:
    """[S-08] 缺 Status 行时投影为 draft，未知状态保留原文。"""
    from cf_task_doc import parse_task_document

    text = (
        "## TASK-001: no status\n"
        "- **Depends**: TASK-002\n\n"
        "## TASK-002: finished\n"
        "- **Status**: done\n"
    )

    document = parse_task_document(text)

    assert [task.status for task in document.tasks] == ["draft", "done"]
    assert document.tasks[0].depends == ("TASK-002",)


def test_task_doc_boundaries() -> None:
    """[B-02] CRLF 文档正常解析；无 TASK 段落抛 task_document_empty。"""
    from cf_task_doc import TaskDocumentError, parse_task_document

    crlf = (
        "## TASK-001: crlf task\r\n"
        "- **Status**: done\r\n"
        "- **Depends**: TASK-002\r\n"
        "\r\n"
        "## TASK-002: dependency\r\n"
        "- **Status**: draft\r\n"
    )

    document = parse_task_document(crlf, source="crlf.md")

    assert [(task.id, task.status) for task in document.tasks] == [
        ("TASK-001", "done"),
        ("TASK-002", "draft"),
    ]
    assert document.tasks[0].depends == ("TASK-002",)
    assert document.source == "crlf.md"

    for empty in ("", "# Tasks\n\nNo sections here.\n"):
        with pytest.raises(TaskDocumentError) as error:
            parse_task_document(empty)
        assert error.value.code == "task_document_empty"


def test_task_flow_consistency() -> None:
    pytest.skip("plan skeleton: implemented in TASK-005")


def test_plan_gate_duplicate() -> None:
    pytest.skip("plan skeleton: implemented in TASK-005")


def _git_repo_with_changes(root: Path) -> None:
    def git(*arguments: str) -> None:
        subprocess.run(("git", *arguments), cwd=str(root), text=True, capture_output=True,
                       check=True, timeout=30)

    git("init", "-q")
    git("config", "user.email", "test@example.com")
    git("config", "user.name", "Test")
    (root / "tracked.txt").write_text("one\n", encoding="utf-8")
    git("add", "-A")
    git("commit", "-qm", "init")
    (root / "tracked.txt").write_text("two\n", encoding="utf-8")
    (root / "untracked.txt").write_text("new\n", encoding="utf-8")


def test_git_primitive_parity(tmp_path: Path) -> None:
    """[S-10] 真实 git 仓库：spec_context / evidence_store / task_parallel 变更集合一致。"""
    from cf_evidence_store import _run_git
    from cf_git import changed_entries, changed_files, run_git
    from cf_spec_context import _git_changes
    from cf_task_parallel import _status_paths

    root = tmp_path / "repo"
    root.mkdir()
    _git_repo_with_changes(root)
    expected = {"tracked.txt", "untracked.txt"}

    spec_changes = _git_changes(str(root))
    assert set(spec_changes) == expected
    assert spec_changes["tracked.txt"] == "modified"
    assert spec_changes["untracked.txt"] == "untracked"

    parallel_changes = set(_status_paths(root))
    assert parallel_changes == expected

    raw = _run_git(root, ("status", "--porcelain=v1", "-z", "--untracked-files=all"))
    assert raw is not None
    evidence_changes = {record[3:] for record in raw.split("\0") if record}
    assert evidence_changes == expected

    assert set(changed_files(str(root))) == expected
    assert set(changed_entries(str(root))) == expected
    toplevel = run_git(str(root), ("rev-parse", "--show-toplevel")).strip()
    assert Path(toplevel).resolve() == root.resolve()


def test_atomic_write(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """[S-11] 真实文件系统：注入异常后目标文件保留原内容，临时文件被清理。"""
    import cf_fs

    target = tmp_path / "state.json"
    original = '{"ok": true}\n'
    cf_fs.write_text(str(target), original)

    def fail_replace(source: str, destination: str) -> None:
        raise OSError(f"injected replace failure: {source} -> {destination}")

    monkeypatch.setattr(cf_fs.os, "replace", fail_replace)
    with pytest.raises(OSError, match="injected replace failure"):
        cf_fs.atomic_write_text(str(target), '{"ok": false}\n')

    assert target.read_text(encoding="utf-8") == original
    assert list(tmp_path.glob(f".{target.name}.*.tmp")) == []

    monkeypatch.undo()
    cf_fs.atomic_write_text(str(target), '{"ok": false}\n')
    assert target.read_text(encoding="utf-8") == '{"ok": false}\n'


def test_markdown_primitives(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.syspath_prepend(str(SCRIPTS))
    from cf_markdown import parse_frontmatter, table_columns

    # No frontmatter → empty metadata, body unchanged.
    meta, body = parse_frontmatter("# Title\n\nplain markdown\n")
    assert meta == {}
    assert body == "# Title\n\nplain markdown\n"

    # Frontmatter is split from the body.
    meta, body = parse_frontmatter("---\ndescription: 示例\n---\nbody\n")
    assert meta == {"description": "示例"}
    assert body == "body\n"

    # No header row → empty column index.
    assert table_columns(["no table"]) == {}
    assert table_columns(["| --- | --- |"]) == {}

    # Column order changes are resolved by header text, not position.
    columns = table_columns(["| 测试层级 | 执行命令 | 场景ID |", "| --- | --- | --- |"])
    assert columns == {"测试层级": 0, "执行命令": 1, "场景ID": 2}
    reordered = table_columns(["| 场景ID | 执行命令 | 测试层级 |", "| --- | --- | --- |"])
    assert reordered["执行命令"] == 1
    assert reordered["测试层级"] == 2


def test_legacy_removal() -> None:
    pytest.skip("plan skeleton: implemented in TASK-008")


def test_verify_plan_reads() -> None:
    pytest.skip("plan skeleton: implemented in TASK-009")


def test_snapshot_drift() -> None:
    pytest.skip("plan skeleton: implemented in TASK-009")


def test_four_platform_install() -> None:
    pytest.skip("plan skeleton: implemented in TASK-011")


def test_package_upgrade_cleanup() -> None:
    pytest.skip("plan skeleton: implemented in TASK-011")


def test_canonical_parity() -> None:
    pytest.skip("plan skeleton: implemented in TASK-010")


def test_migration_rollback() -> None:
    pytest.skip("plan skeleton: implemented in TASK-011")
