#!/usr/bin/env python3
"""TASK-013: batch finish executes shared code checks once and reports per task."""
from __future__ import annotations

import io
import json
import subprocess
import sys
from pathlib import Path

import yaml


SCRIPTS = Path(__file__).resolve().parents[1] / "src/core/code-flow/scripts"
sys.path.insert(0, str(SCRIPTS))

from cf_spec_context import BindingInput, bind_specs, new_context, save_context, load_context  # noqa: E402
from cf_spec_resolver import resolve_candidates  # noqa: E402
from cf_task_index import parse_task_file  # noqa: E402
from cf_task_workflow import finish_batch, main  # noqa: E402


TASK_FILE = ".code-flow/tasks/2026-10-22/batch/batch.md"


def _git(root: Path, *arguments: str) -> str:
    result = subprocess.run(
        ("git", *arguments), cwd=str(root), text=True, encoding="utf-8", capture_output=True, check=False
    )
    assert result.returncode == 0, result.stderr
    return result.stdout


def _spec(spec_id: str, rule: str, argv: list[str]) -> str:
    metadata = {
        "id": spec_id,
        "description": f"{spec_id} runtime check",
        "stages": ["code"],
        "enforcement": "required",
        "verifiers": [{
            "rule": rule,
            "type": "command",
            "config": {"argv": argv, "timeout": 30},
        }],
    }
    frontmatter = yaml.safe_dump(metadata, sort_keys=False, allow_unicode=True)
    return f"---\n{frontmatter}---\n# {spec_id}\n\n## Rules\n\n- [{rule}] Runtime constraint.\n"


def _task_section(task: str, refs: str, capability: str) -> str:
    return (
        f"## {task}: {task} capability\n\n"
        f"- **Status**: draft\n"
        f"- **Depends**:\n"
        f"- **Capability**: {capability}\n"
        f"- **Spec-Refs**: {refs}\n\n"
        f"### Log\n- [2026-10-22] created (draft)\n"
    )


def _task_file_text(tasks: list[tuple[str, str, str]]) -> str:
    sections = [_task_section(task, refs, capability) for task, refs, capability in tasks]
    return "# Batch demo\n\n---\n\n" + "\n---\n\n".join(sections)


def _shared_command(marker: Path) -> list[str]:
    return [
        sys.executable,
        "-c",
        "from pathlib import Path\n"
        f"p = Path({str(marker)!r})\n"
        "p.write_text((p.read_text() if p.exists() else '') + 'x')\n",
    ]


def _failing_command() -> list[str]:
    return [sys.executable, "-c", "raise SystemExit(1)"]


def _repo(tmp_path: Path, tasks: list[tuple[str, str, str]], marker: Path) -> tuple[Path, Path]:
    """Real git repo + real specs/context; every task references the shared rule."""
    root = tmp_path / "batch-proj"
    root.mkdir()
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "cf@test")
    _git(root, "config", "user.name", "cf-test")
    app = root / "src/app.py"
    app.parent.mkdir()
    app.write_text("VALUE = 1\n", encoding="utf-8")
    specs = root / ".code-flow/specs"
    (specs / "shared").mkdir(parents=True)
    (specs / "shared/rules.md").write_text(
        _spec("shared-runtime", "RULE-shared-001", _shared_command(marker)), encoding="utf-8"
    )
    config = {"path_mapping": {"src": {"patterns": ["src/*"], "specs": [{"path": "shared/rules.md"}]}}}
    (root / ".code-flow/config.yml").write_text(yaml.safe_dump(config), encoding="utf-8")
    task_dir = root / Path(TASK_FILE).parent
    task_dir.mkdir(parents=True)
    task_path = root / TASK_FILE
    task_path.write_text(_task_file_text(tasks), encoding="utf-8")
    candidates = resolve_candidates(str(root), "code", ["src/app.py"])
    context = new_context("batch-demo", (("test", "batch"),))
    context = bind_specs(context, tuple(
        BindingInput(candidate, "plan", f"path matched {candidate.spec_id}") for candidate in candidates
    ))
    save_context(str(task_dir / "spec-context.yml"), context)
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "init batch repo")
    return root, task_dir


def _write_per_task_manifest(root: Path, marker: Path, failing_task: str = "TASK-002") -> None:
    """Shared check for two TASKs plus one TASK-owned failing check."""
    task_dir = root / Path(TASK_FILE).parent
    checks = [
        {"id": "CHK-SHARED", "command": _shared_command(marker), "timeout": 30},
        {"id": "CHK-FAIL", "command": _failing_command(), "timeout": 30},
    ]
    scenarios = []
    for index, task in enumerate(("TASK-001", "TASK-002", "TASK-003"), start=1):
        check = "CHK-FAIL" if task == failing_task else "CHK-SHARED"
        scenarios.append({
            "id": f"S-{index:02d}",
            "kind": "functional",
            "owner": task,
            "check": check,
            "command": _failing_command() if check == "CHK-FAIL" else _shared_command(marker),
        })
    (task_dir / ".acceptance-manifest.json").write_text(
        json.dumps({"schema": 3, "checks": checks, "scenarios": scenarios}, ensure_ascii=False),
        encoding="utf-8",
    )


def _statuses(root: Path) -> dict[str, str]:
    return {node.task_id: node.status for node in parse_task_file(str(root / TASK_FILE))}


