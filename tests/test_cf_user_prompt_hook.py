#!/usr/bin/env python3
"""Context-first UserPromptSubmit path extraction and fail-closed protocol."""

import io
import json
from pathlib import Path
import subprocess
import sys
from unittest import mock

import yaml

SCRIPTS = Path(__file__).resolve().parents[1] / "src/core/code-flow/scripts"
sys.path.insert(0, str(SCRIPTS))

from cf_user_prompt_hook import _session_reminder, extract_paths_from_prompt, main


def test_extracts_supported_path_forms_and_normalizes_windows() -> None:
    prompt = "edit src/a.py, @src\\b.py, and `src/c.js`"
    assert extract_paths_from_prompt(prompt) == ["src/a.py", "src/b.py", "src/c.js"]


def test_extracts_path_followed_by_chinese_and_deduplicates() -> None:
    assert extract_paths_from_prompt("修改 src/a.py和src/a.py，再看 src/b.py") == ["src/a.py", "src/b.py"]


def test_ignores_versions_and_plain_words() -> None:
    assert extract_paths_from_prompt("use version 1.2.3 and README") == []


def _run(root: Path, prompt: str) -> dict:
    output = io.StringIO()
    payload = json.dumps({"prompt": prompt, "session_id": "session-1"})
    with mock.patch("sys.stdin", io.StringIO(payload)), mock.patch("sys.stdout", output), mock.patch("os.getcwd", return_value=str(root)):
        main()
    return json.loads(output.getvalue())


def test_no_task_no_path_emits_catalog_and_schema_one_state(tmp_path: Path) -> None:
    spec = tmp_path / ".code-flow/specs/app/rules.md"
    spec.parent.mkdir(parents=True)
    spec.write_text("# Rules\n", encoding="utf-8")
    config = {
        "spec_workflow": {"schema_version": 1, "enforcement": "required", "catalog": {"dedup_window": 5}},
        "path_mapping": {"app": {"patterns": ["src/*"], "specs": [{"path": "app/rules.md"}]}},
    }
    (tmp_path / ".code-flow/config.yml").write_text(yaml.safe_dump(config), encoding="utf-8")
    result = _run(tmp_path, "explain architecture")
    assert "Spec Catalog" in result["hookSpecificOutput"]["additionalContext"]
    state = json.loads((tmp_path / ".code-flow/.catalog-state.json").read_text(encoding="utf-8"))
    assert state == {"version": 1, "session_id": "session-1", "prompt_count": 1, "last_emitted": 1}


def test_invalid_path_spec_metadata_is_fail_closed(tmp_path: Path) -> None:
    spec = tmp_path / ".code-flow/specs/app/rules.md"
    spec.parent.mkdir(parents=True)
    spec.write_text("# missing metadata\n", encoding="utf-8")
    config = {
        "spec_workflow": {"schema_version": 1, "enforcement": "required"},
        "path_mapping": {"app": {"patterns": ["src/*"], "specs": [{"path": "app/rules.md"}]}},
    }
    (tmp_path / ".code-flow/config.yml").write_text(yaml.safe_dump(config), encoding="utf-8")
    result = _run(tmp_path, "edit src/app.py")
    assert "SPEC_WORKFLOW_BLOCKED" in result["hookSpecificOutput"]["additionalContext"]


def _reminder_config(tmp_path: Path, enabled: bool = True) -> None:
    (tmp_path / ".code-flow").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".code-flow/config.yml").write_text(
        yaml.safe_dump(
            {
                "spec_workflow": {"schema_version": 1, "enforcement": "required"},
                "quality_loop": {"enabled": True, "compress_reminder": enabled},
            }
        ),
        encoding="utf-8",
    )


def _run_output(root: Path, prompt: str, sid: str = "session-1") -> str:
    output = io.StringIO()
    payload = json.dumps({"prompt": prompt, "session_id": sid})
    with mock.patch("sys.stdin", io.StringIO(payload)), mock.patch("sys.stdout", output), mock.patch("os.getcwd", return_value=str(root)):
        main()
    return output.getvalue()


