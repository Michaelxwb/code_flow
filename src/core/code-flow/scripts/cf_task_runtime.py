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
from cf_spec_metadata import SpecMetadata, load_spec_metadata
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
    deferred_requirement: int = 0
    deferred_budget: int = 0
    deferred_heavy: int = 0


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
    # Cheap-gate skips carry no per-run diff freshness requirement: dedup on
    # (verifier_ref, result_sha256) — the third slot stays None on BOTH sides.
    # Storing a real diff_sha256 in the signature made every Stop append a
    # duplicate skip entry (signature never matched).
    signature = (evidence.get("verifier_ref"), evidence.get("result_sha256"),
                 None if evidence.get("error_code") == "skipped_in_cheap_gate" else evidence.get("diff_sha256"))
    if any(
        (item.get("verifier_ref"), item.get("result_sha256"),
         None if item.get("error_code") == "skipped_in_cheap_gate" else item.get("diff_sha256")) == signature
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


def _task_scope_specs(root: str, task_dir: str, owner: str, files: tuple[str, ...]) -> set[str]:
    """本任务的验证范围：Spec-Refs ∪ 改动文件经 path_mapping 命中的 spec。

    范围外的 code 层 command/test verifier 延后到需求级 verify-e2e 全量补跑。
    """
    scope = {
        candidate.spec_id
        for candidate in resolve_candidates(root, "code", files)
        if candidate.scope == "path"
    }
    from cf_workflow_service import locate_task_file

    task = locate_task_file(task_dir, owner)
    if task is None:
        return scope
    from cf_spec_session import _refs, _task_section

    try:
        refs = _refs(_task_section(task.read_text(encoding="utf-8"), owner))
    except ValueError:
        refs = ()
    for ref in refs:
        spec_id = ref.split("#", 1)[0].strip()
        if spec_id:
            scope.add(spec_id)
    return scope


def _binding_deferrals(
    binding: SpecBinding,
    metadata: SpecMetadata,
    scope_specs: set[str],
    budget: float,
    run_started: float,
) -> dict[str, str]:
    """计算本 binding 内 code 层 command/test verifier 的延后原因。

    - `out_of_task_scope`：不属于本任务（需求级累积绑定）；
    - `over_finish_budget`：声明 timeout 超预算，或本次 finish 已用满预算。
    document/regex/ast 静态检查始终执行，不参与延后。
    """
    deferred: dict[str, str] = {}
    verifier_by_rule = {item.rule: item for item in metadata.verifiers}
    for rule in binding.rules:
        verifier = verifier_by_rule.get(rule.ref)
        if verifier is None or verifier.type not in ("command", "test"):
            continue
        status = rule.stage_status.get("code")
        if status is None or status.status in ("not_applicable", "waived"):
            continue
        if binding.spec_id not in scope_specs:
            deferred[rule.ref] = "out_of_task_scope"
            continue
        if budget > 0:
            raw_timeout = verifier.config.get("timeout", 30)
            try:
                declared = float(raw_timeout)
            except (TypeError, ValueError):
                declared = 30.0
            if declared > budget or (time.monotonic() - run_started) >= budget:
                deferred[rule.ref] = "over_finish_budget"
    return deferred


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


def _run_finish_validation(root: str, files: tuple[str, ...]) -> tuple[str, int]:
    """Light validation.yml once per TASK finish; heavy validators defer by default.

    Stop-time checks stay cheap; `heavy: true` suites (full tests/builds/e2e) are
    skipped unless `quality_loop.heavy_at_finish: true`, and run again at archive
    `cf_validation` / `/cf-validate`. Returns (issue, deferred_heavy_count).
    """
    quality = resolve_quality_loop(load_config(root))
    if not quality.get("finish_check"):
        return "", 0
    include_heavy = bool(quality.get("heavy_at_finish"))
    from cf_validation import validate_files

    try:
        result = validate_files(root, files, include_heavy=include_heavy)
    except (OSError, ValueError) as exc:
        return f"finish validation error: {exc}", 0
    deferred_heavy = 0
    if not include_heavy:
        from cf_stop_hook import load_validators, trigger_matches

        deferred_heavy = sum(
            1
            for validator in load_validators(root)
            if isinstance(validator, dict)
            and validator.get("heavy") is True
            and any(trigger_matches(str(validator.get("trigger", "")), name) for name in files)
        )
    reason = result.get("reason")
    if result.get("decision") == "pass" or reason in ("no_changes", "no_validators_configured"):
        return "", deferred_heavy
    failures = result.get("failures")
    names = ", ".join(str(item.get("name", "validator")) for item in failures[:3]) if isinstance(failures, list) and failures else "validator"
    if result.get("incomplete") and not failures:
        return "finish validation 预算耗尽：部分 validator 未执行", deferred_heavy
    suffix = "（预算耗尽，部分未执行）" if result.get("incomplete") else ""
    return f"finish validation failed{suffix}: {names}", deferred_heavy


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
    deferred_requirement = 0
    deferred_budget = 0
    deferred_heavy = 0
    quality = resolve_quality_loop(load_config(root))
    verifier_budget = float(quality.get("finish_verifier_budget", 300.0))
    scope_specs = set() if cheap else _task_scope_specs(root, task_dir, owner, scope_result.files)
    if not cheap and not scope_specs:
        # 既无 Spec-Refs 也无路径命中（老任务/无改动可定位）：回退全量绑定，
        # 避免把"定位不到"误当成"无需验证"。
        scope_specs = {binding.spec_id for binding in context.bindings}
    run_started = time.monotonic()
    for binding in context.bindings:
        phase_started = time.monotonic()
        metadata = load_spec_metadata(str(Path(root) / ".code-flow/specs" / binding.path))
        deferred_review += sum(1 for rule in binding.rules if rule.verifier_stage == "review")
        deferrals = {} if cheap else _binding_deferrals(binding, metadata, scope_specs, verifier_budget, run_started)
        deferred_requirement += sum(
            1 for rule in binding.rules
            if deferrals.get(rule.ref) == "out_of_task_scope" and rule.enforcement == "required"
        )
        deferred_budget += sum(
            1 for rule in binding.rules
            if deferrals.get(rule.ref) == "over_finish_budget" and rule.enforcement == "required"
        )
        confirmations: dict[str, Mapping[str, object]] = {}
        for rule in binding.rules:
            confirmation = _rule_manual_confirmation(rule)
            if confirmation is not None:
                confirmations[rule.ref] = confirmation
        remaining = None if budget is None else budget - (time.monotonic() - started)
        result = run_all_verifiers(
            metadata, VerificationScope(root, scope_result.files, diff_hash), confirmations, cheap, remaining,
            stage="code", deferred=deferrals or None,
        )
        phase_timing(f"done.verify.{binding.spec_id}", phase_started)
        all_evidence.extend(_evidence_data(item) for item in result.evidence)
    updated = _apply_evidence(context, tuple(all_evidence))
    if updated != context:
        save_context(_context_path(task_dir), updated)
    gate = validate_stage(updated, "code", diff_sha256=diff_hash, allow_cheap_skips=cheap,
                          allow_deferred_skips=True)
    if gate.decision == "pass" and not cheap:
        validation_issue, deferred_heavy = _run_finish_validation(root, scope_result.files)
        if validation_issue:
            return DoneResult("block", scope_result.files, tuple(all_evidence), validation_issue,
                              deferred_review, deferred_requirement, deferred_budget, deferred_heavy)
    phase_timing("done.total", started)
    return DoneResult(gate.decision, scope_result.files, tuple(all_evidence),
                      "; ".join(issue.message for issue in gate.errors), deferred_review,
                      deferred_requirement, deferred_budget, deferred_heavy)


def run_done_gate(root: str, task_dir: str, cheap: bool = False, budget: Optional[float] = None, include_e2e: bool = False, task_id: str = "") -> DoneResult:
    with execution_session():
        return _run_done_gate(root, task_dir, cheap, budget, include_e2e, task_id)
