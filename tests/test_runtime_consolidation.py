"""Architecture guards and plan skeletons for runtime consolidation.

The three implemented tests are the TASK-001 acceptance contract (S-15, S-16,
B-03). The remaining skeletons are registered during plan and replaced by their
implementing tasks; no production import belongs at module scope so collection
stays independent of unimplemented modules.
"""
from __future__ import annotations

import ast
import hashlib
import json
import os
import re
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
DEPLOYED_SCRIPTS = ROOT / ".code-flow" / "scripts"
CLI = ROOT / "src" / "cli.js"
CANONICAL_IGNORE = ROOT / "src" / "core" / "code-flow" / ".gitignore"
RUNTIME_RESOURCES = ROOT / "src" / "core" / "code-flow" / "scripts" / "runtime-resources.json"
DEPLOYED_RESOURCES = ROOT / ".code-flow" / "scripts" / "runtime-resources.json"
RUNTIME_IGNORE_START = "# >>> code-flow:runtime schema=1"
RUNTIME_IGNORE_END = "# <<< code-flow:runtime schema=1"
RUNTIME_IGNORE_ENTRIES = 20
sys.path.insert(0, str(SCRIPTS))

CURRENT_BATCH = 7

LAYERS: dict[str, int] = {
    "cf_acceptance_evidence": 1,
    "cf_acceptance_manifest": 2,
    "cf_acceptance_manifest_core": 1,
    "cf_acceptance_plan": 1,
    "cf_acceptance_registration": 2,
    "cf_acceptance_risk": 1,
    "cf_acceptance_runner": 2,
    "cf_acceptance_schema": 1,
    "cf_acceptance_selection": 1,
    "cf_active_task": 1,
    "cf_audit": 3,
    "cf_check_inputs": 1,
    "cf_check_registration": 1,
    "cf_checks": 1,
    "cf_codex_hook": 3,
    "cf_context_cache": 1,
    "cf_context_refresh": 1,
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
    "cf_requirement_verification": 2,
    "cf_runtime_install": 0,
    "cf_scenario_source": 1,
    "cf_scan": 3,
    "cf_scenario_quality": 1,
    "cf_scenarios": 1,
    "cf_session_state": 0,
    "cf_spec_context": 2,
    "cf_spec_context_model": 1,
    "cf_spec_gate": 2,
    "cf_spec_metadata": 1,
    "cf_spec_migrate": 3,
    "cf_spec_resolver": 1,
    "cf_spec_router": 2,
    "cf_spec_session": 2,
    "cf_spec_verify": 2,
    "cf_stats": 3,
    "cf_stage_gate": 1,
    "cf_stop_guard": 0,
    "cf_stop_hook": 3,
    "cf_sync": 3,
    "cf_task_doc": 1,
    "cf_task_index": 1,
    "cf_task_merge": 2,
    "cf_task_parallel": 2,
    "cf_task_plan": 1,
    "cf_task_projection": 1,
    "cf_task_runtime": 2,
    "cf_task_state": 0,
    "cf_task_workflow": 3,
    "cf_traceability": 3,
    "cf_user_prompt_hook": 3,
    "cf_validation": 3,
    "cf_validation_service": 1,
    "cf_validators": 1,
    "cf_workflow_service": 2,
    "cf_workflow_transaction": 2,
    "cf_worktree_env": 0,
}

# (importer, imported module, batch after which the edge must be gone)
DEPENDENCY_EDGE_ALLOWLIST = frozenset({
})

# (importer, source module, private symbol, batch after which it must be gone)
PRIVATE_SYMBOL_ALLOWLIST = frozenset({
})


def _rebound_names(tree: ast.Module) -> set[str]:
    rebound: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
            rebound.add(node.id)
        elif isinstance(node, ast.arg):
            rebound.add(node.arg)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            rebound.add(node.name)
        elif isinstance(node, ast.ExceptHandler) and node.name:
            rebound.add(node.name)
        elif (isinstance(node, ast.Attribute) and node.attr == "TYPE_CHECKING"
              and isinstance(node.ctx, (ast.Store, ast.Del)) and isinstance(node.value, ast.Name)):
            rebound.add(node.value.id)
        elif isinstance(node, ast.Import):
            rebound.update(item.asname or item.name.split(".")[0] for item in node.names if item.name != "typing")
        elif isinstance(node, ast.ImportFrom):
            rebound.update(item.asname or item.name for item in node.names
                           if node.module != "typing" or item.name != "TYPE_CHECKING")
    return rebound


def _typing_aliases(tree: ast.Module) -> tuple[set[str], set[str]]:
    names: set[str] = set()
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(item.asname or item.name for item in node.names if item.name == "typing")
        elif isinstance(node, ast.ImportFrom) and node.module == "typing":
            names.update(item.asname or item.name for item in node.names if item.name == "TYPE_CHECKING")
    rebound = _rebound_names(tree)
    return (set(), set()) if "*" in rebound else (names - rebound, modules - rebound)


def _runtime_truth(test: ast.expr, names: set[str], modules: set[str]) -> Optional[bool]:
    if isinstance(test, ast.Constant) and isinstance(test.value, bool):
        return test.value
    if isinstance(test, ast.Name) and test.id in names:
        return False
    if (isinstance(test, ast.Attribute) and test.attr == "TYPE_CHECKING"
            and isinstance(test.value, ast.Name) and test.value.id in modules):
        return False
    if isinstance(test, ast.UnaryOp) and isinstance(test.op, ast.Not):
        value = _runtime_truth(test.operand, names, modules)
        return None if value is None else not value
    if isinstance(test, ast.BoolOp):
        values = [_runtime_truth(item, names, modules) for item in test.values]
        if isinstance(test.op, ast.And):
            return False if False in values else (True if all(v is True for v in values) else None)
        if isinstance(test.op, ast.Or):
            return True if True in values else (False if all(v is False for v in values) else None)
    return None


def _type_only_nodes(tree: ast.Module) -> frozenset[int]:
    """Skip branches proven unreachable from typing constants or literal booleans.

    Unimported, rebound and otherwise ambiguous names are scanned on both sides.
    """
    names, modules = _typing_aliases(tree)
    skipped: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.If):
            continue
        truth = _runtime_truth(node.test, names, modules)
        if truth is None:
            continue
        for statement in node.orelse if truth else node.body:
            skipped.update(id(child) for child in ast.walk(statement))
    return frozenset(skipped)


def _script_files(scripts: Path) -> list[Path]:
    return sorted(path for path in scripts.rglob("*.py") if path.name != "__init__.py")


