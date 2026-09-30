#!/usr/bin/env python3
"""Active-task scope expansion and hash-bound Done verification."""

from __future__ import annotations

from dataclasses import dataclass, replace
import hashlib
import json
from pathlib import Path
import time
from typing import Mapping, Optional

from cf_spec_context import (
    BindingInput,
    RuleBinding,
    RuleStageStatus,
    SpecBinding,
    SpecContext,
    bind_specs,
    current_owned_paths,
    load_active_task,
    load_context,
    pause_active_task,
    resync_active_hash,
    save_context,
)
from cf_spec_gate import validate_stage
from cf_spec_metadata import load_spec_metadata
from cf_spec_resolver import resolve_candidates, SpecCandidate
from cf_spec_session import context_sha256
from cf_spec_verify import VerificationEvidence, VerificationScope, run_all_verifiers
from cf_core import load_config, phase_timing, resolve_quality_loop
from cf_acceptance_schema import load_manifest, validate_execution_baseline
from cf_exec_base import execution_session


@dataclass(frozen=True)
class ScopeResult:
    decision: str
    files: tuple[str, ...]
    new_specs: tuple[str, ...]
    message: str


@dataclass(frozen=True)
class DoneResult:
    decision: str
    files: tuple[str, ...]
    evidence: tuple[Mapping[str, object], ...]
    message: str = ""
    deferred_review: int = 0


def _context_path(task_dir: str) -> str:
    return str(Path(task_dir) / "spec-context.yml")


def _acceptance_baseline_issue(task_dir: str, owner: str) -> str:
    from cf_workflow_service import locate_task_file
    path = Path(task_dir) / ".acceptance-manifest.json"
    task = locate_task_file(task_dir, owner)
    try:
        requires = task is not None and "## Acceptance Coverage" in task.read_text(encoding="utf-8")
        if not path.is_file():
            return "acceptance_manifest_missing" if requires else ""
        data = load_manifest(path)
        if requires:
            from cf_acceptance_manifest import validate_manifest
            valid, reason = validate_manifest(str(task), str(path))
            if not valid:
                return reason
        validate_execution_baseline(path, data)
        return ""
    except (OSError, ValueError) as exc:
        return f"acceptance_manifest_invalid: {exc}"


def _required_candidate(candidate: SpecCandidate) -> bool:
    metadata = candidate.metadata
    return metadata.enforcement == "required" and any(
        rule.enforcement == "required" for rule in metadata.rules
    )


def evaluate_scope(root: str, task_dir: str) -> ScopeResult:
    active = load_active_task(root)
    files = current_owned_paths(root, active)
    context = load_context(_context_path(task_dir))
    candidates = resolve_candidates(root, "code", files)
    existing = {binding.spec_id for binding in context.bindings}
    new = tuple(
        candidate
        for candidate in candidates
        if candidate.scope == "path" and candidate.spec_id not in existing
    )
    if not new:
        return ScopeResult("continue", files, (), "scope unchanged")
    selections = tuple(
        BindingInput(candidate, "scope:path", f"Git diff matched {','.join(candidate.matched_paths)}")
        for candidate in new
    )
    save_context(_context_path(task_dir), bind_specs(context, selections))
    # The toolchain expanded the context itself; re-sync the marker so this
    # automatic change does not surface as active_context_drift with no recovery.
    resync_active_hash(root, task_dir, context_sha256(load_context(_context_path(task_dir))))
    required = tuple(candidate.spec_id for candidate in new if _required_candidate(candidate))
    if required:
        pause_active_task(root)
        message = "新增 required Spec 已暂停 TASK；请选择局部 Plan 或回 Align 更新设计"
        return ScopeResult("pause", files, required, message)
    return ScopeResult("continue", files, tuple(candidate.spec_id for candidate in new), "advisory scope expanded")


def _diff_hash(root: str, files: tuple[str, ...]) -> str:
    digest = hashlib.sha256()
    for relative in files:
        path = Path(root) / relative
        digest.update(relative.encode())
        digest.update(path.read_bytes() if path.is_file() else b"<deleted>")
    return digest.hexdigest()


