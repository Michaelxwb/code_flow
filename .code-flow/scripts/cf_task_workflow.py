"""Executable task handoffs used by every platform command."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import fnmatch
import json
import os
from pathlib import Path
import re
from typing import IO, Mapping, Optional, Sequence
import sys
import time

from cf_acceptance_manifest import record_manual_evidence
from cf_acceptance_runner import run_manifest
from cf_acceptance_schema import load_manifest, validate_execution_baseline, verified_evidence
from cf_exec_base import execution_session
from cf_spec_context import (ContextError, DEFAULT_ACTIVE_EXCLUDES, Decision, SpecContext,
                             _git_changes, _run_git, apply_decision, load_active_task,
                             load_context, save_context, start_active_task)
from cf_spec_gate import evidence_deferral_kind, validate_stage
from cf_spec_metadata import load_spec_metadata
from cf_spec_session import context_sha256
from cf_spec_verify import (VerificationScope, _git_tracked_files, run_all_verifiers,
                             store_verification_evidence)
from cf_exec_base import worktree_fingerprint
from cf_task_index import parse_task_file
from cf_task_runtime import (_NON_EXECUTION_ERRORS, _apply_evidence, _evidence_data,
                             run_done_gate)
from cf_workflow_service import (FINISHED_STATUSES, _require_marker_task,
                                 _sync_markdown, block_task, check_startable,
                                 cleanup_session_projections, complete_task,
                                 locate_task_file, provisional_task, read_task_section,
                                 remove_session_projection, resume_task, task_truth_issues)
from cf_workflow_transaction import recover_transition


def finish_task(root: str, directory: str, task_file: str, task_id: str) -> dict[str, object]:
    _require_marker_task(root, task_id, directory, task_file)
    gate = run_done_gate(root, directory, task_id=task_id)
    if gate.decision == "provisional":
        transition = provisional_task(root, directory, task_file, task_id, gate.message)
        return {
            "decision": "provisional",
            "reason": gate.message,
            "missing_checks": list(gate.missing_checks),
            "next": gate.next_action,
            "deferred_review": gate.deferred_review,
            "deferred_requirement": gate.deferred_requirement,
            "deferred_budget": gate.deferred_budget,
            "deferred_heavy": gate.deferred_heavy,
            "evidence": gate.evidence,
            **transition,
        }
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


_CAPABILITY_LINE = re.compile(r"^- \*\*(?:Capability|Demo)\*\*:[ \t]*(.*)$")


def _normalize_capability(value: str) -> str:
    return " ".join(value.split()).casefold()


def _task_capability(task_file: Path, task_id: str) -> str:
    """Read the user-demonstrable capability declared by one TASK section."""
    try:
        section = read_task_section(str(task_file), task_id)
    except ValueError:
        return ""
    for line in section.splitlines():
        match = _CAPABILITY_LINE.match(line)
        if match:
            return " ".join(match.group(1).split())
    return ""


def _unique_ids(values: Sequence[str]) -> list[str]:
    seen: set[str] = set()
    chosen: list[str] = []
    for value in values:
        task_id = value.strip()
        if task_id and task_id not in seen:
            seen.add(task_id)
            chosen.append(task_id)
    return chosen


def _batch_selection(directory: Path, tasks: Sequence[str],
                     capability: str) -> tuple[list[tuple[Path, str, str]], str]:
    """Resolve --batch IDs or a --capability name to TASK file/status tuples."""
    available = _demand_tasks(directory)
    by_id = {task_id: (task_file, status) for task_file, task_id, status in available}
    if capability.strip():
        wanted = _normalize_capability(capability)
        selected = [
            (task_file, task_id, status)
            for task_file, task_id, status in available
            if _normalize_capability(_task_capability(task_file, task_id)) == wanted
        ]
        if not selected:
            known = sorted({_task_capability(f, t) for f, t, _ in available} - {""})
            raise ValueError(
                f"unknown_capability: {capability.strip()}; available: {', '.join(known) or 'none'}"
            )
        return selected, "capability"
    chosen = _unique_ids(tasks)
    if not chosen:
        raise ValueError("batch_empty: pass --batch TASK-... or --capability <name>")
    unknown = [task_id for task_id in chosen if task_id not in by_id]
    if unknown:
        raise ValueError(f"unknown_tasks: {', '.join(unknown)}")
    return [(by_id[task_id][0], task_id, by_id[task_id][1]) for task_id in chosen], "batch"


def _batch_working_changes(root: str) -> tuple[str, ...]:
    """Current business changes, ignoring the paths the active marker excludes."""
    return tuple(sorted(
        path for path in _git_changes(root)
        if not any(fnmatch.fnmatchcase(path, pattern) for pattern in DEFAULT_ACTIVE_EXCLUDES)
    ))


def _batch_active_task(root: str) -> str:
    if not (Path(root) / ".code-flow/.active-task.json").exists():
        return ""
    return load_active_task(root).task_id


def _ensure_batch_marker(root: str, directory: str, task_id: str) -> bool:
    """Open a transient marker for one batch task; returns True when created.

    A pre-existing marker is only accepted for the same TASK. Other TASKs are
    rejected: silently switching identity would let a batch finish arbitrary
    work that was never started.
    """
    marker = Path(root) / ".code-flow/.active-task.json"
    if marker.exists():
        active = load_active_task(root)
        if active.task_id != task_id:
            raise ValueError(f"active_mismatch: marker={active.task_id} requested={task_id}")
        if active.status != "active":
            raise ValueError(f"active_not_ready: {active.task_id} is {active.status}")
        return False
    context = load_context(str(Path(directory) / "spec-context.yml"))
    start_active_task(root, directory, task_id, context_sha256(context), _batch_working_changes(root))
    return True


def _abandon_batch_marker(root: str) -> bool:
    """Drop a batch marker without changing the Markdown view.

    A failed TASK must stay open (draft/in-progress) and must not claim done;
    the marker only holds the single active slot, so it cannot be left behind
    while the rest of the batch continues.
    """
    marker = Path(root) / ".code-flow/.active-task.json"
    if not marker.exists():
        return False
    from cf_spec_context import doctor_active_task

    doctor_active_task(root, "", abandon=True)
    return True


def _task_evidence_counts(evidence: Sequence[Mapping[str, object]]) -> tuple[int, int]:
    executed = reused = 0
    for item in evidence:
        if evidence_deferral_kind(item) in ("review_stage", "heavy"):
            continue
        if item.get("error_code") in _NON_EXECUTION_ERRORS:
            continue
        details = item.get("details")
        details = details if isinstance(details, Mapping) else {}
        if details.get("cache_reused"):
            reused += 1
        else:
            executed += 1
    return executed, reused


def _acceptance_task_evidence(directory: str, task_id: str) -> list[dict[str, object]]:
    """Project the TASK's persisted manifest rows into per-check evidence."""
    manifest = Path(directory) / ".acceptance-manifest.json"
    if not manifest.is_file():
        return []
    try:
        data = load_manifest(manifest)
    except (OSError, ValueError):
        return []
    items: list[dict[str, object]] = []
    for row in data.get("scenarios") or ():
        if not isinstance(row, Mapping):
            continue
        owner = row.get("owner")
        if isinstance(owner, str) and owner and owner != task_id:
            continue
        record = row.get("evidence")
        if not isinstance(record, Mapping):
            continue
        scenario_id = str(row.get("id", ""))
        check_id = str(row.get("check") or scenario_id)
        verified = row.get("status") == "verified"
        items.append({
            "verifier_ref": check_id,
            "check_id": check_id,
            "status": "verified" if verified else "unverified",
            "error_code": None if verified else "acceptance_failed",
            "details": {"scenario": scenario_id, "cache_reused": bool(record.get("cache_reused"))},
        })
    return items


