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


def _git(root: Path, *args: str) -> None:
    import subprocess
    subprocess.run(("git", *args), cwd=root, check=True, capture_output=True)


def _git_repo(tmp_path: Path) -> None:
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "t@t")
    _git(tmp_path, "config", "user.name", "t")
    (tmp_path / "src").mkdir()
    (tmp_path / "src/app.py").write_text("VALUE = 1\n", encoding="utf-8")
    # 测试产物应被忽略：ignored 文件不参与内容指纹（与真实项目一致）
    (tmp_path / ".gitignore").write_text("*.txt\n", encoding="utf-8")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-qm", "init")


def test_verified_scenario_reused_when_content_unchanged(tmp_path: Path) -> None:
    """[perf] 内容未变的已验证场景跨运行复用，不重复执行 E2E。"""
    _git_repo(tmp_path)
    marker = tmp_path / "runs.txt"
    command = [sys.executable, "-c",
               f"from pathlib import Path; p=Path({str(marker)!r}); "
               "p.write_text((p.read_text() if p.exists() else '') + 'x')"]
    manifest_dir = tmp_path / ".code-flow"
    manifest_dir.mkdir(exist_ok=True)
    manifest = manifest_dir / ".acceptance-manifest.json"
    manifest.write_text(json.dumps({"scenarios": [
        {"id": "E-01", "kind": "e2e", "owner": "TASK-001", "command": command,
         "cwd": ".", "timeout": 30, "depends_on": [], "status": "planned"},
    ]}), encoding="utf-8")

    first = run_manifest(str(manifest), str(tmp_path), write_evidence=True, only_e2e=True)
    assert first["decision"] == "pass"
    assert marker.read_text(encoding="utf-8") == "x", "首次必须真实执行"

    second = run_manifest(str(manifest), str(tmp_path), write_evidence=True, only_e2e=True)
    assert second["decision"] == "pass"
    assert second["results"][0].get("cache_reused") is True, second
    assert marker.read_text(encoding="utf-8") == "x", "内容未变不得重复执行"

    saved = json.loads(manifest.read_text(encoding="utf-8"))["scenarios"][0]
    assert saved["status"] == "verified"
    assert len(saved["runs"]) == 1, "复用不得新增运行记录"


def test_content_change_invalidates_acceptance_cache(tmp_path: Path) -> None:
    """工作树内容变化必须使复用失效并重跑 E2E。"""
    _git_repo(tmp_path)
    marker = tmp_path / "runs.txt"
    command = [sys.executable, "-c",
               f"from pathlib import Path; p=Path({str(marker)!r}); "
               "p.write_text((p.read_text() if p.exists() else '') + 'x')"]
    manifest_dir = tmp_path / ".code-flow"
    manifest_dir.mkdir(exist_ok=True)
    manifest = manifest_dir / ".acceptance-manifest.json"
    manifest.write_text(json.dumps({"scenarios": [
        {"id": "E-01", "kind": "e2e", "owner": "TASK-001", "command": command,
         "cwd": ".", "timeout": 30, "depends_on": [], "status": "planned"},
    ]}), encoding="utf-8")

    assert run_manifest(str(manifest), str(tmp_path), write_evidence=True, only_e2e=True)["decision"] == "pass"
    (tmp_path / "src/app.py").write_text("VALUE = 2\n", encoding="utf-8")
    assert run_manifest(str(manifest), str(tmp_path), write_evidence=True, only_e2e=True)["decision"] == "pass"
    assert marker.read_text(encoding="utf-8") == "xx", "内容变化后必须重跑"


def test_no_cache_flag_forces_reexecution(tmp_path: Path) -> None:
    _git_repo(tmp_path)
    marker = tmp_path / "runs.txt"
    command = [sys.executable, "-c",
               f"from pathlib import Path; p=Path({str(marker)!r}); "
               "p.write_text((p.read_text() if p.exists() else '') + 'x')"]
    manifest_dir = tmp_path / ".code-flow"
    manifest_dir.mkdir(exist_ok=True)
    manifest = manifest_dir / ".acceptance-manifest.json"
    manifest.write_text(json.dumps({"scenarios": [
        {"id": "E-01", "kind": "e2e", "owner": "TASK-001", "command": command,
         "cwd": ".", "timeout": 30, "depends_on": [], "status": "planned"},
    ]}), encoding="utf-8")
    assert run_manifest(str(manifest), str(tmp_path), write_evidence=True, only_e2e=True)["decision"] == "pass"
    forced = run_manifest(str(manifest), str(tmp_path), write_evidence=True, only_e2e=True, use_cache=False)
    assert forced["decision"] == "pass"
    assert marker.read_text(encoding="utf-8") == "xx", "--no-cache 必须强制重跑"


def test_dependent_scenario_never_reuses_across_runs(tmp_path: Path) -> None:
    """依赖场景（depends_on）不复用：依赖副作用不在指纹内。"""
    _git_repo(tmp_path)
    marker = tmp_path / "dep-runs.txt"
    command = [sys.executable, "-c",
               f"from pathlib import Path; p=Path({str(marker)!r}); "
               "p.write_text((p.read_text() if p.exists() else '') + 'x')"]
    manifest_dir = tmp_path / ".code-flow"
    manifest_dir.mkdir(exist_ok=True)
    manifest = manifest_dir / ".acceptance-manifest.json"
    manifest.write_text(json.dumps({"scenarios": [
        {"id": "S-01", "kind": "functional", "owner": "TASK-001", "command": command,
         "cwd": ".", "timeout": 30, "depends_on": [], "status": "planned"},
        {"id": "S-02", "kind": "functional", "owner": "TASK-001", "command": command,
         "cwd": ".", "timeout": 30, "depends_on": ["S-01"], "status": "planned"},
    ]}), encoding="utf-8")
    assert run_manifest(str(manifest), str(tmp_path), write_evidence=True)["decision"] == "pass"
    assert run_manifest(str(manifest), str(tmp_path), write_evidence=True)["decision"] == "pass"
    # S-01 复用一次；S-02 因 depends_on 每次执行 → 首次 2 次 + 第二次 1 次 = 3
    assert marker.read_text(encoding="utf-8") == "xxx"


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


def test_only_e2e_does_not_reuse_functional_not_included_result(tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.json"
    failing = [sys.executable, "-c", "raise SystemExit(7)"]
    manifest.write_text(json.dumps({"scenarios": [
        {"id": "S-01", "kind": "functional", "command": failing},
        {"id": "E-01", "kind": "e2e", "command": failing},
    ]}), encoding="utf-8")

    result = run_manifest(str(manifest), str(tmp_path), only_e2e=True)

    statuses = {item["id"]: item["status"] for item in result["results"]}
    assert statuses["S-01"] == "not_included"
    assert statuses["E-01"] == "failed"
    assert result["decision"] == "block"
