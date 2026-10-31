"""Archive verification through real CLI, Git and filesystem boundaries."""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

import pytest
SCRIPTS = Path(__file__).resolve().parents[1] / "src/core/code-flow/scripts"
sys.path.insert(0, str(SCRIPTS))
from codeflow.cli.cf_acceptance_manifest import write_manifest
from codeflow.cli.cf_acceptance_runner import run_manifest

CLI = SCRIPTS.parents[2] / "cli.js"


def _git(root: Path, *args: str) -> str:
    return subprocess.run(("git", *args), cwd=root, check=True, capture_output=True, text=True).stdout.strip()


def _cli(root: Path, *args: str) -> tuple[int, dict]:
    result = subprocess.run(("node", str(CLI), *args), cwd=root, capture_output=True, text=True)
    return result.returncode, json.loads(result.stdout)


def _project(root: Path) -> tuple[Path, Path]:
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "test@example.invalid")
    _git(root, "config", "user.name", "Test")
    init = subprocess.run(("node", str(CLI), "init", "--platform=codex"), cwd=root, capture_output=True, text=True)
    assert init.returncode == 0, init.stderr
    (root / ".code-flow/validation.yml").write_text(
        "validators:\n  - name: syntax\n    trigger: '*.py'\n    command: 'python3 -m py_compile {files}'\n    timeout: 30000\n", encoding="utf-8")
    (root / ".gitignore").write_text(".code-flow/\n__pycache__/\n", encoding="utf-8")
    (root / "a.py").write_text("value = 1\n", encoding="utf-8")
    (root / "b.py").write_text("value = 1\n", encoding="utf-8")
    task_dir = root / ".code-flow/tasks/demo"
    task_dir.mkdir(parents=True)
    rows = []
    for index, name in enumerate(("a", "b"), 1):
        code = f"from pathlib import Path; p=Path('.code-flow/{name}.count'); p.write_text((p.read_text() if p.exists() else '')+'x'); assert Path('{name}.py').read_text().strip() == 'value = 1'"
        command = json.dumps([sys.executable, "-c", code])
        inputs = json.dumps([f"{name}.py"])
        rows.append(f"| S-0{index} | d#1 | integration | real | TASK-001 | planned | {command} | {inputs} |")
    task = task_dir / "demo.md"
    task.write_text("# Demo\n\n## Acceptance Coverage\n"
        "| 场景ID | 来源设计 | 测试层级 | 关键真实边界 | 负责任务 | 状态 | 执行命令 | 输入 |\n"
        "|---|---|---|---|---|---|---|---|\n" + "\n".join(rows) +
        "\n\n## TASK-001: Demo\n- **Status**: done\n- **Acceptance-Refs**: S-01, S-02\n", encoding="utf-8")
    manifest = task_dir / ".acceptance-manifest.json"
    write_manifest(str(task), str(manifest))
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "baseline")
    result = run_manifest(str(manifest), str(root), write_evidence=True)
    assert result["decision"] == "pass", result
    return task_dir, manifest


def _run(root: Path, task: Path, action: str) -> dict:
    code, result = _cli(root, "task", action, "--root", str(root), "--task-dir", str(task), "--json", *(["--profile", "full"] if action == "verify" else []))
    assert code in (0, 3), result
    return result


def test_s08_archive_reuses_complete_evidence(tmp_path: Path) -> None:
    task, _ = _project(tmp_path)
    verified = _run(tmp_path, task, "verify")
    assert verified["decision"] == "pass", verified
    before = [(tmp_path / f".code-flow/{name}.count").read_text(encoding="utf-8") for name in ("a", "b")]
    archived = _run(tmp_path, task, "archive")
    assert archived["decision"] == "pass", archived
    assert not task.exists() and Path(archived["archived_to"]).is_dir()
    assert [(tmp_path / f".code-flow/{name}.count").read_text(encoding="utf-8") for name in ("a", "b")] == before


def test_e05_archive_reruns_only_missing_evidence(tmp_path: Path) -> None:
    task, _ = _project(tmp_path)
    assert _run(tmp_path, task, "verify")["decision"] == "pass"
    before = [(tmp_path / f".code-flow/{name}.count").read_text(encoding="utf-8") for name in ("a", "b")]
    (tmp_path / "a.py").write_text("value = 2\n", encoding="utf-8")
    result = _run(tmp_path, task, "archive")
    assert result["decision"] == "block" and task.is_dir()
    assert (tmp_path / ".code-flow/a.count").read_text(encoding="utf-8") == before[0] + "x"
    assert (tmp_path / ".code-flow/b.count").read_text(encoding="utf-8") == before[1]
    root = tmp_path / "missing"
    root.mkdir()
    task, manifest = _project(root)
    assert _run(root, task, "verify")["decision"] == "pass"
    before = [(root / f".code-flow/{name}.count").read_text(encoding="utf-8") for name in ("a", "b")]
    data = json.loads(manifest.read_text(encoding="utf-8"))
    data["scenarios"][1].pop("evidence")
    data["scenarios"][1]["status"] = "planned"
    manifest.write_text(json.dumps(data), encoding="utf-8")
    result = _run(root, task, "archive")
    assert result["decision"] == "pass", result
    assert (root / ".code-flow/a.count").read_text(encoding="utf-8") == before[0]
    assert (root / ".code-flow/b.count").read_text(encoding="utf-8") == before[1] + "x"


def test_b01_archive_detects_input_change_before_move(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    task, manifest = _project(tmp_path)
    data = json.loads(manifest.read_text(encoding="utf-8"))
    data["scenarios"][0].pop("evidence")
    data["scenarios"][0]["status"] = "verified"
    manifest.write_text(json.dumps(data), encoding="utf-8")
    result = _run(tmp_path, task, "archive")
    assert result["decision"] == "block" and task.is_dir()
    from codeflow.cli import cf_task_workflow as workflow
    root = tmp_path / "race"
    root.mkdir()
    task, _ = _project(root)
    actual = workflow.verify_layers
    def verify_then_change(*args: object, **kwargs: object) -> dict:
        verified = actual(*args, **kwargs)
        (root / "a.py").write_text("value = 2\n", encoding="utf-8")
        return verified
    monkeypatch.setattr(workflow, "verify_layers", verify_then_change)
    blocked = workflow.archive_requirement(str(root), str(task))
    assert blocked["decision"] == "block" and task.is_dir()
    assert "snapshot" in blocked["reason"]
    from codeflow.spec.cf_spec_context_model import new_context, save_context
    root2 = tmp_path / "context-race"
    root2.mkdir()
    task2, _ = _project(root2)
    context = task2 / "spec-context.yml"
    save_context(str(context), new_context("before", (("test", "fixture"),)))
    def verify_then_change_context(*args: object, **kwargs: object) -> dict:
        verified = actual(*args, **kwargs)
        save_context(str(context), new_context("after", (("test", "fixture"),)))
        return verified
    monkeypatch.setattr(workflow, "verify_layers", verify_then_change_context)
    changed = workflow.archive_requirement(str(root2), str(task2))
    assert changed["decision"] == "block" and changed["reason"] == "archive_snapshot_changed"
    assert task2.is_dir()
