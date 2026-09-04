from pathlib import Path
import json
import sys

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "src/core/code-flow/scripts"
sys.path.insert(0, str(SCRIPTS))

from cf_acceptance_manifest import extract_manifest, record_manual_evidence, validate_manifest, write_manifest


TASK = """# Tasks\n\n## Acceptance Coverage\n| 场景ID | 来源设计 | 测试层级 | 关键真实边界 | 负责任务 | 状态 |\n|--------|---------|---------|-------------|---------|------|\n| S-01 | design#1 | integration | service -> store | TASK-001 | planned |\n\n## TASK-001: Demo\n- **Acceptance-Refs**: S-01\n"""


def test_manifest_lock_and_detects_task_drift(tmp_path: Path) -> None:
    task = tmp_path / "demo.md"
    manifest = tmp_path / ".acceptance-manifest.json"
    task.write_text(TASK, encoding="utf-8")
    locked = write_manifest(str(task), str(manifest))
    assert len(locked["scenarios"]) == 1
    assert locked["scenarios"][0]["kind"] == "functional"
    assert locked["task_file"] == "demo.md"
    assert validate_manifest(str(task), str(manifest)) == (True, "")
    task.write_text(TASK.replace("service -> store", "service -> queue"), encoding="utf-8")
    assert validate_manifest(str(task), str(manifest))[0] is False


def test_manifest_requires_coverage_table(tmp_path: Path) -> None:
    task = tmp_path / "empty.md"
    task.write_text("# Tasks\n", encoding="utf-8")
    with pytest.raises(ValueError):
        extract_manifest(str(task))


def test_manual_evidence_requires_user_and_marks_verified(tmp_path: Path) -> None:
    task = tmp_path / "manual.md"
    manifest = tmp_path / ".acceptance-manifest.json"
    task.write_text(TASK.replace("integration", "manual"), encoding="utf-8")
    write_manifest(str(task), str(manifest))
    with pytest.raises(ValueError):
        record_manual_evidence(str(manifest), "S-01", "agent:codex", "done")
    record_manual_evidence(str(manifest), "S-01", "user:jahan", "screenshot:/tmp/a.png")
    assert json.loads(manifest.read_text(encoding="utf-8"))["scenarios"][0]["status"] == "verified"
    assert "S-01: verified" in task.read_text(encoding="utf-8")


def test_manual_evidence_syncs_to_owning_task_section(tmp_path: Path) -> None:
    task = tmp_path / "multi.md"
    manifest = tmp_path / ".acceptance-manifest.json"
    task.write_text(
        "# Tasks\n\n"
        "## Acceptance Coverage\n"
        "| 场景ID | 来源设计 | 测试层级 | 关键真实边界 | 负责任务 | 状态 |\n"
        "|--------|---------|---------|-------------|---------|------|\n"
        "| S-01 | design#1 | manual | real | TASK-002 | planned |\n\n"
        "## TASK-001: First\n- **Acceptance-Refs**:\n\n"
        "## TASK-002: Second\n- **Acceptance-Refs**: S-01\n",
        encoding="utf-8",
    )
    write_manifest(str(task), str(manifest))
    record_manual_evidence(str(manifest), "S-01", "user:jahan", "screenshot:/tmp/a.png")
    text = task.read_text(encoding="utf-8")
    before, after = text.split("## TASK-002:", 1)
    assert "S-01: verified" not in before
    assert "S-01: verified" in "## TASK-002:" + after
