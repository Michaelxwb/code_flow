#!/usr/bin/env python3
"""[S-06][E-06] 统一 workflow service 与 Start 硬门禁回归测试。

真实边界：真实 git 仓库 + 真实 service 状态机（无 mock）。
"""
import subprocess
import sys
from pathlib import Path

import pytest


SCRIPTS = Path(__file__).resolve().parents[1] / "src/core/code-flow/scripts"
sys.path.insert(0, str(SCRIPTS))

from cf_workflow_service import WorkflowError, block_task, complete_task, resume_task, start_task  # noqa: E402
from cf_spec_context import load_active_task  # noqa: E402


def _git(root: Path, *args: str) -> None:
    subprocess.run(("git", *args), cwd=root, check=True, capture_output=True)


def _repo(tmp_path: Path, sections: str) -> tuple[Path, Path]:
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "t@t")
    _git(tmp_path, "config", "user.name", "t")
    task_dir = tmp_path / "demand"
    task_dir.mkdir()
    (task_dir / "work.md").write_text(sections, encoding="utf-8")
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
    (tmp_path / ".code-flow" / "config.yml").write_text(
        "spec_workflow:\n  schema_version: 1\n  enforcement: required\n"
        "path_mapping:\n  app:\n    patterns: ['src/*']\n    specs: [{path: app/rules.md}]\n",
        encoding="utf-8",
    )
    from cf_spec_context import BindingInput, bind_specs, new_context, save_context
    from cf_spec_resolver import resolve_candidates

    candidate = resolve_candidates(str(tmp_path), "code", ["src/app.py"])[0]
    save_context(
        str(task_dir / "spec-context.yml"),
        bind_specs(new_context("demo", (("test", "wf"),)), (BindingInput(candidate, "service", "app"),)),
    )
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-qm", "init")
    return tmp_path, task_dir


def _section(task_id: str, status: str, depends: str = "", notes: str = "", refs: str = "S-01") -> str:
    return (
        f"## {task_id}: Demo\n- **Status**: {status}\n- **Depends**: {depends}\n"
        f"- **Spec-Refs**: app-runtime#RULE-app-001\n"
        f"- **Acceptance-Refs**: {refs}\n### Acceptance Contract\n- S-01: x\n"
        f"### Acceptance Evidence\nnone\n{notes}"
        "### Log\n- [2026-01-01] created (draft)\n"
    )


def test_start_refuses_blocked_notes_and_missing_depends_together(tmp_path: Path) -> None:
    """[S-06] 三缺口一次指全并阻断。"""
    root, task_dir = _repo(
        tmp_path,
        _section("TASK-001", "blocked", "TASK-999", "> 讨论 #NOTES 选型未定\n"),
    )
    with pytest.raises(WorkflowError) as exc_info:
        start_task(str(root), str(task_dir), str(task_dir / "work.md"), "TASK-001", ())
    message = str(exc_info.value)
    assert exc_info.value.code == "start_blocked"
    assert "blocked" in message and "NOTES" in message and "TASK-999" in message


def test_start_draft_activates_and_marks_in_progress(tmp_path: Path) -> None:
    root, task_dir = _repo(tmp_path, _section("TASK-001", "draft"))
    result = start_task(str(root), str(task_dir), str(task_dir / "work.md"), "TASK-001", ())
    assert result["ok"] is True
    assert result["active"]["task_id"] == "TASK-001"
    assert load_active_task(str(root)).task_id == "TASK-001"
    text = (task_dir / "work.md").read_text(encoding="utf-8")
    assert "- **Status**: in-progress" in text


def test_block_and_resume_sync_marker_and_markdown(tmp_path: Path) -> None:
    """[S-06] block/resume 双写一致，无 active_exists 残留。"""
    root, task_dir = _repo(tmp_path, _section("TASK-001", "draft"))
    start_task(str(root), str(task_dir), str(task_dir / "work.md"), "TASK-001", ())
    blocked = block_task(str(root), str(task_dir), str(task_dir / "work.md"), "TASK-001", "wait sdk")
    assert blocked["markdown"] == "synced"
    assert load_active_task(str(root)).status == "blocked"
    text = (task_dir / "work.md").read_text(encoding="utf-8")
    assert "- **Status**: blocked" in text and "wait sdk" in text
    resumed = resume_task(str(root), str(task_dir), str(task_dir / "work.md"), "TASK-001")
    assert load_active_task(str(root)).status == "active"
    assert "- **Status**: in-progress" in (task_dir / "work.md").read_text(encoding="utf-8")
    assert resumed["markdown"] == "synced"


