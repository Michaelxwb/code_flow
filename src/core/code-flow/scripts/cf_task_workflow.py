"""Executable task handoffs used by every platform command."""
from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path
from typing import IO, Optional, Sequence
import sys

from cf_acceptance_runner import run_manifest
from cf_acceptance_schema import load_manifest, validate_execution_baseline, verified_evidence
from cf_task_index import parse_task_file
from cf_task_runtime import run_done_gate
from cf_workflow_service import (FINISHED_STATUSES, _require_marker_task,
                                 _sync_markdown, block_task, complete_task, locate_task_file, resume_task)
from cf_workflow_transaction import recover_transition


def finish_task(root: str, directory: str, task_file: str, task_id: str) -> dict[str, object]:
    _require_marker_task(root, task_id, directory, task_file)
    gate = run_done_gate(root, directory, task_id=task_id)
    if gate.decision != "pass":
        return {"decision": "block", "reason": gate.message, "evidence": gate.evidence}
    return {"decision": "pass", **complete_task(root, directory, task_file, task_id, True)}


def _demand_tasks(directory: Path) -> list[tuple[Path, str, str]]:
    tasks = []
    seen = set()
    for task_file in sorted(directory.glob("*.md")):
        if task_file.name.endswith((".design.md", ".prd.md")):
            continue
        if not re.search(r"(?m)^## TASK-\d+:", task_file.read_text(encoding="utf-8")):
            continue
        for node in parse_task_file(str(task_file)):
            if node.task_id in seen:
                raise ValueError(f"duplicate task id: {node.task_id}")
            seen.add(node.task_id)
            tasks.append((task_file, node.task_id, node.status))
    if not tasks:
        raise ValueError("no TASK sections found")
    return tasks


def verify_e2e(root: str, directory: str) -> dict[str, object]:
    recover_transition(root)
    tasks = _demand_tasks(Path(directory))
    unfinished = [task_id for _, task_id, status in tasks if status not in FINISHED_STATUSES]
    if unfinished:
        return {"decision": "block", "reason": "unfinished_tasks", "tasks": unfinished}
    if (Path(root) / ".code-flow/.active-task.json").exists():
        return {"decision": "block", "reason": "finish_active_task_first"}
    manifest = Path(directory) / ".acceptance-manifest.json"
    data = load_manifest(manifest)
    validate_execution_baseline(manifest, data)
    bound_task = (manifest.parent / str(data.get("task_file", ""))).resolve()
    if {task.resolve() for task, _, _ in tasks} != {bound_task}:
        return {"decision": "block", "reason": "acceptance_manifest_task_mismatch"}
    required = [row["id"] for row in data["scenarios"] if row.get("kind", "functional") != "e2e"
                and not verified_evidence(row)]
    if required:
        return {"decision": "block", "reason": "functional_or_manual_evidence_missing", "scenarios": required}
    result = run_manifest(str(manifest), root, write_evidence=True, only_e2e=True)
    if result["decision"] == "pass":
        for task_file, task_id, _ in tasks:
            _sync_markdown(str(task_file), task_id, "verified")
    return result


def main(argv: Optional[Sequence[str]] = None, stdout: IO[str] = sys.stdout) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("finish", "block", "resume", "verify-e2e"))
    parser.add_argument("--root", default=os.getcwd())
    parser.add_argument("--task-dir", required=True)
    parser.add_argument("--task", default="")
    parser.add_argument("--reason", default="")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        root = str(Path(args.root).resolve())
        directory = str((Path(root) / args.task_dir).resolve())
        if Path(root) not in Path(directory).parents:
            raise ValueError("task directory outside project")
        recover_transition(root)
        if args.action == "verify-e2e":
            result = verify_e2e(root, directory)
        else:
            task = locate_task_file(directory, args.task)
            if task is None:
                raise ValueError("task file missing or ambiguous")
            if args.action == "finish":
                result = finish_task(root, directory, str(task), args.task)
            elif args.action == "block":
                result = block_task(root, directory, str(task), args.task, args.reason)
            else:
                result = resume_task(root, directory, str(task), args.task)
        stdout.write(json.dumps(result, ensure_ascii=False))
        return 3 if result.get("decision") == "block" else 0
    except (OSError, ValueError) as exc:
        stdout.write(json.dumps({"decision": "block", "error": str(exc)}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
