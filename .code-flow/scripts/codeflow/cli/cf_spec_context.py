#!/usr/bin/env python3
"""Persisted Spec Context CLI: binding, decisions, refresh and doctor.

The pure model, serialization and identity hash live in
`codeflow.spec.cf_spec_context_model`; the active marker, lock and Git
ownership scope live in `codeflow.spec.cf_active_task`. This module keeps the
CLI entry, doctor and decision orchestration.
"""

from __future__ import annotations

import argparse
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import sys
import time
from typing import IO, Mapping, Optional, Sequence

from codeflow.spec.cf_active_task import (  # re-exported context API
    ACTIVE_STATUSES,
    ActiveBaseline,
    ActiveTask,
    DEFAULT_ACTIVE_EXCLUDES,
    DoctorResult,
    PathSnapshot,
    active_data,
    active_paths,
    block_active_task,
    business_changes as _business_changes,
    complete_active_task,
    current_owned_paths,
    doctor_active_task,
    git_changes as _git_changes,
    load_active_task,
    pause_active_task,
    resume_active_task,
    save_active_task,
    start_active_task,
)
from codeflow.spec.cf_spec_context_model import (  # re-exported context API
    ArtifactRef,
    BindingInput,
    ContextError,
    ContextSource,
    Decision,
    DriftChange,
    DriftResult,
    RuleBinding,
    RuleStageStatus,
    SpecBinding,
    SpecContext,
    context_sha256,
    decision_from_data,
    error_payload,
    load_context,
    mapping_field,
    new_context,
    now_iso,
    save_context,
    sequence_field,
    string_field,
    validate_decision,
)
from codeflow.spec.cf_spec_metadata import SpecHashes, SpecMetadata, SpecRule, load_spec_metadata
from codeflow.spec.cf_spec_resolver import SpecCandidate, resolve_candidates
from codeflow.task.cf_task_doc import TaskDocumentError, task_section
from codeflow.core.cf_core import phase_timing


_FILE_HASH_CACHE: dict[str, tuple[int, int, int, str]] = {}
_PERSISTENT_HASH_CACHE: dict[str, dict[str, object]] = {}
_PERSISTENT_HASH_PATHS: set[str] = set()
_MAX_HASH_CACHE_ENTRIES = 4096


def task_contract_digest(root: str, task_dir: str, task_id: str) -> str:
    """Legacy version digest of TASK Spec/Design refs and acceptance inputs.

    Two TASKs may share one Context hash while owning different scenarios; the
    digest separates their injection versions so switching TASKs re-injects.
    Returns "" when the TASK section cannot be located (fail-open to the
    legacy context-hash-only key rather than crashing the hook hot path).
    """
    try:
        files = sorted((Path(root) / task_dir).glob("*.md"))
    except OSError:
        return ""
    for path in files:
        if path.name.endswith((".prd.md", ".design.md")):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            continue
        try:
            section = task_section(text, task_id, source=str(path))
        except TaskDocumentError as exc:
            if exc.code in ("task_document_empty", "task_not_found"):
                continue
            return ""
        body = section.body
        chunks: list[str] = []
        for heading in ("Spec-Refs", "Source", "Design-Refs", "Acceptance-Refs", "Acceptance Contract", "Acceptance Evidence"):
            index = body.find(heading)
            if index == -1:
                chunks.append(f"{heading}:missing")
                continue
            end = body.find("\n### ", index)
            chunks.append(body[index:] if end == -1 else body[index:end])
        return hashlib.sha256("\n".join(chunks).encode("utf-8")).hexdigest()
    return ""


def injection_version(root: str, session_id: str, context_sha: str) -> str:
    """Version key for hook injection dedup.

    Covers session + task_dir + task_id + context hash + TASK contract digest,
    so a TASK switch (or an in-place contract edit) always re-injects while a
    repeated prompt on the same contract stays suppressed.
    """
    try:
        active = load_active_task(root)
    except (ContextError, OSError, ValueError):
        return f"none:{session_id}:{context_sha}"
    digest = task_contract_digest(root, active.task_dir, active.task_id)
    raw = "\n".join((session_id, active.task_dir, active.task_id, context_sha, digest))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def resync_active_hash(root: str, task_dir: str, current_sha256: str) -> bool:
    """Re-sync the active marker's context hash after toolchain-initiated
    context edits (bind/decision/refresh) so they never surface as
    unrecoverable active_context_drift. No-op without an active marker or when
    the hash already matches; never raises on a missing marker.

    Only the active demand may re-sync: editing another demand's context must
    never overwrite the marker hash (cross-demand drift).
    """
    marker = Path(root) / ".code-flow" / ".active-task.json"
    if not marker.exists():
        return False
    active = load_active_task(root)
    requested = Path(task_dir)
    requested = (Path(root) / requested if not requested.is_absolute() else requested).resolve()
    active_dir = Path(active.task_dir)
    active_dir = (Path(root) / active_dir if not active_dir.is_absolute() else active_dir).resolve()
    if active_dir != requested:
        return False
    if active.context_sha256 == current_sha256:
        return False
    save_active_task(root, replace(active, context_sha256=current_sha256))
    return True


def _find_root(task_dir: str) -> Optional[str]:
    """Walk up from a task dir to the project root that owns its marker."""
    current = Path(task_dir).resolve()
    for candidate in (current, *current.parents):
        if (candidate / ".code-flow" / ".active-task.json").exists():
            return str(candidate)
    return None


def _resync_after_save(args: argparse.Namespace, context_path: Path) -> bool:
    """Post-save marker re-sync used by CLI commands that persist the context."""
    root = getattr(args, "root", "") or _find_root(str(context_path.parent)) or ""
    if not root:
        return False
    current = context_sha256(load_context(str(context_path)))
    return resync_active_hash(root, str(context_path.parent), current)


def _binding_from_input(selection: BindingInput) -> SpecBinding:
    if not selection.selected_by.strip() or not selection.reason.strip():
        raise ContextError("invalid_binding", "selection", "selected_by/reason 必须非空")
    candidate = selection.candidate
    verifier_by_rule = {item.rule: item for item in candidate.metadata.verifiers}
    rules: list[RuleBinding] = []
    for rule in candidate.metadata.rules:
        if rule.enforcement == "informational":
            continue
        enforcement = "advisory" if candidate.metadata.enforcement == "advisory" else rule.enforcement
        statuses = {
            stage: RuleStageStatus("pending", (), None, ()) for stage in candidate.metadata.stages
        }
        verifier = verifier_by_rule.get(rule.ref)
        verifier_ref = f"{candidate.spec_id}#{rule.ref}" if verifier is not None else "advisory:none"
        rules.append(
            RuleBinding(
                rule.ref, rule.text, rule.text_sha256, enforcement, verifier_ref, statuses,
                verifier.stage if verifier is not None else "code",
            )
        )
    return SpecBinding(
        candidate.spec_id,
        candidate.path,
        candidate.metadata.hashes,
        selection.selected_by.strip(),
        selection.reason.strip(),
        candidate.metadata.enforcement,
        candidate.metadata.stages,
        tuple(rules),
    )


