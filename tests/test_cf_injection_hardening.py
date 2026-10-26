"""Real routing regressions for drift, dedup, budgets and edit batches."""
from __future__ import annotations

import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
from unittest import mock

import pytest
import yaml

from test_cf_user_prompt_hook import _run_raw, _task_repo
import cf_log
from cf_core import build_effective_mapping, build_spec_catalog, estimate_tokens, load_config
from cf_edit_service import prepare_edit, prepare_edits
from cf_injection import injection_output
from cf_spec_context import (BindingInput, bind_specs, context_sha256, load_context,
                             refresh_context, resync_active_hash, save_context)
from cf_spec_resolver import resolve_candidates
from cf_spec_router import route_prompt
from cf_user_prompt_hook import build_prompt_context, extract_paths_from_prompt

ROOT = Path(__file__).resolve().parents[1]


def _config(root: Path, **changes: object) -> None:
    path = root / ".code-flow/config.yml"
    config = yaml.safe_load(path.read_text())
    config.update(changes)
    path.write_text(yaml.safe_dump(config))


def _path_repo(root: Path) -> Path:
    _task_repo(root)
    (root / ".code-flow/.active-task.json").unlink()
    return root


def _refresh(root: Path) -> None:
    path = root / ".code-flow/tasks/demo/spec-context.yml"
    context = refresh_context(load_context(str(path)), str(root)).context
    save_context(str(path), context)
    resync_active_hash(str(root), str(path.parent), context_sha256(context))


@pytest.mark.parametrize("deleted", [False, True])
def test_bound_source_change_blocks_prompt_and_edit(tmp_path: Path, deleted: bool) -> None:
    root = _task_repo(tmp_path)
    assert "Must define VALUE" in _run_raw(root, "continue")
    spec = root / ".code-flow/specs/app/rules.md"
    if deleted:
        spec.unlink()
    else:
        previous = spec.stat()
        spec.write_text(spec.read_text().replace("Must define", "Never allow"))
        os.utime(spec, ns=(previous.st_atime_ns, previous.st_mtime_ns))
    for sid in ("session-1", "fresh-session"):
        payload = json.loads(_run_raw(root, "continue", sid))
        assert payload["decision"] == "block" and "bound_spec_" in payload["reason"]
    text, blocked = prepare_edit(str(root), "src/app.py", "edit", "Edit")
    assert blocked and "bound_spec_" in text
    if not deleted:
        _refresh(root)
        assert "Never allow VALUE" in _run_raw(root, "continue")


def test_spec_refs_change_reinjects_with_same_context_hash(tmp_path: Path) -> None:
    root = _task_repo(tmp_path)
    spec = root / ".code-flow/specs/app/rules.md"
    spec.write_text(spec.read_text().replace("---\n# Rules", "  - rule: RULE-app-002\n"
                    "    type: regex\n    config: {pattern: SECOND}\n---\n# Rules")
                    + "- [RULE-app-002] Must define SECOND.\n")
    _refresh(root)
    assert "Must define SECOND" not in _run_raw(root, "continue")
    task = root / ".code-flow/tasks/demo/demo.md"
    previous = task.stat()
    task.write_text(task.read_text().replace("app-runtime#RULE-app-001\n",
                    "app-runtime#RULE-app-001, app-runtime#RULE-app-002\n"))
    os.utime(task, ns=(previous.st_atime_ns, previous.st_mtime_ns))
    assert "Must define SECOND" in _run_raw(root, "continue")
    assert _run_raw(root, "continue") == ""


@pytest.mark.parametrize("field", ["Source", "Design-Refs", "Acceptance-Refs"])
def test_task_reference_changes_reinject(tmp_path: Path, field: str) -> None:
    root = _task_repo(tmp_path)
    task = root / ".code-flow/tasks/demo/demo.md"
    task.write_text(task.read_text().replace("### Acceptance Contract", f"- **{field}**: first-ref\n### Acceptance Contract"))
    assert "first-ref" in _run_raw(root, "continue")
    task.write_text(task.read_text().replace("first-ref", "second-ref"))
    assert "second-ref" in _run_raw(root, "continue")


