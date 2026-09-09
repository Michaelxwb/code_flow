#!/usr/bin/env python3
"""[S-03][E-03] 验收清单可执行化与空转阻断回归测试。

真实边界：真实 Runner 子进程 + 真实 manifest 文件。
"""
import json
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "src/core/code-flow/scripts"
sys.path.insert(0, str(SCRIPTS))

from cf_acceptance_manifest import extract_manifest, write_manifest  # noqa: E402
from cf_acceptance_runner import run_manifest  # noqa: E402


def _task_text(rows: str) -> str:
    return (
        "## TASK-001: Demo\n"
        "- **Status**: draft\n"
        "- **Acceptance-Refs**: S-01, S-02\n"
        "### Acceptance Contract\n- S-01: x\n- S-02: y\n"
        "### Acceptance Evidence\nnone\n"
        "## Acceptance Coverage\n" + rows
    )


def test_all_functional_without_commands_blocks(tmp_path: Path) -> None:
    """[S-03] 零可执行场景不得通过执行验收。"""
    task = tmp_path / "t.md"
    task.write_text(
        _task_text(
            "|S-01|src|integration|real Store|TASK-001|planned|\n"
            "|S-02|src|integration|real Store|TASK-001|planned|\n"
            "|---|---|---|---|---|---|\n"
        ),
        encoding="utf-8",
    )
    manifest = tmp_path / ".acceptance-manifest.json"
    write_manifest(str(task), str(manifest))
    result = run_manifest(str(manifest), str(tmp_path))
    assert result["decision"] == "block"
    assert result.get("error") == "no_executable_scenarios"


def test_registered_commands_pass_and_execute_once(tmp_path: Path) -> None:
    """[S-03] 注册命令后执行通过。"""
    cmd = json.dumps([sys.executable, "-c", "pass"])
    task = tmp_path / "t.md"
    task.write_text(
        _task_text(
            f"|S-01|src|integration|real Store|TASK-001|planned|{cmd}|\n"
            f"|S-02|src|integration|real Store|TASK-001|planned|{cmd}|\n"
            "|---|---|---|---|---|---|---|\n"
        ),
        encoding="utf-8",
    )
    manifest = tmp_path / ".acceptance-manifest.json"
    data = write_manifest(str(task), str(manifest))
    assert data["schema"] == 2
    assert all(isinstance(item["command"], list) for item in data["scenarios"])
    result = run_manifest(str(manifest), str(tmp_path))
    assert result["decision"] == "pass"
    assert [item["status"] for item in result["results"]] == ["passed", "passed"]


def test_manual_and_e2e_kinds_remain_counted_without_commands(tmp_path: Path) -> None:
    """[S-03] manual/e2e 延期语义保留（须有种类声明，不得裸 functional 空转）。"""
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps({"scenarios": [
            {"id": "S-01", "kind": "manual"},
            {"id": "E-01", "kind": "e2e"},
        ]}),
        encoding="utf-8",
    )
    result = run_manifest(str(manifest), str(tmp_path))
    assert result["decision"] == "pass"
    assert [item["status"] for item in result["results"]] == ["manual_pending", "e2e_deferred"]


def test_coverage_missing_columns_refuses_lock(tmp_path: Path) -> None:
    """[E-03] 缺列覆盖表拒绝加锁并明确原因。"""
    task = tmp_path / "t.md"
    task.write_text(
        "## TASK-001: Demo\n## Acceptance Coverage\n|S-01|src|\n", encoding="utf-8"
    )
    try:
        extract_manifest(str(task))
    except ValueError as exc:
        assert "Acceptance Coverage" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("missing columns must refuse manifest lock")
