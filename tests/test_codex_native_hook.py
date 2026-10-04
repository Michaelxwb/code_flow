"""Native Codex events must exercise real routing, checks and edit evidence."""
import io
import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "src/core/code-flow/scripts"
sys.path.insert(0, str(SCRIPTS))


def _invoke(root: Path, event: str, command: str, response: object = None) -> str:
    import cf_codex_hook
    payload = {"cwd": str(root), "session_id": "native-test", "hook_event_name": event,
               "tool_name": "apply_patch", "tool_input": {"command": command}}
    if response is not None:
        payload["tool_response"] = response
    with patch("sys.stdin", io.StringIO(json.dumps(payload))), patch("sys.stdout", io.StringIO()) as out:
        cf_codex_hook.main()
    return out.getvalue()


def _project(root: Path) -> None:
    import yaml
    specs = root / ".code-flow/specs/scripts"
    specs.mkdir(parents=True)
    (specs / "rules.md").write_text("""---
id: python-rules
description: Python rules
stages: [code]
enforcement: required
checks:
  - id: no-debug
    type: regex
    pattern: 'print\\('
    files: '*.py'
    message: Remove debug printing
verifiers:
  - rule: RULE-python-001
    type: regex
    config:
      pattern: SAFE
---
## Rules
- [RULE-python-001] Keep SAFE.
""")
    config = {"spec_workflow": {"schema_version": 1}, "quality_loop": {"enabled": True, "code_extensions": [".py"]},
              "path_mapping": {"scripts": {"patterns": ["src/*.py"], "specs": [
                  {"path": "scripts/rules.md", "tags": ["python"], "tier": 1}]}}}
    (root / ".code-flow/config.yml").write_text(yaml.safe_dump(config))
    import hashlib
    (root / ".code-flow/.version").write_text("test")
    manifest = {"schema_version": 1, "version": "test", "files": {
        ".code-flow/config.yml": hashlib.sha256((root / ".code-flow/config.yml").read_bytes()).hexdigest()}}
    (root / ".code-flow/.runtime-install.json").write_text(json.dumps(manifest))
    (root / "src").mkdir()
    (root / "src/a.py").write_text("print('debug')\n")


PATCH = "*** Begin Patch\n*** Update File: src/a.py\n@@\n-old\n+new\n*** Add File: src/b.py\n+SAFE\n*** End Patch"


def test_native_patch_routes_every_file_and_records_success(tmp_path: Path) -> None:
    import cf_log
    _project(tmp_path)
    (tmp_path / "src/b.py").write_text("SAFE\n")
    pre = json.loads(_invoke(tmp_path, "PreToolUse", PATCH))
    assert "RULE-python-001" in pre["hookSpecificOutput"]["additionalContext"]
    assert {e["data"]["file"] for e in cf_log.read_events(str(tmp_path), events=("edit_intent",))} == {"src/a.py", "src/b.py"}
    post = json.loads(_invoke(tmp_path, "PostToolUse", PATCH, {"output": "Success. Updated the following files:\nM src/a.py\nA src/b.py"}))
    assert "Remove debug printing" in post["hookSpecificOutput"]["additionalContext"]
    assert {e["data"]["file"] for e in cf_log.read_events(str(tmp_path), events=("edit",))} == {"src/a.py", "src/b.py"}


def test_failed_patch_never_records_completed_edits(tmp_path: Path) -> None:
    import cf_log
    _project(tmp_path)
    assert _invoke(tmp_path, "PostToolUse", PATCH, {"output": "Failed to find expected lines"}) == ""
    assert not cf_log.read_events(str(tmp_path), events=("edit",))


def test_patch_parser_handles_moves_deletes_and_header_like_content() -> None:
    from cf_codex_hook import parse_patch
    command = "*** Begin Patch\n*** Delete File: old.py\n*** Update File: before.py\n*** Move to: after.py\n@@\n+*** Add File: fake.py\n*** Add File: a file.py\n+x\n*** End Patch"
    operations = parse_patch(command)
    assert [(o.kind, o.path, o.destination) for o in operations] == [
        ("delete", "old.py", ""), ("move", "before.py", "after.py"), ("add", "a file.py", "")]


@pytest.mark.parametrize("command", ["", "*** Update File: a.py", "*** Begin Patch\n*** Update File: a.py"])
def test_invalid_patch_is_an_explicit_error(command: str) -> None:
    from cf_codex_hook import parse_patch
    with pytest.raises(ValueError):
        parse_patch(command)


def test_subdirectory_paths_and_deleted_move_source_are_recorded(tmp_path: Path) -> None:
    import cf_log
    _project(tmp_path)
    moved = tmp_path / "src/new name.py"
    moved.write_text("SAFE\n")
    (tmp_path / "src/a.py").unlink()
    command = "*** Begin Patch\n*** Update File: a.py\n*** Move to: new name.py\n@@\n-old\n+SAFE\n*** End Patch"
    assert _invoke(tmp_path / "src", "PostToolUse", command, "Success. Updated the following files:\nM new name.py") == ""
    files = {e["data"]["file"] for e in cf_log.read_events(str(tmp_path), events=("edit",))}
    assert files == {"src/a.py", "src/new name.py"}


