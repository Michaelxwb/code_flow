#!/usr/bin/env python3
"""S-04/B-02 coverage for exact TASK session projection."""

from pathlib import Path
import re
import subprocess
import sys

import yaml


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "src/core/code-flow/scripts"
sys.path.insert(0, str(SCRIPTS))

from cf_spec_context import BindingInput, bind_specs, load_context, new_context, save_context
from cf_spec_resolver import resolve_candidates
from cf_spec_session import context_sha256, project_task_session


def _spec(count: int) -> str:
    verifiers = "\n".join(
        f"  - rule: RULE-session-{index:03d}\n    type: test\n    config:\n      command: pytest -q"
        for index in range(1, count + 1)
    )
    rules = "\n".join(
        f"- [RULE-session-{index:03d}] Required session rule {index}."
        for index in range(1, count + 1)
    )
    return (
        "---\nid: session-rules\ndescription: Session rules\nstages: [code, review]\n"
        f"enforcement: required\nverifiers:\n{verifiers}\n---\n\n# Rules\n\n## Rules\n{rules}\n"
    )


def _project(tmp_path: Path, count: int) -> tuple[Path, Path, Path]:
    spec = tmp_path / ".code-flow/specs/app/rules.md"
    spec.parent.mkdir(parents=True)
    spec.write_text(_spec(count), encoding="utf-8")
    config = {"path_mapping": {"app": {"patterns": ["src/*"], "specs": [{"path": "app/rules.md"}]}}}
    (tmp_path / ".code-flow/config.yml").write_text(yaml.safe_dump(config), encoding="utf-8")
    task_dir = tmp_path / ".code-flow/tasks/demo"
    task_dir.mkdir(parents=True)
    candidate = resolve_candidates(str(tmp_path), "code", ["src/app.py"])[0]
    context = bind_specs(new_context("demo", (("test", "session"),)), (BindingInput(candidate, "plan", "task refs"),))
    save_context(str(task_dir / "spec-context.yml"), context)
    refs = ", ".join(f"session-rules#RULE-session-{index:03d}" for index in range(1, count + 1))
    task_file = task_dir / "demo.md"
    task_file.write_text(
        f"# Tasks\n\n## TASK-001: Current\n- **Source**: demo.design.md#3\n- **Spec-Refs**: {refs}\n"
        "### Acceptance Contract\n| S-04 | E2E | Task, Context, session | exact refs |\n\n"
        "## TASK-002: Other\n- **Spec-Refs**: other#RULE-other-001\n",
        encoding="utf-8",
    )
    return task_dir, task_file, task_dir / "session.md"


def test_s_04_projects_only_current_task_with_hashes(tmp_path: Path) -> None:
    task_dir, task_file, output = _project(tmp_path, 2)
    context = load_context(str(task_dir / "spec-context.yml"))

    result = project_task_session(context, str(task_file), "TASK-001", 4000)
    output.write_text(result.text, encoding="utf-8")

    assert result.total_rules == 2
    assert result.included_rules == 2
    assert context_sha256(context) in result.text
    assert "RULE-session-001" in result.text
    assert "RULE-other-001" not in result.text
    assert "Acceptance Contract" in result.text
    assert "Catalog" not in result.text


def test_b_02_large_task_is_bounded_without_mutating_context(tmp_path: Path) -> None:
    task_dir, task_file, unused_output = _project(tmp_path, 50)
    del unused_output
    before = (task_dir / "spec-context.yml").read_bytes()
    context = load_context(str(task_dir / "spec-context.yml"))

    result = project_task_session(context, str(task_file), "TASK-001", 1200)

    assert result.truncated is True
    assert result.included_rules < result.total_rules == 50
    assert len(result.text) <= 1200
    assert "请拆分 TASK" in result.text
    assert (task_dir / "spec-context.yml").read_bytes() == before


def test_default_budget_does_not_truncate_many_required_rules(tmp_path: Path) -> None:
    """A realistic 10-rule TASK with a wide contract must not hit task_projection_truncated."""
    count = 10
    long_rules = "\n".join(
        f"- [RULE-session-{i:03d}] Required session rule {i} must keep deterministic routing and fail-closed stage gates without silently dropping required constraints under budget pressure."
        for i in range(1, count + 1)
    )
    long_verifiers = "\n".join(
        f"  - rule: RULE-session-{i:03d}\n    type: test\n    config:\n      command: pytest -q"
        for i in range(1, count + 1)
    )
    spec_path = tmp_path / ".code-flow/specs/app/rules.md"
    spec_path.parent.mkdir(parents=True)
    spec_path.write_text(
        "---\nid: session-rules\ndescription: Session rules\nstages: [code]\n"
        f"enforcement: required\nverifiers:\n{long_verifiers}\n---\n\n# Rules\n\n## Rules\n{long_rules}\n",
        encoding="utf-8",
    )
    config = {"path_mapping": {"app": {"patterns": ["src/*"], "specs": [{"path": "app/rules.md"}]}}}
    (tmp_path / ".code-flow/config.yml").write_text(yaml.safe_dump(config), encoding="utf-8")
    task_dir = tmp_path / ".code-flow/tasks/demo"
    task_dir.mkdir(parents=True)
    candidate = resolve_candidates(str(tmp_path), "code", ["src/app.py"])[0]
    context = bind_specs(new_context("demo", (("test", "budget"),)), (BindingInput(candidate, "plan", "task refs"),))
    save_context(str(task_dir / "spec-context.yml"), context)
    refs = ", ".join(f"session-rules#RULE-session-{i:03d}" for i in range(1, count + 1))
    contract = "\n".join(
        f"| S-{i:02d} | integration | service, store, real fixture | assert observable {i} | tests/test_{i:02d}.py | pytest -q | planned |"
        for i in range(1, 9)
    )
    task_file = task_dir / "demo.md"
    task_file.write_text(
        f"# Tasks\n\n## TASK-001: Big\n- **Source**: demo.design.md#3\n- **Spec-Refs**: {refs}\n"
        f"### Acceptance Contract\n{contract}\n",
        encoding="utf-8",
    )
    context = load_context(str(task_dir / "spec-context.yml"))

    tight = project_task_session(context, str(task_file), "TASK-001", 4000)
    result = project_task_session(context, str(task_file), "TASK-001")

    assert tight.truncated is True, "scenario must exceed the old 4000 budget"
    assert result.truncated is False
    assert result.included_rules == result.total_rules == count


def test_start_workflow_refreshes_before_hash_bound_activation() -> None:
    for path in (
        ROOT / "src/adapters/claude/commands/cf-task/start.md",
        ROOT / "src/adapters/codex/skills/cf-task-start/SKILL.md",
        ROOT / "src/adapters/costrict/commands/cf-task/start.md",
        ROOT / "src/adapters/opencode/commands/cf-task/start.md",
    ):
        text = path.read_text(encoding="utf-8")
        refresh = text.index("cf_spec_context.py start")
        active = text.index("active start", refresh)
        session = text.index("session 输出路径", active)
        progress = text.index("in-progress", session)
        assert refresh < active < session < progress
        assert "禁止先 start 再 refresh" in text
        assert "禁止重新 catalog" in text
        section = text.split("### 3. 激活并准备验收测试", 1)[1].split("RED 证据写入", 1)[0]
        assert [int(value) for value in re.findall(r"(?m)^(\d+)\. ", section)] == list(range(1, 7))