def test_batch_shared_check_executes_once_and_returns_per_task_results(tmp_path: Path) -> None:
    marker = tmp_path / "shared-check.log"
    tasks = [
        ("TASK-001", "shared-runtime#RULE-shared-001", "batch finish"),
        ("TASK-002", "shared-runtime#RULE-shared-001", "batch finish"),
        ("TASK-003", "shared-runtime#RULE-shared-001", "batch finish"),
    ]
    root, task_dir = _repo(tmp_path, tasks, marker)

    result = finish_batch(str(root), str(task_dir), ["TASK-001", "TASK-002", "TASK-003"])

    assert result["decision"] == "pass", result
    assert [item["task"] for item in result["results"]] == ["TASK-001", "TASK-002", "TASK-003"]
    assert [item["decision"] for item in result["results"]] == ["pass", "pass", "pass"]
    assert marker.read_text(encoding="utf-8") == "x", "shared code check must run exactly once"
    checks = {item["check_id"]: item for item in result["evidence"]}
    shared = checks["shared-runtime#RULE-shared-001"]
    assert shared["tasks"] == ["TASK-001", "TASK-002", "TASK-003"]
    assert shared["executions"] == 1
    assert shared["reused"] == 2
    assert _statuses(root) == {"TASK-001": "done", "TASK-002": "done", "TASK-003": "done"}
    # Evidence is aggregated per check: three passes never append three copies.
    binding = next(item for item in load_context(str(task_dir / "spec-context.yml")).bindings
                   if item.spec_id == "shared-runtime")
    assert len(binding.rules[0].stage_status["code"].evidence) == 1
    assert not (root / ".code-flow/.active-task.json").exists()


def test_failed_task_does_not_block_other_tasks_or_write_done(tmp_path: Path) -> None:
    marker = tmp_path / "shared-check.log"
    tasks = [
        ("TASK-001", "shared-runtime#RULE-shared-001", "batch finish"),
        ("TASK-002", "shared-runtime#RULE-shared-001", "batch finish"),
        ("TASK-003", "shared-runtime#RULE-shared-001", "batch finish"),
    ]
    root, task_dir = _repo(tmp_path, tasks, marker)
    _write_per_task_manifest(root, marker)

    result = finish_batch(str(root), str(task_dir), ["TASK-001", "TASK-002", "TASK-003"])

    assert result["decision"] == "block"
    assert [item["task"] for item in result["results"]] == ["TASK-001", "TASK-002", "TASK-003"]
    assert [item["decision"] for item in result["results"]] == ["pass", "block", "pass"]
    assert result["failed"] == ["TASK-002"]
    statuses = _statuses(root)
    assert statuses["TASK-001"] == "done"
    assert statuses["TASK-002"] == "draft", "failed task must not be marked done"
    assert statuses["TASK-003"] == "done"
    assert marker.read_text(encoding="utf-8") == "x"
    checks = {item["check_id"]: item for item in result["evidence"]}
    assert checks["CHK-SHARED"]["tasks"] == ["TASK-001", "TASK-003"]
    assert checks["CHK-SHARED"]["executions"] == 1
    assert checks["CHK-FAIL"]["status"] == "failed"
    assert checks["CHK-FAIL"]["tasks"] == ["TASK-002"]
    assert not (root / ".code-flow/.active-task.json").exists()


def test_capability_selection_finishes_every_matching_task(tmp_path: Path) -> None:
    marker = tmp_path / "shared-check.log"
    tasks = [
        ("TASK-001", "shared-runtime#RULE-shared-001", "capability alpha"),
        ("TASK-002", "shared-runtime#RULE-shared-001", "capability beta"),
        ("TASK-003", "shared-runtime#RULE-shared-001", "capability alpha"),
    ]
    root, task_dir = _repo(tmp_path, tasks, marker)

    result = finish_batch(str(root), str(task_dir), capability="capability alpha")

    assert result["decision"] == "pass", result
    assert result["selection"]["mode"] == "capability"
    assert [item["task"] for item in result["results"]] == ["TASK-001", "TASK-003"]
    assert _statuses(root)["TASK-002"] == "draft"
    assert _statuses(root)["TASK-001"] == "done"
    assert _statuses(root)["TASK-003"] == "done"


def test_batch_rerun_skips_done_tasks_without_duplicate_evidence(tmp_path: Path) -> None:
    marker = tmp_path / "shared-check.log"
    tasks = [
        ("TASK-001", "shared-runtime#RULE-shared-001", "batch finish"),
        ("TASK-002", "shared-runtime#RULE-shared-001", "batch finish"),
    ]
    root, task_dir = _repo(tmp_path, tasks, marker)
    first = finish_batch(str(root), str(task_dir), ["TASK-001", "TASK-002"])
    assert first["decision"] == "pass", first

    second = finish_batch(str(root), str(task_dir), ["TASK-001", "TASK-002"])

    assert second["decision"] == "pass"
    assert [item.get("status") for item in second["results"]] == ["already_done", "already_done"]
    assert marker.read_text(encoding="utf-8") == "x"
    binding = next(item for item in load_context(str(task_dir / "spec-context.yml")).bindings
                   if item.spec_id == "shared-runtime")
    assert len(binding.rules[0].stage_status["code"].evidence) == 1


def test_cli_finish_batch_flag_returns_per_task_json(tmp_path: Path) -> None:
    marker = tmp_path / "shared-check.log"
    tasks = [
        ("TASK-001", "shared-runtime#RULE-shared-001", "batch finish"),
        ("TASK-002", "shared-runtime#RULE-shared-001", "batch finish"),
    ]
    root, task_dir = _repo(tmp_path, tasks, marker)

    buffer = io.StringIO()
    exit_code = main([
        "finish", "--root", str(root),
        "--task-dir", str(task_dir.relative_to(root)),
        "--batch", "TASK-001,TASK-002", "--json",
    ], stdout=buffer)

    payload = json.loads(buffer.getvalue())
    assert exit_code == 0, payload
    assert payload["action"] == "finish-batch"
    assert [item["task"] for item in payload["results"]] == ["TASK-001", "TASK-002"]
    assert marker.read_text(encoding="utf-8") == "x"