@pytest.mark.parametrize("bad_config", ["path_mapping: [\n", "[]\n", "scalar\n"])
def test_invalid_config_is_structured_block(tmp_path: Path, bad_config: str) -> None:
    root = _path_repo(tmp_path)
    (root / ".code-flow/config.yml").write_text(bad_config)
    payload = json.loads(_run_raw(root, "edit src/app.py"))
    assert payload["decision"] == "block" and "invalid_config" in payload["reason"]
    assert prepare_edit(str(root), "src/app.py", "edit", "Edit")[1]


@pytest.mark.parametrize("field", ["Acceptance Contract", "Spec-Refs"])
def test_invalid_projection_is_not_silent(tmp_path: Path, field: str) -> None:
    root = _task_repo(tmp_path)
    task = root / ".code-flow/tasks/demo/demo.md"
    task.write_text(task.read_text().replace(field, "Missing field"))
    payload = json.loads(_run_raw(root, "continue"))
    assert payload["decision"] == "block" and "invalid_task_projection" in payload["reason"]


def test_active_context_precedes_prompt_path_normalization(tmp_path: Path) -> None:
    root = _task_repo(tmp_path)
    assert "TASK-001 Spec Context" in _run_raw(root, "review /elsewhere/notes.py")
    (root / ".code-flow/.active-task.json").write_text("{}")
    payload = json.loads(_run_raw(root, "review /elsewhere/notes.py"))
    assert payload["decision"] == "block" and "invalid_active_task" in payload["reason"]


@pytest.mark.parametrize("mode", ["warn", "inject", {}])
def test_doctor_reports_legacy_modes_without_mutating_config(tmp_path: Path, mode: object) -> None:
    from cf_spec_context import _doctor_config
    root = _task_repo(tmp_path)
    _config(root, spec_workflow={"schema_version": 1, "enforcement": mode})
    path = root / ".code-flow/config.yml"
    before = path.read_bytes()
    findings = _doctor_config(root)
    assert bool(findings) == isinstance(mode, str)
    if findings:
        assert findings[0]["code"] == "legacy_enforcement_mode"
    assert path.read_bytes() == before