def test_session_reminder_fires_every_interval(tmp_path: Path) -> None:
    _reminder_config(tmp_path)
    for _ in range(24):
        assert _session_reminder(str(tmp_path), "s1") == ""
    assert "压缩上下文" in _session_reminder(str(tmp_path), "s1")  # 25th
    assert _session_reminder(str(tmp_path), "s1") == ""            # 26th
    for _ in range(23):
        assert _session_reminder(str(tmp_path), "s1") == ""        # 27..49
    assert "压缩上下文" in _session_reminder(str(tmp_path), "s1")  # 50th


def test_session_reminder_new_session_resets_counter(tmp_path: Path) -> None:
    _reminder_config(tmp_path)
    for _ in range(25):
        _session_reminder(str(tmp_path), "s1")
    for _ in range(24):
        assert _session_reminder(str(tmp_path), "s2") == ""
    assert "压缩上下文" in _session_reminder(str(tmp_path), "s2")


def test_session_reminder_disabled_is_zero_io(tmp_path: Path) -> None:
    _reminder_config(tmp_path, enabled=False)
    assert _session_reminder(str(tmp_path), "s1") == ""
    assert not (tmp_path / ".code-flow/.session-state.json").exists()


def test_compress_reminder_appears_after_25_prompts(tmp_path: Path) -> None:
    _reminder_config(tmp_path)
    for _ in range(24):
        assert "压缩上下文" not in _run_output(tmp_path, "hello")
    assert "压缩上下文" in _run_output(tmp_path, "hello")


def test_corrupt_session_state_does_not_break_hook(tmp_path: Path) -> None:
    spec = tmp_path / ".code-flow/specs/app/rules.md"
    spec.parent.mkdir(parents=True)
    spec.write_text("# Rules\n", encoding="utf-8")
    config = {
        "spec_workflow": {"schema_version": 1, "enforcement": "required", "catalog": {"dedup_window": 5}},
        "path_mapping": {"app": {"patterns": ["src/*"], "specs": [{"path": "app/rules.md"}]}},
        "quality_loop": {"enabled": True, "compress_reminder": True},
    }
    (tmp_path / ".code-flow/config.yml").write_text(yaml.safe_dump(config), encoding="utf-8")
    state = tmp_path / ".code-flow/.session-state.json"
    state.write_text(
        json.dumps({"session_id": "session-1", "prompt_count": "abc", "next_remind_at": None}),
        encoding="utf-8",
    )
    assert _session_reminder(str(tmp_path), "session-1") == ""
    result = _run(tmp_path, "explain architecture")
    assert "Spec Catalog" in result["hookSpecificOutput"]["additionalContext"]


