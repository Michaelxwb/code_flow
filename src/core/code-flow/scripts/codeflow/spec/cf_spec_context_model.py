"""Pure Spec Context model: dataclasses, serialization and identity hashing.

This module owns the persisted schema and its stable error contract. CLI
commands, doctor and decision orchestration stay in `cf_spec_context`; lower
layers (cache, evidence, plan quality) depend on this model instead of the CLI
entry.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
from pathlib import Path
from typing import TYPE_CHECKING, Mapping, Optional, Sequence

from codeflow.core import cf_fs
from codeflow.spec.cf_spec_metadata import SpecHashes

if TYPE_CHECKING:
    from codeflow.spec.cf_spec_resolver import SpecCandidate


CONTEXT_VERSION = 1
STAGE_STATUSES = frozenset(
    ("pending", "applied", "not_applicable", "waived", "verified", "stale", "conflict", "unverified")
)
DECISION_KINDS = frozenset(("not_applicable", "waived", "manual_verification"))
_AGENT_IDENTITIES = frozenset(("agent", "assistant", "codex", "claude", "opencode", "costrict"))


class ContextError(ValueError):
    """A stable context error suitable for JSON CLI output."""

    def __init__(self, code: str, field: str, message: str, path: str = "") -> None:
        self.code = code
        self.field = field
        self.message = message
        self.path = path
        location = f"{path}: " if path else ""
        super().__init__(f"{location}{code} {field}: {message}")

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code, "field": self.field, "message": self.message, "path": self.path}


def error_payload(exc: Exception) -> Optional[dict]:
    """Duck-typed ContextError recognition across duplicate module instances.

    Direct script execution (`python3 cf_spec_context.py`) can make lazy
    `import cf_spec_context` calls inside sibling modules load a second copy,
    so `isinstance(exc, ContextError)` fails even though the error contract is
    identical. Recognize it structurally instead of masking it as
    `internal_error`.
    """
    to_dict = getattr(exc, "to_dict", None)
    if not callable(to_dict) or not isinstance(getattr(exc, "code", None), str):
        return None
    payload = to_dict()
    return payload if isinstance(payload, dict) else None


@dataclass(frozen=True)
class ContextSource:
    type: str
    ref: str


@dataclass(frozen=True)
class Decision:
    kind: str
    reason: str
    confirmed_by: str
    confirmed_at: str
    source: str
    expires_at: Optional[str]


@dataclass(frozen=True)
class ArtifactRef:
    artifact: str
    section_id: str
    item_id: str
    artifact_sha256: str


@dataclass(frozen=True)
class RuleStageStatus:
    status: str
    refs: tuple[ArtifactRef, ...]
    decision: Optional[Decision]
    evidence: tuple[Mapping[str, object], ...]


@dataclass(frozen=True)
class RuleBinding:
    ref: str
    summary: str
    text_sha256: str
    enforcement: str
    verifier_ref: str
    stage_status: Mapping[str, RuleStageStatus]
    verifier_stage: str = "code"


@dataclass(frozen=True)
class SpecBinding:
    spec_id: str
    path: str
    hashes: SpecHashes
    selected_by: str
    reason: str
    enforcement: str
    stages: tuple[str, ...]
    rules: tuple[RuleBinding, ...]
    status: str = "active"


@dataclass(frozen=True)
class SpecContext:
    version: int
    task: str
    enforcement: str
    updated_at: str
    sources: tuple[ContextSource, ...]
    bindings: tuple[SpecBinding, ...]


@dataclass(frozen=True)
class BindingInput:
    candidate: SpecCandidate
    selected_by: str
    reason: str


@dataclass(frozen=True)
class DriftChange:
    kind: str
    spec_id: str
    rule_ref: str
    old_hash: str
    new_hash: str
    stages: tuple[str, ...]


@dataclass(frozen=True)
class DriftResult:
    context: SpecContext
    changes: tuple[DriftChange, ...]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def atomic_text(target: Path, text: str) -> None:
    """Atomic write with the Context's stable error code on failure."""
    try:
        cf_fs.atomic_write_text(target, text)
    except OSError as exc:
        raise ContextError("atomic_write_error", "file", str(exc), str(target)) from exc