def _evidence_data(evidence: VerificationEvidence) -> Mapping[str, object]:
    return {
        "verifier_ref": evidence.verifier_ref,
        "executed_at": evidence.executed_at,
        "status": evidence.status,
        "rule_text_sha256": evidence.rule_text_sha256,
        "artifact_sha256": evidence.artifact_sha256,
        "diff_sha256": evidence.diff_sha256,
        "result_sha256": evidence.result_sha256,
        "error_code": evidence.error_code,
        "details": evidence.details,
    }


def _update_rule(rule: RuleBinding, evidence: Mapping[str, object]) -> RuleBinding:
    stage = rule.verifier_stage or "code"
    if stage not in rule.stage_status:
        return rule
    statuses = dict(rule.stage_status)
    current = statuses[stage]
    if current.status in ("not_applicable", "waived"):
        return rule
    status = "verified" if evidence.get("status") == "verified" else "unverified"
    if evidence.get("error_code") == "skipped_in_cheap_gate":
        signature = (evidence.get("verifier_ref"), evidence.get("result_sha256"), None)
    else:
        signature = (evidence.get("verifier_ref"), evidence.get("result_sha256"), evidence.get("diff_sha256"))
    if any(
        (item.get("verifier_ref"), item.get("result_sha256"), item.get("diff_sha256")) == signature
        for item in current.evidence
    ):
        statuses[stage] = replace(current, status=status)
    else:
        statuses[stage] = replace(current, status=status, evidence=(*current.evidence, evidence))
    return replace(rule, stage_status=statuses)


def _apply_evidence(context: SpecContext, evidence: tuple[Mapping[str, object], ...]) -> SpecContext:
    by_ref = {str(item["verifier_ref"]): item for item in evidence}
    bindings: list[SpecBinding] = []
    for binding in context.bindings:
        rules = tuple(
            _update_rule(rule, by_ref[f"{binding.spec_id}#{rule.ref}"])
            if f"{binding.spec_id}#{rule.ref}" in by_ref else rule
            for rule in binding.rules
        )
        bindings.append(replace(binding, rules=rules))
    return replace(context, bindings=tuple(bindings))


def _rule_manual_confirmation(rule: RuleBinding) -> Optional[Mapping[str, object]]:
    status = rule.stage_status.get("code")
    if status is None or status.decision is None or status.decision.kind != "manual_verification":
        return None
    decision = status.decision
    return {
        "reason": decision.reason,
        "confirmed_by": decision.confirmed_by,
        "confirmed_at": decision.confirmed_at,
        "source": decision.source,
    }


def _run_acceptance(root: str, task_dir: str, owner: str, include_e2e: bool,
                    deadline: Optional[float], cheap: bool = False) -> str:
    baseline_issue = _acceptance_baseline_issue(task_dir, owner)
    if baseline_issue:
        return baseline_issue
    # manual 场景的人工确认统一在需求级终验（verify-e2e + confirm-manual）完成，
    # 不在每个任务的 Done Gate 中逐任务阻断。
    if cheap:
        # 轻量门禁：只做 manifest 基线检查，不执行 functional 场景；
        # 场景命令由 finish 的全量 Done Gate 执行。
        return ""
    manifest_path = Path(task_dir) / ".acceptance-manifest.json"
    if manifest_path.is_file():
        from cf_acceptance_runner import run_manifest
        scenario_result = run_manifest(str(manifest_path), root, write_evidence=True, include_e2e=include_e2e, owner=owner, deadline=deadline)
        if scenario_result["decision"] == "block":
            reason = scenario_result.get("error") or "acceptance scenario failed"
            return f"acceptance scenario failed: {reason}"
    return ""