def _task_repo(tmp_path: Path) -> Path:
    """Minimal active-task repo: one bound spec + committed git + marker."""
    spec = tmp_path / ".code-flow/specs/app/rules.md"
    spec.parent.mkdir(parents=True)
    spec.write_text(
        "---\nid: app-runtime\ndescription: app rules\nstages: [code]\nenforcement: required\n"
        "verifiers:\n  - rule: RULE-app-001\n    type: regex\n    config: {pattern: VALUE}\n"
        "---\n# Rules\n## Rules\n- [RULE-app-001] Must define VALUE.\n",
        encoding="utf-8",
    )
    config = {
        "spec_workflow": {"schema_version": 1, "enforcement": "required"},
        "path_mapping": {"app": {"patterns": ["src/*"], "specs": [{"path": "app/rules.md"}]}},
    }
    (tmp_path / ".code-flow/config.yml").write_text(yaml.safe_dump(config), encoding="utf-8")
    (tmp_path / "src").mkdir()
    (tmp_path / "src/app.py").write_text("VALUE = 1\n", encoding="utf-8")
    subprocess.run(("git", "init", "-q"), cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(("git", "config", "user.email", "t@t"), cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(("git", "config", "user.name", "t"), cwd=tmp_path, check=True, capture_output=True)
    task_dir = tmp_path / ".code-flow/tasks/demo"
    task_dir.mkdir(parents=True)
    (task_dir / "demo.md").write_text(
        "# Tasks\n\n## TASK-001: Demo\n- **Spec-Refs**: app-runtime#RULE-app-001\n"
        "### Acceptance Contract\n| S-01 | unit | real | assert |\n",
        encoding="utf-8",
    )
    sys.path.insert(0, str(SCRIPTS))
    from cf_spec_context import BindingInput, bind_specs, context_sha256, load_context, new_context, save_context, start_active_task
    from cf_spec_resolver import resolve_candidates

    candidate = resolve_candidates(str(tmp_path), "code", ["src/app.py"])[0]
    context = bind_specs(new_context("demo", (("test", "dedup"),)), (BindingInput(candidate, "plan", "app"),))
    save_context(str(task_dir / "spec-context.yml"), context)
    subprocess.run(("git", "add", "-A"), cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(("git", "commit", "-qm", "init"), cwd=tmp_path, check=True, capture_output=True)
    start_active_task(str(tmp_path), ".code-flow/tasks/demo", "TASK-001", context_sha256(load_context(str(task_dir / "spec-context.yml"))))
    return tmp_path


def _run_raw(root: Path, prompt: str, sid: str = "session-1") -> str:
    output = io.StringIO()
    payload = json.dumps({"prompt": prompt, "session_id": sid})
    with mock.patch("sys.stdin", io.StringIO(payload)), mock.patch("sys.stdout", output), mock.patch("os.getcwd", return_value=str(root)):
        main()
    return output.getvalue()


def test_task_projection_injected_once_then_deduped(tmp_path: Path) -> None:
    root = _task_repo(tmp_path)

    first = _run_raw(root, "继续 TASK-001")
    second = _run_raw(root, "继续 TASK-001")
    assert "TASK-001 Spec Context" in first
    assert second == "", "unchanged context must not re-inject the projection"


def test_task_projection_reinjected_after_context_change(tmp_path: Path) -> None:
    root = _task_repo(tmp_path)
    _run_raw(root, "继续 TASK-001")
    task_dir = root / ".code-flow/tasks/demo"
    from cf_spec_context import BindingInput, bind_specs, context_sha256, load_context, resync_active_hash, save_context
    from cf_spec_resolver import resolve_candidates

    candidate = resolve_candidates(str(root), "code", ["src/app.py"])[0]
    context = bind_specs(load_context(str(task_dir / "spec-context.yml")), (BindingInput(candidate, "plan", "changed reason"),))
    save_context(str(task_dir / "spec-context.yml"), context)
    resync_active_hash(str(root), str(task_dir), context_sha256(load_context(str(task_dir / "spec-context.yml"))))

    third = _run_raw(root, "继续 TASK-001")
    assert "TASK-001 Spec Context" in third, "context change must re-inject"


def test_inject_enforcement_degrades_router_error_silently(tmp_path: Path) -> None:
    spec = tmp_path / ".code-flow/specs/app/rules.md"
    spec.parent.mkdir(parents=True)
    spec.write_text("# missing metadata\n", encoding="utf-8")
    config = {
        "spec_workflow": {"schema_version": 1, "enforcement": "inject"},
        "path_mapping": {"app": {"patterns": ["src/*"], "specs": [{"path": "app/rules.md"}]}},
    }
    (tmp_path / ".code-flow/config.yml").write_text(yaml.safe_dump(config), encoding="utf-8")

    assert _run_raw(tmp_path, "edit src/app.py") == ""


def test_warn_enforcement_degrades_router_error_to_advisory(tmp_path: Path) -> None:
    spec = tmp_path / ".code-flow/specs/app/rules.md"
    spec.parent.mkdir(parents=True)
    spec.write_text("# missing metadata\n", encoding="utf-8")
    config = {
        "spec_workflow": {"schema_version": 1, "enforcement": "warn"},
        "path_mapping": {"app": {"patterns": ["src/*"], "specs": [{"path": "app/rules.md"}]}},
    }
    (tmp_path / ".code-flow/config.yml").write_text(yaml.safe_dump(config), encoding="utf-8")

    text = _run_raw(tmp_path, "edit src/app.py")
    assert "warn 模式" in text
    assert "SPEC_WORKFLOW_BLOCKED" not in text


def test_task_projection_refreshes_every_interval_without_reminder(tmp_path: Path) -> None:
    root = _task_repo(tmp_path)  # no quality_loop → compress_reminder off
    _run_raw(root, "继续 TASK-001")  # 1st injects
    for _ in range(24):
        assert _run_raw(root, "继续 TASK-001") == ""  # 2..25 skipped
    assert "TASK-001 Spec Context" in _run_raw(root, "继续 TASK-001")  # 26th refreshes