def mapping_field(value: object, field: str, path: str) -> Mapping[str, object]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise ContextError("invalid_context", field, "必须是字符串 key mapping", path)
    return value


def sequence_field(value: object, field: str, path: str) -> Sequence[object]:
    if not isinstance(value, list):
        raise ContextError("invalid_context", field, "必须是列表", path)
    return value


def string_field(value: object, field: str, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ContextError("invalid_context", field, "必须是非空字符串", path)
    return value.strip()


def _decision_string(value: object, field: str, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ContextError("invalid_decision", field, "必须是非空字符串", path)
    return value.strip()


def _timestamp(value: str, field: str) -> None:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ContextError("invalid_decision", field, "必须是 RFC3339 时间") from exc
    if parsed.tzinfo is None:
        raise ContextError("invalid_decision", field, "必须包含时区")


def validate_decision(decision: Decision) -> None:
    if decision.kind not in DECISION_KINDS:
        raise ContextError("invalid_decision", "decision.kind", f"不支持 {decision.kind!r}")
    for field in ("reason", "confirmed_by", "confirmed_at", "source"):
        if not getattr(decision, field).strip():
            raise ContextError("invalid_decision", f"decision.{field}", "必须是非空字符串")
    identity = decision.confirmed_by.lower().split(":", 1)[0]
    if identity in _AGENT_IDENTITIES:
        raise ContextError("agent_confirmation_forbidden", "decision.confirmed_by", "Agent 不能自行确认")
    _timestamp(decision.confirmed_at, "decision.confirmed_at")
    if decision.kind == "waived" and not decision.expires_at:
        raise ContextError("invalid_decision", "decision.expires_at", "waived 必须有失效时间")
    if decision.expires_at:
        _timestamp(decision.expires_at, "decision.expires_at")


def decision_from_data(value: object, path: str) -> Optional[Decision]:
    if value is None:
        return None
    data = mapping_field(value, "decision", path)
    expires = data.get("expires_at")
    if expires is not None and not isinstance(expires, str):
        raise ContextError("invalid_decision", "decision.expires_at", "必须是字符串或 null", path)
    decision = Decision(
        _decision_string(data.get("kind"), "decision.kind", path),
        _decision_string(data.get("reason"), "decision.reason", path),
        _decision_string(data.get("confirmed_by"), "decision.confirmed_by", path),
        _decision_string(data.get("confirmed_at"), "decision.confirmed_at", path),
        _decision_string(data.get("source"), "decision.source", path),
        expires,
    )
    validate_decision(decision)
    return decision


def _decision_data(decision: Optional[Decision]) -> Optional[dict[str, object]]:
    if decision is None:
        return None
    return {
        "kind": decision.kind,
        "reason": decision.reason,
        "confirmed_by": decision.confirmed_by,
        "confirmed_at": decision.confirmed_at,
        "source": decision.source,
        "expires_at": decision.expires_at,
    }


def _artifact_from_data(value: object, path: str) -> ArtifactRef:
    data = mapping_field(value, "refs[]", path)
    return ArtifactRef(
        string_field(data.get("artifact"), "refs[].artifact", path),
        string_field(data.get("section_id"), "refs[].section_id", path),
        string_field(data.get("item_id"), "refs[].item_id", path),
        string_field(data.get("artifact_sha256"), "refs[].artifact_sha256", path),
    )


def _artifact_data(reference: ArtifactRef) -> dict[str, str]:
    return {
        "artifact": reference.artifact,
        "section_id": reference.section_id,
        "item_id": reference.item_id,
        "artifact_sha256": reference.artifact_sha256,
    }


def _stage_from_data(value: object, field: str, path: str) -> RuleStageStatus:
    data = mapping_field(value, field, path)
    status = string_field(data.get("status"), f"{field}.status", path)
    if status not in STAGE_STATUSES:
        raise ContextError("invalid_context", f"{field}.status", f"不支持 {status!r}", path)
    refs = tuple(_artifact_from_data(item, path) for item in sequence_field(data.get("refs", []), f"{field}.refs", path))
    evidence = tuple(mapping_field(item, f"{field}.evidence[]", path) for item in sequence_field(data.get("evidence", []), f"{field}.evidence", path))
    decision = decision_from_data(data.get("decision"), path)
    if status == "applied" and not refs:
        raise ContextError("invalid_context", f"{field}.refs", "applied 必须有 artifact ref", path)
    if status in ("not_applicable", "waived") and decision is None:
        raise ContextError("invalid_context", f"{field}.decision", f"{status} 必须有确认记录", path)
    return RuleStageStatus(status, refs, decision, evidence)


def _stage_data(status: RuleStageStatus) -> dict[str, object]:
    return {
        "status": status.status,
        "refs": [_artifact_data(item) for item in status.refs],
        "decision": _decision_data(status.decision),
        "evidence": [dict(item) for item in status.evidence],
    }


def _rule_from_data(value: object, path: str) -> RuleBinding:
    data = mapping_field(value, "rules[]", path)
    stages = mapping_field(data.get("stage_status"), "rules[].stage_status", path)
    parsed = {stage: _stage_from_data(item, f"stage_status.{stage}", path) for stage, item in stages.items()}
    return RuleBinding(
        string_field(data.get("ref"), "rules[].ref", path),
        string_field(data.get("summary"), "rules[].summary", path),
        string_field(data.get("text_sha256"), "rules[].text_sha256", path),
        string_field(data.get("enforcement"), "rules[].enforcement", path),
        string_field(data.get("verifier_ref"), "rules[].verifier_ref", path),
        parsed,
        string_field(data.get("verifier_stage", "code"), "rules[].verifier_stage", path),
    )


def _rule_data(rule: RuleBinding) -> dict[str, object]:
    return {
        "ref": rule.ref,
        "summary": rule.summary,
        "text_sha256": rule.text_sha256,
        "enforcement": rule.enforcement,
        "verifier_ref": rule.verifier_ref,
        "verifier_stage": rule.verifier_stage,
        "stage_status": {stage: _stage_data(status) for stage, status in rule.stage_status.items()},
    }


def _hashes_from_data(value: object, path: str) -> SpecHashes:
    data = mapping_field(value, "hashes", path)
    return SpecHashes(
        string_field(data.get("file_sha256"), "hashes.file_sha256", path),
        string_field(data.get("metadata_sha256"), "hashes.metadata_sha256", path),
        string_field(data.get("rules_sha256"), "hashes.rules_sha256", path),
    )


def _binding_from_data(value: object, path: str) -> SpecBinding:
    data = mapping_field(value, "bindings[]", path)
    stages = tuple(string_field(item, "bindings[].stages[]", path) for item in sequence_field(data.get("stages"), "bindings[].stages", path))
    rules = tuple(_rule_from_data(item, path) for item in sequence_field(data.get("rules"), "bindings[].rules", path))
    return SpecBinding(
        string_field(data.get("spec_id"), "bindings[].spec_id", path),
        string_field(data.get("path"), "bindings[].path", path),
        _hashes_from_data(data.get("hashes"), path),
        string_field(data.get("selected_by"), "bindings[].selected_by", path),
        string_field(data.get("reason"), "bindings[].reason", path),
        string_field(data.get("enforcement"), "bindings[].enforcement", path),
        stages,
        rules,
        string_field(data.get("status", "active"), "bindings[].status", path),
    )


def _binding_data(binding: SpecBinding) -> dict[str, object]:
    return {
        "spec_id": binding.spec_id,
        "path": binding.path,
        "status": binding.status,
        "hashes": {
            "file_sha256": binding.hashes.file_sha256,
            "metadata_sha256": binding.hashes.metadata_sha256,
            "rules_sha256": binding.hashes.rules_sha256,
        },
        "selected_by": binding.selected_by,
        "reason": binding.reason,
        "enforcement": binding.enforcement,
        "stages": list(binding.stages),
        "rules": [_rule_data(rule) for rule in binding.rules],
    }


def context_to_data(context: SpecContext) -> dict[str, object]:
    return {
        "version": context.version,
        "task": context.task,
        "enforcement": context.enforcement,
        "updated_at": context.updated_at,
        "sources": [{"type": item.type, "ref": item.ref} for item in context.sources],
        "bindings": [_binding_data(binding) for binding in context.bindings],
    }


def context_to_identity(context: SpecContext) -> dict[str, object]:
    """Stable identity projection for marker drift detection.

    Excludes volatile runtime state (`updated_at`, `stage_status` including
    evidence timestamps) so the active marker only invalidates when the bound
    rules themselves change (rule/spec text, bindings, sources).
    """
    return {
        "version": context.version,
        "task": context.task,
        "enforcement": context.enforcement,
        "sources": [{"type": item.type, "ref": item.ref} for item in context.sources],
        "bindings": [
            {
                "spec_id": binding.spec_id,
                "path": binding.path,
                "status": binding.status,
                "hashes": {
                    "file_sha256": binding.hashes.file_sha256,
                    "metadata_sha256": binding.hashes.metadata_sha256,
                    "rules_sha256": binding.hashes.rules_sha256,
                },
                "selected_by": binding.selected_by,
                "reason": binding.reason,
                "enforcement": binding.enforcement,
                "stages": list(binding.stages),
                "rules": [
                    {
                        "ref": rule.ref,
                        "summary": rule.summary,
                        "text_sha256": rule.text_sha256,
                        "enforcement": rule.enforcement,
                        "verifier_ref": rule.verifier_ref,
                    }
                    for rule in binding.rules
                ],
            }
            for binding in context.bindings
        ],
    }


def context_sha256(context: SpecContext) -> str:
    """Deterministic identity hash binding the active marker to the bound rules.

    Computed from the stable identity projection (never volatile runtime state),
    so evidence timestamps and stage statuses cannot drift the marker.
    """
    import yaml
    data = yaml.safe_dump(context_to_identity(context), sort_keys=True, allow_unicode=True).encode()
    return hashlib.sha256(data).hexdigest()


def new_context(task: str, sources: Sequence[tuple[str, str]]) -> SpecContext:
    if not task.strip():
        raise ContextError("invalid_context", "task", "必须是非空字符串")
    parsed = tuple(ContextSource(string_field(kind, "sources[].type", ""), string_field(ref, "sources[].ref", "")) for kind, ref in sources)
    return SpecContext(CONTEXT_VERSION, task.strip(), "required", now_iso(), parsed, ())


def load_context(path: str, *, source: Optional[bytes] = None) -> SpecContext:
    import yaml
    try:
        raw = Path(path).read_bytes() if source is None else source
        loaded = yaml.safe_load(raw.decode("utf-8")) or {}
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise ContextError("context_read_error", "file", str(exc), path) from exc
    return context_from_data(loaded, path)


def context_from_data(loaded: object, path: str) -> SpecContext:
    """Validate a parsed Context through the same schema for YAML and cache reads."""
    data = mapping_field(loaded, "context", path)
    version = data.get("version")
    if version != CONTEXT_VERSION:
        raise ContextError("unsupported_version", "version", f"仅支持 {CONTEXT_VERSION}，收到 {version!r}", path)
    source_values = sequence_field(data.get("sources", []), "sources", path)
    sources = tuple(
        ContextSource(
            string_field(mapping_field(item, "sources[]", path).get("type"), "sources[].type", path),
            string_field(mapping_field(item, "sources[]", path).get("ref"), "sources[].ref", path),
        )
        for item in source_values
    )
    bindings = tuple(_binding_from_data(item, path) for item in sequence_field(data.get("bindings", []), "bindings", path))
    return SpecContext(
        CONTEXT_VERSION,
        string_field(data.get("task"), "task", path),
        string_field(data.get("enforcement"), "enforcement", path),
        string_field(data.get("updated_at"), "updated_at", path),
        sources,
        bindings,
    )


def save_context(path: str, context: SpecContext) -> None:
    import yaml
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    text = yaml.safe_dump(context_to_data(context), sort_keys=False, allow_unicode=True)
    try:
        atomic_text(target, text)
    except ContextError as exc:
        raise ContextError("context_write_error", "file", str(exc), path) from exc
