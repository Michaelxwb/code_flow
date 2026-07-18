#!/usr/bin/env python3
"""Context-first UserPromptSubmit path extraction and fail-closed protocol."""

import io
import json
from pathlib import Path
import sys
from unittest import mock

import yaml

SCRIPTS = Path(__file__).resolve().parents[1] / "src/core/code-flow/scripts"
sys.path.insert(0, str(SCRIPTS))

from cf_user_prompt_hook import extract_paths_from_prompt, main


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