def _run_finish_validation(root: str, files: tuple[str, ...]) -> str:
    """Full validation.yml (including heavy validators) once per TASK finish.

    Stop-time checks stay cheap; this is the single automatic execution point
    for slow suites (task finish `/cf-validate` scope). `quality_loop.finish_check:
    false` disables it; projects without validation.yml / package.json scripts are a no-op.
    """
    if not resolve_quality_loop(load_config(root)).get("finish_check"):
        return ""
    from cf_validation import validate_files

    try:
        result = validate_files(root, files)
    except (OSError, ValueError) as exc:
        return f"finish validation error: {exc}"
    reason = result.get("reason")
    if result.get("decision") == "pass" or reason in ("no_changes", "no_validators_configured"):
        return ""
    failures = result.get("failures")
    names = ", ".join(str(item.get("name", "validator")) for item in failures[:3]) if isinstance(failures, list) and failures else "validator"
    if result.get("incomplete") and not failures:
        return "finish validation 预算耗尽：部分 validator 未执行"
    suffix = "（预算耗尽，部分未执行）" if result.get("incomplete") else ""
    return f"finish validation failed{suffix}: {names}"


def _run_done_gate(root: str, task_dir: str, cheap: bool = False, budget: Optional[float] = None, include_e2e: bool = False, task_id: str = "") -> DoneResult:
    active = load_active_task(root)
    owner = task_id or active.task_id
    if owner != active.task_id or (Path(root) / active.task_dir).resolve() != Path(task_dir).resolve():
        return DoneResult("block", (), (), "active_mismatch: task identity does not match marker")
    started = time.monotonic()
    scope_result = evaluate_scope(root, task_dir)
    phase_timing("done.evaluate_scope", started)
    if scope_result.decision == "pause":
        return DoneResult("block", scope_result.files, (), scope_result.message)
    deadline = started + budget if budget is not None else None
    issue = _run_acceptance(root, task_dir, owner, include_e2e, deadline, cheap)
    if issue:
        return DoneResult("block", scope_result.files, (), issue)
    phase_started = time.monotonic()
    context = load_context(_context_path(task_dir))
    diff_hash = _diff_hash(root, scope_result.files)
    phase_timing("done.load_context_and_diff", phase_started)
    all_evidence: list[Mapping[str, object]] = []
    deferred_review = 0
    for binding in context.bindings:
        phase_started = time.monotonic()
        metadata = load_spec_metadata(str(Path(root) / ".code-flow/specs" / binding.path))
        deferred_review += sum(1 for rule in binding.rules if rule.verifier_stage == "review")
        confirmations: dict[str, Mapping[str, object]] = {}
        for rule in binding.rules:
            confirmation = _rule_manual_confirmation(rule)
            if confirmation is not None:
                confirmations[rule.ref] = confirmation
        remaining = None if budget is None else budget - (time.monotonic() - started)
        result = run_all_verifiers(
            metadata, VerificationScope(root, scope_result.files, diff_hash), confirmations, cheap, remaining,
            stage="code",
        )
        phase_timing(f"done.verify.{binding.spec_id}", phase_started)
        all_evidence.extend(_evidence_data(item) for item in result.evidence)
    updated = _apply_evidence(context, tuple(all_evidence))
    if updated != context:
        save_context(_context_path(task_dir), updated)
    gate = validate_stage(updated, "code", diff_sha256=diff_hash, allow_cheap_skips=cheap)
    if gate.decision == "pass" and not cheap:
        validation_issue = _run_finish_validation(root, scope_result.files)
        if validation_issue:
            return DoneResult("block", scope_result.files, tuple(all_evidence), validation_issue, deferred_review)
    phase_timing("done.total", started)
    return DoneResult(gate.decision, scope_result.files, tuple(all_evidence),
                      "; ".join(issue.message for issue in gate.errors), deferred_review)


def run_done_gate(root: str, task_dir: str, cheap: bool = False, budget: Optional[float] = None, include_e2e: bool = False, task_id: str = "") -> DoneResult:
    with execution_session():
        return _run_done_gate(root, task_dir, cheap, budget, include_e2e, task_id)