def _finish_batch_task(root: str, directory: str, task_file: str, task_id: str) -> dict[str, object]:
    """Run one TASK inside the shared batch execution session."""
    activated = _ensure_batch_marker(root, directory, task_id)
    try:
        gate = run_done_gate(root, directory, task_id=task_id)
        evidence = [*gate.evidence, *_acceptance_task_evidence(directory, task_id)]
        executed, reused = _task_evidence_counts(evidence)
        if gate.decision == "pass":
            completed = complete_task(root, directory, task_file, task_id, True)
            result = {
                **completed,
                "task": task_id,
                "decision": "pass",
                "status": "done",
                "activated": activated,
                "executed": executed,
                "reused": reused,
                "evidence": evidence,
                "session_projection": remove_session_projection(root, task_file),
            }
            return result
        result = {
            "task": task_id,
            "decision": gate.decision,
            "status": "unchanged",
            "reason": gate.message,
            "activated": activated,
            "executed": executed,
            "reused": reused,
            "missing_checks": list(gate.missing_checks),
            "next": gate.next_action,
            "evidence": evidence,
        }
        result["marker_cleared"] = _abandon_batch_marker(root)
        return result
    except Exception:
        _abandon_batch_marker(root)
        raise


def _aggregate_batch_checks(
    results: Sequence[Mapping[str, object]],
) -> tuple[list[dict[str, object]], int, int]:
    """Fold per-task evidence into one entry per check (executed once, reused N)."""
    checks: dict[str, dict[str, object]] = {}
    order: list[str] = []
    for result in results:
        task = str(result.get("task", ""))
        evidence = result.get("evidence")
        if not isinstance(evidence, Sequence):
            continue
        for item in evidence:
            if not isinstance(item, Mapping):
                continue
            kind = evidence_deferral_kind(item)
            if kind in ("review_stage", "heavy"):
                continue
            check_id = str(item.get("verifier_ref") or item.get("check_id") or "")
            if not check_id:
                continue
            entry = checks.get(check_id)
            if entry is None:
                entry = {"check_id": check_id, "status": "verified", "tasks": [],
                         "executions": 0, "reused": 0}
                checks[check_id] = entry
                order.append(check_id)
            if task and task not in entry["tasks"]:
                entry["tasks"].append(task)
            if item.get("status") != "verified":
                entry["status"] = "failed"
            if item.get("error_code") in _NON_EXECUTION_ERRORS:
                continue
            if entry["executions"] == 0:
                entry["executions"] = 1
            else:
                entry["reused"] = int(entry["reused"]) + 1
    aggregated = [checks[check_id] for check_id in order]
    executed = sum(1 for item in aggregated if int(item["executions"]) > 0)
    reused = sum(int(item["reused"]) for item in aggregated)
    return aggregated, executed, reused


