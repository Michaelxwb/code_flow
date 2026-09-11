#!/usr/bin/env python3
"""[S-08][E-08][B-08] Manifest 严格校验与证据幂等回归测试。

真实边界：真实 manifest/任务文件 + 真实 Runner 子进程。
"""
import json
import sys
import time
from pathlib import Path


SCRIPTS = Path(__file__).resolve().parents[1] / "src/core/code-flow/scripts"
sys.path.insert(0, str(SCRIPTS))

from cf_acceptance_manifest import (  # noqa: E402
    _sync_task_evidence,
    validate_manifest,
    write_manifest,
)
from cf_acceptance_runner import run_manifest  # noqa: E402


def _task(tmp_path: Path, coverage: str) -> Path:
    task = tmp_path / "t.md"
    task.write_text(
        "## TASK-001: Demo\n"
        "- **Status**: done\n"
        "- **Acceptance-Refs**: S-01\n"
        "### Acceptance Contract\n- S-01: do x\n"
        "### Acceptance Evidence\nnone\n"
        "## Acceptance Coverage\n" + coverage,
        encoding="utf-8",
    )
    return task


def test_tampered_manifest_fields_fail_validation(tmp_path: Path) -> None:
    """[S-08] manifest 内 kind/boundary 私改必须 drift。"""
    task = _task(tmp_path, "|S-01|src|integration|real Store|TASK-001|planned|\n|---|---|---|---|---|---|\n")
    manifest = tmp_path / ".acceptance-manifest.json"
    write_manifest(str(task), str(manifest))
    assert validate_manifest(str(task), str(manifest)) == (True, "")
    data = json.loads(manifest.read_text(encoding="utf-8"))
    data["scenarios"][0]["kind"] = "manual"
    data["scenarios"][0]["boundary"] = "mock"
    manifest.write_text(json.dumps(data, ensure_ascii=False, indent=2))
    ok, reason = validate_manifest(str(task), str(manifest))
    assert ok is False
    assert "field_changed" in reason


def test_evidence_sync_is_idempotent_and_closes_coverage(tmp_path: Path) -> None:
    """[S-08] 重复同步不堆叠，且 Coverage 同步 verified、无粘连破坏。"""
    task = _task(tmp_path, "|S-01|src|integration|real Store|TASK-001|planned|\n|---|---|---|---|---|---|\n")
    _sync_task_evidence(task, "S-01", "runner", "automated command passed", "TASK-001")
    _sync_task_evidence(task, "S-01", "runner", "automated command passed", "TASK-001")
    text = task.read_text(encoding="utf-8")
    assert text.count("S-01: verified") == 2, text  # contract 一行 + evidence 一行
    assert "verified###" not in text, "Contract 尾换行不得丢失"
    coverage = text.split("## Acceptance Coverage", 1)[1]
    assert "verified" in coverage.splitlines()[1]


def test_failure_then_success_keeps_single_verified_plus_log(tmp_path: Path) -> None:
    """[E-08] 失败日志保留，成功不堆叠 verified。"""
    cmd_fail = json.dumps([sys.executable, "-c", "from pathlib import Path; print('boom'); assert Path('ready').exists()"])
    task = _task(
        tmp_path,
        f"|S-01|src|integration|real Store|TASK-001|planned|{cmd_fail}|\n"
        "|---|---|---|---|---|---|---|\n",
    )
    manifest = tmp_path / ".acceptance-manifest.json"
    write_manifest(str(task), str(manifest))
    first = run_manifest(str(manifest), str(tmp_path), write_evidence=True)
    assert first["decision"] == "block"
    saved = json.loads(manifest.read_text(encoding="utf-8"))
    assert saved["scenarios"][0]["evidence"]["status"] == "failed"
    assert "boom" in json.dumps(saved["scenarios"][0]["evidence"])
    (tmp_path / "ready").touch()
    second = run_manifest(str(manifest), str(tmp_path), write_evidence=True)
    assert second["decision"] == "pass"
    body = task.read_text(encoding="utf-8")
    assert body.count("S-01: verified") == 2, body


def test_empty_and_large_manifest_bounds(tmp_path: Path) -> None:
    """[B-08] 0 场景拒锁；500 场景校验 <1s。"""
    task = tmp_path / "empty.md"
    task.write_text("## TASK-001: Demo\n## Acceptance Coverage\n| 场景ID | 来源 | 层级 | 边界 | 负责 | 状态 |\n", encoding="utf-8")
    try:
        write_manifest(str(task), str(tmp_path / "m.json"))
    except ValueError:
        pass
    else:  # pragma: no cover
        raise AssertionError("empty coverage must refuse lock")
    rows = "".join(
        f"|S-{i:03d}|src|integration|real|TASK-001|planned|\n" for i in range(1, 501)
    )
    big = _task(tmp_path, rows)
    refs = "S-001, " + ", ".join(f"S-{i:03d}" for i in range(1, 501))
    big.write_text(
        big.read_text(encoding="utf-8").replace("- **Acceptance-Refs**: S-01", f"- **Acceptance-Refs**: {refs}"),
        encoding="utf-8",
    )
    manifest = tmp_path / "big.json"
    write_manifest(str(big), str(manifest))
    started = time.monotonic()
    assert validate_manifest(str(big), str(manifest))[0] is True
    assert time.monotonic() - started < 1.0