def _with_declared_stages(rule: RuleBinding, stages: Sequence[str]) -> RuleBinding:
    """兼容补齐：绑定旧版本时声明的 stages 缺状态，按声明补 pending。"""
    missing = [stage for stage in stages if stage not in rule.stage_status]
    if not missing:
        return rule
    statuses = dict(rule.stage_status)
    for stage in missing:
        statuses[stage] = RuleStageStatus("pending", (), None, ())
    return replace(rule, stage_status=statuses)


def _rule_from_metadata(spec_id: str, metadata: SpecMetadata, rule: SpecRule) -> RuleBinding:
    enforcement = "advisory" if metadata.enforcement == "advisory" else rule.enforcement
    statuses = {stage: RuleStageStatus("pending", (), None, ()) for stage in metadata.stages}
    verifier = next((item for item in metadata.verifiers if item.rule == rule.ref), None)
    verifier_ref = f"{spec_id}#{rule.ref}" if verifier is not None else "advisory:none"
    return RuleBinding(
        rule.ref, rule.text, rule.text_sha256, enforcement, verifier_ref, statuses,
        verifier.stage if verifier is not None else "code",
    )


def bind_specs(context: SpecContext, selections: Sequence[BindingInput]) -> SpecContext:
    bindings = {binding.spec_id: binding for binding in context.bindings}
    for selection in selections:
        incoming = _binding_from_input(selection)
        existing = bindings.get(incoming.spec_id)
        if existing is not None and existing.hashes != incoming.hashes:
            raise ContextError(
                "stale_binding",
                "selection",
                f"{incoming.spec_id} 已绑定版本发生变化，请先 refresh",
            )
        if existing is not None:
            incoming = replace(
                existing,
                selected_by=incoming.selected_by,
                reason=incoming.reason,
                enforcement=incoming.enforcement,
                stages=incoming.stages,
            )
        bindings[incoming.spec_id] = incoming
    ordered = tuple(bindings[key] for key in sorted(bindings))
    if ordered == context.bindings:
        return context
    return replace(context, updated_at=now_iso(), bindings=ordered)


def refresh_missing_specs(context: SpecContext, root: str) -> SpecContext:
    spec_root = Path(root) / ".code-flow" / "specs"
    bindings: list[SpecBinding] = []
    for binding in context.bindings:
        if (spec_root / binding.path).is_file():
            bindings.append(binding)
            continue
        rules = []
        for rule in binding.rules:
            stages = {stage: replace(status, status="stale") for stage, status in rule.stage_status.items()}
            rules.append(replace(rule, stage_status=stages))
        bindings.append(replace(binding, status="missing", rules=tuple(rules)))
    return replace(context, updated_at=now_iso(), bindings=tuple(bindings))


def _stale_rule(rule: RuleBinding) -> RuleBinding:
    statuses = {stage: replace(status, status="stale") for stage, status in rule.stage_status.items()}
    return replace(rule, stage_status=statuses)


def _removed_rule(rule: RuleBinding) -> RuleBinding:
    statuses = {
        stage: status
        if status.status in ("not_applicable", "waived") and status.decision is not None
        else replace(status, status="stale")
        for stage, status in rule.stage_status.items()
    }
    return replace(rule, stage_status=statuses)


