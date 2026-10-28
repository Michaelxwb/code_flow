"""Bind and refresh Spec Context against real Specs and task artifacts."""
from __future__ import annotations

from dataclasses import replace
import hashlib
import json
from pathlib import Path
import time
from typing import Optional, Sequence

from codeflow.core.cf_core import phase_timing
from codeflow.core.cf_log import warn
from codeflow.spec.cf_spec_context_model import (
    BindingInput, ContextError, DriftChange, DriftResult, RuleBinding, RuleStageStatus,
    SpecBinding, SpecContext, now_iso,
)
from codeflow.spec.cf_spec_metadata import SpecMetadata, SpecRule, load_spec_metadata


FILE_HASH_CACHE: dict[str, tuple[int, int, int, str]] = {}
_PERSISTENT_HASH_CACHE: dict[str, dict[str, object]] = {}
_PERSISTENT_HASH_PATHS: set[str] = set()
_MAX_HASH_CACHE_ENTRIES = 4096


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


def _load_hash_cache(cache_path: Optional[Path]) -> None:
    if cache_path is None or str(cache_path) in _PERSISTENT_HASH_PATHS:
        return
    try:
        loaded = json.loads(cache_path.read_text(encoding="utf-8"))
        if not isinstance(loaded, dict):
            raise ValueError("expected an object")
        _PERSISTENT_HASH_CACHE.update({str(k): v for k, v in loaded.items() if isinstance(v, dict)})
    except FileNotFoundError:
        loaded = {}
    except (OSError, ValueError) as exc:
        warn(f"artifact hash cache unavailable; rebuilding: {exc}")
    _PERSISTENT_HASH_PATHS.add(str(cache_path))


def _store_hash_cache(cache_path: Optional[Path], key: str, signature: tuple[int, int, int], digest: str) -> None:
    if cache_path is None:
        return
    _PERSISTENT_HASH_CACHE[key] = dict(zip(("mtime_ns", "size", "ino", "sha256"), (*signature, digest)))
    while len(_PERSISTENT_HASH_CACHE) > _MAX_HASH_CACHE_ENTRIES:
        _PERSISTENT_HASH_CACHE.pop(next(iter(_PERSISTENT_HASH_CACHE)))
    try:
        temporary = cache_path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(_PERSISTENT_HASH_CACHE, ensure_ascii=False, sort_keys=True), encoding="utf-8")
        temporary.replace(cache_path)
    except OSError as exc:
        warn(f"artifact hash cache could not be saved: {exc}")


def file_sha256(path: Path) -> str:
    try:
        stat = path.stat()
        key = str(path)
        signature = (stat.st_mtime_ns, stat.st_size, stat.st_ino)
        cached = FILE_HASH_CACHE.get(key)
        if cached is not None and cached[:3] == signature:
            return cached[3]
        cache_path = next((parent / ".artifact-hash-cache.json" for parent in path.parents
                           if parent.name == ".code-flow"), None)
        _load_hash_cache(cache_path)
        persistent = _PERSISTENT_HASH_CACHE.get(key)
        if isinstance(persistent, dict) and tuple(persistent.get(k) for k in ("mtime_ns", "size", "ino")) == signature:
            digest = persistent.get("sha256")
            if isinstance(digest, str) and digest:
                FILE_HASH_CACHE[key] = (*signature, digest)
                return digest
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        FILE_HASH_CACHE[key] = (*signature, digest)
        _store_hash_cache(cache_path, key, signature, digest)
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
            current = file_sha256(path) if path.is_file() else "missing"
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


