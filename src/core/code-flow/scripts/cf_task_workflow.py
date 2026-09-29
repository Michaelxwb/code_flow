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
from cf_spec_context import ContextError, _git_changes, _run_git, load_context, save_context
from cf_spec_gate import validate_stage
from cf_spec_metadata import load_spec_metadata
from cf_spec_verify import VerificationScope, _git_tracked_files, run_all_verifiers
from cf_task_index import parse_task_file
from cf_task_runtime import _apply_evidence, _evidence_data, run_done_gate
from cf_workflow_service import (FINISHED_STATUSES, _require_marker_task,
                                 _sync_markdown, block_task, complete_task, locate_task_file, resume_task)
from cf_workflow_transaction import recover_transition


def finish_task(root: str, directory: str, task_file: str, task_id: str) -> dict[str, object]:
    _require_marker_task(root, task_id, directory, task_file)
    gate = run_done_gate(root, directory, task_id=task_id)
    if gate.decision != "pass":
        return {"decision": "block", "reason": gate.message, "evidence": gate.evidence}
    result = {"decision": "pass", "deferred_review": gate.deferred_review, **complete_task(root, directory, task_file, task_id, True)}
    if gate.deferred_review:
        result["deferred_hint"] = f"{gate.deferred_review} review-layer verifier(s) deferred; run cf-task:verify-e2e for the requirement directory"
    return result


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


def _head_token(root: str) -> str:
    try:
        return "head:" + _run_git(root, ("rev-parse", "HEAD")).strip()
    except ContextError:
        return "head:none"


def _review_scope(root: str) -> VerificationScope:
    files = set(_git_tracked_files(root))
    try:
        files.update(_git_changes(root))
    except ContextError:
        pass
    return VerificationScope(root, tuple(sorted(files)), _head_token(root))


def collect_review_bindings(directory: Path) -> dict[str, dict[str, object]]:
    """收集需求目录下全部 task context 的 review 层绑定。

    返回 spec_id -> {"path": spec 相对路径, "rules": {rule_ref: [(context_path, context), ...]}}。
    读取失败 fail-closed（报告文件与原因），不允许静默跳过。
    """
    targets: dict[str, dict[str, object]] = {}
    for ctx_path in sorted(directory.rglob("spec-context.yml")):
        try:
            context = load_context(str(ctx_path))
        except (ContextError, OSError, ValueError) as exc:
            raise ValueError(f"review_context_unreadable: {ctx_path}: {exc}") from exc
        for binding in context.bindings:
            for rule in binding.rules:
                if rule.verifier_stage != "review":
                    continue
                entry = targets.setdefault(binding.spec_id, {"path": binding.path, "rules": {}})
                entry["rules"].setdefault(rule.ref, []).append((ctx_path, context))
    return targets


def _run_review_targets(root: str, targets: dict[str, dict[str, object]]) -> dict[str, object]:
    """执行 review 层 verifier（按 spec/rule 去重），证据写回全部相关 context。"""
    executed = reused = 0
    failures: list[str] = []
    context_paths: set[Path] = set()
    scope = _review_scope(root)
    for spec_id in sorted(targets):
        info = targets[spec_id]
        metadata = load_spec_metadata(str(Path(root) / ".code-flow/specs" / str(info["path"])))
        result = run_all_verifiers(metadata, scope, stage="review")
        by_rule: dict[str, object] = {}
        for evidence in result.evidence:
            rule_ref = evidence.verifier_ref.split("#", 1)[-1]
            by_rule[rule_ref] = evidence
            if evidence.status != "verified":
                failures.append(evidence.verifier_ref)
            elif (evidence.details or {}).get("cache_reused"):
                reused += 1
            else:
                executed += 1
        for rule_ref, entries in info["rules"].items():
            evidence = by_rule.get(rule_ref)
            if evidence is None:
                continue
            payload = (_evidence_data(evidence),)
            for ctx_path, context in entries:
                context_paths.add(ctx_path)
                updated = _apply_evidence(context, payload)
                if updated != context:
                    save_context(str(ctx_path), updated)
    for ctx_path in sorted(context_paths):
        gate = validate_stage(load_context(str(ctx_path)), "review", diff_sha256=scope.diff_sha256)
        failures.extend(f"{issue.spec_id}#{issue.rule_ref}" for issue in gate.errors)
    return {"executed": executed, "reused": reused, "failed": sorted(set(failures))}


def verify_e2e(root: str, directory: str) -> dict[str, object]:
    recover_transition(root)
    tasks = _demand_tasks(Path(directory))
    unfinished = [task_id for _, task_id, status in tasks if status not in FINISHED_STATUSES]
    if unfinished:
        return {"decision": "block", "reason": "unfinished_tasks", "tasks": unfinished}
    if (Path(root) / ".code-flow/.active-task.json").exists():
        return {"decision": "block", "reason": "finish_active_task_first"}
    try:
        targets = collect_review_bindings(Path(directory))
    except ValueError as exc:
        return {"decision": "block", "reason": "review_context_unreadable", "detail": str(exc)}
    manifest = Path(directory) / ".acceptance-manifest.json"
    if not targets and not manifest.exists():
        return {"decision": "pass", "executed": 0, "reused": 0, "failed": [], "reason": "nothing_to_verify"}
    review = _run_review_targets(root, targets) if targets else {"executed": 0, "reused": 0, "failed": []}
    acceptance: dict[str, object] = {"decision": "pass", "results": []}
    if manifest.exists():
        data = load_manifest(manifest)
        validate_execution_baseline(manifest, data)
        bound_task = (manifest.parent / str(data.get("task_file", ""))).resolve()
        if {task.resolve() for task, _, _ in tasks} != {bound_task}:
            return {"decision": "block", "reason": "acceptance_manifest_task_mismatch"}
        required = [row["id"] for row in data["scenarios"] if row.get("kind", "functional") != "e2e"
                    and not verified_evidence(row)]
        if required:
            return {"decision": "block", "reason": "functional_or_manual_evidence_missing", "scenarios": required}
        acceptance = run_manifest(str(manifest), root, write_evidence=True, only_e2e=True)
    decision = "pass" if not review["failed"] and acceptance.get("decision") == "pass" else "block"
    result = {
        **acceptance,
        "decision": decision,
        "executed": review["executed"],
        "reused": review["reused"],
        "failed": review["failed"],
        "review": review,
    }
    if decision == "pass":
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
