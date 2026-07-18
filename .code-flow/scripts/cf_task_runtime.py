#!/usr/bin/env python3
"""Active-task scope expansion and hash-bound Done verification."""

from __future__ import annotations

from dataclasses import dataclass, replace
import hashlib
from pathlib import Path
from typing import Mapping

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
    save_context,
)
from cf_spec_gate import validate_stage
from cf_spec_metadata import load_spec_metadata
from cf_spec_resolver import resolve_candidates, SpecCandidate
from cf_spec_verify import VerificationEvidence, VerificationScope, run_all_verifiers


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


def _context_path(task_dir: str) -> str:
    return str(Path(task_dir) / "spec-context.yml")


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
    if "code" not in rule.stage_status:
        return rule
    statuses = dict(rule.stage_status)
    current = statuses["code"]
    status = "verified" if evidence.get("status") == "verified" else "unverified"
    statuses["code"] = replace(current, status=status, evidence=(*current.evidence, evidence))
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


def run_done_gate(root: str, task_dir: str) -> DoneResult:
    scope_result = evaluate_scope(root, task_dir)
    if scope_result.decision == "pause":
        return DoneResult("block", scope_result.files, ())
    context = load_context(_context_path(task_dir))
    diff_hash = _diff_hash(root, scope_result.files)
    all_evidence: list[Mapping[str, object]] = []
    for binding in context.bindings:
        metadata = load_spec_metadata(str(Path(root) / ".code-flow/specs" / binding.path))
        result = run_all_verifiers(metadata, VerificationScope(root, scope_result.files, diff_hash))
        all_evidence.extend(_evidence_data(item) for item in result.evidence)
    updated = _apply_evidence(context, tuple(all_evidence))
    save_context(_context_path(task_dir), updated)
    gate = validate_stage(updated, "code")
    return DoneResult(gate.decision, scope_result.files, tuple(all_evidence))