def _run_batch_tasks(root: str, directory: str,
                     selected: Sequence[tuple[Path, str, str]]) -> list[dict[str, object]]:
    results: list[dict[str, object]] = []
    with execution_session():
        for task_file, task_id, status in selected:
            if status in FINISHED_STATUSES:
                results.append({"task": task_id, "decision": "pass", "status": "already_done",
                                "reason": "already_done", "activated": False,
                                "executed": 0, "reused": 0, "evidence": []})
                continue
            blockers = check_startable(str(task_file), task_id)
            if blockers:
                results.append({"task": task_id, "decision": "block", "status": status,
                                "reason": "start_blocked", "blockers": blockers,
                                "activated": False, "executed": 0, "reused": 0, "evidence": []})
                continue
            try:
                results.append(_finish_batch_task(root, directory, str(task_file), task_id))
            except (OSError, ValueError) as exc:
                results.append({"task": task_id, "decision": "block", "status": status,
                                "reason": "batch_task_error", "error": str(exc),
                                "activated": False, "executed": 0, "reused": 0, "evidence": []})
    return results


def _batch_payload(results: Sequence[Mapping[str, object]], selected: Sequence[tuple[Path, str, str]],
                   mode: str, capability: str) -> dict[str, object]:
    checks, executed, reused = _aggregate_batch_checks(results)
    decisions = {str(item.get("decision")) for item in results}
    decision = "block" if "block" in decisions else "provisional" if "provisional" in decisions else "pass"
    failed = [str(item["task"]) for item in results if item.get("decision") == "block"]
    first_reason = next(
        (str(item.get("reason", "")) for item in results if item.get("decision") != "pass"), ""
    )
    return {
        "decision": decision,
        "action": "finish-batch",
        "reason": "batch_failed: " + ", ".join(failed) if failed else first_reason,
        "selection": {"mode": mode, "tasks": [item[1] for item in selected],
                      "capability": capability.strip() or None},
        "results": list(results),
        "evidence": checks,
        "executed": executed,
        "reused": reused,
        "failed": failed,
        "env_blocked": sum(
            1 for item in results if str(item.get("reason", "")).startswith("env")
        ),
        "incomplete": sum(1 for item in results if item.get("decision") == "provisional"),
    }