def test_claude_style_entry_denies_corrupt_context_from_subdirectory(tmp_path: Path) -> None:
    import cf_pre_tool_hook
    root = _task_repo(tmp_path)
    (root / ".code-flow/.active-task.json").write_text("{}")
    event = {"tool_name": "Edit", "tool_input": {"file_path": "app.py"}, "session_id": "claude"}
    with mock.patch("sys.stdin", io.StringIO(json.dumps(event))), mock.patch("sys.stdout", io.StringIO()) as out, mock.patch(
        "os.getcwd", return_value=str(root / "src"),
    ):
        cf_pre_tool_hook.main()
    assert json.loads(out.getvalue())["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert not (root / "src/.code-flow").exists()


def test_claude_style_entry_is_noop_outside_project(tmp_path: Path) -> None:
    import cf_pre_tool_hook
    event = {"tool_name": "Edit", "tool_input": {"file_path": "app.py"}, "session_id": "outside"}
    with mock.patch("sys.stdin", io.StringIO(json.dumps(event))), mock.patch("sys.stdout", io.StringIO()) as out, mock.patch(
        "os.getcwd", return_value=str(tmp_path),
    ):
        cf_pre_tool_hook.main()
    assert out.getvalue() == "" and not (tmp_path / ".code-flow").exists()
def test_absolute_paths_urls_and_bare_frontend_files(tmp_path: Path) -> None:
    root = _path_repo(tmp_path)
    absolute = str(root / "src/app.py")
    assert extract_paths_from_prompt(f"edit `{absolute}`", str(root)) == ["src/app.py"]
    assert extract_paths_from_prompt("edit ./src/app.py and src/../src/app.py", str(root)) == ["src/app.py"]
    assert extract_paths_from_prompt("see https://example.com/docs/api.md and @src/app.py") == ["src/app.py"]
    assert extract_paths_from_prompt("edit App.tsx and App.vue") == ["App.tsx", "App.vue"]
    assert "Must define VALUE" in _run_raw(root, f"edit {absolute}")
    assert "Spec Catalog" in _run_raw(root, "review https://example.com/docs/api.md")


def test_unrelated_broken_metadata_does_not_block_path(tmp_path: Path) -> None:
    root = _path_repo(tmp_path)
    broken = root / ".code-flow/specs/other/broken.md"
    broken.parent.mkdir()
    broken.write_text("# invalid metadata\n")
    _config(root, path_mapping={"app": {"patterns": ["src/*"]}, "other": {"patterns": ["server/*"]}})
    result = route_prompt(str(root), ("src/app.py",), "path")
    assert result.specs == ("app/rules.md",) and "Must define VALUE" in result.text
    with pytest.raises(ValueError, match="frontmatter"):
        resolve_candidates(str(root), "code", ())


def test_metadata_cache_invalidates_when_mtime_and_size_are_preserved(tmp_path: Path) -> None:
    root = _path_repo(tmp_path)
    first = resolve_candidates(str(root), "code", ("src/app.py",))[0]
    spec = root / ".code-flow/specs/app/rules.md"
    previous = spec.stat()
    spec.write_text(spec.read_text().replace("Must define", "Never allow"))
    os.utime(spec, ns=(previous.st_atime_ns, previous.st_mtime_ns))
    second = resolve_candidates(str(root), "code", ("src/app.py",))[0]
    assert first.metadata.rules[0].text != second.metadata.rules[0].text


def test_path_budget_blocks_without_truncating_required_rules(tmp_path: Path) -> None:
    root = _path_repo(tmp_path)
    spec = root / ".code-flow/specs/app/rules.md"
    spec.write_text(spec.read_text() + "\n## Guidance\n" + "Long constraint. " * 2000)
    _config(root, budget={"total": 2500, "l1_max": 1700})
    payload = json.loads(_run_raw(root, "edit src/app.py"))
    assert payload["decision"] == "block" and "spec_budget_exceeded" in payload["reason"]
    assert len(payload["reason"]) < 1000


def test_path_dedup_is_shared_with_edit_and_isolated_by_session(tmp_path: Path) -> None:
    root = _path_repo(tmp_path)
    assert "Must define VALUE" in _run_raw(root, "edit src/app.py", "one")
    assert _run_raw(root, "edit src/app.py", "one") == ""
    assert prepare_edit(str(root), "src/app.py", "one", "Edit") == ("", False)
    assert "Must define VALUE" in _run_raw(root, "edit src/app.py", "two")
    assert _run_raw(root, "edit src/app.py", "one") == ""
    assert len(cf_log.read_events(str(root), events=("inject",))) == 2


def test_failed_output_does_not_commit_injection_or_catalog(tmp_path: Path) -> None:
    root = _path_repo(tmp_path)
    with pytest.raises(OSError, match="output failed"):
        with injection_output():
            assert "Must define VALUE" in build_prompt_context("edit src/app.py", "one", str(root))[0]
            raise OSError("output failed")
    assert "Must define VALUE" in _run_raw(root, "edit src/app.py", "one")
    with pytest.raises(OSError):
        with injection_output():
            build_prompt_context("explore", "catalog", str(root))
            raise OSError("output failed")
    assert not (root / ".code-flow/.catalog-state.json").exists()


def test_catalog_excludes_session_and_reports_omissions(tmp_path: Path) -> None:
    root = _path_repo(tmp_path)
    session = root / ".code-flow/specs/_session/obsolete.md"
    session.parent.mkdir()
    session.write_text("# obsolete TASK\n")
    template = (root / ".code-flow/specs/app/rules.md").read_text()
    for index in range(30):
        (root / f".code-flow/specs/app/extra-{index}.md").write_text(
            template.replace("app-runtime", f"catalog-{index}").replace("RULE-app-001", f"RULE-catalog-{index:03}"))
    config = load_config(str(root))
    text = build_spec_catalog(str(root), build_effective_mapping(str(root), config["path_mapping"]), 200)
    assert "_session/" not in text
    assert "已展示" in text and "/31" in text
    assert "code-flow spec catalog --root . --stage code --json" in text
    assert estimate_tokens(text) <= 200


def _large_context(root: Path, count: int = 200) -> None:
    _task_repo(root)
    template = (root / ".code-flow/specs/app/rules.md").read_text()
    for index in range(1, count):
        (root / f".code-flow/specs/app/rules-{index}.md").write_text(
            template.replace("app-runtime", f"app-extra-{index}")
                    .replace("RULE-app-001", f"RULE-extra-{index:03}"))
    candidates = resolve_candidates(str(root), "code", ("src/app.py",))
    path = root / ".code-flow/tasks/demo/spec-context.yml"
    context = bind_specs(load_context(str(path)), tuple(BindingInput(item, "plan", "batch test") for item in candidates))
    save_context(str(path), context)
    resync_active_hash(str(root), str(path.parent), context_sha256(context))


def test_twenty_file_batch_reads_context_once(tmp_path: Path) -> None:
    import cf_context_cache
    import cf_spec_router
    import cf_spec_resolver
    _large_context(tmp_path)
    paths = tuple(f"src/item-{index}.py" for index in range(20))
    with mock.patch.object(cf_spec_router, "load_context", wraps=load_context) as contexts, mock.patch.object(
        cf_spec_resolver, "load_spec_header", wraps=cf_spec_resolver.load_spec_header,
    ) as headers, mock.patch.object(cf_context_cache, "context_sha256", wraps=context_sha256) as hashes:
        text, blocked = prepare_edits(str(tmp_path), paths, "batch", "apply_patch")
    assert not blocked and "Must define VALUE" in text
    assert contexts.call_count == 1 and hashes.call_count == 1
    assert headers.call_count == 0
    assert len(cf_log.read_events(str(tmp_path), events=("edit_intent",))) == 20


def test_context_parse_cache_never_masks_source_changes(tmp_path: Path) -> None:
    import cf_spec_router
    root = _task_repo(tmp_path)
    assert "Must define VALUE" in _run_raw(root, "continue")
    with mock.patch.object(cf_spec_router, "load_context", side_effect=AssertionError("unneeded YAML parse")):
        assert _run_raw(root, "continue") == ""
    cache = root / ".code-flow/.context-state.json"
    cached = json.loads(cache.read_text())
    cached["context"]["bindings"] = []
    cache.write_text(json.dumps(cached))
    assert "Must define VALUE" in _run_raw(root, "continue", "fresh")
    source = root / ".code-flow/tasks/demo/spec-context.yml"
    previous = source.stat()
    source.write_text("bindings: [\n")
    os.utime(source, ns=(previous.st_atime_ns, previous.st_mtime_ns))
    assert json.loads(_run_raw(root, "continue"))["decision"] == "block"


def test_native_twenty_file_entry_finishes_before_configured_timeout(tmp_path: Path) -> None:
    _large_context(tmp_path)
    config = tmp_path / ".code-flow/config.yml"
    (tmp_path / ".code-flow/.version").write_text("test")
    (tmp_path / ".code-flow/.runtime-install.json").write_text(json.dumps({
        "schema_version": 1, "version": "test", "files": {
            ".code-flow/config.yml": hashlib.sha256(config.read_bytes()).hexdigest()},
    }))
    command = "*** Begin Patch\n" + "".join(
        f"*** Add File: src/item-{index}.py\n+VALUE = 1\n" for index in range(20)) + "*** End Patch"
    payload = {"cwd": str(tmp_path), "session_id": "native", "hook_event_name": "PreToolUse",
               "tool_name": "apply_patch", "tool_input": {"command": command}}
    result = subprocess.run([sys.executable, str(ROOT / "src/core/code-flow/scripts/cf_codex_hook.py")],
                            cwd=tmp_path, input=json.dumps(payload), capture_output=True, text=True,
                            timeout=5, check=False)
    assert result.returncode == 0, result.stderr
    assert "Must define VALUE" in json.loads(result.stdout)["hookSpecificOutput"]["additionalContext"]