def _file_sha256(path: Path) -> str:
    try:
        stat = path.stat()
        key = str(path)
        cached = _FILE_HASH_CACHE.get(key)
        signature = (stat.st_mtime_ns, stat.st_size, stat.st_ino)
        if cached is not None and cached[:3] == signature:
            return cached[3]
        cache_path = next(
            (parent / ".artifact-hash-cache.json" for parent in path.parents if parent.name == ".code-flow"),
            None,
        )
        cache_key = str(cache_path) if cache_path is not None else ""
        if cache_key and cache_key not in _PERSISTENT_HASH_PATHS:
            try:
                loaded = json.loads(cache_path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    _PERSISTENT_HASH_CACHE.update({str(k): v for k, v in loaded.items() if isinstance(v, dict)})
            except (OSError, ValueError):
                pass
            _PERSISTENT_HASH_PATHS.add(cache_key)
        persistent = _PERSISTENT_HASH_CACHE.get(key)
        if (
            isinstance(persistent, dict)
            and persistent.get("mtime_ns") == stat.st_mtime_ns
            and persistent.get("size") == stat.st_size
            and persistent.get("ino") == stat.st_ino
        ):
            digest = persistent.get("sha256")
            if isinstance(digest, str) and digest:
                _FILE_HASH_CACHE[key] = (signature[0], signature[1], signature[2], digest)
                return digest
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        _FILE_HASH_CACHE[key] = (signature[0], signature[1], signature[2], digest)
        if cache_key:
            _PERSISTENT_HASH_CACHE[key] = {
                "mtime_ns": stat.st_mtime_ns,
                "size": stat.st_size,
                "ino": stat.st_ino,
                "sha256": digest,
            }
            while len(_PERSISTENT_HASH_CACHE) > _MAX_HASH_CACHE_ENTRIES:
                _PERSISTENT_HASH_CACHE.pop(next(iter(_PERSISTENT_HASH_CACHE)))
            try:
                temporary = cache_path.with_suffix(".json.tmp")
                temporary.write_text(
                    json.dumps(_PERSISTENT_HASH_CACHE, ensure_ascii=False, sort_keys=True),
                    encoding="utf-8",
                )
                temporary.replace(cache_path)
            except OSError:
                pass
        return digest
    except OSError as exc:
        raise ContextError("artifact_read_error", "artifact", str(exc), str(path)) from exc


def _refresh_artifacts(
    spec_id: str, rule: RuleBinding, artifact_root: Path
) -> tuple[RuleBinding, tuple[DriftChange, ...]]:
    statuses = dict(rule.stage_status)
    changes: list[DriftChange] = []
    for stage, status in rule.stage_status.items():
        for reference in status.refs:
            path = artifact_root / reference.artifact
            current = _file_sha256(path) if path.is_file() else "missing"
            if current == reference.artifact_sha256:
                continue
            if status.status == "applied" and current != "missing":
                statuses[stage] = replace(
                    status,
                    refs=tuple(
                        replace(item, artifact_sha256=current) if item is reference else item
                        for item in status.refs
                    ),
                )
            else:
                statuses[stage] = replace(status, status="stale")
            changes.append(
                DriftChange("artifact_changed", spec_id, rule.ref, reference.artifact_sha256, current, (stage,))
            )
            break
    return replace(rule, stage_status=statuses), tuple(changes)


def _refresh_existing_rule(
    binding: SpecBinding, existing: RuleBinding, current: SpecRule, metadata: SpecMetadata
) -> tuple[RuleBinding, Optional[DriftChange]]:
    enforcement = "advisory" if metadata.enforcement == "advisory" else current.enforcement
    verifier = next((item for item in metadata.verifiers if item.rule == current.ref), None)
    verifier_ref = f"{binding.spec_id}#{current.ref}" if verifier is not None else "advisory:none"
    updated = replace(
        existing,
        summary=current.text,
        text_sha256=current.text_sha256,
        enforcement=enforcement,
        verifier_ref=verifier_ref,
        verifier_stage=verifier.stage if verifier is not None else "code",
    )
    if existing.text_sha256 == current.text_sha256:
        return updated, None
    change = DriftChange(
        "rule_changed", binding.spec_id, current.ref, existing.text_sha256, current.text_sha256, tuple(existing.stage_status)
    )
    return _stale_rule(updated), change


def _refresh_binding(
    binding: SpecBinding, spec_root: Path, artifact_root: Path
) -> tuple[SpecBinding, tuple[DriftChange, ...]]:
    path = spec_root / binding.path
    if not path.is_file():
        stale = replace(binding, status="missing", rules=tuple(_stale_rule(rule) for rule in binding.rules))
        change = DriftChange("spec_missing", binding.spec_id, "", binding.hashes.file_sha256, "missing", binding.stages)
        return stale, (change,)
    metadata = load_spec_metadata(str(path))
    existing = {rule.ref: rule for rule in binding.rules}
    rules: list[RuleBinding] = []
    changes: list[DriftChange] = []
    if metadata.hashes.metadata_sha256 != binding.hashes.metadata_sha256:
        changes.append(
            DriftChange("metadata_changed", binding.spec_id, "", binding.hashes.metadata_sha256, metadata.hashes.metadata_sha256, ())
        )
    for current in metadata.rules:
        if current.enforcement == "informational":
            continue
        prior = existing.pop(current.ref, None)
        if prior is None:
            rule = _rule_from_metadata(binding.spec_id, metadata, current)
            changes.append(DriftChange("rule_added", binding.spec_id, current.ref, "", current.text_sha256, metadata.stages))
        else:
            rule, change = _refresh_existing_rule(binding, prior, current, metadata)
            if change is not None:
                changes.append(change)
        rule = _with_declared_stages(rule, metadata.stages)
        rule, artifact_changes = _refresh_artifacts(binding.spec_id, rule, artifact_root)
        rules.append(rule)
        changes.extend(artifact_changes)
    for removed in existing.values():
        rules.append(_removed_rule(removed))
        changes.append(DriftChange("rule_removed", binding.spec_id, removed.ref, removed.text_sha256, "missing", tuple(removed.stage_status)))
    updated = replace(binding, hashes=metadata.hashes, enforcement=metadata.enforcement, stages=metadata.stages, rules=tuple(rules), status="active")
    return updated, tuple(changes)


def refresh_context(context: SpecContext, root: str, artifact_root: Optional[str] = None) -> DriftResult:
    started = time.monotonic()
    specs = Path(root) / ".code-flow" / "specs"
    artifacts = Path(artifact_root) if artifact_root is not None else Path(root)
    bindings: list[SpecBinding] = []
    changes: list[DriftChange] = []
    for binding in context.bindings:
        phase_started = time.monotonic()
        updated, binding_changes = _refresh_binding(binding, specs, artifacts)
        phase_timing(f"context.refresh.{binding.spec_id}", phase_started)
        bindings.append(updated)
        changes.extend(binding_changes)
    refreshed = replace(context, updated_at=now_iso(), bindings=tuple(bindings))
    phase_timing("context.refresh.total", started)
    if refreshed.bindings == context.bindings:
        return DriftResult(context, tuple(changes))
    return DriftResult(refreshed, tuple(changes))


def diff_spec_hashes(context: SpecContext, root: str) -> DriftResult:
    return refresh_context(context, root)


def apply_decision(
    context: SpecContext,
    spec_id: str,
    rule_ref: str,
    stage: str,
    decision: Decision,
    batch: bool = False,
) -> SpecContext:
    if batch:
        raise ContextError("batch_confirmation_forbidden", "batch", "N/A/豁免必须逐项确认")
    validate_decision(decision)
    target_status = {"not_applicable": "not_applicable", "waived": "waived", "manual_verification": "verified"}[decision.kind]
    found = False
    bindings: list[SpecBinding] = []
    for binding in context.bindings:
        changed_rules: list[RuleBinding] = []
        for rule in binding.rules:
            if binding.spec_id == spec_id and rule.ref == rule_ref:
                if stage not in rule.stage_status:
                    raise ContextError("unknown_stage", "stage", f"Rule 不适用于 {stage}")
                statuses = dict(rule.stage_status)
                statuses[stage] = replace(statuses[stage], status=target_status, decision=decision)
                rule = replace(rule, stage_status=statuses)
                found = True
            changed_rules.append(rule)
        bindings.append(replace(binding, rules=tuple(changed_rules)))
    if not found:
        raise ContextError("unknown_rule", "rule_ref", f"未找到 {spec_id}#{rule_ref}")
    return replace(context, updated_at=now_iso(), bindings=tuple(bindings))


def _upsert_artifact_ref(
    references: Sequence[ArtifactRef], replacement: ArtifactRef
) -> tuple[ArtifactRef, ...]:
    identity = (replacement.artifact, replacement.section_id, replacement.item_id)
    updated: list[ArtifactRef] = []
    replaced = False
    for reference in references:
        current = (reference.artifact, reference.section_id, reference.item_id)
        if current != identity:
            updated.append(reference)
        elif not replaced:
            updated.append(replacement)
            replaced = True
    if not replaced:
        updated.append(replacement)
    return tuple(updated)


def apply_artifact_ref(
    context: SpecContext,
    spec_id: str,
    rule_ref: str,
    stage: str,
    reference: ArtifactRef,
) -> SpecContext:
    found = False
    bindings: list[SpecBinding] = []
    for binding in context.bindings:
        rules: list[RuleBinding] = []
        for rule in binding.rules:
            if binding.spec_id == spec_id and rule.ref == rule_ref:
                if stage not in rule.stage_status:
                    raise ContextError("unknown_stage", "stage", f"Rule 不适用于 {stage}")
                statuses = dict(rule.stage_status)
                current = statuses[stage]
                refs = _upsert_artifact_ref(current.refs, reference)
                if current.decision is not None:
                    statuses[stage] = replace(current, refs=refs)
                else:
                    statuses[stage] = replace(current, status="applied", refs=refs)
                rule = replace(rule, stage_status=statuses)
                found = True
            rules.append(rule)
        bindings.append(replace(binding, rules=tuple(rules)))
    if not found:
        raise ContextError("unknown_rule", "rule_ref", f"未找到 {spec_id}#{rule_ref}")
    return replace(context, updated_at=now_iso(), bindings=tuple(bindings))


def _json_payload(stream: IO[str]) -> Mapping[str, object]:
    try:
        raw = stream.read()
    except (OSError, UnicodeError) as exc:
        raise ContextError("invalid_json", "stdin", str(exc)) from exc
    if not raw.strip():
        # 空 stdin = 无 payload（例如 active doctor --resync 全参数走 CLI 开关）。
        return {}
    try:
        loaded = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ContextError("invalid_json", "stdin", str(exc)) from exc
    return mapping_field(loaded, "stdin", "")


def _candidate_data(candidate: SpecCandidate) -> dict[str, object]:
    return {
        "spec_id": candidate.spec_id,
        "path": candidate.path,
        "scope": candidate.scope,
        "priority": candidate.priority,
        "matched_paths": list(candidate.matched_paths),
        "description": candidate.metadata.description,
        "enforcement": candidate.metadata.enforcement,
        "stages": list(candidate.metadata.stages),
        "hashes": {
            "file_sha256": candidate.metadata.hashes.file_sha256,
            "metadata_sha256": candidate.metadata.hashes.metadata_sha256,
            "rules_sha256": candidate.metadata.hashes.rules_sha256,
        },
        "rules": [
            {"ref": rule.ref, "text": rule.text, "enforcement": rule.enforcement}
            for rule in candidate.metadata.rules
        ],
    }


def _catalog_command(args: argparse.Namespace) -> dict[str, object]:
    candidates = resolve_candidates(args.root, args.stage, tuple(args.paths))
    return {
        "ok": True,
        "stage": args.stage,
        "total": len(candidates),
        "candidates": [_candidate_data(item) for item in candidates],
    }


def _application_ref(task_dir: str, value: Mapping[str, object]) -> ArtifactRef:
    artifact = string_field(value.get("artifact"), "applications[].artifact", "")
    base = Path(task_dir).resolve()
    target = (base / artifact).resolve()
    if base != target and base not in target.parents:
        raise ContextError("artifact_outside_task", "applications[].artifact", artifact, task_dir)
    from codeflow.spec.cf_rule_readiness import artifact_problem
    section = string_field(value.get("section_id"), "applications[].section_id", "")
    item = string_field(value.get("item_id"), "applications[].item_id", "")
    problem = artifact_problem(str(base), artifact, section, item)
    if problem:
        raise ContextError(problem, "applications[]", f"{artifact}#{section}/{item}", task_dir)
    try:
        artifact_hash = hashlib.sha256(target.read_bytes()).hexdigest()
    except OSError as exc:
        raise ContextError("artifact_read_error", "applications[].artifact", str(exc), str(target)) from exc
    return ArtifactRef(
        artifact,
        section,
        item,
        artifact_hash,
    )


def _apply_payload(context: SpecContext, task_dir: str, payload: Mapping[str, object]) -> SpecContext:
    updated = context
    for raw in sequence_field(payload.get("applications", []), "applications", ""):
        item = mapping_field(raw, "applications[]", "")
        updated = apply_artifact_ref(
            updated,
            string_field(item.get("spec_id"), "applications[].spec_id", ""),
            string_field(item.get("rule_ref"), "applications[].rule_ref", ""),
            string_field(item.get("stage"), "applications[].stage", ""),
            _application_ref(task_dir, item),
        )
    return updated


def _decision_command(args: argparse.Namespace, payload: Mapping[str, object]) -> dict[str, object]:
    context_path = Path(args.task_dir) / "spec-context.yml"
    decision = decision_from_data(payload.get("decision"), str(context_path))
    if decision is None:
        raise ContextError("invalid_decision", "decision", "必须提供 decision")
    context = apply_decision(
        load_context(str(context_path)),
        string_field(payload.get("spec_id"), "spec_id", ""),
        string_field(payload.get("rule_ref"), "rule_ref", ""),
        string_field(payload.get("stage"), "stage", ""),
        decision,
        payload.get("batch") is True,
    )
    save_context(str(context_path), context)
    _resync_after_save(args, context_path)
    # Report the status of the rule the decision targeted, not the first binding
    # (bindings[0].rules[0] previously returned an unrelated rule).
    spec_id = string_field(payload.get("spec_id"), "spec_id", "")
    rule_ref = string_field(payload.get("rule_ref"), "rule_ref", "")
    stage = string_field(payload.get("stage"), "stage", "")
    status = "unknown"
    for binding in context.bindings:
        if binding.spec_id != spec_id:
            continue
        for rule in binding.rules:
            if rule.ref == rule_ref:
                stage_status = rule.stage_status.get(stage)
                status = stage_status.status if stage_status is not None else "missing"
    return {"ok": True, "status": status}


def _bind_command(args: argparse.Namespace, payload: Mapping[str, object]) -> dict[str, object]:
    context_path = Path(args.task_dir) / "spec-context.yml"
    paths = tuple(string_field(item, "paths[]", "") for item in sequence_field(payload.get("paths", []), "paths", ""))
    candidates = {item.spec_id: item for item in resolve_candidates(args.root, args.stage, paths)}
    selections: list[BindingInput] = []
    for raw in sequence_field(payload.get("selections"), "selections", ""):
        item = mapping_field(raw, "selections[]", "")
        spec_id = string_field(item.get("spec_id"), "selections[].spec_id", "")
        if spec_id not in candidates:
            raise ContextError("unknown_candidate", "selections[].spec_id", spec_id)
        selections.append(
            BindingInput(
                candidates[spec_id],
                string_field(item.get("selected_by"), "selections[].selected_by", ""),
                string_field(item.get("reason"), "selections[].reason", ""),
            )
        )
    if context_path.exists():
        context = load_context(str(context_path))
    else:
        task = string_field(payload.get("task"), "task", "")
        context = new_context(task, (("cli", "bind"),))
    context = bind_specs(context, selections)
    context = _apply_payload(context, args.task_dir, payload)
    save_context(str(context_path), context)
    _resync_after_save(args, context_path)
    applied = sum(
        status.status == "applied"
        for binding in context.bindings
        for rule in binding.rules
        for status in rule.stage_status.values()
    )
    return {"ok": True, "bindings": len(context.bindings), "applied": applied}


def _active_command(args: argparse.Namespace, payload: Mapping[str, object]) -> dict[str, object]:
    from codeflow.spec.cf_workflow_service import WorkflowError, locate_task_file
    from codeflow.spec.cf_workflow_transaction import recover_transition

    recover_transition(args.root)
    if args.active_action in ("pause", "resume", "block", "complete"):
        marker = active_paths(args.root)[0]
        if marker.exists():
            current = load_active_task(args.root)
            if (current.task_id != args.task or
                    (Path(args.root) / current.task_dir).resolve() != (Path(args.root) / args.task_dir).resolve()):
                raise ContextError("active_mismatch", "active", "requested TASK does not match marker", str(marker))

    def _directory() -> str:
        return args.task_dir if Path(args.task_dir).is_absolute() else str(Path(args.root) / args.task_dir)

    def _reraise(exc: WorkflowError) -> ContextError:
        return ContextError(exc.code, "workflow", str(exc), args.task_dir)

    task_file = locate_task_file(_directory(), args.task)
    if args.active_action == "start":
        owned = tuple(
            string_field(item, "owned_paths[]", "")
            for item in sequence_field(payload.get("owned_paths", []), "owned_paths", "")
        )
        if task_file is None:
            active = start_active_task(
                args.root, args.task_dir, args.task, args.context_sha256, owned
            )
            return {"ok": True, "active": active_data(active)}
        from codeflow.spec.cf_workflow_service import start_task

        try:
            return start_task(args.root, args.task_dir, str(task_file), args.task, owned)
        except WorkflowError as exc:
            raise _reraise(exc) from exc
    if args.active_action == "pause":
        active = pause_active_task(args.root)
    elif args.active_action == "resume":
        if task_file is None:
            active = resume_active_task(args.root)
        else:
            from codeflow.spec.cf_workflow_service import resume_task

            try:
                return resume_task(args.root, _directory(), str(task_file), args.task)
            except WorkflowError as exc:
                raise _reraise(exc) from exc
    elif args.active_action == "block":
        if task_file is None:
            active = block_active_task(args.root)
        else:
            from codeflow.spec.cf_workflow_service import block_task

            reason = payload.get("reason", "")
            try:
                return block_task(args.root, _directory(), str(task_file), args.task, reason if isinstance(reason, str) else "")
            except WorkflowError as exc:
                raise _reraise(exc) from exc
    elif args.active_action == "complete":
        gate = payload.get("gate_passed") is True
        if task_file is None:
            active = complete_active_task(args.root, gate)
        else:
            from codeflow.spec.cf_workflow_service import complete_task

            try:
                return complete_task(args.root, _directory(), str(task_file), args.task, gate)
            except WorkflowError as exc:
                raise _reraise(exc) from exc
    else:
        abandon = payload.get("abandon") is True or args.abandon
        resync = payload.get("resync") is True or args.resync
        if abandon and resync:
            raise ContextError("conflicting_recovery", "doctor", "abandon 与 resync 不能同时使用", args.task_dir)
        result = doctor_active_task(args.root, args.context_sha256, abandon, resync)
        return {"ok": True, "action": result.action, "active": active_data(result.active)}
    return {"ok": True, "active": active_data(active)}


def _start_command(args: argparse.Namespace, payload: Mapping[str, object]) -> dict[str, object]:
    """Run refresh, activation and TASK projection in one guarded process.

    Delegates to the unified workflow service: hard preconditions (status,
    NOTES, depends, marker) are enforced before any state changes, and the
    Markdown view flips to in-progress in the same call.
    """
    from codeflow.spec.cf_workflow_service import WorkflowError, start_task

    owned = tuple(
        string_field(item, "owned_paths[]", "")
        for item in sequence_field(payload.get("owned_paths", []), "owned_paths", "")
    )
    try:
        return start_task(
            args.root, args.task_dir, args.task_file, args.task, owned, args.session_output
        )
    except WorkflowError as exc:
        raise ContextError(exc.code, "workflow", str(exc), args.task_dir) from exc


def _status_command(args: argparse.Namespace) -> dict[str, object]:
    """Human-readable Spec Context status: task, marker health, gate, rules."""
    from codeflow.spec.cf_stage_gate import result_to_data, validate_stage

    context_path = Path(args.task_dir) / "spec-context.yml"
    context = load_context(str(context_path))
    gate = validate_stage(context, "code")
    root = getattr(args, "root", "") or _find_root(args.task_dir) or ""
    marker: dict[str, object] = {"exists": False}
    if root:
        marker_path = Path(root) / ".code-flow" / ".active-task.json"
        if marker_path.exists():
            active = load_active_task(root)
            marker = {
                "exists": True,
                "task_id": active.task_id,
                "status": active.status,
                "hash_match": active.context_sha256 == context_sha256(context),
                "baseline_head": active.baseline.head,
            }
    bindings = []
    for binding in context.bindings:
        rules = []
        for rule in binding.rules:
            status = rule.stage_status.get("code")
            stages = {stage: item.status for stage, item in sorted(rule.stage_status.items())}
            rules.append(
                {
                    "ref": f"{binding.spec_id}#{rule.ref}",
                    "enforcement": rule.enforcement,
                    "status": status.status if status else "missing",
                    "stages": stages,
                    "verifier": rule.verifier_ref,
                }
            )
        bindings.append({"spec_id": binding.spec_id, "path": binding.path, "status": binding.status, "rules": rules})
    return {
        "task": context.task,
        "context_sha256": context_sha256(context),
        "gate": result_to_data(gate),
        "marker": marker,
        "bindings": bindings,
    }


def _status_text(data: dict[str, object]) -> str:
    lines = [f"# {data['task']} — Spec Context 状态"]
    marker = data["marker"]
    if marker["exists"]:
        match = "✓ 一致" if marker["hash_match"] else "✗ 漂移"
        lines.append(f"- TASK {marker['task_id']}（{marker['status']}），marker hash {match}")
        if not marker["hash_match"]:
            lines.append("  下一步: 运行 cf-spec refresh 自动重同步 marker hash；仍不一致时用 active doctor --resync（hash 取本命令 --json 的 context_sha256）")
    else:
        lines.append("- 无 active TASK（path/catalog 路由模式）")
    gate = data["gate"]
    if gate["decision"] == "pass":
        lines.append("- code Gate: ✓ pass")
    else:
        lines.append(f"- code Gate: ✗ block（{len(gate['errors'])} 项）")
        for issue in gate["errors"]:
            lines.append(f"  ✗ {issue['message']}")
    for binding in data["bindings"]:
        lines.append(f"- {binding['spec_id']}（{binding['path']}）— {binding['status']}")
        for rule in binding["rules"]:
            stage_text = " ".join(f"{stage}={value}" for stage, value in rule.get("stages", {}).items())
            lines.append(f"  {stage_text:<24} {rule['ref']}（{rule['verifier']}）")
    return "\n".join(lines)


def _doctor_finding(code: str, severity: str, message: str, path: str = "", fix: str = "") -> dict[str, str]:
    return {"code": code, "severity": severity, "message": message, "path": path, "fix": fix}


def _doctor_runtime(root: Path) -> tuple[dict[str, object], list[dict[str, str]]]:
    """Diagnose install manifest drift without mutating the runtime."""
    runtime: dict[str, object] = {
        "installed": False, "version": "", "manifest_version": "",
        "files_checked": 0, "files_missing": [], "files_drifted": [], "commands": 0,
    }
    version_path = root / ".code-flow/.version"
    manifest_path = root / ".code-flow/.runtime-install.json"
    if not version_path.exists() and not manifest_path.exists():
        return runtime, [_doctor_finding(
            "runtime_not_installed", "info", "未检测到运行时安装清单", str(manifest_path),
            "code-flow init 或 code-flow migrate --runtime --apply")]
    runtime["installed"] = True
    if not version_path.is_file():
        return runtime, [_doctor_finding(
            "runtime_version_missing", "block", "缺少 .code-flow/.version", str(version_path),
            "code-flow migrate --runtime --apply")]
    version = version_path.read_text(encoding="utf-8").strip()
    runtime["version"] = version
    if not _valid_version(version):
        return runtime, [_doctor_finding(
            "runtime_version_invalid", "block", f"运行时不合法: {version!r}", str(version_path),
            "code-flow migrate --runtime --apply")]
    findings = _doctor_manifest(root, manifest_path, version, runtime)
    findings.extend(_doctor_contract(root, runtime))
    package_version = _package_version(root)
    if package_version:
        runtime["cli_version"] = package_version
        if package_version != version:
            upgrade = tuple(map(int, package_version.split("."))) < tuple(map(int, version.split(".")))
            repair = (f"npm install --global @michaelxwb/code-flow@{version}" if upgrade
                      else "code-flow migrate --runtime --dry-run")
            findings.append(_doctor_finding(
                "runtime_cli_version_mismatch", "warn",
                f"CLI 包版本 {package_version} 与运行时版本 {version} 不一致",
                str(root / "package.json"), repair))
    return runtime, findings


def _package_version(root: Path) -> str:
    cli_version = os.environ.get("CF_CLI_VERSION", "")
    if _valid_version(cli_version):
        return cli_version
    path = root / "package.json"
    if not path.is_file():
        return ""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return ""
    if not isinstance(data, Mapping) or data.get("name") != "@michaelxwb/code-flow":
        return ""
    version = data.get("version")
    return version if isinstance(version, str) else ""


def _valid_version(value: str) -> bool:
    parts = value.split(".")
    return len(parts) == 3 and all(part.isdigit() for part in parts)


def _doctor_manifest(root: Path, path: Path, version: str,
                     runtime: dict[str, object]) -> list[dict[str, str]]:
    if not path.is_file():
        return [_doctor_finding("runtime_manifest_missing", "block", "缺少 .runtime-install.json",
                                str(path), "code-flow migrate --runtime --apply")]
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return [_doctor_finding("runtime_manifest_invalid", "block", str(exc), str(path),
                                "code-flow migrate --runtime --apply")]
    if not isinstance(manifest, dict) or manifest.get("schema_version") != 1:
        return [_doctor_finding("runtime_manifest_invalid", "block", "manifest schema 不支持",
                                str(path), "code-flow migrate --runtime --apply")]
    manifest_version = manifest.get("version")
    runtime["manifest_version"] = manifest_version if isinstance(manifest_version, str) else ""
    files = manifest.get("files")
    if not isinstance(files, dict) or not files:
        return [_doctor_finding("runtime_manifest_incomplete", "block", "manifest.files 为空",
                                str(path), "code-flow migrate --runtime --apply")]
    findings: list[dict[str, str]] = []
    if manifest_version != version:
        findings.append(_doctor_finding(
            "runtime_version_drift", "block",
            f"version {version} 与 manifest {manifest_version} 不一致", str(path),
            "code-flow migrate --runtime --apply"))
    missing, drifted = _doctor_files(root, files)
    runtime["files_checked"] = len(files)
    runtime["files_missing"] = missing
    runtime["files_drifted"] = drifted
    if missing:
        findings.append(_doctor_finding(
            "runtime_file_missing", "block", f"{len(missing)} 个受管理文件缺失: {', '.join(missing[:5])}",
            str(root / ".code-flow"), "code-flow migrate --runtime --apply"))
    if drifted:
        findings.append(_doctor_finding(
            "runtime_file_drift", "block", f"{len(drifted)} 个受管理文件被修改: {', '.join(drifted[:5])}",
            str(root / ".code-flow"), "code-flow migrate --runtime --apply"))
    if not isinstance(manifest.get("hook_contracts"), dict):
        findings.append(_doctor_finding("runtime_hooks_missing", "warn", "manifest 缺 hook_contracts",
                                        str(path), "code-flow migrate --runtime --apply"))
    return findings


def _doctor_files(root: Path, files: Mapping[str, object]) -> tuple[list[str], list[str]]:
    missing: list[str] = []
    drifted: list[str] = []
    base = root.resolve()
    for relative, expected in files.items():
        target = (root / str(relative)).resolve()
        if target != base and base not in target.parents:
            missing.append(str(relative))
        elif not target.is_file():
            missing.append(str(relative))
        elif not isinstance(expected, str) or _file_sha256(target) != expected:
            drifted.append(str(relative))
    return missing, drifted


def _doctor_contract(root: Path, runtime: dict[str, object]) -> list[dict[str, str]]:
    path = root / ".code-flow/runtime-commands.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return [_doctor_finding("runtime_contract_invalid", "block", str(exc), str(path),
                                "code-flow migrate --runtime --apply")]
    commands = data.get("commands") if isinstance(data, dict) else None
    if not isinstance(data, dict) or data.get("schema_version") != 1 or not isinstance(commands, dict) or not commands:
        return [_doctor_finding("runtime_contract_invalid", "block", "runtime-commands.json 契约损坏",
                                str(path), "code-flow migrate --runtime --apply")]
    runtime["commands"] = len(commands)
    return []