def finish_batch(root: str, directory: str, tasks: Sequence[str] = (),
                 capability: str = "") -> dict[str, object]:
    """Batch Done Gate: one shared execution session for a TASK list/capability.

    Every selected TASK is gated independently, so one failure does not mark
    the others done or block their completion. Code checks shared by the batch
    execute once inside the session; their evidence is folded per check.
    """
    recover_transition(root)
    selected, mode = _batch_selection(Path(directory), tasks, capability)
    active_id = _batch_active_task(root)
    selected_ids = [task_id for _, task_id, _ in selected]
    if active_id and active_id not in selected_ids:
        return {
            "decision": "block",
            "action": "finish-batch",
            "reason": "active_mismatch",
            "detail": f"marker={active_id}; batch={','.join(selected_ids)}",
            "results": [],
        }
    # The active TASK must be consumed before any transient marker is opened.
    selected.sort(key=lambda item: 0 if item[1] == active_id else 1)
    return _batch_payload(_run_batch_tasks(root, directory, selected), selected, mode, capability)


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
    directory: str,
    targets: dict[str, dict[str, object]],
    confirmations: Optional[Mapping[str, Mapping[str, Mapping[str, object]]]] = None,
) -> dict[str, object]:
    """执行需求级全量 verifier（code+review 按 spec/rule 去重），证据写回全部相关 context。"""
    executed = reused = env_blocked = incomplete = 0
    failures: list[str] = []
    summaries: list[dict[str, object]] = []
    context_paths: set[Path] = set()
    evidence_by_context: dict[Path, list[Mapping[str, object]]] = {}
    scope = _review_scope(root)
    for spec_id in sorted(targets):
        info = targets[spec_id]
        metadata = load_spec_metadata(str(Path(root) / ".code-flow/specs" / str(info["path"])))
        result = run_all_verifiers(metadata, scope, (confirmations or {}).get(spec_id), stage=None)
        try:
            from cf_evidence_store import requirement_key
            store_verification_evidence(
                metadata, scope, result, requirement=requirement_key(directory),
            )
        except (OSError, ValueError) as exc:
            sys.stderr.write(f"cf_task_workflow: verifier evidence sidecar failed: {exc}\n")
        by_rule: dict[str, object] = {}
        for evidence in result.evidence:
            rule_ref = evidence.verifier_ref.split("#", 1)[-1]
            by_rule[rule_ref] = evidence
            summaries.append({
                "check_id": evidence.verifier_ref,
                "status": evidence.status,
                "error_code": evidence.error_code,
            })
            if evidence.status != "verified":
                if evidence.error_code in _ENV_ERROR_CODES:
                    env_blocked += 1
                elif evidence.error_code == "verifier_timeout":
                    incomplete += 1
                else:
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
    return {
        "executed": executed,
        "reused": reused,
        "failed": sorted(set(failures)),
        "env_blocked": env_blocked,
        "incomplete": incomplete,
        "evidence": summaries,
    }


VERIFY_LAYERS = ("validators", "review", "e2e")
VERIFY_PROFILES = ("smoke", "changed", "full")
_ENV_ERROR_CODES = frozenset(("env_blocked", "environment_unavailable", "command_unavailable"))


def parse_verify_layers(value: Optional[str]) -> tuple[str, ...]:
    if value is None or not value.strip():
        return VERIFY_LAYERS
    chosen: set[str] = set()
    for item in value.split(","):
        name = item.strip()
        if not name:
            continue
        if name not in VERIFY_LAYERS:
            raise ValueError(f"unknown verify layer: {name}; allowed: {', '.join(VERIFY_LAYERS)}")
        chosen.add(name)
    if not chosen:
        raise ValueError(f"--layers requires at least one of: {', '.join(VERIFY_LAYERS)}")
    return tuple(name for name in VERIFY_LAYERS if name in chosen)


def parse_verify_profile(value: Optional[str], default: str = "changed") -> str:
    profile = (value or default).strip()
    if profile not in VERIFY_PROFILES:
        raise ValueError(f"unknown verify profile: {profile}; allowed: {', '.join(VERIFY_PROFILES)}")
    return profile


def _layer_result(decision: str, *, reason: str = "", executed: int = 0, reused: int = 0,
                  failed: Optional[Sequence[str]] = None, env_blocked: int = 0, incomplete: int = 0,
                  evidence: Optional[Sequence[Mapping[str, object]]] = None,
                  **extra: object) -> dict[str, object]:
    result: dict[str, object] = {
        "decision": decision,
        "reason": reason,
        "executed": executed,
        "reused": reused,
        "failed": list(failed or ()),
        "env_blocked": env_blocked,
        "incomplete": incomplete,
        "evidence": list(evidence or ()),
    }
    result.update(extra)
    return result


def _nothing_to_verify() -> dict[str, object]:
    return _layer_result("pass", reason="nothing_to_verify")


def _validation_view(details: Mapping[str, object]) -> dict[str, object]:
    return {
        "decision": details.get("decision"),
        "reason": details.get("reason", ""),
        "reused": details.get("reused", 0),
        "failures": details.get("failures", []),
    }


def _validator_execution_count(root: str, selected: Sequence[str], reused: int) -> int:
    from cf_stop_hook import trigger_matches
    from cf_validation import _validators

    applicable = 0
    for validator in _validators(root):
        if not isinstance(validator, Mapping):
            continue
        trigger = str(validator.get("trigger", ""))
        if any(trigger_matches(trigger, path) for path in selected):
            applicable += 1
    return max(0, applicable - reused)


