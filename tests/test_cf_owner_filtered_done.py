#!/usr/bin/env python3
"""[S-04][E-04] 按 TASK owner 执行验收与命令去重回归测试。

真实边界：真实 git 仓库 + 真实 Runner 子进程 + 真实 Done 门。
"""
import json
import subprocess
import sys
from pathlib import Path


SCRIPTS = Path(__file__).resolve().parents[1] / "src/core/code-flow/scripts"
sys.path.insert(0, str(SCRIPTS))

from cf_acceptance_manifest import write_manifest  # noqa: E402
from cf_spec_context import new_context, save_context, start_active_task  # noqa: E402
from cf_task_runtime import run_done_gate  # noqa: E402


def _git(root: Path, *args: str) -> None:
    subprocess.run(("git", *args), cwd=root, check=True, capture_output=True)


def _repo(tmp_path: Path, coverage: str, refs_001: str = "S-01", refs_002: str = "S-02") -> tuple[Path, Path]:
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "t@t")
    _git(tmp_path, "config", "user.name", "t")
    task_dir = tmp_path / ".code-flow" / "tasks" / "demand"
    task_dir.mkdir(parents=True)
    (tmp_path / ".code-flow" / "specs").mkdir(parents=True)
    (task_dir / "work.md").write_text(
        "## TASK-001: First\n"
        "- **Status**: draft\n"
        f"- **Acceptance-Refs**: {refs_001}\n"
        "### Acceptance Contract\n- S-01: first\n"
        "### Acceptance Evidence\nnone\n"
        "## TASK-002: Second\n"
        "- **Status**: draft\n"
        f"- **Acceptance-Refs**: {refs_002}\n"
        "### Acceptance Contract\n- S-02: second\n"
        "### Acceptance Evidence\nnone\n"
        "## Acceptance Coverage\n" + coverage,
        encoding="utf-8",
    )
    save_context(str(task_dir / "spec-context.yml"), new_context("demo", (("test", "owner"),)))
    (tmp_path / ".code-flow" / "config.yml").write_text(
        "spec_workflow:\n  schema_version: 1\n  enforcement: required\npath_mapping: {}\n",
        encoding="utf-8",
    )
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-qm", "init")
    write_manifest(str(task_dir / "work.md"), str(task_dir / ".acceptance-manifest.json"))
    return tmp_path, task_dir


def test_done_gate_runs_only_active_task_scenarios(tmp_path: Path) -> None:
    """[S-04] TASK-001 的 Done 不执行/不等待 TASK-002 的失败场景。"""
    fail = json.dumps([sys.executable, "-c", "raise SystemExit(1)"])
    ok = json.dumps([sys.executable, "-c", "pass"])
    root, task_dir = _repo(
        tmp_path,
        f"|S-01|src|integration|real|TASK-001|planned|{ok}|\n"
        f"|S-02|src|integration|real|TASK-002|planned|{fail}|\n"
        "|---|---|---|---|---|---|---|\n",
    )
    start_active_task(str(root), ".code-flow/tasks/demand", "TASK-001", "ctx")
    result = run_done_gate(str(root), str(task_dir), task_id="TASK-001")
    assert result.decision == "pass", result.message


def test_shared_command_failure_maps_to_all_bound_scenarios_once(tmp_path: Path) -> None:
    """[E-04] 同命令多场景：失败映射到全部，只执行一次。"""
    marker = tmp_path / "runs.txt"
    code = "import sys; open(sys.argv[1], 'a').write('x\\n'); raise SystemExit(1)"
    cmd = json.dumps([sys.executable, "-c", code, str(marker)])
    root, task_dir = _repo(
        tmp_path,
        f"|S-01|src|integration|real|TASK-001|planned|{cmd}|\n"
        f"|S-02|src|integration|real|TASK-001|planned|{cmd}|\n"
        "|---|---|---|---|---|---|---|\n",
        refs_001="S-01, S-02",
    )
    start_active_task(str(root), ".code-flow/tasks/demand", "TASK-001", "ctx")
    result = run_done_gate(str(root), str(task_dir), task_id="TASK-001")
    assert result.decision == "block"
    assert marker.read_text(encoding="utf-8") == "x\n", "同一命令必须只执行一次"