def test_worktree_owns_its_native_events(tmp_path: Path) -> None:
    import cf_log
    _project(tmp_path)
    worktree = tmp_path / ".code-flow/worktrees/run/task"
    _project(worktree)
    _invoke(worktree, "PreToolUse", PATCH)
    assert cf_log.read_events(str(worktree), events=("edit_intent",))
    assert not cf_log.read_events(str(tmp_path), events=("edit_intent",))


def test_outside_patch_is_reported_without_partial_evidence(tmp_path: Path) -> None:
    import cf_log
    _project(tmp_path)
    command = "*** Begin Patch\n*** Update File: src/a.py\n@@\n-old\n+new\n*** Delete File: ../foreign.py\n*** End Patch"
    result = json.loads(_invoke(tmp_path, "PreToolUse", command))
    assert "outside project" in result["systemMessage"]
    assert not cf_log.read_events(str(tmp_path), events=("edit_intent",))


def test_prompt_and_stop_use_the_native_session_directory(tmp_path: Path) -> None:
    import cf_codex_hook
    _project(tmp_path)
    data = {"cwd": str(tmp_path / "src"), "session_id": "prompt-native",
            "hook_event_name": "UserPromptSubmit", "prompt": "review src/a.py"}
    with patch("sys.stdout", io.StringIO()) as out:
        cf_codex_hook.dispatch(data)
    assert "RULE-python-001" in json.loads(out.getvalue())["hookSpecificOutput"]["additionalContext"]
    data.update(hook_event_name="Stop", stop_hook_active=True)
    with patch("sys.stdout", io.StringIO()) as out:
        cf_codex_hook.dispatch(data)
    assert out.getvalue() == ""


def test_corrupt_active_marker_injects_a_blocked_context(tmp_path: Path) -> None:
    _project(tmp_path)
    (tmp_path / ".code-flow/.active-task.json").write_text("{}")
    payload = json.loads(_invoke(tmp_path, "PreToolUse", PATCH))
    assert "SPEC_WORKFLOW_BLOCKED" in payload["hookSpecificOutput"]["additionalContext"]


@pytest.mark.parametrize("event", ["Stop", "PreToolUse", "PostToolUse", "UserPromptSubmit"])
def test_installation_drift_blocks_stop_and_diagnoses_other_events(tmp_path: Path, event: str) -> None:
    _project(tmp_path)
    (tmp_path / ".code-flow/config.yml").write_text("damaged installation")
    result = json.loads(_invoke(tmp_path, event, PATCH))
    if event == "Stop":
        assert set(result) == {"decision", "reason"}
        assert result["decision"] == "block"
        assert "drifted" in result["reason"]
    else:
        assert set(result) == {"systemMessage"}
        assert "drifted" in result["systemMessage"]


def test_native_stop_blocks_corrupt_active_task(tmp_path: Path) -> None:
    _project(tmp_path)
    (tmp_path / ".code-flow/.active-task.json").write_text("{}")
    result = json.loads(_invoke(tmp_path, "Stop", ""))
    assert set(result) == {"decision", "reason"}
    assert result["decision"] == "block"
    assert "SPEC_WORKFLOW_BLOCKED" in result["reason"]


def test_managed_hook_drift_is_visible_and_never_records_edits(tmp_path: Path) -> None:
    import cf_log
    _project(tmp_path)
    manifest_path = tmp_path / ".code-flow/.runtime-install.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["hook_contracts"] = {".codex/hooks.json": {"PostToolUse": [{"hooks": [{"command": "expected"}]}]}}
    manifest_path.write_text(json.dumps(manifest))
    (tmp_path / ".codex").mkdir()
    (tmp_path / ".codex/hooks.json").write_text('{"hooks": {}}')
    result = json.loads(_invoke(tmp_path, "PostToolUse", PATCH, "Success. Updated the following files:"))
    assert "managed hook has drifted" in result["systemMessage"]
    assert not cf_log.read_events(str(tmp_path), events=("edit",))


@pytest.mark.parametrize("response", [None, "unknown success text", {"status": "completed"}])
def test_unconfirmed_patch_result_leaves_diagnostic_evidence(tmp_path: Path, response: object) -> None:
    import cf_log
    _project(tmp_path)
    assert _invoke(tmp_path, "PostToolUse", PATCH, response) == ""
    assert not cf_log.read_events(str(tmp_path), events=("edit",))
    events = cf_log.read_events(str(tmp_path), events=("degrade",))
    assert events[-1]["data"]["component"] == "codex_post_tool"
