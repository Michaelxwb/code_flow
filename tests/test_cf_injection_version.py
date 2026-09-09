#!/usr/bin/env python3
"""[S-05] 跨 TASK 注入版本键回归测试。

真实边界：真实 git 仓库 + 真实 Hook 主入口（stdin/stdout mock，仅截获 IO）。
同 Context 切 TASK 后必须重注；同 TASK 重复 prompt 不重复注入。
"""
import io
import json
import subprocess
from pathlib import Path
import sys
from unittest import mock

import yaml


SCRIPTS = Path(__file__).resolve().parents[1] / "src/core/code-flow/scripts"
sys.path.insert(0, str(SCRIPTS))

from cf_spec_context import (  # noqa: E402
    BindingInput,
    bind_specs,
    complete_active_task,
    new_context,
    save_context,
    start_active_task,
)
from cf_spec_resolver import resolve_candidates  # noqa: E402
from cf_spec_session import context_sha256  # noqa: E402
from cf_spec_context import load_context  # noqa: E402
import cf_user_prompt_hook as prompt_hook  # noqa: E402
import cf_pre_tool_hook as pre_tool_hook  # noqa: E402


def _git(root: Path, *args: str) -> None:
    subprocess.run(("git", *args), cwd=root, check=True, capture_output=True)


def _repo(tmp_path: Path) -> Path:
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "t@t")
    _git(tmp_path, "config", "user.name", "t")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
    spec = tmp_path / ".code-flow/specs/app/rules.md"
    spec.parent.mkdir(parents=True)
    spec.write_text(
        "---\nid: app-runtime\ndescription: rules\nstages: [code]\n"
        "enforcement: required\n"
        "verifiers:\n  - rule: RULE-app-001\n    type: regex\n"
        "    config:\n      pattern: 'VALUE = 2'\n      files: '*.py'\n"
        "---\n\n# Rule\n## Rules\n- [RULE-app-001] Value must stay constant.\n",
        encoding="utf-8",
    )
    config = {
        "spec_workflow": {"schema_version": 1, "enforcement": "required"},
        "path_mapping": {"app": {"patterns": ["src/*"], "specs": [{"path": "app/rules.md"}]}},
    }
    (tmp_path / ".code-flow/config.yml").write_text(yaml.safe_dump(config), encoding="utf-8")
    task_dir = tmp_path / ".code-flow/tasks/demo"
    task_dir.mkdir(parents=True)
    (task_dir / "demo.md").write_text(
        "## TASK-001: First\n"
        "- **Status**: draft\n"
        "- **Spec-Refs**: app-runtime#RULE-app-001\n"
        "- **Acceptance-Refs**: S-01\n"
        "### Acceptance Contract\n- S-01: first contract\n"
        "### Acceptance Evidence\nnone\n"
        "## TASK-002: Second\n"
        "- **Status**: draft\n"
        "- **Spec-Refs**: app-runtime#RULE-app-001\n"
        "- **Acceptance-Refs**: S-99\n"
        "### Acceptance Contract\n- S-99: second contract\n"
        "### Acceptance Evidence\nnone\n",
        encoding="utf-8",
    )
    candidate = resolve_candidates(str(tmp_path), "code", ["src/app.py"])[0]
    context = bind_specs(new_context("demo", (("test", "switch"),)), (BindingInput(candidate, "plan", "app"),))
    save_context(str(task_dir / "spec-context.yml"), context)
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-qm", "init")
    return tmp_path


def _ctx(root: Path) -> str:
    return context_sha256(load_context(str(root / ".code-flow/tasks/demo/spec-context.yml")))


def _prompt(root: Path, text: str = "continue working") -> str:
    output = io.StringIO()
    payload = json.dumps({"prompt": text, "session_id": "s-1"})
    with mock.patch("sys.stdin", io.StringIO(payload)), mock.patch("sys.stdout", output), mock.patch(
        "os.getcwd", return_value=str(root)
    ):
        prompt_hook.main()
    raw = output.getvalue()
    if not raw.strip():
        return ""
    return json.loads(raw)["hookSpecificOutput"]["additionalContext"]


def _pretool(root: Path) -> str:
    output = io.StringIO()
    payload = json.dumps({"tool_name": "Edit", "tool_input": {"file_path": "src/app.py"}, "session_id": "s-1"})
    with mock.patch("sys.stdin", io.StringIO(payload)), mock.patch("sys.stdout", output), mock.patch(
        "os.getcwd", return_value=str(root)
    ):
        pre_tool_hook.main()
    raw = output.getvalue()
    if not raw.strip():
        return ""
    return json.loads(raw)["hookSpecificOutput"]["additionalContext"]


def test_switch_task_reinjects_same_context(tmp_path: Path) -> None:
    """[S-05] Prompt：切 TASK 后必须重注，同 TASK 不重复。"""
    root = _repo(tmp_path)
    start_active_task(str(root), ".code-flow/tasks/demo", "TASK-001", _ctx(root), ())
    first = _prompt(root)
    assert "S-01" in first
    assert _prompt(root) == "", "同 TASK 同契约不得重复注入"
    complete_active_task(str(root), True)
    start_active_task(str(root), ".code-flow/tasks/demo", "TASK-002", _ctx(root), ())
    third = _prompt(root)
    assert "S-99" in third, "同 Context 切 TASK 后必须注入新契约"
    assert _prompt(root) == ""


def test_pretool_switch_task_reinjects(tmp_path: Path) -> None:
    """[S-05] PreTool：切 TASK 后必须重注。"""
    root = _repo(tmp_path)
    start_active_task(str(root), ".code-flow/tasks/demo", "TASK-001", _ctx(root), ())
    _prompt(root)
    assert _pretool(root) == ""
    complete_active_task(str(root), True)
    start_active_task(str(root), ".code-flow/tasks/demo", "TASK-002", _ctx(root), ())
    assert "S-99" in _pretool(root)
