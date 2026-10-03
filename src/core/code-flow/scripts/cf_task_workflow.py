"""Executable task handoffs used by every platform command."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
from typing import IO, Mapping, Optional, Sequence
import sys

from cf_acceptance_manifest import record_manual_evidence
from cf_acceptance_runner import run_manifest
from cf_acceptance_schema import load_manifest, validate_execution_baseline, verified_evidence
from cf_spec_context import (ContextError, Decision, SpecContext, _git_changes, _run_git,
                             apply_decision, load_context, save_context)
from cf_spec_gate import validate_stage
from cf_spec_metadata import load_spec_metadata
from cf_spec_verify import VerificationScope, _git_tracked_files, run_all_verifiers
from cf_task_index import parse_task_file
from cf_task_runtime import _apply_evidence, _evidence_data, run_done_gate
from cf_workflow_service import (FINISHED_STATUSES, _require_marker_task,
                                 _sync_markdown, block_task, cleanup_session_projections,
                                 complete_task, locate_task_file, remove_session_projection,
                                 resume_task)
from cf_workflow_transaction import recover_transition


def finish_task(root: str, directory: str, task_file: str, task_id: str) -> dict[str, object]:
    _require_marker_task(root, task_id, directory, task_file)
    gate = run_done_gate(root, directory, task_id=task_id)
    if gate.decision != "pass":
        return {"decision": "block", "reason": gate.message, "evidence": gate.evidence}
    completed = complete_task(root, directory, task_file, task_id, True)
    # 完成后清理本任务的 Spec Session 投影（瞬时文件，避免往期规则被后续会话读到）
    result = {
        "decision": "pass",
        "deferred_review": gate.deferred_review,
        "deferred_requirement": gate.deferred_requirement,
        "deferred_budget": gate.deferred_budget,
        "deferred_heavy": gate.deferred_heavy,
        "session_projection": remove_session_projection(root, task_file),
        **completed,
    }
    hints = []
    deferred_total = gate.deferred_review + gate.deferred_requirement + gate.deferred_budget
    if deferred_total:
        hints.append(f"{deferred_total} verifier(s) deferred; run cf-task:verify-e2e for the requirement directory")
    if gate.deferred_heavy:
        hints.append(f"{gate.deferred_heavy} heavy validator(s) deferred; archive / cf-validate runs them")
    if hints:
        result["deferred_hint"] = " | ".join(hints)
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


def collect_requirement_bindings(directory: Path,
                                 stages: Sequence[str] = ("review",)) -> dict[str, dict[str, object]]:
    """收集需求目录下全部 task context 中指定阶段的绑定。

    返回 spec_id -> {"path": spec 相对路径, "rules": {rule_ref: [(context_path, context), ...]}}。
    读取失败 fail-closed（报告文件与原因），不允许静默跳过。
    """
    allowed = set(stages)
    targets: dict[str, dict[str, object]] = {}
    for ctx_path in sorted(directory.rglob("spec-context.yml")):
        try:
            context = load_context(str(ctx_path))
        except (ContextError, OSError, ValueError) as exc:
            raise ValueError(f"review_context_unreadable: {ctx_path}: {exc}") from exc
        for binding in context.bindings:
            for rule in binding.rules:
                if rule.verifier_stage not in allowed:
                    continue
                entry = targets.setdefault(binding.spec_id, {"path": binding.path, "rules": {}})
                entry["rules"].setdefault(rule.ref, []).append((ctx_path, context))
    return targets


def collect_review_bindings(directory: Path) -> dict[str, dict[str, object]]:
    """review 层绑定（manual 确认与待确认清单专用）。"""
    return collect_requirement_bindings(directory, ("review",))


def _confirmed_manual(spec_id: str, entries: Sequence[tuple[Path, SpecContext]],
                      rule_ref: str) -> Optional[Mapping[str, object]]:
    """从任意绑定该 rule 的 context 读取有效的用户确认记录（按 rule 自身 stage）。"""
    for _, context in entries:
        for binding in context.bindings:
            if binding.spec_id != spec_id:
                continue
            for rule in binding.rules:
                if rule.ref != rule_ref:
                    continue
                status = rule.stage_status.get(rule.verifier_stage or "code")
                decision = status.decision if status is not None else None
                if (status is not None and status.status == "verified"
                        and decision is not None and decision.kind == "manual_verification"):
                    return {
                        "reason": decision.reason,
                        "confirmed_by": decision.confirmed_by,
                        "confirmed_at": decision.confirmed_at,
                        "source": decision.source,
                    }
    return None


def _pending_manual_rules(
    root: str, targets: Mapping[str, Mapping[str, object]]
) -> tuple[list[dict[str, object]], dict[str, dict[str, Mapping[str, object]]]]:
    """收集 review 层 manual 规则：待用户确认清单 + 已确认项的 verifier 入参。"""
    pending: list[dict[str, object]] = []
    confirmations: dict[str, dict[str, Mapping[str, object]]] = {}
    for spec_id in sorted(targets):
        info = targets[spec_id]
        metadata = load_spec_metadata(str(Path(root) / ".code-flow/specs" / str(info["path"])))
        manual = {item.rule: item for item in metadata.verifiers if item.type == "manual"}
        for rule_ref, entries in sorted(info["rules"].items()):
            confirmation = _confirmed_manual(spec_id, entries, rule_ref)
            if confirmation is not None:
                confirmations.setdefault(spec_id, {})[rule_ref] = confirmation
            elif rule_ref in manual:
                verifier = manual[rule_ref]
                pending.append({
                    "ref": f"{spec_id}#{rule_ref}",
                    "spec_id": spec_id,
                    "checklist": verifier.config.get("checklist", ""),
                    "owner": verifier.config.get("owner", ""),
                    "bound_contexts": len(entries),
                })
    return pending, confirmations


def _manual_confirmations(root: str, targets: Mapping[str, Mapping[str, object]]) -> dict[str, dict[str, Mapping[str, object]]]:
    """收集各 manual rule 自身 stage 上已记录的用户确认（verifier 入参）。"""
    confirmations: dict[str, dict[str, Mapping[str, object]]] = {}
    for spec_id in sorted(targets):
        info = targets[spec_id]
        metadata = load_spec_metadata(str(Path(root) / ".code-flow/specs" / str(info["path"])))
        manual_refs = {item.rule for item in metadata.verifiers if item.type == "manual"}
        for rule_ref, entries in sorted(info["rules"].items()):
            if rule_ref not in manual_refs:
                continue
            confirmation = _confirmed_manual(spec_id, entries, rule_ref)
            if confirmation is not None:
                confirmations.setdefault(spec_id, {})[rule_ref] = confirmation
    return confirmations


def _run_requirement_verifiers(
    root: str,
    targets: dict[str, dict[str, object]],
    confirmations: Optional[Mapping[str, Mapping[str, Mapping[str, object]]]] = None,
) -> dict[str, object]:
    """执行需求级全量 verifier（code+review 按 spec/rule 去重），证据写回全部相关 context。"""
    executed = reused = 0
    failures: list[str] = []
    context_paths: set[Path] = set()
    evidence_by_context: dict[Path, list[Mapping[str, object]]] = {}
    scope = _review_scope(root)
    for spec_id in sorted(targets):
        info = targets[spec_id]
        metadata = load_spec_metadata(str(Path(root) / ".code-flow/specs" / str(info["path"])))
        result = run_all_verifiers(metadata, scope, (confirmations or {}).get(spec_id), stage=None)
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
            payload = _evidence_data(evidence)
            for ctx_path, _context in entries:
                context_paths.add(ctx_path)
                evidence_by_context.setdefault(ctx_path, []).append(payload)
    # 同一 context 常绑定多个 spec：必须加载一次、合并全部证据后写回一次。
    # 逐 spec 从收集时的旧 context 存盘会互相覆盖（历史缺陷：verify-e2e 报 pass
    # 但只有最后一个 spec 的 status 翻牌）。
    for ctx_path in sorted(evidence_by_context, key=str):
        context = load_context(str(ctx_path))
        updated = _apply_evidence(context, tuple(evidence_by_context[ctx_path]))
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
        review_targets = collect_review_bindings(Path(directory))
        all_targets = collect_requirement_bindings(Path(directory), ("code", "review"))
    except ValueError as exc:
        return {"decision": "block", "reason": "review_context_unreadable", "detail": str(exc)}
    manifest = Path(directory) / ".acceptance-manifest.json"
    if not all_targets and not manifest.exists():
        return {"decision": "pass", "executed": 0, "reused": 0, "failed": [], "reason": "nothing_to_verify"}
    manual_scenarios: list[dict[str, object]] = []
    functional_required: list[object] = []
    if manifest.exists():
        data = load_manifest(manifest)
        validate_execution_baseline(manifest, data)
        bound_task = (manifest.parent / str(data.get("task_file", ""))).resolve()
        if {task.resolve() for task, _, _ in tasks} != {bound_task}:
            return {"decision": "block", "reason": "acceptance_manifest_task_mismatch"}
        for row in data["scenarios"]:
            if verified_evidence(row):
                continue
            if row.get("kind") == "manual":
                manual_scenarios.append({
                    "id": row.get("id"),
                    "owner": row.get("owner", ""),
                    "boundary": row.get("boundary", ""),
                })
            elif row.get("kind", "functional") != "e2e":
                functional_required.append(row["id"])
    if functional_required:
        return {"decision": "block", "reason": "functional_or_manual_evidence_missing", "scenarios": functional_required}
    try:
        pending_rules, _ = _pending_manual_rules(root, review_targets)
    except ValueError as exc:
        return {"decision": "block", "reason": "manual_review_context_unreadable", "detail": str(exc)}
    if pending_rules or manual_scenarios:
        return {
            "decision": "block",
            "reason": "manual_confirmation_required",
            "manual_rules": pending_rules,
            "manual_scenarios": manual_scenarios,
            "next": ("向用户展示待确认清单并取得明确回复后，运行 confirm-manual 批量写入确认，再重跑 verify-e2e；"
                     "Agent 不得代确认。"),
        }
    validation: dict[str, object] = {"decision": "pass", "reason": "no_validators_configured", "reused": 0}
    try:
        from cf_validation import validate_files

        validation = validate_files(root, tuple(sorted(_git_tracked_files(root))), include_heavy=True)
    except (OSError, ValueError) as exc:
        return {"decision": "block", "reason": "validation_error", "detail": str(exc)}
    if validation.get("decision") != "pass" and validation.get("reason") != "no_validators_configured":
        return {"decision": "block", "reason": "validation_failed", "validation": validation}
    confirmations = _manual_confirmations(root, all_targets)
    review = (_run_requirement_verifiers(root, all_targets, confirmations) if all_targets
              else {"executed": 0, "reused": 0, "failed": []})
    acceptance: dict[str, object] = {"decision": "pass", "results": []}
    if manifest.exists():
        acceptance = run_manifest(str(manifest), root, write_evidence=True, only_e2e=True)
    decision = "pass" if not review["failed"] and acceptance.get("decision") == "pass" else "block"
    result = {
        **acceptance,
        "decision": decision,
        "executed": review["executed"],
        "reused": review["reused"],
        "failed": review["failed"],
        "review": review,
        "validation": {
            "decision": validation.get("decision"),
            "reason": validation.get("reason", ""),
            "reused": validation.get("reused", 0),
            "failures": validation.get("failures", []),
        },
    }
    if decision == "pass":
        for task_file, task_id, _ in tasks:
            _sync_markdown(str(task_file), task_id, "verified")
    return result


def confirm_manual(root: str, directory: str, refs: Sequence[str], scenarios: Sequence[str],
                   confirmed_by: str, source: str, reason: str = "", evidence: str = "") -> dict[str, object]:
    """用户确认后批量写入 manual 验收记录（review 层 spec 规则 + manifest 场景）。

    只有用户明确确认后才能调用；Agent 不得代确认（agent 身份会被拒绝）。
    """
    owner = confirmed_by.strip()
    if not owner:
        raise ValueError("confirm-manual 需要 --confirmed-by <用户身份>")
    if not source.strip():
        raise ValueError("confirm-manual 需要 --source <用户回复原文>")
    targets = collect_review_bindings(Path(directory))
    pending_rules, confirmations = _pending_manual_rules(root, targets)
    known = {str(item["ref"]) for item in pending_rules}
    for spec_id, by_rule in confirmations.items():
        known.update(f"{spec_id}#{rule_ref}" for rule_ref in by_rule)
    chosen = [ref.strip() for ref in refs if ref.strip()] or sorted(str(item["ref"]) for item in pending_rules)
    unknown = sorted(ref for ref in chosen if ref not in known)
    if unknown:
        raise ValueError(f"unknown_or_not_review_manual_ref: {', '.join(unknown)}")
    reason_text = reason.strip() or "需求级人工验收确认"
    confirmed_at = datetime.now(timezone.utc).isoformat()
    records: dict[Path, SpecContext] = {}
    for ref in chosen:
        spec_id, rule_ref = ref.split("#", 1)
        for ctx_path, _ in targets[spec_id]["rules"][rule_ref]:
            context = records.get(ctx_path) or load_context(str(ctx_path))
            decision = Decision("manual_verification", reason_text, owner, confirmed_at, source.strip(), None)
            records[ctx_path] = apply_decision(context, spec_id, rule_ref, "review", decision)
    for ctx_path in sorted(records, key=str):
        save_context(str(ctx_path), records[ctx_path])
    recorded_scenarios: list[str] = []
    manifest = Path(directory) / ".acceptance-manifest.json"
    if manifest.is_file():
        data = load_manifest(manifest)
        rows = {str(row.get("id")): row for row in data.get("scenarios", [])}
        if scenarios:
            chosen_scenarios = [sid.strip() for sid in scenarios if sid.strip()]
        else:
            chosen_scenarios = [sid for sid, row in rows.items()
                                if row.get("kind") == "manual" and not verified_evidence(row)]
        for sid in chosen_scenarios:
            row = rows.get(sid)
            if row is None or row.get("kind") != "manual":
                raise ValueError(f"unknown_manual_scenario: {sid}")
            if verified_evidence(row):
                continue
            record_manual_evidence(str(manifest), sid, owner, evidence.strip() or source.strip())
            recorded_scenarios.append(sid)
    if not chosen and not recorded_scenarios:
        raise ValueError("no_pending_manual_confirmation")
    return {
        "ok": True,
        "rules": chosen,
        "scenarios": recorded_scenarios,
        "confirmed_by": owner,
        "confirmed_at": confirmed_at,
        "note": "确认已写入 spec-context / manifest；重跑 verify-e2e 完成终验",
    }


def main(argv: Optional[Sequence[str]] = None, stdout: IO[str] = sys.stdout) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("finish", "block", "resume", "verify-e2e", "confirm-manual", "cleanup-session"))
    parser.add_argument("--root", default=os.getcwd())
    parser.add_argument("--task-dir", required=True)
    parser.add_argument("--task", default="")
    parser.add_argument("--reason", default="")
    parser.add_argument("--refs", default="")
    parser.add_argument("--scenarios", default="")
    parser.add_argument("--confirmed-by", default="")
    parser.add_argument("--source", default="")
    parser.add_argument("--evidence", default="")
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
        elif args.action == "cleanup-session":
            result = cleanup_session_projections(root, directory)
        elif args.action == "confirm-manual":
            refs = [item.strip() for item in args.refs.split(",") if item.strip()]
            scenarios = [item.strip() for item in args.scenarios.split(",") if item.strip()]
            result = confirm_manual(root, directory, refs, scenarios, args.confirmed_by, args.source,
                                    args.reason, args.evidence)
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