def _doctor_config(root: Path) -> list[dict[str, str]]:
    import yaml

    path = root / ".code-flow/config.yml"
    if not path.is_file():
        return [_doctor_finding("config_missing", "warn", "缺少 config.yml", str(path), "code-flow init")]
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        return [_doctor_finding("config_unreadable", "block", str(exc), str(path), "修复 config.yml 后重试")]
    if not isinstance(data, dict):
        return [_doctor_finding("config_unreadable", "block", "config.yml 不是 mapping", str(path),
                                "修复 config.yml 后重试")]
    workflow = data.get("spec_workflow")
    schema = workflow.get("schema_version") if isinstance(workflow, dict) else None
    if schema is None:
        return [_doctor_finding("config_schema_missing", "warn", "spec_workflow.schema_version 未声明",
                                str(path), "code-flow migrate --spec-workflow --dry-run")]
    if schema != 1:
        return [_doctor_finding("config_schema_unsupported", "block", f"不支持的 schema {schema!r}",
                                str(path), "code-flow migrate --spec-workflow --dry-run")]
    mode = workflow.get("enforcement")
    if isinstance(mode, str) and mode in {"warn", "inject"}:
        return [_doctor_finding("legacy_enforcement_mode", "warn",
                                "历史 warn/inject 模式会降低部分验证门禁；路由完整性错误仍阻断",
                                str(path), "审查现有工作流后显式将 spec_workflow.enforcement 改为 required")]
    return []


