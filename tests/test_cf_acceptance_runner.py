from pathlib import Path
import json
import sys

SCRIPTS = Path(__file__).resolve().parents[1] / "src/core/code-flow/scripts"
sys.path.insert(0, str(SCRIPTS))

from cf_acceptance_runner import run_manifest
import pytest


def test_runner_executes_functional_and_reports_manual(tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"scenarios": [
        {"id": "S-01", "kind": "functional", "command": [sys.executable, "-c", "pass"]},
        {"id": "E-01", "kind": "manual"},
    ]}), encoding="utf-8")
    result = run_manifest(str(manifest), str(tmp_path))
    assert result["decision"] == "pass"
    assert [item["status"] for item in result["results"]] == ["passed", "manual_pending"]


def test_runner_blocks_failed_command(tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"scenarios": [
        {"id": "S-01", "kind": "e2e_smoke", "command": [sys.executable, "-c", "raise SystemExit(2)"]},
    ]}), encoding="utf-8")
    assert run_manifest(str(manifest), str(tmp_path))["decision"] == "block"


def test_runner_blocks_unconfigured_automated_case_when_execution_is_enabled(tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"scenarios": [
        {"id": "S-01", "kind": "functional"},
        {"id": "S-02", "kind": "functional", "command": [sys.executable, "-c", "pass"]},
    ]}), encoding="utf-8")
    assert run_manifest(str(manifest), str(tmp_path))["decision"] == "block"


def test_runner_rejects_dependency_cycle(tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"scenarios": [
        {"id": "S-01", "kind": "functional", "depends_on": ["S-02"]},
        {"id": "S-02", "kind": "functional", "depends_on": ["S-01"]},
    ]}), encoding="utf-8")
    with pytest.raises(ValueError, match="dependency cycle"):
        run_manifest(str(manifest), str(tmp_path))


def test_runner_orders_dependencies_and_can_write_evidence(tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.json"
    task = tmp_path / "task.md"
    task.write_text("## TASK-001: Demo\n", encoding="utf-8")
    manifest.write_text(json.dumps({"scenarios": [
        {"id": "S-01", "kind": "functional", "command": [sys.executable, "-c", "pass"], "owner": "TASK-001"},
        {"id": "S-02", "kind": "functional", "depends_on": ["S-01"], "command": [sys.executable, "-c", "pass"]},
    ], "task_file": str(task)}), encoding="utf-8")
    result = run_manifest(str(manifest), str(tmp_path), write_evidence=True)
    assert result["decision"] == "pass"
    saved = json.loads(manifest.read_text(encoding="utf-8"))
    assert all(item["status"] == "verified" for item in saved["scenarios"])
    assert "S-01: verified" in task.read_text(encoding="utf-8")