def _validators_layer(root: str, profile: str) -> dict[str, object]:
    try:
        from cf_validation import validate_files

        files = tuple(sorted(_git_tracked_files(root)))
        details = validate_files(root, files, include_heavy=profile == "full")
    except (OSError, ValueError) as exc:
        return _layer_result("block", reason="validation_error", detail=str(exc))
    view = _validation_view(details)
    if details.get("reason") in ("no_changes", "no_validators_configured"):
        return _layer_result("pass", reason="nothing_to_verify", validation=view)
    failures = list(details.get("failures") or ())
    failed = [str(item.get("name", "validator")) for item in failures if not item.get("incomplete")]
    incomplete = sum(1 for item in failures if item.get("incomplete"))
    reused = int(details.get("reused") or 0)
    selected = details.get("files") or ()
    executed = _validator_execution_count(root, selected, reused)
    decision = "pass" if details.get("decision") == "pass" else "block"
    return _layer_result(
        decision,
        reason="" if decision == "pass" else "validation_failed",
        executed=executed,
        reused=reused,
        failed=failed,
        incomplete=incomplete,
        validation=view,
    )


def _review_layer(root: str, directory: str) -> dict[str, object]:
    try:
        review_targets = collect_review_bindings(Path(directory))
        pending_rules, _ = _pending_manual_rules(root, review_targets)
    except ValueError as exc:
        return _layer_result("block", reason="manual_review_context_unreadable", detail=str(exc))
    if pending_rules:
        return _layer_result(
            "block",
            reason="manual_confirmation_required",
            manual_rules=pending_rules,
            next=("向用户展示待确认清单并取得明确回复后，运行 confirm-manual 批量写入确认，再重跑 verify；"
                  "Agent 不得代确认。"),
        )
    try:
        all_targets = collect_requirement_bindings(Path(directory), ("code", "review"))
    except ValueError as exc:
        return _layer_result("block", reason="review_context_unreadable", detail=str(exc))
    if not all_targets:
        return _nothing_to_verify()
    confirmations = _manual_confirmations(root, all_targets)
    review = _run_requirement_verifiers(root, directory, all_targets, confirmations)
    blocked = bool(review["failed"] or review["env_blocked"] or review["incomplete"])
    return _layer_result(
        "block" if blocked else "pass",
        reason="review_failed" if blocked else "",
        executed=int(review["executed"]),
        reused=int(review["reused"]),
        failed=review["failed"],
        env_blocked=int(review["env_blocked"]),
        incomplete=int(review["incomplete"]),
        evidence=review["evidence"],
        review={"executed": review["executed"], "reused": review["reused"], "failed": review["failed"]},
    )


def _acceptance_counts(acceptance: Mapping[str, object]) -> dict[str, object]:
    executed = reused = incomplete = env_blocked = 0
    failed: list[str] = []
    evidence: list[dict[str, object]] = []
    for item in acceptance.get("results") or ():
        if not isinstance(item, Mapping):
            continue
        scenario_id = str(item.get("id", ""))
        status = str(item.get("status", ""))
        evidence.append({"check_id": scenario_id, "status": status})
        if status == "incomplete":
            incomplete += 1
        elif status == "env_blocked":
            env_blocked += 1
        elif status in ("failed", "not_configured"):
            failed.append(scenario_id)
        elif status == "passed":
            if item.get("cache_reused"):
                reused += 1
            else:
                executed += 1
    return {"executed": executed, "reused": reused, "failed": sorted(failed),
            "env_blocked": env_blocked, "incomplete": incomplete, "evidence": evidence}


def _e2e_preflight(manifest: Path, tasks: Sequence[tuple[Path, str, str]],
                   requirement_gate: bool, profile: str = "changed") -> tuple[Optional[dict[str, object]], Optional[dict[str, object]]]:
    try:
        data = load_manifest(manifest)
        validate_execution_baseline(manifest, data)
    except (OSError, ValueError) as exc:
        return None, _layer_result("block", reason="acceptance_manifest_invalid", detail=str(exc))
    bound_task = (manifest.parent / str(data.get("task_file", ""))).resolve()
    if {task.resolve() for task, _, _ in tasks} != {bound_task}:
        return None, _layer_result("block", reason="acceptance_manifest_task_mismatch")
    if not requirement_gate:
        if not any(row.get("kind") == "e2e" for row in data["scenarios"]):
            return None, _nothing_to_verify()
        return data, None
    functional_required: list[object] = []
    manual_scenarios: list[dict[str, object]] = []
    for row in data["scenarios"]:
        if row.get("exec") == "aspirational":
            continue
        if verified_evidence(row):
            continue
        if row.get("kind") == "manual" or row.get("exec") == "manual":
            manual_scenarios.append({
                "id": row.get("id"),
                "owner": row.get("owner", ""),
                "boundary": row.get("boundary", ""),
            })
        elif row.get("kind", "functional") != "e2e":
            functional_required.append(row["id"])
    if functional_required:
        return None, _layer_result("block", reason="functional_or_manual_evidence_missing",
                                   scenarios=functional_required)
    if manual_scenarios:
        return None, _layer_result(
            "block",
            reason="manual_confirmation_required",
            manual_scenarios=manual_scenarios,
            next=("向用户展示待确认清单并取得明确回复后，运行 confirm-manual 批量写入确认，再重跑 verify；"
                  "Agent 不得代确认。"),
        )
    if not any(row.get("kind") == "e2e" for row in data["scenarios"]) and not functional_required:
        return None, _nothing_to_verify()
    return data, None