def _doctor_migrations(root: Path) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    lock = root / ".code-flow/.runtime-migration.lock"
    if lock.exists():
        findings.append(_doctor_finding("runtime_migration_lock", "block", "存在运行时迁移锁", str(lock),
                                        "按 lock owner 输出执行 migrate --runtime --rollback <id>"))
    workspace = root / ".code-flow/migrations"
    for journal in sorted(workspace.glob("runtime-*/journal.json")) if workspace.is_dir() else ():
        try:
            status = json.loads(journal.read_text(encoding="utf-8")).get("status")
        except (OSError, UnicodeError, json.JSONDecodeError):
            findings.append(_doctor_finding("migration_journal_invalid", "warn", "迁移 journal 不可读",
                                            str(journal), "检查 migrations 目录"))
            continue
        if status in ("staging", "applying"):
            findings.append(_doctor_finding(
                "runtime_migration_recovery", "block", f"迁移未完成: {status}", str(journal),
                f"code-flow migrate --runtime --rollback {journal.parent.name}"))
    return findings


def _doctor_legacy(root: Path) -> list[dict[str, str]]:
    retired = ("cf_inject_hook.py", "cf_session_hook.py", "cf_codex_user_prompt_hook.py")
    findings = [
        _doctor_finding("legacy_runtime_residue", "warn", f"旧 Hook 脚本仍存在: {name}",
                        str(root / ".code-flow/scripts" / name), "code-flow migrate --runtime --apply")
        for name in retired if (root / ".code-flow/scripts" / name).exists()
    ]
    legacy_inject = root / ".claude/skills/cf-inject.md"
    if legacy_inject.exists():
        findings.append(_doctor_finding("legacy_skill_residue", "warn", "旧 cf-inject skill 仍存在",
                                        str(legacy_inject), "code-flow init --force"))
    return findings