def _is_entry_shim(path: Path, implementation: Path, scripts: Path) -> bool:
    if path.parent != scripts or implementation.relative_to(scripts).parts[0] != "codeflow":
        return False
    text = path.read_text(encoding="utf-8")
    if len(text.splitlines()) > 15:
        return False
    tree = ast.parse(text)
    if any(isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) for node in ast.walk(tree)):
        return False
    dotted = ".".join(implementation.relative_to(scripts).with_suffix("").parts)
    package, _, stem = dotted.rpartition(".")
    aliases = {item.asname or item.name for node in ast.walk(tree)
               if isinstance(node, ast.ImportFrom) and node.module == package
               for item in node.names if item.name == stem}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign) or not isinstance(node.value, ast.Name) or node.value.id not in aliases:
            continue
        for target in node.targets:
            if (isinstance(target, ast.Subscript) and isinstance(target.slice, ast.Name)
                    and target.slice.id == "__name__" and isinstance(target.value, ast.Attribute)
                    and target.value.attr == "modules" and isinstance(target.value.value, ast.Name)
                    and target.value.value.id == "sys"):
                return True
    return False


def _script_modules(scripts: Path) -> frozenset[str]:
    grouped: dict[str, list[Path]] = {}
    for path in _script_files(scripts):
        grouped.setdefault(path.stem, []).append(path)
    for stem, paths in grouped.items():
        if len(paths) <= 1:
            continue
        implementations = [path for path in paths if path.parent != scripts]
        if len(implementations) != 1 or any(
            not _is_entry_shim(path, implementations[0], scripts)
            for path in paths if path != implementations[0]
        ):
            raise ValueError(f"ambiguous module stem {stem}: {', '.join(map(str, paths))}")
    return frozenset(grouped)


def _import_target(name: str, modules: frozenset[str]) -> Optional[str]:
    if name in modules:
        return name
    if name.startswith("codeflow.") and name.rsplit(".", 1)[-1] in modules:
        return name.rsplit(".", 1)[-1]
    return None


def _from_targets(node: ast.ImportFrom, modules: frozenset[str]) -> set[str]:
    target = _import_target(node.module or "", modules)
    if target:
        return {target}
    if node.level or node.module == "codeflow" or (node.module or "").startswith("codeflow."):
        return {target for item in node.names if (target := _import_target(item.name, modules))}
    return set()


def _dynamic_aliases(tree: ast.Module, skip: frozenset[int]) -> tuple[set[str], set[str], set[str]]:
    imports: set[str] = set()
    functions: set[str] = set()
    builtins = {"__import__"}
    for node in ast.walk(tree):
        if id(node) in skip:
            continue
        if isinstance(node, ast.Import):
            imports.update(item.asname or item.name for item in node.names if item.name == "importlib")
        elif isinstance(node, ast.ImportFrom) and node.module == "importlib":
            functions.update(item.asname or item.name for item in node.names if item.name == "import_module")
        elif isinstance(node, ast.ImportFrom) and node.module == "builtins":
            builtins.update(item.asname or item.name for item in node.names if item.name == "__import__")
    return imports, functions, builtins


def _dynamic_target(
    node: ast.Call, modules: frozenset[str], imports: set[str], functions: set[str], builtins: set[str]
) -> Optional[str]:
    """Resolve direct importlib/builtin calls; fail on nonliteral module names."""
    func = node.func
    dynamic = isinstance(func, ast.Name) and func.id in functions | builtins
    dynamic |= (isinstance(func, ast.Attribute) and func.attr == "import_module"
                and isinstance(func.value, ast.Name) and func.value.id in imports)
    if not dynamic:
        return None
    name_arg = node.args[0] if node.args else next((kw.value for kw in node.keywords if kw.arg == "name"), None)
    if not isinstance(name_arg, ast.Constant) or not isinstance(name_arg.value, str):
        raise ValueError(f"dynamic import at line {node.lineno} must use a literal module name")
    name = name_arg.value
    return _import_target(name.rsplit(".", 1)[-1] if name.startswith(".") else name, modules)


def _builtin_fromlist(node: ast.Call) -> tuple[str, ...]:
    argument = node.args[3] if len(node.args) > 3 else next(
        (kw.value for kw in node.keywords if kw.arg == "fromlist"), None
    )
    if argument is None or (isinstance(argument, ast.Constant) and argument.value is None):
        return ()
    if not isinstance(argument, (ast.List, ast.Tuple)):
        raise ValueError(f"dynamic import at line {node.lineno} must use a literal fromlist")
    if any(not isinstance(item, ast.Constant) or not isinstance(item.value, str) or item.value == "*"
           for item in argument.elts):
        raise ValueError(f"dynamic import at line {node.lineno} must use a literal fromlist")
    return tuple(item.value for item in argument.elts if isinstance(item, ast.Constant))


def _dynamic_targets(
    node: ast.Call, modules: frozenset[str], imports: set[str], functions: set[str], builtins: set[str]
) -> set[str]:
    target = _dynamic_target(node, modules, imports, functions, builtins)
    targets = {target} if target else set()
    if isinstance(node.func, ast.Name) and node.func.id in builtins:
        name_arg = node.args[0] if node.args else next(kw.value for kw in node.keywords if kw.arg == "name")
        assert isinstance(name_arg, ast.Constant) and isinstance(name_arg.value, str)
        for item in _builtin_fromlist(node):
            member = _import_target(f"{name_arg.value}.{item}", modules)
            if member:
                targets.add(member)
    return targets