def _stale_functional_rows(data: Mapping[str, object], root: str) -> list[str]:
    """Functional rows claiming verified but recorded against different content."""
    fingerprint = worktree_fingerprint(root, include_untracked=False)
    stale: list[str] = []
    for row in data.get("scenarios", []) or []:
        if not isinstance(row, Mapping):
            continue
        if str(row.get("kind", "functional")) in ("manual", "e2e"):
            continue
        if row.get("status") == "verified" and not verified_evidence(row, fingerprint):
            stale.append(str(row.get("id")))
    return stale


def _unverified_functional_rows(data: Mapping[str, object]) -> list[str]:
    rows: list[str] = []
    for row in data.get("scenarios", []) or []:
        if not isinstance(row, Mapping):
            continue
        if str(row.get("kind", "functional")) in ("manual", "e2e") or row.get("exec") in ("manual", "aspirational"):
            continue
        if not verified_evidence(row):
            rows.append(str(row.get("id")))
    return rows


def _e2e_layer(root: str, directory: str, tasks: Sequence[tuple[Path, str, str]],
               requirement_gate: bool, profile: str = "changed", resume: bool = True,
               deadline: Optional[float] = None, max_failures: int = 0,
               fail_fast: bool = False, jobs: int = 0) -> dict[str, object]:
    manifest = Path(directory) / ".acceptance-manifest.json"
    if not manifest.exists():
        return _nothing_to_verify()
    data, failure = _e2e_preflight(manifest, tasks, requirement_gate, profile)
    if failure is not None:
        return failure
    stale = _stale_functional_rows(data, root) if requirement_gate else []
    unverified = _unverified_functional_rows(data) if requirement_gate else []
    if (stale or unverified) and profile == "changed":
        return _layer_result(
            "block",
            reason="functional_evidence_stale",
            scenarios=stale or unverified,
            next="stale functional evidence requires --profile full to re-run all affected checks",
        )
    if profile == "smoke":
        # Smoke only needs the E2E subset; functional freshness is handled by
        # the explicit changed/full gate, not by the batch smoke.
        stale = []
        unverified = []
    try:
        acceptance = run_manifest(
            str(manifest), root, write_evidence=True,
            include_e2e=bool(stale or unverified) or profile == "full",
            only_e2e=not (stale or unverified) and profile != "full",
            profile=profile, resume=resume, deadline=deadline,
            max_failures=max_failures, fail_fast=fail_fast, jobs=jobs,
        )
    except (OSError, ValueError) as exc:
        return _layer_result("block", reason="acceptance_run_error", detail=str(exc))
    counts = _acceptance_counts(acceptance)
    decision = "pass" if acceptance.get("decision") == "pass" else "block"
    extra: dict[str, object] = {"results": acceptance.get("results", [])}
    if "checks" in acceptance:
        extra["checks"] = acceptance["checks"]
    if "error" in acceptance:
        extra["error"] = acceptance["error"]
    return _layer_result(
        decision,
        reason="" if decision == "pass" else "e2e_failed",
        executed=counts["executed"],
        reused=counts["reused"],
        failed=counts["failed"],
        env_blocked=counts["env_blocked"],
        incomplete=counts["incomplete"],
        evidence=counts["evidence"],
        acceptance=acceptance,
        **extra,
    )


def _aggregate_layers(layer_results: Mapping[str, Mapping[str, object]], profile: str,
                      selected: Sequence[str]) -> dict[str, object]:
    blocking = [(name, layer) for name, layer in layer_results.items() if layer.get("decision") != "pass"]
    every_layer_empty = bool(layer_results) and all(
        layer.get("reason") == "nothing_to_verify" for layer in layer_results.values()
    )
    if blocking:
        first = blocking[0]
        reason = str(first[1].get("reason") or f"{first[0]}_failed")
    elif every_layer_empty:
        reason = "nothing_to_verify"
    else:
        reason = ""
    evidence = [
        {"layer": name, **item}
        for name, layer in layer_results.items()
        for item in layer.get("evidence", [])
        if isinstance(item, Mapping)
    ]
    result: dict[str, object] = {
        "decision": "block" if blocking else "pass",
        "reason": reason,
        "profile": profile,
        "selected_layers": list(selected),
        "layers": dict(layer_results),
        "executed": sum(int(layer.get("executed", 0)) for layer in layer_results.values()),
        "reused": sum(int(layer.get("reused", 0)) for layer in layer_results.values()),
        "failed": sorted({str(item) for layer in layer_results.values()
                          for item in layer.get("failed", [])}),
        "env_blocked": sum(int(layer.get("env_blocked", 0)) for layer in layer_results.values()),
        "incomplete": sum(int(layer.get("incomplete", 0)) for layer in layer_results.values()),
        "evidence": evidence,
    }
    for field in ("manual_rules", "manual_scenarios", "scenarios", "next"):
        merged = [layer[field] for layer in layer_results.values() if field in layer]
        if merged:
            result[field] = merged[0] if len(merged) == 1 else merged
    return result