def _doctor_marker(root: Path, task_dir: str, context: SpecContext) -> tuple[dict[str, object], list[dict[str, str]]]:
    marker_path = root / ".code-flow/.active-task.json"
    info: dict[str, object] = {"exists": False, "task_id": "", "status": "", "hash_match": False,
                               "task_match": False}
    if not marker_path.is_file():
        return info, []
    try:
        active = load_active_task(str(root))
    except ContextError as exc:
        return info, [_doctor_finding("corrupt_marker", "block", exc.message, str(marker_path),
                                      "确认放弃后运行 code-flow spec active doctor --abandon")]
    task_match = Path(active.task_dir).resolve() == Path(task_dir).resolve()
    hash_match = active.context_sha256 == context_sha256(context)
    info.update({"exists": True, "task_id": active.task_id, "status": active.status,
                 "hash_match": hash_match, "task_match": task_match})
    findings: list[dict[str, str]] = []
    if not hash_match:
        findings.append(_doctor_finding(
            "marker_hash_drift", "block", "marker context hash 漂移", str(marker_path),
            "code-flow spec refresh --task-dir <需求目录> --root \"$PWD\" --json"))
    if not task_match:
        findings.append(_doctor_finding(
            "marker_task_mismatch", "block", f"marker 属于 {active.task_dir}", str(marker_path),
            "回到原需求目录，或用 spec active doctor --resync 重新绑定"))
    if active.status == "activating":
        findings.append(_doctor_finding(
            "marker_stuck_activating", "block", "start 事务停在 activating", str(marker_path),
            "code-flow spec active doctor --resync --context-sha256 <hash>"))
    return info, findings


