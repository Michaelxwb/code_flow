"""0.8 review remediation regressions: the gaps that 668 green tests missed."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "src/core/code-flow/scripts"
sys.path.insert(0, str(SCRIPTS))

import cf_acceptance_runner as runner  # noqa: E402
from cf_acceptance_schema import load_manifest  # noqa: E402
from cf_evidence_store import EvidenceStore  # noqa: E402
from cf_task_parallel import ParallelEvidenceError, _evidence_state  # noqa: E402
from cf_worktree_env import _lock_is_stale, effective_parallel_safe, worktree_identity  # noqa: E402


def _git(root: Path, *args: str) -> None:
    import subprocess
    subprocess.run(("git", *args), cwd=root, check=True, capture_output=True)


def _repo(tmp_path: Path) -> Path:
    root = tmp_path / "proj"
    root.mkdir()
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "review@test")
    _git(root, "config", "user.name", "review")
    (root / "src").mkdir()
    (root / "src/app.py").write_text("VALUE = 1\n", encoding="utf-8")
    (root / ".gitignore").write_text("report.tmp\n", encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "init")
    return root


def test_latest_reads_newest_run_even_if_hint_is_stale(tmp_path: Path) -> None:
    store = EvidenceStore(tmp_path, "demo")
    old = {"run_id": "old", "check_id": "CHK", "status": "passed", "exit_code": 0,
           "executed_at": "2026-10-22T00:00:00+00:00", "input_hash": "a"}
    new = {"run_id": "new", "check_id": "CHK", "status": "passed", "exit_code": 0,
           "executed_at": "2026-10-22T00:01:00+00:00", "input_hash": "b"}
    store.write_run("CHK", old)
    store.write_run("CHK", new)
    store.latest_path("CHK").write_text(json.dumps(old), encoding="utf-8")
    assert store.read_latest("CHK")["run_id"] == "new"


def test_untracked_artifact_does_not_invalidate_acceptance_cache(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    marker = root / "runs.txt"
    command = [sys.executable, "-c",
               "from pathlib import Path; p=Path('runs.txt'); "
               "p.write_text((p.read_text() if p.exists() else '') + 'x')"]
    manifest = root / ".acceptance-manifest.json"
    manifest.write_text(json.dumps({"scenarios": [
        {"id": "S-01", "kind": "functional", "command": command, "cwd": ".", "timeout": 30,
         "depends_on": [], "status": "planned"},
    ]}), encoding="utf-8")
    assert runner.run_manifest(str(manifest), str(root), write_evidence=True)["decision"] == "pass"
    (root / "report.tmp").write_text("e2e artifact\n", encoding="utf-8")
    second = runner.run_manifest(str(manifest), str(root), write_evidence=True)
    assert second["decision"] == "pass"
    assert second["results"][0].get("cache_reused") is True, second


def test_profile_smoke_selects_p0_only(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(runner, "_changed_paths", lambda root: set())
    data = {
        "schema": 3,
        "checks": [
            {"id": "CHK-P0", "command": ["true"], "cwd": ".", "timeout": 30, "profile": "smoke"},
            {"id": "CHK-P1", "command": ["true"], "cwd": ".", "timeout": 30, "profile": "changed"},
        ],
        "scenarios": [
            {"id": "S-01", "kind": "functional", "check": "CHK-P0", "priority": "P0"},
            {"id": "S-02", "kind": "functional", "check": "CHK-P1", "priority": "P1"},
        ],
    }
    selected = runner._select_profile(data, "/tmp", "smoke")
    assert [item["id"] for item in selected["scenarios"]] == ["S-01"]


def test_profile_changed_filters_by_inputs(monkeypatch: pytest.MonkeyPatch) -> None:
    data = {
        "schema": 3,
        "checks": [
            {"id": "CHK-A", "command": ["true"], "cwd": ".", "timeout": 30, "inputs": ["src/a.py"]},
            {"id": "CHK-B", "command": ["true"], "cwd": ".", "timeout": 30, "inputs": ["src/b.py"]},
        ],
        "scenarios": [
            {"id": "S-01", "kind": "functional", "check": "CHK-A", "priority": "P1"},
            {"id": "S-02", "kind": "functional", "check": "CHK-B", "priority": "P1"},
        ],
    }
    monkeypatch.setattr(runner, "_changed_paths", lambda root: {"src/a.py"})
    selected = runner._select_profile(data, "/tmp", "changed")
    assert [item["id"] for item in selected["scenarios"]] == ["S-01"]


def test_dangling_check_is_rejected(tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({
        "schema": 3,
        "checks": [{"id": "CHK-A", "command": ["true"], "cwd": ".", "timeout": 30}],
        "scenarios": [{"id": "S-01", "kind": "functional", "check": "MISSING", "command": ["true"]}],
    }), encoding="utf-8")
    with pytest.raises(ValueError, match="missing check"):
        load_manifest(manifest)


def test_aspirational_scenario_is_not_executed(tmp_path: Path) -> None:
    marker = tmp_path / "aspirational.txt"
    command = [sys.executable, "-c", f"from pathlib import Path; Path({str(marker)!r}).write_text('x')"]
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"scenarios": [
        {"id": "B-01", "kind": "functional", "exec": "aspirational", "command": command,
         "cwd": ".", "timeout": 30, "status": "planned"},
    ]}), encoding="utf-8")
    result = runner.run_manifest(str(manifest), str(tmp_path))
    assert result["decision"] == "pass"
    assert not marker.exists(), "aspirational 不得执行"


def test_parallel_safe_defaults_false() -> None:
    assert effective_parallel_safe({"env_scope": "isolated"}) is False
    assert effective_parallel_safe({"env_scope": "isolated", "parallel_safe": True}) is True


def test_shared_lock_live_pid_is_never_stale(tmp_path: Path) -> None:
    lock = tmp_path / "lock"
    lock.write_text(json.dumps({
        "pid": os.getpid(),
        "host": __import__("socket").gethostname(),
        "created_at": 0,
    }), encoding="utf-8")
    assert _lock_is_stale(lock, 1.0) is False


def test_worktree_identity_distinguishes_same_basename(tmp_path: Path) -> None:
    first = tmp_path / "run-a" / "TASK-001"
    second = tmp_path / "run-b" / "TASK-001"
    first.mkdir(parents=True)
    second.mkdir(parents=True)
    assert worktree_identity(str(first)) != worktree_identity(str(second))


def test_collect_requires_manifest_when_spec_refs_exist(tmp_path: Path) -> None:
    worktree = tmp_path / "wt"
    worktree.mkdir()
    task_dir = worktree / ".code-flow/tasks/demo"
    task_dir.mkdir(parents=True)
    (task_dir / "demo.md").write_text(
        "# Demo\n\n## TASK-001: A\n- **Status**: done\n- **Spec-Refs**: app#RULE-a\n",
        encoding="utf-8",
    )
    with pytest.raises(ParallelEvidenceError) as error:
        _evidence_state(worktree, "TASK-001", ".code-flow/tasks/demo/demo.md")
    assert error.value.code == "required_evidence_missing"


def test_task_verify_cli_exposes_resume_and_deadline() -> None:
    import subprocess
    script = SCRIPTS / "cf_task_workflow.py"
    result = subprocess.run((sys.executable, str(script), "verify", "--help"),
                            text=True, capture_output=True, check=False)
    assert result.returncode == 0
    assert "--resume" in result.stdout
    assert "--deadline" in result.stdout
    assert "--max-failures" in result.stdout


def test_stale_functional_rows_detects_content_change(tmp_path: Path) -> None:
    from cf_task_workflow import _stale_functional_rows

    root = _repo(tmp_path)
    manifest = root / ".acceptance-manifest.json"
    command = [sys.executable, "-c", "import sys; sys.exit(0 if open('src/app.py').read().strip() == 'VALUE = 1' else 9)"]
    manifest.write_text(json.dumps({"scenarios": [
        {"id": "S-01", "kind": "functional", "command": command, "cwd": ".", "timeout": 30,
         "status": "planned"},
    ]}), encoding="utf-8")
    assert runner.run_manifest(str(manifest), str(root), write_evidence=True)["decision"] == "pass"
    data = json.loads(manifest.read_text(encoding="utf-8"))
    assert _stale_functional_rows(data, str(root)) == []
    (root / "src/app.py").write_text("VALUE = 2\n", encoding="utf-8")
    assert _stale_functional_rows(data, str(root)) == ["S-01"]


def test_full_verify_reruns_stale_functional_and_blocks(tmp_path: Path) -> None:
    from cf_acceptance_manifest import write_manifest
    from cf_task_workflow import verify_layers

    root = _repo(tmp_path)
    task_dir = root / ".code-flow/tasks/2026-10-22/demo"
    task_dir.mkdir(parents=True)
    task = task_dir / "demo.md"
    functional = [sys.executable, "-c",
                  "import sys; sys.exit(0 if open('src/app.py').read().strip() == 'VALUE = 1' else 9)"]
    e2e = [sys.executable, "-c", "pass"]
    task.write_text(
        "# Demo\n\n## Acceptance Coverage\n"
        "| 场景ID | 来源设计 | 测试层级 | 关键真实边界 | 负责任务 | 状态 | 执行命令 |\n"
        "|--------|---------|---------|-------------|---------|------|---------|\n"
        f'| S-01 | d#2.5 | integration | runner | TASK-001 | planned | {json.dumps(functional)} |\n'
        f'| E-01 | d#2.5 | E2E | runner | TASK-001 | planned | {json.dumps(e2e)} |\n\n'
        "## TASK-001: A\n- **Status**: done\n- **Acceptance-Refs**: S-01, E-01\n",
        encoding="utf-8",
    )
    manifest = task_dir / ".acceptance-manifest.json"
    write_manifest(str(task), str(manifest))
    first = runner.run_manifest(str(manifest), str(root), write_evidence=True, include_e2e=True)
    assert first["decision"] == "pass", first

    (root / "src/app.py").write_text("VALUE = 2\n", encoding="utf-8")
    blocked = verify_layers(str(root), str(task_dir), layers="e2e", profile="full")
    assert blocked["decision"] == "block", blocked
    assert blocked["layers"]["e2e"]["reason"] == "e2e_failed", blocked
    assert blocked["layers"]["e2e"]["failed"] == ["S-01"], blocked


def test_profile_run_does_not_truncate_manifest(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = _repo(tmp_path)
    manifest = root / ".acceptance-manifest.json"
    command = [sys.executable, "-c", "pass"]
    manifest.write_text(json.dumps({
        "schema": 3,
        "checks": [
            {"id": "CHK-P0", "command": command, "cwd": ".", "timeout": 30, "profile": "smoke"},
            {"id": "CHK-P1", "command": command, "cwd": ".", "timeout": 30, "profile": "changed"},
        ],
        "scenarios": [
            {"id": "S-01", "kind": "functional", "check": "CHK-P0", "priority": "P0",
             "command": command, "cwd": ".", "timeout": 30, "status": "planned"},
            {"id": "S-02", "kind": "functional", "check": "CHK-P1", "priority": "P1",
             "command": command, "cwd": ".", "timeout": 30, "status": "planned"},
        ],
    }), encoding="utf-8")
    monkeypatch.setattr(runner, "_changed_paths", lambda root: set())
    result = runner.run_manifest(str(manifest), str(root), write_evidence=True, profile="smoke")
    assert result["decision"] == "pass"
    saved = json.loads(manifest.read_text(encoding="utf-8"))
    assert {item["id"] for item in saved["scenarios"]} == {"S-01", "S-02"}
    assert {item["id"] for item in saved["checks"]} == {"CHK-P0", "CHK-P1"}


def test_manifest_missing_blocks_when_acceptance_is_declared(tmp_path: Path) -> None:
    from cf_task_workflow import verify_layers

    root = _repo(tmp_path)
    task_dir = root / ".code-flow/tasks/2026-10-22/demo"
    task_dir.mkdir(parents=True)
    (task_dir / "demo.md").write_text(
        "# Demo\n\n## Acceptance Coverage\n"
        "| 场景ID | 来源设计 | 测试层级 | 关键真实边界 | 负责任务 | 状态 | 执行命令 |\n"
        "|--------|---------|---------|-------------|---------|------|---------|\n"
        '| S-01 | d#2.5 | integration | runner | TASK-001 | planned | ["python3", "-c", "pass"] |\n\n'
        "## TASK-001: A\n- **Status**: done\n- **Acceptance-Refs**: S-01\n",
        encoding="utf-8",
    )
    result = verify_layers(str(root), str(task_dir), layers="e2e", profile="full")
    assert result["decision"] == "block"
    assert result["layers"]["e2e"]["reason"] == "acceptance_manifest_missing"


def test_functional_only_stale_full_reruns_and_blocks(tmp_path: Path) -> None:
    from cf_acceptance_manifest import write_manifest
    from cf_task_workflow import verify_layers

    root = _repo(tmp_path)
    task_dir = root / ".code-flow/tasks/2026-10-22/demo"
    task_dir.mkdir(parents=True)
    task = task_dir / "demo.md"
    command = [sys.executable, "-c",
               "import sys; sys.exit(0 if open('src/app.py').read().strip() == 'VALUE = 1' else 9)"]
    task.write_text(
        "# Demo\n\n## Acceptance Coverage\n"
        "| 场景ID | 来源设计 | 测试层级 | 关键真实边界 | 负责任务 | 状态 | 执行命令 |\n"
        "|--------|---------|---------|-------------|---------|------|---------|\n"
        f'| S-01 | d#2.5 | integration | runner | TASK-001 | planned | {json.dumps(command)} |\n\n'
        "## TASK-001: A\n- **Status**: done\n- **Acceptance-Refs**: S-01\n",
        encoding="utf-8",
    )
    manifest = task_dir / ".acceptance-manifest.json"
    write_manifest(str(task), str(manifest))
    assert runner.run_manifest(str(manifest), str(root), write_evidence=True)["decision"] == "pass"
    (root / "src/app.py").write_text("VALUE = 2\n", encoding="utf-8")
    result = verify_layers(str(root), str(task_dir), layers="validators,review,e2e", profile="full")
    assert result["decision"] == "block", result
    assert result["layers"]["e2e"]["failed"] == ["S-01"], result


def test_smoke_selection_includes_e2e_even_with_p0_functional(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(runner, "_changed_paths", lambda root: set())
    data = {
        "schema": 3,
        "checks": [
            {"id": "CHK-F", "command": ["true"], "cwd": ".", "timeout": 30},
            {"id": "CHK-E", "command": ["true"], "cwd": ".", "timeout": 30},
        ],
        "scenarios": [
            {"id": "S-01", "kind": "functional", "check": "CHK-F", "priority": "P0"},
            {"id": "E-01", "kind": "e2e", "check": "CHK-E", "priority": "P1"},
        ],
    }
    selected = runner._select_profile(data, "/tmp", "smoke")
    assert {item["id"] for item in selected["scenarios"]} == {"S-01", "E-01"}


def test_archive_runtime_moves_only_after_pass(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from cf_task_workflow import archive_requirement
    import cf_task_workflow as workflow

    root = tmp_path / "repo"
    source = root / ".code-flow/tasks/2026-10-22/demo"
    source.mkdir(parents=True)
    (source / "demo.md").write_text("# Demo\n", encoding="utf-8")

    monkeypatch.setattr(workflow, "verify_layers", lambda *args, **kwargs: {"decision": "block"})
    blocked = archive_requirement(str(root), str(source))
    assert blocked["decision"] == "block"
    assert source.is_dir()

    monkeypatch.setattr(workflow, "verify_layers", lambda *args, **kwargs: {"decision": "pass"})
    passed = archive_requirement(str(root), str(source))
    assert passed["decision"] == "pass"
    assert not source.exists()
    assert Path(passed["archived_to"]).is_dir()