def _promote_verified(tasks: Sequence[tuple[Path, str, str]]) -> None:
    for task_file, task_id, _ in tasks:
        _sync_markdown(str(task_file), task_id, "verified")


def _compact_requirement_contexts(root: str, directory: str) -> None:
    """Keep spec-context bounded after a full requirement gate passes."""
    from cf_evidence_store import compact_context_file
    for path in sorted(Path(directory).rglob("spec-context.yml")):
        try:
            compact_context_file(path, root=root, requirement=Path(directory).name)
        except (OSError, ValueError) as exc:
            sys.stderr.write(f"cf_task_workflow: context compaction failed: {exc}\n")


def verify_layers(root: str, directory: str, layers: Optional[str] = None,
                  profile: Optional[str] = None,
                  only_tasks: Optional[Sequence[str]] = None,
                  resume: bool = True, deadline: Optional[float] = None,
                  max_failures: int = 0, fail_fast: bool = False,
                  jobs: int = 0) -> dict[str, object]:
    """Run validators/review/e2e independently and aggregate truthful layer results.

    ``only_tasks`` scopes the batch smoke gate to the tasks merged by this run;
    unrelated unfinished tasks in the same requirement must not block it.
    """
    recover_transition(root)
    tasks = _demand_tasks(Path(directory))
    if only_tasks is not None:
        wanted = {str(task_id) for task_id in only_tasks}
        known = {task_id for _, task_id, _ in tasks}
        if wanted - known:
            return {"decision": "block", "reason": "unknown_tasks", "tasks": sorted(wanted - known)}
        tasks = [item for item in tasks if item[1] in wanted]
    unfinished = [task_id for _, task_id, status in tasks if status not in FINISHED_STATUSES]
    if unfinished:
        return {"decision": "block", "reason": "unfinished_tasks", "tasks": unfinished}
    if (Path(root) / ".code-flow/.active-task.json").exists():
        return {"decision": "block", "reason": "finish_active_task_first"}
    selected = parse_verify_layers(layers)
    resolved_profile = parse_verify_profile(profile)
    requirement_gate = set(selected) == set(VERIFY_LAYERS)
    layer_results: dict[str, dict[str, object]] = {}
    for name in selected:
        if name == "validators":
            layer_results[name] = _validators_layer(root, resolved_profile)
        elif name == "review":
            layer_results[name] = _review_layer(root, directory)
        else:
            layer_results[name] = _e2e_layer(
                root, directory, tasks, requirement_gate,
                profile=resolved_profile, resume=resume, deadline=deadline,
                max_failures=max_failures, fail_fast=fail_fast, jobs=jobs,
            )
    result = _aggregate_layers(layer_results, resolved_profile, selected)
    if requirement_gate and resolved_profile == "full" and result["decision"] == "pass":
        context_path = Path(directory) / "spec-context.yml"
        if context_path.is_file():
            context = load_context(str(context_path))
            mismatches = [
                {"task": task_id, "issues": list(issues)}
                for task_file, task_id, _ in tasks
                for issues in (task_truth_issues(str(task_file), task_id, context),)
                if issues
            ]
            if mismatches:
                result["decision"] = "block"
                result["reason"] = "task_status_truth_mismatch"
                result["tasks"] = mismatches
                return result
        _compact_requirement_contexts(root, directory)
        _promote_verified(tasks)
    return result


def verify_e2e(root: str, directory: str, layers: Optional[str] = None,
               profile: Optional[str] = None) -> dict[str, object]:
    """Legacy alias: all layers under the explicit full profile."""
    result = verify_layers(root, directory, layers or ",".join(VERIFY_LAYERS), profile or "full")
    layer_map = result.get("layers", {})
    if "review" in layer_map:
        review = layer_map["review"]
        result["review"] = review.get("review", {
            "executed": review.get("executed", 0),
            "reused": review.get("reused", 0),
            "failed": review.get("failed", []),
        })
        result["executed"] = review.get("executed", 0)
        result["reused"] = review.get("reused", 0)
        result["failed"] = review.get("failed", [])
    if "validators" in layer_map:
        result["validation"] = layer_map["validators"].get("validation", {
            "decision": layer_map["validators"].get("decision"),
            "reason": layer_map["validators"].get("reason", ""),
            "reused": layer_map["validators"].get("reused", 0),
            "failures": layer_map["validators"].get("failed", []),
        })
    if "e2e" in layer_map:
        for key in ("results", "checks", "error"):
            if key in layer_map["e2e"]:
                result[key] = layer_map["e2e"][key]
    return result