def test_done_marker_with_active_marker_refuses_with_doctor_hint(tmp_path: Path) -> None:
    """[E-06] Markdown done + marker active 拒绝新 start 并给恢复步骤。"""
    root, task_dir = _repo(tmp_path, _section("TASK-001", "done"))
    from cf_spec_context import start_active_task

    start_active_task(str(root), str(task_dir), "TASK-001", "ctx")
    with pytest.raises(WorkflowError) as exc_info:
        start_task(str(root), str(task_dir), str(task_dir / "work.md"), "TASK-001", ())
    assert "active_exists" in str(exc_info.value) or "doctor" in str(exc_info.value).lower()


def test_complete_requires_gate_and_syncs_done(tmp_path: Path) -> None:
    root, task_dir = _repo(tmp_path, _section("TASK-001", "draft"))
    start_task(str(root), str(task_dir), str(task_dir / "work.md"), "TASK-001", ())
    with pytest.raises(WorkflowError):
        complete_task(str(root), str(task_dir), str(task_dir / "work.md"), "TASK-001", False)
    done = complete_task(str(root), str(task_dir), str(task_dir / "work.md"), "TASK-001", True)
    assert done["ok"] is True
    assert "- **Status**: done" in (task_dir / "work.md").read_text(encoding="utf-8")


def _task_doc(with_log: bool = True) -> str:
    """真实 plan 产物格式：任务段落以 `---` 分隔符结尾，下一节前有空行。"""
    log = "### Log\n- [2026-10-03] created (draft)\n\n" if with_log else ""
    return (
        "## TASK-001: Demo\n- **Status**: draft\n"
        "- **Spec-Refs**: app-runtime#RULE-app-001\n"
        "- **Acceptance-Refs**: S-01\n"
        "### Acceptance Contract\n- S-01: x\n"
        "### Acceptance Evidence\nnone\n"
        f"{log}---\n\n"
        "## TASK-002: Other\n- **Status**: draft\n"
        "- **Spec-Refs**: app-runtime#RULE-app-001\n"
        "- **Acceptance-Refs**: S-01\n"
        "### Acceptance Contract\n- S-01: x\n"
        "### Acceptance Evidence\nnone\n"
        "### Log\n- [2026-10-03] created (draft)\n\n---\n"
    )


def test_lifecycle_entries_stay_inside_log_list(tmp_path: Path) -> None:
    """start/block/resume 记录必须落在 ### Log 列表内（回归：曾落在 --- 之后）。"""
    root, task_dir = _repo(tmp_path, _task_doc())

    start_task(str(root), str(task_dir), str(task_dir / "work.md"), "TASK-001", ())
    block_task(str(root), str(task_dir), str(task_dir / "work.md"), "TASK-001", "wait sdk")
    resume_task(str(root), str(task_dir), str(task_dir / "work.md"), "TASK-001")

    text = (task_dir / "work.md").read_text(encoding="utf-8")
    region = text.split("## TASK-002:", 1)[0]
    log_body = region.split("### Log", 1)[1].split("---", 1)[0]
    tail = region.split("---", 1)[1]
    assert log_body.count("- [") == 4, log_body  # created + started + blocked + resumed
    assert "- [" not in tail, "生命周期记录不得落在分隔符之后"
    assert "> BLOCKED: wait sdk" in region
    assert region.index("> BLOCKED: wait sdk") < region.index("### Log")
    assert "\n\n## TASK-002" in text, "下一节前的空行必须保留"


def test_log_section_created_before_trailing_separator(tmp_path: Path) -> None:
    """无 ### Log 段落：新建小节必须落在尾部分隔符之前，不破坏后续结构。"""
    root, task_dir = _repo(tmp_path, _task_doc(with_log=False))

    start_task(str(root), str(task_dir), str(task_dir / "work.md"), "TASK-001", ())

    text = (task_dir / "work.md").read_text(encoding="utf-8")
    region = text.split("## TASK-002:", 1)[0]
    assert "\n\n### Log\n- [" in region
    assert region.index("### Log") < region.index("---")
    assert "- [" not in region.split("---", 1)[1]
    assert "\n\n## TASK-002" in text


def test_log_inserted_before_last_separator_when_body_has_rule(tmp_path: Path) -> None:
    """段落正文含 `---` 横线时，以最后一个分隔符为锚点（项目补丁曾取第一个）。"""
    doc = _task_doc(with_log=False).replace(
        "### Acceptance Evidence\nnone\n",
        "### Acceptance Evidence\nnone\n\n---\n\n> 段落内横线示例\n",
    )
    root, task_dir = _repo(tmp_path, doc)

    start_task(str(root), str(task_dir), str(task_dir / "work.md"), "TASK-001", ())

    region = (task_dir / "work.md").read_text(encoding="utf-8").split("## TASK-002:", 1)[0]
    assert region.index("### Log") > region.index("段落内横线示例")
    assert region.rindex("---") > region.index("### Log")
    assert region.index("---") < region.index("### Log")
