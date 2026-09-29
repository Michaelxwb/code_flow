from pathlib import Path
import json
import sys

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "src/core/code-flow/scripts"
sys.path.insert(0, str(SCRIPTS))

from cf_acceptance_manifest import (
    _kind,
    _legacy_kind,
    extract_manifest,
    record_manual_evidence,
    validate_manifest,
    write_manifest,
)


def test_legacy_annotated_e2e_manifest_is_healed(tmp_path: Path) -> None:
    """旧版精确匹配把带注解的 E2E 锁成 functional；内容未变时应自动升级并保留 evidence。"""
    task = tmp_path / "demo.md"
    manifest = tmp_path / ".acceptance-manifest.json"
    task.write_text(
        "# Tasks\n\n## Acceptance Coverage\n"
        "| 场景ID | 来源设计 | 测试层级 | 关键真实边界 | 负责任务 | 状态 |\n"
        "|--------|---------|---------|-------------|---------|------|\n"
        "| S-01 | design#1 | E2E（Playwright） | browser -> api | TASK-001 | planned |\n\n"
        "## TASK-001: Demo\n- **Acceptance-Refs**: S-01\n",
        encoding="utf-8",
    )
    legacy = extract_manifest(str(task), _legacy_kind)
    assert legacy["scenarios"][0]["kind"] == "functional", "旧解析确实会误判"
    legacy["task_file"] = "demo.md"
    legacy["scenarios"][0]["evidence"] = {"status": "passed", "exit_code": 0}
    manifest.write_text(json.dumps(legacy, ensure_ascii=False) + "\n", encoding="utf-8")

    assert validate_manifest(str(task), str(manifest)) == (True, "")
    healed = json.loads(manifest.read_text(encoding="utf-8"))
    assert healed["scenarios"][0]["kind"] == "e2e"
    assert healed["scenarios"][0]["evidence"]["exit_code"] == 0, "运行态 evidence 必须保留"
    assert validate_manifest(str(task), str(manifest)) == (True, "")

    task.write_text(task.read_text(encoding="utf-8").replace("browser -> api", "browser -> queue"), encoding="utf-8")
    valid, reason = validate_manifest(str(task), str(manifest))
    assert valid is False and reason == "acceptance_manifest_drift"


def test_kind_tolerates_level_annotations() -> None:
    """带注解的层级不得误判：E2E 误判成 functional 会导致每个 TASK 都触发 E2E 执行。"""
    assert _kind("E2E") == "e2e"
    assert _kind("e2e") == "e2e"
    assert _kind("E2E（Playwright）") == "e2e"
    assert _kind("e2e/chrome") == "e2e"
    assert _kind("端到端") == "e2e"
    assert _kind("end-to-end") == "e2e"
    assert _kind("manual") == "manual"
    assert _kind("manual(chrome)") == "manual"
    assert _kind("integration") == "functional"
    assert _kind("unit") == "functional"
    assert _kind("") == "functional"
    assert _kind("E2E 场景") == "e2e"


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