def archive_requirement(root: str, directory: str) -> dict[str, object]:
    """Runtime archive gate: full verify first, then move the requirement dir."""
    from datetime import date
    from pathlib import Path as _Path

    result = verify_layers(root, directory, layers=",".join(VERIFY_LAYERS), profile="full")
    if result.get("decision") != "pass":
        return {"decision": "block", "reason": "archive_verify_failed", "verify": result}
    source = _Path(directory)
    base = _Path(root) / ".code-flow/tasks/archived" / date.today().isoformat()
    target = base / source.name
    suffix = 2
    while target.exists():
        target = base / f"{source.name}-{suffix}"
        suffix += 1
    base.mkdir(parents=True, exist_ok=True)
    shutil.move(str(source), str(target))
    return {"decision": "pass", "archived_to": str(target)}


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


def _verify_layers_argument(layers: str, checks: bool) -> Optional[str]:
    """Map the cf-validate compatible ``--checks`` flag onto validators only."""
    if not checks:
        return layers or None
    if layers and parse_verify_layers(layers) != ("validators",):
        raise ValueError("--checks is an alias for --layers validators; pass one of them")
    return "validators"


def main(argv: Optional[Sequence[str]] = None, stdout: IO[str] = sys.stdout) -> int:
    parser = argparse.ArgumentParser(prog=os.environ.get("CF_RUNTIME_COMMAND") or None)
    parser.add_argument("action", choices=("finish", "block", "resume", "verify", "verify-e2e",
                                           "confirm-manual", "cleanup-session", "archive"),
                        metavar=os.environ.get("CF_RUNTIME_ACTION") or None)
    parser.add_argument("--root", default=os.getcwd())
    parser.add_argument("--task-dir", required=True)
    parser.add_argument("--task", default="")
    parser.add_argument("--batch", default="", help="finish multiple TASKs: TASK-001,TASK-002")
    parser.add_argument("--capability", default="", help="finish every TASK whose Capability matches")
    parser.add_argument("--layers", default="", help="verify layers: validators,review,e2e (default all)")
    parser.add_argument("--checks", action="store_true",
                        help="alias for --layers validators (cf-validate compatible entry)")
    parser.add_argument("--profile", default="", help="verify profile: smoke,changed,full (default changed)")
    parser.add_argument("--resume", action="store_true", default=False, help="resume from the first unfinished check")
    parser.add_argument("--deadline", type=float, default=0.0, help="absolute monotonic deadline (0 = unbounded)")
    parser.add_argument("--max-failures", type=int, default=0, help="stop after N failed checks (0 = unlimited)")
    parser.add_argument("--fail-fast", action="store_true", default=False, help="stop after the first failed check")
    parser.add_argument("--jobs", type=int, default=0, help="parallel check workers (0 = automatic)")
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
        if args.action == "archive":
            result = archive_requirement(root, directory)
        elif args.action == "verify":
            layers = _verify_layers_argument(args.layers, args.checks)
            result = verify_layers(
                root, directory, layers, args.profile or None,
                resume=args.resume,
                deadline=(time.monotonic() + args.deadline) if args.deadline else None,
                max_failures=args.max_failures, fail_fast=args.fail_fast, jobs=args.jobs,
            )
        elif args.action == "verify-e2e":
            result = verify_e2e(root, directory, args.layers or None, args.profile or None)
        elif args.action == "cleanup-session":
            result = cleanup_session_projections(root, directory)
        elif args.action == "confirm-manual":
            refs = [item.strip() for item in args.refs.split(",") if item.strip()]
            scenarios = [item.strip() for item in args.scenarios.split(",") if item.strip()]
            result = confirm_manual(root, directory, refs, scenarios, args.confirmed_by, args.source,
                                    args.reason, args.evidence)
        elif args.action == "finish" and (args.batch or args.capability):
            result = finish_batch(root, directory,
                                  [item for item in args.batch.split(",") if item.strip()],
                                  args.capability)
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
        return 3 if result.get("decision") in ("block", "provisional") else 0
    except (OSError, ValueError) as exc:
        stdout.write(json.dumps({"decision": "block", "error": str(exc)}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