def _import_edges(path: Path, modules: frozenset[str]) -> set[tuple[str, str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    skip = _type_only_nodes(tree)
    imports, functions, builtins = _dynamic_aliases(tree, skip)
    edges: set[tuple[str, str]] = set()
    for node in ast.walk(tree):
        if id(node) in skip:
            continue
        targets: set[str] = set()
        if isinstance(node, ast.Import):
            targets = {target for item in node.names if (target := _import_target(item.name, modules))}
        elif isinstance(node, ast.ImportFrom):
            targets = _from_targets(node, modules)
        elif isinstance(node, ast.Call):
            targets = _dynamic_targets(node, modules, imports, functions, builtins)
        edges.update((path.stem, target) for target in targets if target != path.stem)
    return edges


def _module_aliases(tree: ast.Module, modules: frozenset[str], skip: frozenset[int]) -> dict[str, set[str]]:
    aliases: dict[str, set[str]] = {}
    for node in ast.walk(tree):
        if id(node) in skip:
            continue
        if isinstance(node, ast.Import):
            for item in node.names:
                target = _import_target(item.name, modules)
                if target:
                    aliases.setdefault(item.asname or item.name, set()).add(target)
        elif isinstance(node, ast.ImportFrom) and not _import_target(node.module or "", modules):
            if node.level or node.module == "codeflow" or (node.module or "").startswith("codeflow."):
                for item in node.names:
                    target = _import_target(item.name, modules)
                    if target:
                        aliases.setdefault(item.asname or item.name, set()).add(target)
    imports, functions, builtins = _dynamic_aliases(tree, skip)
    for node in ast.walk(tree):
        if id(node) in skip or not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        if not isinstance(node.value, ast.Call):
            continue
        target = _dynamic_target(node.value, modules, imports, functions, builtins)
        if isinstance(node.value.func, ast.Name) and node.value.func.id in builtins:
            first = node.value.args[0] if node.value.args else next(
                (kw.value for kw in node.value.keywords if kw.arg == "name"), None
            )
            if isinstance(first, ast.Constant) and isinstance(first.value, str) and "." in first.value:
                target = target if _builtin_fromlist(node.value) else None
        if target:
            destinations = node.targets if isinstance(node, ast.Assign) else [node.target]
            for destination in destinations:
                if isinstance(destination, ast.Name):
                    aliases.setdefault(destination.id, set()).add(target)
    return aliases


def _dotted_name(node: ast.expr) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return f"{_dotted_name(node.value)}.{node.attr}"
    return ""


def _private_imports(path: Path, modules: frozenset[str]) -> set[tuple[str, str, str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    skip = _type_only_nodes(tree)
    aliases = _module_aliases(tree, modules, skip)
    found: set[tuple[str, str, str]] = set()
    for node in ast.walk(tree):
        if id(node) in skip:
            continue
        if isinstance(node, ast.ImportFrom):
            targets = _from_targets(node, modules) - {path.stem}
            found.update((path.stem, target, item.name) for target in targets for item in node.names
                         if item.name.startswith("_") and not item.name.startswith("__"))
        elif isinstance(node, ast.Attribute) and node.attr.startswith("_") and not node.attr.startswith("__"):
            targets = aliases.get(_dotted_name(node.value), set()) - {path.stem}
            found.update((path.stem, target, node.attr) for target in targets)
    return found


def _layer_violations(edges: Iterable[tuple[str, str]]) -> set[tuple[str, str]]:
    return {(source, target) for source, target in edges if LAYERS[source] < LAYERS[target]}


def test_type_checking_rebinding_is_conservative(tmp_path: Path) -> None:
    module = tmp_path / "cf_actor.py"
    cases = (
        ("TYPE_CHECKING = True", "TYPE_CHECKING"),
        ("from typing import TYPE_CHECKING\nTYPE_CHECKING = True", "TYPE_CHECKING"),
        ("import typing as t\nt = object()", "t.TYPE_CHECKING"),
        ("import typing as t\nt.TYPE_CHECKING = True", "t.TYPE_CHECKING"),
        ("from typing import TYPE_CHECKING\ndef f(TYPE_CHECKING):\n    pass", "TYPE_CHECKING"),
    )
    for setup, condition in cases:
        module.write_text(f"{setup}\nif {condition}:\n    from cf_other import live\n", encoding="utf-8")
        assert _import_edges(module, frozenset({"cf_actor", "cf_other"})) == {("cf_actor", "cf_other")}


def _expired(entries: Iterable[tuple[object, ...]], current_batch: int) -> list[tuple[object, ...]]:
    return sorted(entry for entry in entries
                  if isinstance(entry[-1], int) and entry[-1] <= current_batch)


_REGEX_CALLS = frozenset({
    "compile", "match", "search", "finditer", "findall", "sub", "subn", "fullmatch",
})
_TASK_HEADING_PATTERN = re.compile(r"\^##\s*\(?TASK-")


def _task_heading_regexes(path: Path) -> list[tuple[int, str]]:
    """Regex literals that anchor a TASK heading (`^## TASK-...`)."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not node.args:
            continue
        func = node.func
        if isinstance(func, ast.Attribute):
            if not (isinstance(func.value, ast.Name) and func.value.id == "re"):
                continue
            name = func.attr
        elif isinstance(func, ast.Name):
            name = func.id
        else:
            continue
        if name not in _REGEX_CALLS:
            continue
        first = node.args[0]
        if (isinstance(first, ast.Constant) and isinstance(first.value, str)
                and _TASK_HEADING_PATTERN.search(first.value)):
            found.append((node.lineno, first.value))
    return found


def test_dependency_direction() -> None:
    modules = _script_modules(SCRIPTS)
    missing = sorted(modules - LAYERS.keys())
    assert not missing, f"add layer mapping for: {missing}"
    edges: set[tuple[str, str]] = set()
    for path in _script_files(SCRIPTS):
        edges |= _import_edges(path, modules)
    violations = _layer_violations(edges)
    allowed = {(source, target) for source, target, _ in DEPENDENCY_EDGE_ALLOWLIST}
    unexpected = sorted(violations - allowed)
    stale = sorted(allowed - violations)
    assert not unexpected, f"new reverse dependencies: {unexpected}"
    assert not stale, f"allowlist entries no longer violate; remove them: {stale}"
    synthetic = {("cf_log", "cf_spec_context")}
    assert _layer_violations(synthetic) == synthetic, "guard must flag L0 -> L2 imports"


_CLI_MANIFEST_IMPORT = re.compile(
    r"(?m)^\s*(?:from\s+codeflow\.cli\.cf_acceptance_manifest\b"
    r"|from\s+codeflow\.cli\s+import\s+[^\n]*\bcf_acceptance_manifest\b)"
)


def test_acceptance_manifest_consumers_use_low_level_owner() -> None:
    """[S-03] schema/plan quality/scenarios 只依赖 acceptance 低层 owner，不反向导入 CLI 入口。"""
    consumers = (
        "codeflow/acceptance/cf_acceptance_schema.py",
        "codeflow/acceptance/cf_plan_quality.py",
        "codeflow/cli/cf_scenarios.py",
    )
    offenders = [
        f"{scripts.name}/{relative}"
        for scripts in (SCRIPTS, DEPLOYED_SCRIPTS)
        for relative in consumers
        if _CLI_MANIFEST_IMPORT.search((scripts / relative).read_text(encoding="utf-8"))
    ]
    assert not offenders, f"acceptance consumers must import the low-level owner: {offenders}"


def test_private_symbol_guard() -> None:
    modules = _script_modules(SCRIPTS)
    actual: set[tuple[str, str, str]] = set()
    for path in _script_files(SCRIPTS):
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


def _strongly_connected_sizes(edges: set[tuple[str, str]]) -> list[int]:
    graph: dict[str, set[str]] = {}
    for source, target in edges:
        graph.setdefault(source, set()).add(target)
        graph.setdefault(target, set())
    index: dict[str, int] = {}
    low: dict[str, int] = {}
    stack: list[str] = []
    on_stack: set[str] = set()
    sizes: list[int] = []
    counter = [0]

    def visit(node: str) -> None:
        index[node] = low[node] = counter[0]
        counter[0] += 1
        stack.append(node)
        on_stack.add(node)
        for target in graph.get(node, ()):
            if target not in index:
                visit(target)
                low[node] = min(low[node], low[target])
            elif target in on_stack:
                low[node] = min(low[node], index[target])
        if low[node] != index[node]:
            return
        size = 0
        while True:
            member = stack.pop()
            on_stack.discard(member)
            size += 1
            if member == node:
                break
        if size > 1:
            sizes.append(size)

    for node in graph:
        if node not in index:
            visit(node)
    return sizes


def test_scc_budget() -> None:
    """[S-10] Any multi-module import cycle violates the final ratchet."""
    modules = _script_modules(SCRIPTS)
    edges: set[tuple[str, str]] = set()
    for path in _script_files(SCRIPTS):
        edges |= _import_edges(path, modules)
    sizes = _strongly_connected_sizes(edges)
    assert not sizes, f"dependency SCCs must be empty: {sorted(sizes, reverse=True)}"
    synthetic = {("cf_context_cache", "cf_spec_context")}
    assert _layer_violations(synthetic) == synthetic, "reintroducing a batch-4 edge must fail"


def test_task_parser_single_source() -> None:
    """[TASK-005] `^## TASK-` 正则只允许出现在 cf_task_doc.py（双副本）。"""
    owners = {
        scripts / "codeflow" / "task" / "cf_task_doc.py" for scripts in (SCRIPTS, DEPLOYED_SCRIPTS)
    }
    offenders: list[str] = []
    for scripts in (SCRIPTS, DEPLOYED_SCRIPTS):
        for path in _script_files(scripts):
            if path in owners:
                continue
            for lineno, pattern in _task_heading_regexes(path):
                offenders.append(f"{path.relative_to(ROOT)}:{lineno}: {pattern}")
    assert not offenders, (
        "TASK headings must be parsed only by cf_task_doc:\n" + "\n".join(offenders)
    )
    for owner in owners:
        assert _task_heading_regexes(owner), f"{owner.relative_to(ROOT)} must own the heading regex"


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


def _runtime_ignore_declaration() -> dict[str, object]:
    data = json.loads(RUNTIME_RESOURCES.read_text(encoding="utf-8"))
    block = data["gitignore"]
    assert isinstance(block, dict)
    return block


def test_runtime_ignore_single_source() -> None:
    """[S-08] One packaged declaration drives CLI, migrator, and source template."""
    block = _runtime_ignore_declaration()
    assert block["start"] == RUNTIME_IGNORE_START
    assert block["end"] == RUNTIME_IGNORE_END
    entries = block["entries"]
    assert isinstance(entries, list)
    assert len(entries) == RUNTIME_IGNORE_ENTRIES
    assert len(entries) == len(set(entries)), "runtime ignore entries must not repeat"

    canonical = CANONICAL_IGNORE.read_text(encoding="utf-8")
    assert canonical == "\n".join([RUNTIME_IGNORE_START, *entries, RUNTIME_IGNORE_END]) + "\n", (
        "src/core/code-flow/.gitignore must be derived from the declaration"
    )
    assert DEPLOYED_RESOURCES.is_file(), "deployed runtime must ship the declaration"
    assert DEPLOYED_RESOURCES.read_bytes() == RUNTIME_RESOURCES.read_bytes(), (
        "canonical and deployed declarations must stay identical"
    )

    cli = CLI.read_text(encoding="utf-8")
    assert "runtime-resources.json" in cli, "cli.js must read the runtime declaration"
    for entry in entries:
        assert f"'{entry}'," not in cli, f"cli.js must not embed runtime entry: {entry}"

    for scripts in (SCRIPTS, DEPLOYED_SCRIPTS):
        migrator = scripts / "codeflow" / "spec" / "cf_spec_migrate.py"
        text = migrator.read_text(encoding="utf-8")
        assert "runtime-resources.json" in text, f"{migrator.relative_to(ROOT)} must read the declaration"
        assert '".active-task.json\\n"' not in text, (
            f"{migrator.relative_to(ROOT)} must not embed the ignore list"
        )


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
        packed_resources = (
            extracted / "package" / "src" / "core" / "code-flow" / "scripts" / "runtime-resources.json"
        )
        assert packed_resources.is_file(), "tarball must ship the runtime ignore declaration"

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
        assert entries == _runtime_ignore_declaration()["entries"]
        assert entries == _ignore_entries(CANONICAL_IGNORE.read_text())
        installed_resources = project / ".code-flow" / "scripts" / "runtime-resources.json"
        assert installed_resources.is_file(), "init must install the declaration beside the runtime"
        assert installed_resources.read_bytes() == RUNTIME_RESOURCES.read_bytes()


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
    from codeflow.core import cf_log

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
    from codeflow.task.cf_task_runtime import _run_finish_validation
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
    from codeflow.task.cf_task_runtime import _run_finish_validation
    from cf_validation import validate_files
    from codeflow.core.cf_validators import load_validators

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
    from codeflow.task.cf_task_runtime import _run_finish_validation

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
    from codeflow.task.cf_task_doc import parse_task_document

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


def test_task_contract_digest_uses_canonical_sections(tmp_path: Path) -> None:
    """[S-01] 摘要只读真实段落：行内示例与重复 ID 不改变注入版本。"""
    from codeflow.cli.cf_spec_context import task_contract_digest

    root = tmp_path / "project"
    task_dir = root / ".code-flow/tasks/demo"
    task_dir.mkdir(parents=True)
    task_file = task_dir / "demo.md"

    def write(contract: str) -> None:
        task_file.write_text(
            "# Tasks\n\n"
            "Example: `## TASK-001: Sample`\n\n"
            "## TASK-001: Actual\n"
            "- **Status**: done\n"
            "- **Spec-Refs**: app#RULE-1\n"
            "### Acceptance Contract\n"
            f"- S-01: {contract}\n"
            "### Acceptance Evidence\nnone\n",
            encoding="utf-8",
        )

    write("old")
    first = task_contract_digest(str(root), ".code-flow/tasks/demo", "TASK-001")
    write("new")
    second = task_contract_digest(str(root), ".code-flow/tasks/demo", "TASK-001")

    assert first and second and first != second

    (task_dir / "a.scenarios.md").write_text("---\nschema: 1\n---\n", encoding="utf-8")
    assert task_contract_digest(str(root), ".code-flow/tasks/demo", "TASK-001") == second

    task_file.write_text(
        "## TASK-001: first\n- **Status**: draft\n\n"
        "## TASK-001: second\n- **Status**: done\n",
        encoding="utf-8",
    )
    assert task_contract_digest(str(root), ".code-flow/tasks/demo", "TASK-001") == ""


def test_duplicate_task_id(tmp_path: Path) -> None:
    """[S-07] 五个消费者对重复 TASK ID 一致拒绝，禁止择一。"""
    from cf_spec_context import SpecContext
    from cf_spec_gate import validate_plan_coverage
    from cf_spec_session import _task_section
    from cf_task_index import parse_task_file
    from codeflow.task.cf_task_plan import parse_plan_tasks
    from codeflow.spec.cf_workflow_service import WorkflowError, read_task_section

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
    from codeflow.task.cf_task_doc import parse_task_document

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
    from codeflow.task.cf_task_doc import TaskDocumentError, parse_task_document

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


def _run_script(script: str, *arguments: str, cwd: Path,
                stdin: Optional[str] = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        (sys.executable, str(SCRIPTS / script), *arguments),
        cwd=str(cwd), input=stdin, text=True, capture_output=True, timeout=120,
    )


def _duplicate_task_text() -> str:
    return (
        "## TASK-001: first\n"
        "- **Status**: done\n\n"
        "## TASK-001: second\n"
        "- **Status**: done\n"
    )


def test_task_flow_consistency(tmp_path: Path) -> None:
    """[S-09] 真实任务目录：start → finish → spec gate 三命令读取同一 TASK 状态。"""
    from test_audit_mainline_e2e import _repo

    from codeflow.task.cf_task_doc import parse_task_document
    from cf_task_index import parse_task_file

    root, task_dir = _repo(tmp_path)
    work = task_dir / "work.md"

    started = _run_script(
        "cf_spec_context.py", "start",
        "--task-dir", str(task_dir), "--task-file", str(work),
        "--task", "TASK-001", "--root", str(root), "--json",
        cwd=root, stdin=json.dumps({"owned_paths": []}),
    )
    assert started.returncode == 0, started.stdout + started.stderr
    start_data = json.loads(started.stdout)
    assert start_data["ok"] is True, start_data
    assert start_data["active"]["task_id"] == "TASK-001"
    assert parse_task_document(work.read_text(encoding="utf-8")).tasks[0].status == "in-progress"

    finished = _run_script(
        "cf_task_workflow.py", "finish",
        "--task-dir", str(task_dir), "--task", "TASK-001",
        "--root", str(root), "--json",
        cwd=root,
    )
    assert finished.returncode == 0, finished.stdout + finished.stderr
    finish_data = json.loads(finished.stdout)
    assert finish_data["decision"] == "pass", finish_data
    assert parse_task_document(work.read_text(encoding="utf-8")).tasks[0].status == "done"

    gate = _run_script(
        "cf_spec_gate.py",
        "--task-dir", str(task_dir), "--stage", "code",
        "--task", "TASK-001", "--json",
        cwd=root,
    )
    assert gate.returncode == 0, gate.stdout + gate.stderr
    gate_data = json.loads(gate.stdout)
    assert gate_data["decision"] == "pass", gate_data
    nodes = {node.task_id: node.status for node in parse_task_file(str(work))}
    assert nodes["TASK-001"] == "done"


def test_plan_gate_duplicate(tmp_path: Path) -> None:
    """[E-03] plan 阶段 gate 对重复 TASK ID 返回 block 且引用 duplicate_task_id。"""
    root = tmp_path / "project"
    task_dir = root / ".code-flow" / "tasks" / "demo"
    task_dir.mkdir(parents=True)
    (root / ".code-flow" / "config.yml").write_text(
        "spec_workflow:\n  schema_version: 1\n  enforcement: required\npath_mapping: {}\n",
        encoding="utf-8",
    )
    (task_dir / "spec-context.yml").write_text(
        yaml.safe_dump({
            "version": 1,
            "task": "demo",
            "enforcement": "required",
            "updated_at": "2026-10-26T00:00:00+00:00",
            "sources": [],
            "bindings": [],
        }),
        encoding="utf-8",
    )
    task_file = task_dir / "work.md"
    task_file.write_text(_duplicate_task_text(), encoding="utf-8")

    completed = _run_script(
        "cf_spec_gate.py",
        "--task-dir", str(task_dir), "--stage", "plan",
        "--artifact", str(task_file), "--json",
        cwd=root,
    )

    assert completed.returncode == 3, completed.stdout + completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["decision"] == "block", payload
    assert [issue["code"] for issue in payload["errors"]] == ["duplicate_task_id"]


def test_manifest_and_stop_reject_duplicate_task_id(tmp_path: Path) -> None:
    """[TASK-005] manifest Contract 提取与 Stop 收尾对重复 ID 一致拒绝。"""
    from cf_acceptance_manifest import _contract_commands
    from cf_stop_hook import task_acceptance_failures

    with pytest.raises(ValueError, match="duplicate_task_id"):
        _contract_commands(_duplicate_task_text())

    root = tmp_path / "project"
    relative = ".code-flow/tasks/demo/work.md"
    task_file = root / relative
    task_file.parent.mkdir(parents=True)
    task_file.write_text(
        _duplicate_task_text() + "\n## Acceptance Coverage\n| 场景ID | 状态 |\n|---|---|\n",
        encoding="utf-8",
    )

    failures = task_acceptance_failures(str(root), [relative])

    assert any("duplicate_task_id" in str(item.get("detail", "")) for item in failures), failures


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
    from codeflow.evidence.cf_evidence_store import _run_git
    from codeflow.core.cf_git import changed_entries, changed_files, run_git
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
    from codeflow.core import cf_fs

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
    from codeflow.core.cf_markdown import parse_frontmatter, table_columns

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


def test_legacy_removal(tmp_path: Path) -> None:
    """[S-13] 删除旧 Spec 函数后，公开 Hook/CLI 路由输出保持一致。

    真实边界：`node src/cli.js init` 安装的四平台运行时、安装后的
    `cf_user_prompt_hook.py` 子进程、`spec catalog` CLI。无 mock。
    """
    import importlib.util

    from codeflow.core import cf_core

    legacy = ("read_matched_specs", "read_specs", "extract_context_tags")
    for name in legacy:
        assert not hasattr(cf_core, name), f"canonical cf_core still exports {name}"
    live_path = ROOT / ".code-flow/scripts/codeflow/core/cf_core.py"
    live_spec = importlib.util.spec_from_file_location("cf_core_live", live_path)
    assert live_spec is not None and live_spec.loader is not None
    live_core = importlib.util.module_from_spec(live_spec)
    live_spec.loader.exec_module(live_core)
    for name in legacy:
        assert not hasattr(live_core, name), f"live cf_core still exports {name}"

    project = tmp_path / "project"
    project.mkdir()
    installed = subprocess.run(
        ("node", str(CLI), "init", "--platform=claude"),
        cwd=project, text=True, capture_output=True, check=False, timeout=60,
    )
    assert installed.returncode == 0, installed.stderr

    hook = project / ".code-flow/scripts/cf_user_prompt_hook.py"

    def route(prompt: str) -> str:
        result = subprocess.run(
            (sys.executable, str(hook)),
            cwd=project, input=json.dumps({"prompt": prompt, "session_id": "legacy-session"}),
            text=True, capture_output=True, check=False, timeout=60,
        )
        assert result.returncode == 0 and result.stderr == ""
        payload = json.loads(result.stdout)
        return payload["hookSpecificOutput"]["additionalContext"]

    catalog = route("explain the architecture")
    assert catalog.startswith("## Spec Catalog (code-flow)")
    for path in (
        "backend/code-quality-performance.md",
        "backend/database.md",
        "backend/directory-structure.md",
        "backend/logging.md",
        "backend/platform-rules.md",
        "frontend/component-specs.md",
        "frontend/directory-structure.md",
        "frontend/quality-standards.md",
    ):
        assert f"`{path}`" in catalog
    assert "Active Specs" not in catalog

    matched = route("edit src/components/Button.tsx")
    assert matched.startswith("## Active Specs (path-mapped)")
    assert "frontend/component-specs.md" in matched
    assert "frontend/directory-structure.md" in matched
    assert "frontend/quality-standards.md" in matched
    assert "backend/database.md" not in matched
    assert "Spec Catalog" not in matched

    catalogued = subprocess.run(
        ("node", str(CLI), "spec", "catalog", "--root", str(project), "--stage", "code",
         "--paths", "src/components/Button.tsx", "--json"),
        cwd=project, text=True, capture_output=True, check=False, timeout=60,
    )
    assert catalogued.returncode == 0, catalogued.stderr
    data = json.loads(catalogued.stdout)
    scopes = {item["path"]: item["scope"] for item in data["candidates"]}
    assert data["ok"] is True and data["total"] == 8
    assert scopes["frontend/component-specs.md"] == "path"
    assert scopes["frontend/directory-structure.md"] == "path"
    assert scopes["frontend/quality-standards.md"] == "path"
    assert scopes["backend/database.md"] == "unmatched"


def _plan_repo(tmp_path: Path) -> tuple[Path, Path, Path]:
    from cf_acceptance_manifest import write_manifest
    from test_audit_mainline_e2e import _repo

    root, demand = _repo(tmp_path)
    task_file = demand / "work.md"
    source_file = demand / "demo.scenarios.md"
    rows = [
        {"id": scenario_id, "level": "integration", "boundary": "real", "steps": ["run the check"],
         "expected": ["exit code 0"], "expected_refs": [{"expected": 1, "steps": [1]}]}
        for scenario_id in ("S-01", "S-02")
    ]
    source_file.write_text(yaml.safe_dump({"schema": 1, "scenarios": rows}, allow_unicode=True),
                           encoding="utf-8")
    write_manifest(str(task_file), str(demand / ".acceptance-manifest.json"), str(source_file))
    return root, demand, source_file


def test_verify_plan_reads(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """[S-14] 单次 verify_plan 对 TASK/场景/manifest 各至多读取一次，结果不变。"""
    from codeflow.acceptance.cf_plan_quality import verify_plan

    _root_dir, demand, source_file = _plan_repo(tmp_path)
    task_file = demand / "work.md"
    targets = {"task": task_file, "scenarios": source_file,
               "manifest": demand / ".acceptance-manifest.json"}
    counts = {name: 0 for name in targets}
    original = Path.read_text

    def counting_read_text(self: Path, *args: object, **kwargs: object) -> str:
        for name, target in targets.items():
            if self.resolve() == target.resolve():
                counts[name] += 1
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", counting_read_text)
    result = verify_plan(str(demand), str(task_file))

    assert result["decision"] == "pass", result
    assert counts == {"task": 1, "scenarios": 1, "manifest": 1}, counts
    assert result["e2e_quality"]["ok"] is True
    assert result["registration"]["ok"] is True
    assert result["design_lint"]["decision"] == "pass"
    assert result["coverage"]["decision"] == "pass"
    assert result["gate"]["decision"] == "pass"


def test_snapshot_drift(tmp_path: Path) -> None:
    """[E-04] 快照加载后 TASK 变化必须 drift 阻断，不能继续使用陈旧快照。"""
    from codeflow.acceptance.cf_plan_quality import load_plan_snapshot, verify_plan

    _root_dir, demand, _source = _plan_repo(tmp_path)
    task_file = demand / "work.md"
    snapshot = load_plan_snapshot(str(demand), str(task_file))
    assert verify_plan(str(demand), str(task_file), snapshot=snapshot)["decision"] == "pass"

    task_file.write_text(task_file.read_text(encoding="utf-8") + "\n## drift\n", encoding="utf-8")
    result = verify_plan(str(demand), str(task_file), snapshot=snapshot)

    assert result["decision"] == "block", result
    assert result["reason"] == "plan_snapshot_drift"


PLATFORMS = ("claude", "codex", "costrict", "opencode")
PACKAGE_GROUPS = ("core", "spec", "task", "acceptance", "evidence", "hooks", "cli")
LEGACY_RUNTIME_VERSION = "0.7.0"


def _package_version() -> str:
    return json.loads((ROOT / "package.json").read_text(encoding="utf-8"))["version"]


def _run_runtime_cli(project: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [_node_binary(), str(CLI), *arguments],
        cwd=str(project), text=True, capture_output=True, timeout=180, check=False,
    )


def _hook_probe(project: Path, script: str, payload: dict) -> str:
    """[S-17] Run an installed hook exactly as the host does: path + stdin JSON."""
    result = subprocess.run(
        [sys.executable, str(project / ".code-flow/scripts" / script)],
        cwd=str(project), input=json.dumps(payload), text=True,
        capture_output=True, timeout=120, check=False,
    )
    assert result.returncode == 0, f"{script} exited {result.returncode}:\n{result.stderr}"
    output = result.stdout.strip()
    if output:
        parsed = json.loads(output)  # non-JSON stdout breaks the host protocol
        assert isinstance(parsed, dict), f"{script} must emit a single JSON object"
    return output


@pytest.mark.parametrize("platform", PLATFORMS)
def test_four_platform_install(platform: str, tmp_path: Path) -> None:
    """[S-17] 真实四平台 fresh 安装：22 个入口存在，Hook 返回合法 JSON 或静默 no-op。"""
    project = tmp_path / platform
    project.mkdir()
    installed = _run_runtime_cli(project, "init", f"--platform={platform}")
    assert installed.returncode == 0, installed.stdout + installed.stderr

    scripts = project / ".code-flow/scripts"
    for module in sorted(_flat_entry_modules()):
        assert (scripts / f"{module}.py").is_file(), f"{platform}: missing entry {module}.py"
    for group in PACKAGE_GROUPS:
        assert (scripts / "codeflow" / group / "__init__.py").is_file(), f"{platform}: missing codeflow/{group}"

    event = {"session_id": "s-17", "hook_event_name": "PreToolUse", "tool_name": "Read",
             "tool_input": {"file_path": "README.md"}}
    _hook_probe(project, "cf_user_prompt_hook.py",
                {"prompt": "explain the architecture", "session_id": "s-17"})
    _hook_probe(project, "cf_pre_tool_hook.py", event)
    _hook_probe(project, "cf_post_hook.py", {**event, "hook_event_name": "PostToolUse"})
    _hook_probe(project, "cf_stop_hook.py", {"session_id": "s-17", "hook_event_name": "Stop"})
    if platform == "codex":
        _hook_probe(project, "cf_codex_hook.py",
                    {"cwd": str(project), "session_id": "s-17",
                     "hook_event_name": "PreToolUse", "tool_name": "Read", "tool_input": {}})
        _hook_probe(project, "cf_codex_hook.py",
                    {"cwd": str(project), "session_id": "s-17",
                     "hook_event_name": "UserPromptSubmit", "prompt": "explain the architecture"})
    if platform == "opencode":
        _hook_probe(project, "cf_opencode_event.py",
                    {"kind": "session.prompt", "directory": str(project),
                     "event": {"sessionID": "s-17", "prompt": {"text": "explain the architecture"}}})


_PACKAGE_MODULE_IMPORT = re.compile(
    r"(?m)^(?P<indent>[ \t]*)from codeflow\.(?:core|spec|task|acceptance|evidence|hooks|cli)\."
    r"(?P<module>cf_[a-z_]+) import ")
_PACKAGE_NAME_IMPORT = re.compile(
    r"(?m)^(?P<indent>[ \t]*)from codeflow\.(?:core|spec|task|acceptance|evidence|hooks|cli) import "
    r"(?P<names>cf_[a-z_]+(?:, cf_[a-z_]+)*)[ \t]*(?:#.*)?$")
_PACKAGE_DOTTED_IMPORT = re.compile(
    r"(?m)^(?P<indent>[ \t]*)import codeflow\.(?:core|spec|task|acceptance|evidence|hooks|cli)\."
    r"(?P<module>cf_[a-z_]+)(?P<alias> as cf_[a-z_]+)?$")


def _flatten_imports(text: str) -> str:
    text = _PACKAGE_MODULE_IMPORT.sub(lambda match: f"{match['indent']}from {match['module']} import ", text)
    text = _PACKAGE_NAME_IMPORT.sub(lambda match: f"{match['indent']}import {match['names']}", text)
    text = _PACKAGE_DOTTED_IMPORT.sub(
        lambda match: f"{match['indent']}import {match['module']}{match['alias'] or ''}", text)
    return text


def _flatten_legacy_layout(project: Path) -> set[str]:
    """Rewrite a packaged runtime into the pre-package flat layout (no mocks)."""
    scripts = project / ".code-flow/scripts"
    flat: dict[str, str] = {}
    for path in sorted((scripts / "codeflow").rglob("*.py")):
        if path.name == "__init__.py":
            continue
        flat[path.stem] = _flatten_imports(path.read_text(encoding="utf-8"))
    shutil.rmtree(scripts / "codeflow")
    for stem, text in flat.items():
        (scripts / f"{stem}.py").write_text(text, encoding="utf-8")
    return {f"{stem}.py" for stem in flat}


def _legacy_flat_install(project: Path) -> set[str]:
    """Install the current runtime, then downgrade it to a genuine flat layout."""
    for platform in PLATFORMS:
        result = _run_runtime_cli(project, "init", f"--platform={platform}")
        assert result.returncode == 0, result.stdout + result.stderr
    flat = _flatten_legacy_layout(project)

    scripts = project / ".code-flow/scripts"
    manifest_path = project / ".code-flow/.runtime-install.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["version"] = LEGACY_RUNTIME_VERSION
    for relative in [key for key in manifest["files"] if key.startswith(".code-flow/scripts/")]:
        del manifest["files"][relative]
    for path in sorted(scripts.rglob("*.py")):
        relative = path.relative_to(project).as_posix()
        manifest["files"][relative] = hashlib.sha256(path.read_bytes()).hexdigest()
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    (project / ".code-flow/.version").write_text(LEGACY_RUNTIME_VERSION + "\n", encoding="utf-8")
    versions_path = project / ".code-flow/.adapter-versions.json"
    versions = json.loads(versions_path.read_text(encoding="utf-8"))
    versions["core"] = LEGACY_RUNTIME_VERSION
    versions["adapters"] = {name: LEGACY_RUNTIME_VERSION for name in versions["adapters"]}
    versions_path.write_text(json.dumps(versions, indent=2) + "\n", encoding="utf-8")
    return flat


def _script_snapshot(project: Path) -> dict[str, str]:
    snapshot: dict[str, str] = {}
    for relative in (".code-flow/.version", ".code-flow/.runtime-install.json"):
        snapshot[relative] = hashlib.sha256((project / relative).read_bytes()).hexdigest()
    for path in sorted((project / ".code-flow/scripts").rglob("*")):
        if path.is_file() and "__pycache__" not in path.parts:
            snapshot[path.relative_to(project).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return snapshot


def test_package_upgrade_cleanup(tmp_path: Path) -> None:
    """[S-18] 旧平铺安装真实 runtime migrate：保留 shim、清理旧实现、manifest 校验通过。"""
    project = tmp_path / "project"
    project.mkdir()
    flat = _legacy_flat_install(project)
    scripts = project / ".code-flow/scripts"
    assert not (scripts / "codeflow").exists(), "legacy fixture must be a flat layout"
    assert (scripts / "cf_task_runtime.py").is_file()

    applied = _run_runtime_cli(project, "migrate", "--runtime", "--apply")
    assert applied.returncode == 0, applied.stdout + applied.stderr
    data = json.loads(applied.stdout)
    assert data["status"] == "committed", data

    entries = _flat_entry_modules()
    assert {path.name for path in scripts.glob("*.py")} == {f"{module}.py" for module in entries}, (
        "old flat implementation files must be removed; only the 22 entry shims remain"
    )
    for module in entries:
        shim = scripts / f"{module}.py"
        assert shim.is_file()
        assert len(shim.read_text(encoding="utf-8").splitlines()) <= 15, f"{module}.py is not a thin shim"
    for group in PACKAGE_GROUPS:
        assert (scripts / "codeflow" / group / "__init__.py").is_file(), f"missing codeflow/{group}"
        assert any((scripts / "codeflow" / group).glob("*.py")), f"empty codeflow/{group}"

    manifest = json.loads((project / ".code-flow/.runtime-install.json").read_text(encoding="utf-8"))
    version = (project / ".code-flow/.version").read_text(encoding="utf-8").strip()
    assert manifest["version"] == version == _package_version()
    for relative, digest in manifest["files"].items():
        target = project / relative
        assert target.is_file(), f"manifest lists missing artifact: {relative}"
        assert hashlib.sha256(target.read_bytes()).hexdigest() == digest, f"artifact drifted: {relative}"
    verified = _run_runtime_cli(project, "spec", "validate", "--help")
    assert verified.returncode == 0, verified.stdout + verified.stderr

    workspace = project / ".code-flow/migrations" / data["migration_id"]
    journal = json.loads((workspace / "journal.json").read_text(encoding="utf-8"))
    stale = ({f".code-flow/scripts/{name}" for name in flat}
             - {f".code-flow/scripts/{module}.py" for module in entries})
    assert stale <= set(journal["deletions"]), "migration must journal every removed flat module"


def _script_py_files(scripts: Path) -> set[str]:
    return {path.relative_to(scripts).as_posix() for path in scripts.rglob("*.py")}


def _flat_entry_modules() -> set[str]:
    contract = json.loads((ROOT / "src/core/code-flow/runtime-commands.json").read_text())
    return {entry["module"] for entry in contract["commands"].values()} | {
        "cf_pre_tool_hook", "cf_post_hook", "cf_user_prompt_hook",
        "cf_stop_hook", "cf_codex_hook", "cf_opencode_event",
    }


def _tarball_py_members(tarball: Path) -> set[str]:
    prefix = "package/src/core/code-flow/scripts/"
    with tarfile.open(tarball) as archive:
        names = [member.name for member in archive.getmembers() if member.isfile()]
    return {name[len(prefix):] for name in names
            if name.startswith(prefix) and name.endswith(".py")}


def test_canonical_parity() -> None:
    """[S-19] canonical 模板、部署副本与 npm 产物共享同一脚本文件集。"""
    canonical = _script_py_files(SCRIPTS)
    deployed = _script_py_files(DEPLOYED_SCRIPTS)
    assert canonical == deployed, (
        "canonical and deployed script trees differ:\n"
        f"only canonical: {sorted(canonical - deployed)}\n"
        f"only deployed: {sorted(deployed - canonical)}"
    )

    flat = {relative for relative in canonical if "/" not in relative}
    assert flat == {f"{module}.py" for module in _flat_entry_modules()}, (
        "the 22 host entry modules must stay flat; internal modules live under codeflow/"
    )
    package = canonical - flat
    for subpackage in ("core", "spec", "task", "acceptance", "evidence", "hooks", "cli"):
        assert f"codeflow/{subpackage}/__init__.py" in package, f"missing codeflow/{subpackage}__init__.py"
        assert any(
            relative.startswith(f"codeflow/{subpackage}/")
            and relative != f"codeflow/{subpackage}/__init__.py"
            for relative in package
        ), f"codeflow/{subpackage}/ has no modules"

    npm = shutil.which("npm")
    assert npm is not None, "npm is required for the canonical parity probe"
    with tempfile.TemporaryDirectory() as tmp:
        pack_dir = Path(tmp)
        packed = subprocess.run(
            [npm, "pack", "--pack-destination", str(pack_dir), "--silent"],
            cwd=ROOT, capture_output=True, text=True, timeout=180, check=False,
        )
        assert packed.returncode == 0, f"npm pack failed:\n{packed.stdout}{packed.stderr}"
        tarballs = list(pack_dir.glob("*.tgz"))
        assert len(tarballs) == 1, f"expected one tarball, got {tarballs}"
        assert _tarball_py_members(tarballs[0]) == canonical, (
            "npm tarball must ship the same package tree and flat entries as src/core"
        )


def test_migration_rollback(tmp_path: Path) -> None:
    """[E-05] 旧平铺布局迁移写入失败后 rollback 恢复全部旧文件与版本。"""
    project = tmp_path / "project"
    project.mkdir()
    _legacy_flat_install(project)
    before = _script_snapshot(project)
    failure_target = ".code-flow/scripts/codeflow/core/cf_core.py"
    assert not (project / failure_target).exists()

    program = """
const fs = require('fs');
const original = fs.copyFileSync;
const root = process.argv[1];
fs.copyFileSync = function(source, target) {
  if (target === root + %s) throw new Error('injected write failure');
  return original(source, target);
};
process.stdout.write(JSON.stringify(require(process.argv[2]).run(root, ['--apply'])));
""" % json.dumps("/" + failure_target)
    result = subprocess.run(
        [_node_binary(), "-e", program, str(project), str(ROOT / "src/migrate/runtime.js")],
        capture_output=True, text=True, timeout=180, check=False,
    )
    data = json.loads(result.stdout)
    assert data["status"] == "rolled_back", data
    assert "injected write failure" in data.get("error", ""), data

    assert _script_snapshot(project) == before, "rollback must restore the old flat layout byte-for-byte"
    assert (project / ".code-flow/.version").read_text(encoding="utf-8").strip() == LEGACY_RUNTIME_VERSION
    assert not list((project / ".code-flow/scripts/codeflow").rglob("*.py")), "rollback must not leave package modules"
    assert (project / ".code-flow/scripts/cf_task_runtime.py").is_file()
    manifest = json.loads((project / ".code-flow/.runtime-install.json").read_text(encoding="utf-8"))
    assert manifest["version"] == LEGACY_RUNTIME_VERSION