def _doctor_command(args: argparse.Namespace) -> dict[str, object]:
    """Read-only drift diagnosis for Context, marker and installed runtime."""
    task_dir = Path(args.task_dir)
    context_path = task_dir / "spec-context.yml"
    runtime: dict[str, object] = {"installed": False, "version": "", "manifest_version": "",
                                  "files_checked": 0, "files_missing": [], "files_drifted": [],
                                  "commands": 0}
    empty_marker: dict[str, object] = {"exists": False, "task_id": "", "status": "",
                                       "hash_match": False, "task_match": False}
    try:
        context = load_context(str(context_path))
        sha = context_sha256(context)
    except ContextError as exc:
        finding = _doctor_finding("invalid_context", "block", exc.message, str(context_path),
                                  "修复 spec-context.yml 后运行 code-flow spec refresh")
        return _doctor_report("", "", empty_marker, runtime, [finding])
    root_value = getattr(args, "root", "") or _find_root(str(task_dir))
    if not root_value:
        finding = _doctor_finding("root_not_found", "block", "无法定位项目根目录", str(task_dir),
                                  "在项目内运行，或显式传入 --root")
        return _doctor_report(context.task, sha, empty_marker, runtime, [finding])
    root = Path(root_value).resolve()
    marker, findings = _doctor_marker(root, str(task_dir), context)
    runtime, runtime_findings = _doctor_runtime(root)
    findings.extend(runtime_findings)
    findings.extend(_doctor_config(root))
    findings.extend(_doctor_migrations(root))
    findings.extend(_doctor_legacy(root))
    from codeflow.spec.cf_rule_readiness import applied_findings, convention_findings
    from codeflow.spec.cf_stage_gate import result_to_data, validate_stage
    findings.extend(applied_findings(context, str(root), task_dir=str(task_dir)))
    findings.extend(convention_findings(str(root), [binding.path for binding in context.bindings]))
    report = _doctor_report(context.task, sha, marker, runtime, findings)
    report["readiness"] = {stage: result_to_data(validate_stage(context, stage, root=str(root), task_dir=str(task_dir)))
                           for stage in ("plan", "code", "review")}
    return report


