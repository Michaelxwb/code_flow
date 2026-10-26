"""Architecture guards and plan skeletons for runtime consolidation.

The three implemented tests are the TASK-001 acceptance contract (S-15, S-16,
B-03). The remaining skeletons are registered during plan and replaced by their
implementing tasks; no production import belongs at module scope so collection
stays independent of unimplemented modules.
"""
from __future__ import annotations

import ast
from pathlib import Path
from typing import Iterable

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "src" / "core" / "code-flow" / "scripts"

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
    "cf_injection": 2,
    "cf_log": 0,
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
    "cf_workflow_service": 2,
    "cf_workflow_transaction": 2,
    "cf_worktree_env": 0,
}

# (importer, imported module, batch after which the edge must be gone)
DEPENDENCY_EDGE_ALLOWLIST = frozenset({
    ("cf_acceptance_evidence", "cf_spec_context", 4),
    ("cf_acceptance_schema", "cf_acceptance_manifest", 4),
    ("cf_context_cache", "cf_spec_context", 4),
    ("cf_evidence_store", "cf_spec_context", 4),
    ("cf_plan_quality", "cf_acceptance_manifest", 4),
    ("cf_plan_quality", "cf_spec_context", 4),
    ("cf_plan_quality", "cf_spec_gate", 6),
    ("cf_scenarios", "cf_acceptance_manifest", 4),
    ("cf_task_parallel", "cf_task_workflow", 6),
    ("cf_task_runtime", "cf_stop_hook", 2),
    ("cf_task_runtime", "cf_validation", 2),
})

# (importer, source module, private symbol, batch after which it must be gone)
PRIVATE_SYMBOL_ALLOWLIST = frozenset({
    ("cf_acceptance_evidence", "cf_spec_context", "_atomic_text", 4),
    ("cf_acceptance_manifest", "cf_scenarios", "_frontmatter", 4),
    ("cf_acceptance_registration", "cf_check_registration", "_collected", 6),
    ("cf_acceptance_registration", "cf_check_registration", "_execution_argv", 6),
    ("cf_acceptance_registration", "cf_check_registration", "_pytest_markers", 6),
    ("cf_acceptance_registration", "cf_check_registration", "_registration_issues", 6),
    ("cf_acceptance_registration", "cf_check_registration", "_requirements", 6),
    ("cf_checks", "cf_core", "_FRONTMATTER_RE", 4),
    ("cf_codex_hook", "cf_core", "_log", 4),
    ("cf_context_cache", "cf_core", "_log", 4),
    ("cf_injection", "cf_core", "_log", 4),
    ("cf_opencode_event", "cf_core", "_log", 4),
    ("cf_post_hook", "cf_core", "_log", 4),
    ("cf_pre_tool_hook", "cf_core", "_log", 4),
    ("cf_spec_router", "cf_core", "_log", 4),
    ("cf_stop_hook", "cf_acceptance_manifest", "_column_indexes", 4),
    ("cf_stop_hook", "cf_acceptance_manifest", "_column_value", 4),
    ("cf_stop_hook", "cf_acceptance_manifest", "_kind", 4),
    ("cf_stop_hook", "cf_acceptance_manifest", "_parse_exec", 4),
    ("cf_stop_hook", "cf_core", "_log", 4),
    ("cf_task_parallel", "cf_task_merge", "_check_conflicts", 6),
    ("cf_task_parallel", "cf_task_runtime", "_task_scope_specs", 6),
    ("cf_task_runtime", "cf_spec_session", "_refs", 3),
    ("cf_task_runtime", "cf_spec_session", "_task_section", 3),
    ("cf_task_workflow", "cf_acceptance_runner", "_accepted_risk", 6),
    ("cf_task_workflow", "cf_acceptance_runner", "_owned", 6),
    ("cf_task_workflow", "cf_acceptance_runner", "_select_profile", 6),
    ("cf_task_workflow", "cf_spec_context", "_git_changes", 4),
    ("cf_task_workflow", "cf_spec_context", "_run_git", 4),
    ("cf_task_workflow", "cf_spec_verify", "_git_tracked_files", 4),
    ("cf_task_workflow", "cf_task_runtime", "_NON_EXECUTION_ERRORS", 6),
    ("cf_task_workflow", "cf_task_runtime", "_apply_evidence", 6),
    ("cf_task_workflow", "cf_task_runtime", "_evidence_data", 6),
    ("cf_task_workflow", "cf_validation", "_validators", 2),
    ("cf_task_workflow", "cf_workflow_service", "_require_marker_task", 7),
    ("cf_task_workflow", "cf_workflow_service", "_sync_markdown", 7),
    ("cf_user_prompt_hook", "cf_core", "_log", 4),
    ("cf_validation", "cf_spec_context", "_git_changes", 4),
    ("cf_workflow_service", "cf_spec_context", "_active_data", 7),
    ("cf_workflow_service", "cf_spec_context", "_atomic_text", 4),
    ("cf_workflow_service", "cf_spec_context", "_new_active", 7),
    ("cf_workflow_transaction", "cf_spec_context", "_acquire_active_lock", 7),
    ("cf_workflow_transaction", "cf_spec_context", "_atomic_text", 4),
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


def test_packed_install_ignore() -> None:
    pytest.skip("plan skeleton: implemented in TASK-002")


def test_upgrade_preserves_user_ignore() -> None:
    pytest.skip("plan skeleton: implemented in TASK-002")


def test_user_owned_ignore_untouched() -> None:
    pytest.skip("plan skeleton: implemented in TASK-002")


def test_canonical_ignore_drift() -> None:
    pytest.skip("plan skeleton: implemented in TASK-002")


def test_validator_corrupt_consistent() -> None:
    pytest.skip("plan skeleton: implemented in TASK-003")


def test_validator_missing_policy() -> None:
    pytest.skip("plan skeleton: implemented in TASK-003")


def test_heavy_deferral() -> None:
    pytest.skip("plan skeleton: implemented in TASK-003")


def test_stop_json_protocol() -> None:
    pytest.skip("plan skeleton: implemented in TASK-003")


def test_task_heading_edges() -> None:
    pytest.skip("plan skeleton: implemented in TASK-004")


def test_duplicate_task_id() -> None:
    pytest.skip("plan skeleton: implemented in TASK-004")


def test_missing_status_draft() -> None:
    pytest.skip("plan skeleton: implemented in TASK-004")


def test_task_doc_boundaries() -> None:
    pytest.skip("plan skeleton: implemented in TASK-004")


def test_task_flow_consistency() -> None:
    pytest.skip("plan skeleton: implemented in TASK-005")


def test_plan_gate_duplicate() -> None:
    pytest.skip("plan skeleton: implemented in TASK-005")


def test_git_primitive_parity() -> None:
    pytest.skip("plan skeleton: implemented in TASK-006")


def test_atomic_write() -> None:
    pytest.skip("plan skeleton: implemented in TASK-006")


def test_markdown_primitives() -> None:
    pytest.skip("plan skeleton: implemented in TASK-007")


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
