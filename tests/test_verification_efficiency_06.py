"""Batch verification against a real CLI and isolated Git project."""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

SCRIPTS = Path(__file__).resolve().parents[1] / "src/core/code-flow/scripts"
sys.path.insert(0, str(SCRIPTS))
from codeflow.cli.cf_acceptance_manifest import write_manifest

CLI = SCRIPTS.parents[2] / "cli.js"


def _git(root: Path, *args: str) -> None:
    subprocess.run(("git", *args), cwd=root, check=True, capture_output=True)


def _project(root: Path, linked: bool = True) -> tuple[Path, Path]:
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "test@example.invalid")
    _git(root, "config", "user.name", "Test")
    result = subprocess.run(("node", str(CLI), "init", "--platform=codex"), cwd=root, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    (root / ".gitignore").write_text(".code-flow/\n__pycache__/\n", encoding="utf-8")
    (root / "shared.py").write_text("ready = True\n", encoding="utf-8")
    (root / ".code-flow/validation.yml").write_text("validators:\n  - name: syntax\n    trigger: '*.py'\n    command: 'python3 -m py_compile {files}'\n", encoding="utf-8")
    task_dir = root / ".code-flow/tasks/demo"
    task_dir.mkdir(parents=True)
    def command(name: str) -> str:
        text = f"from pathlib import Path; p=Path('.code-flow/{name}.count'); p.write_text((p.read_text() if p.exists() else '')+'x'); exec(Path('shared.py').read_text()); assert ready"
        return json.dumps([sys.executable, "-c", text])
    rows = [
        f'| S-01 | d#1 | integration | runtime | TASK-002 | planned | {command("owned")} |  | no |  |',
        f'| E-01 | d#1 | e2e | browser | TASK-001 | planned | {command("shared")} | {"S-01" if linked else ""} | yes | ["shared.py"] |',
        f'| E-02 | d#1 | e2e | browser | TASK-003 | planned | {command("unrelated")} |  | yes |  |',
    ]
    task = task_dir / "demo.md"
    task.write_text("# Demo\n\n## Acceptance Coverage\n"
        "| 场景ID | 来源设计 | 测试层级 | 关键真实边界 | 负责任务 | 状态 | 执行命令 | 依赖 | smoke | 输入 |\n"
        "|---|---|---|---|---|---|---|---|---|---|\n" + "\n".join(rows) +
        "\n\n## TASK-001: Old\n- **Status**: done\n- **Acceptance-Refs**: E-01\n"
        "## TASK-002: Batch\n- **Status**: done\n- **Acceptance-Refs**: S-01\n"
        "## TASK-003: Later\n- **Status**: draft\n- **Acceptance-Refs**: E-02\n", encoding="utf-8")
    manifest = task_dir / ".acceptance-manifest.json"
    write_manifest(str(task), str(manifest))
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "baseline")
    return task_dir, task


def _verify(root: Path, task_dir: Path, tasks: str) -> dict:
    args = ("node", str(CLI), "task", "verify", "--root", str(root), "--task-dir", str(task_dir),
            "--layers", "validators,e2e", "--profile", "smoke", "--tasks", tasks, "--json")
    result = subprocess.run(args, cwd=root, capture_output=True, text=True)
    assert result.stdout, result.stderr
    return json.loads(result.stdout)


def test_s09_selected_batch_verifies_before_requirement_done(tmp_path: Path) -> None:
    task_dir, task = _project(tmp_path)
    result = _verify(tmp_path, task_dir, "TASK-002")
    assert result["decision"] == "pass", result
    assert result["scope"]["type"] == "partial"
    assert (tmp_path / ".code-flow/shared.count").exists()
    assert not (tmp_path / ".code-flow/unrelated.count").exists()
    assert "**Status**: draft" in task.read_text(encoding="utf-8")
    serial = subprocess.run(("node", str(CLI), "task", "finish", "--root", str(tmp_path),
                             "--task-dir", str(task_dir), "--batch", "TASK-002", "--json"),
                            cwd=tmp_path, capture_output=True, text=True, check=False)
    assert serial.stdout, serial.stderr
    batch = json.loads(serial.stdout)
    assert batch["decision"] == "pass" and batch["batch_smoke"]["scope"]["type"] == "partial"
    second_root = tmp_path / "affected"
    second_root.mkdir()
    other_task, _ = _project(second_root, linked=False)
    (second_root / "shared.py").write_text("ready = True\n# changed\n", encoding="utf-8")
    affected = _verify(second_root, other_task, "TASK-002")
    assert affected["decision"] == "pass", affected
    assert (second_root / ".code-flow/shared.count").exists()
    assert not (second_root / ".code-flow/unrelated.count").exists()


def test_e06_partial_failure_never_promotes_requirement(tmp_path: Path) -> None:
    task_dir, task = _project(tmp_path)
    before = task.read_text(encoding="utf-8")
    not_ready = _verify(tmp_path, task_dir, "TASK-003")
    assert not_ready["decision"] == "block" and not_ready["reason"] == "not_ready"
    assert task.read_text(encoding="utf-8") == before
    task.write_text(before.replace("## TASK-001: Old\n- **Status**: done", "## TASK-001: Old\n- **Status**: draft"), encoding="utf-8")
    dependency = _verify(tmp_path, task_dir, "TASK-002")
    assert dependency["decision"] == "block" and dependency["reason"] == "not_ready"
    assert "TASK-001" in dependency["tasks"]
    task.write_text(before, encoding="utf-8")
    (tmp_path / "shared.py").write_text("ready = False\n", encoding="utf-8")
    failed = _verify(tmp_path, task_dir, "TASK-002")
    assert failed["decision"] == "block"
    assert task_dir.exists() and "**Status**: draft" in task.read_text(encoding="utf-8")
    assert not (tmp_path / ".code-flow/unrelated.count").exists()
    repo = SCRIPTS.parents[3]
    parallel = subprocess.run((sys.executable, "-m", "pytest", "-q",
        "tests/test_cf_task_parallel.py::test_batch_smoke_after_merge_runs_shared_e2e_once",
        "tests/test_cf_task_parallel.py::test_batch_smoke_failure_keeps_worktrees_and_blocks_cleanup"),
        cwd=repo, text=True, capture_output=True, check=False)
    assert parallel.returncode == 0, parallel.stdout + parallel.stderr