def _doctor_report(task: str, sha: str, marker: Mapping[str, object],
                   runtime: Mapping[str, object], findings: Sequence[Mapping[str, str]]) -> dict[str, object]:
    blocking = [item for item in findings if item["severity"] == "block"]
    next_steps: list[str] = []
    for item in blocking:
        if item["fix"] and item["fix"] not in next_steps:
            next_steps.append(item["fix"])
    return {
        "ok": not blocking,
        "decision": "block" if blocking else "pass",
        "task": task,
        "context_sha256": sha,
        "marker": dict(marker),
        "runtime": dict(runtime),
        "findings": [dict(item) for item in findings],
        "next": next_steps,
    }


def _doctor_text(data: dict[str, object]) -> str:
    lines = [f"# {data['task'] or '<unknown>'} — Spec Doctor",
             f"- decision: {data['decision']}"]
    runtime = data["runtime"]
    lines.append(f"- runtime: installed={runtime['installed']} version={runtime['version'] or '-'} "
                 f"files={runtime['files_checked']}")
    findings = data["findings"]
    if not findings:
        lines.append("- 未发现漂移")
    for item in findings:
        lines.append(f"- [{item['severity']}] {item['code']}: {item['message']}")
        if item["fix"]:
            lines.append(f"  修复: {item['fix']}")
    return "\n".join(lines)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog=os.environ.get("CF_RUNTIME_COMMAND", "cf_spec_context.py"))
    commands = parser.add_subparsers(dest="command", required=True)
    catalog = commands.add_parser("catalog")
    catalog.add_argument("--root", required=True)
    catalog.add_argument("--stage", required=True)
    catalog.add_argument("--paths", nargs="*", default=())
    catalog.add_argument("--json", action="store_true")
    decision = commands.add_parser("decision")
    decision.add_argument("--task-dir", required=True)
    decision.add_argument("--json", action="store_true")
    bind = commands.add_parser("bind")
    bind.add_argument("--task-dir", required=True)
    bind.add_argument("--root", required=True)
    bind.add_argument("--stage", required=True)
    bind.add_argument("--json", action="store_true")
    validate = commands.add_parser("validate")
    validate.add_argument("--task-dir", required=True)
    validate.add_argument("--json", action="store_true")
    status = commands.add_parser("status")
    status.add_argument("--task-dir", required=True)
    status.add_argument("--root", default="")
    status.add_argument("--json", action="store_true")
    doctor = commands.add_parser("doctor")
    doctor.add_argument("--task-dir", required=True)
    doctor.add_argument("--root", default="")
    doctor.add_argument("--json", action="store_true")
    for name in ("refresh", "refresh-missing"):
        refresh = commands.add_parser(name)
        refresh.add_argument("--task-dir", required=True)
        refresh.add_argument("--root", required=True)
        refresh.add_argument("--json", action="store_true")
    active = commands.add_parser("active")
    active_actions = active.add_subparsers(dest="active_action", required=True)
    for action in ("start", "pause", "resume", "block", "complete", "doctor"):
        command = active_actions.add_parser(action)
        command.add_argument("--root", required=True)
        command.add_argument("--task-dir", required=True)
        command.add_argument("--task", required=True)
        command.add_argument("--context-sha256", required=True)
        command.add_argument("--json", action="store_true")
        if action == "doctor":
            command.add_argument("--abandon", action="store_true", help="确认放弃无法证明的 marker（需用户确认）")
            command.add_argument("--resync", action="store_true", help="用 --context-sha256 重新绑定 marker 并恢复 active")
    start = commands.add_parser("start")
    start.add_argument("--task-dir", required=True)
    start.add_argument("--root", required=True)
    start.add_argument("--task", required=True)
    start.add_argument("--task-file", required=True)
    start.add_argument("--session-output", default="")
    start.add_argument("--json", action="store_true")
    return parser


def _execute(args: argparse.Namespace, stdin: IO[str]) -> dict[str, object]:
    if args.command == "catalog":
        return _catalog_command(args)
    if args.command == "doctor":
        return _doctor_command(args)
    if args.command == "active":
        return _active_command(args, _json_payload(stdin))
    if args.command == "start":
        return _start_command(args, _json_payload(stdin))
    context_path = Path(args.task_dir) / "spec-context.yml"
    if args.command == "decision":
        return _decision_command(args, _json_payload(stdin))
    if args.command == "bind":
        return _bind_command(args, _json_payload(stdin))
    if args.command == "validate":
        context = load_context(str(context_path))
        return {"ok": True, "task": context.task, "bindings": len(context.bindings)}
    if args.command == "refresh-missing":
        context = refresh_missing_specs(load_context(str(context_path)), args.root)
        changes: tuple[DriftChange, ...] = ()
    else:
        result = refresh_context(load_context(str(context_path)), args.root, artifact_root=args.task_dir)
        context, changes = result.context, result.changes
    save_context(str(context_path), context)
    _resync_after_save(args, context_path)
    return {
        "ok": True,
        "missing": sum(item.status == "missing" for item in context.bindings),
        "changes": [change.__dict__ for change in changes],
    }


def main(argv: Optional[Sequence[str]] = None, stdin: IO[str] = sys.stdin, stdout: IO[str] = sys.stdout) -> int:
    try:
        args = _parser().parse_args(argv)
        if args.command == "status":
            data = _status_command(args)
            if args.json:
                stdout.write(json.dumps(data, ensure_ascii=False))
            else:
                stdout.write(_status_text(data) + "\n")
            return 0
        if args.command == "doctor":
            data = _doctor_command(args)
            if args.json:
                stdout.write(json.dumps(data, ensure_ascii=False))
            else:
                stdout.write(_doctor_text(data) + "\n")
            return 0 if data["decision"] == "pass" else 3
        result = _execute(args, stdin)
        stdout.write(json.dumps(result, ensure_ascii=False))
        return 0
    except ContextError as exc:
        stdout.write(json.dumps({"ok": False, "error": exc.to_dict()}, ensure_ascii=False))
        return 3
    except Exception as exc:
        payload = error_payload(exc)
        if payload is not None:
            # Same error contract, different module instance (direct script run).
            stdout.write(json.dumps({"ok": False, "error": payload}, ensure_ascii=False))
            return 3
        sys.stderr.write(f"cf_spec_context unexpected error: {exc}\n")
        stdout.write(json.dumps({"ok": False, "error": {"code": "internal_error"}}, ensure_ascii=False))
        return 2
