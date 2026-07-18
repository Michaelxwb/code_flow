#!/usr/bin/env python3
"""Deterministic stage/path candidate resolution for schema-v1 Specs."""

from __future__ import annotations

from dataclasses import dataclass
import fnmatch
from pathlib import Path
from typing import Mapping, Optional, Sequence

import yaml

from cf_spec_metadata import ALLOWED_STAGES, SpecMetadata, SpecRule, load_spec_metadata


SCOPE_PRIORITY = {"global": 1, "path": 2, "task": 3}
_config_cache: dict[str, tuple[int, int, Mapping[str, object]]] = {}
_metadata_cache: dict[str, tuple[int, int, SpecMetadata]] = {}


class SpecResolutionError(ValueError):
    """An explicit resolver/configuration failure."""

    def __init__(self, path: str, field: str, message: str) -> None:
        self.path = path
        self.field = field
        self.message = message
        super().__init__(f"{path}: resolution_error {field}: {message}")


@dataclass(frozen=True)
class SpecCandidate:
    spec_id: str
    path: str
    scope: str
    priority: int
    matched_paths: tuple[str, ...]
    metadata: SpecMetadata

    @property
    def required_rule_count(self) -> int:
        if self.metadata.enforcement == "advisory":
            return 0
        return sum(rule.enforcement == "required" for rule in self.metadata.rules)


@dataclass(frozen=True)
class ResolvedRule:
    ref: str
    spec_id: str
    text: str
    enforcement: str
    scope: str
    priority: int
    overridden_spec_ids: tuple[str, ...]


@dataclass(frozen=True)
class RuleConflict:
    ref: str
    priority: int
    spec_ids: tuple[str, ...]
    text_sha256: tuple[str, ...]


@dataclass(frozen=True)
class PrecedenceResolution:
    candidates: tuple[SpecCandidate, ...]
    effective_rules: tuple[ResolvedRule, ...]
    conflicts: tuple[RuleConflict, ...]


@dataclass(frozen=True)
class CandidatePage:
    items: tuple[SpecCandidate, ...]
    total: int
    has_more: bool


@dataclass(frozen=True)
class _RuleSource:
    candidate: SpecCandidate
    rule: SpecRule
    enforcement: str


def _fingerprint(path: Path, field: str) -> tuple[int, int]:
    try:
        stat = path.stat()
    except OSError as exc:
        raise SpecResolutionError(str(path), field, f"读取状态失败: {exc}") from exc
    return stat.st_mtime_ns, stat.st_size


def _load_config(root: str) -> Mapping[str, object]:
    path = Path(root) / ".code-flow" / "config.yml"
    if not path.is_file():
        raise SpecResolutionError(str(path), "config", "缺失 config.yml")
    mtime, size = _fingerprint(path, "config")
    cached = _config_cache.get(str(path))
    if cached and cached[:2] == (mtime, size):
        return cached[2]
    try:
        loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise SpecResolutionError(str(path), "config", f"解析失败: {exc}") from exc
    if not isinstance(loaded, dict) or not all(isinstance(key, str) for key in loaded):
        raise SpecResolutionError(str(path), "config", "顶层必须是字符串 key mapping")
    _config_cache[str(path)] = (mtime, size, loaded)
    return loaded


def _path_mapping(config: Mapping[str, object], path: str) -> Mapping[str, object]:
    value = config.get("path_mapping")
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise SpecResolutionError(path, "path_mapping", "必须是字符串 key mapping")
    return value


def _domain_config(mapping: Mapping[str, object], domain: str, config_path: str) -> Mapping[str, object]:
    value = mapping.get(domain, {})
    if not isinstance(value, dict):
        raise SpecResolutionError(config_path, f"path_mapping.{domain}", "必须是 mapping")
    return value


def _patterns(config: Mapping[str, object], field: str, config_path: str) -> tuple[str, ...]:
    value = config.get("patterns", [])
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise SpecResolutionError(config_path, field, "patterns 必须是字符串列表")
    return tuple(item.replace("\\", "/") for item in value)


def _non_injectable(mapping: Mapping[str, object], config_path: str) -> set[str]:
    excluded: set[str] = set()
    for domain in mapping:
        config = _domain_config(mapping, domain, config_path)
        entries = config.get("specs", [])
        if not isinstance(entries, list):
            raise SpecResolutionError(config_path, f"path_mapping.{domain}.specs", "必须是列表")
        for entry in entries:
            if isinstance(entry, dict) and entry.get("tags") == [] and isinstance(entry.get("path"), str):
                excluded.add(str(entry["path"]).replace("\\", "/"))
    return excluded


def _load_metadata(path: Path) -> SpecMetadata:
    mtime, size = _fingerprint(path, "spec")
    cached = _metadata_cache.get(str(path))
    if cached and cached[:2] == (mtime, size):
        return cached[2]
    metadata = load_spec_metadata(str(path))
    _metadata_cache[str(path)] = (mtime, size, metadata)
    return metadata


def _candidate_scope(relative: str, patterns: Sequence[str], paths: Sequence[str]) -> tuple[str, tuple[str, ...]]:
    if relative.startswith("_session/"):
        return "task", ()
    matched = tuple(path for path in paths if any(fnmatch.fnmatch(path, pattern) for pattern in patterns))
    return ("path", matched) if matched else ("global", ())


def _candidate_for(
    path: Path,
    spec_root: Path,
    mapping: Mapping[str, object],
    config_path: str,
    stage: str,
    paths: Sequence[str],
) -> Optional[SpecCandidate]:
    relative = path.relative_to(spec_root).as_posix()
    metadata = _load_metadata(path)
    if stage not in metadata.stages:
        return None
    domain = relative.split("/", 1)[0]
    config = _domain_config(mapping, domain, config_path)
    patterns = _patterns(config, f"path_mapping.{domain}.patterns", config_path)
    scope, matched = _candidate_scope(relative, patterns, paths)
    return SpecCandidate(metadata.id, relative, scope, SCOPE_PRIORITY[scope], matched, metadata)


def resolve_candidates(root: str, stage: str, paths: Sequence[str]) -> tuple[SpecCandidate, ...]:
    if stage not in ALLOWED_STAGES:
        raise SpecResolutionError(root, "stage", f"不支持 stage: {stage!r}")
    normalized_paths = tuple(path.replace("\\", "/") for path in paths)
    config = _load_config(root)
    config_path = str(Path(root) / ".code-flow" / "config.yml")
    mapping = _path_mapping(config, config_path)
    excluded = _non_injectable(mapping, config_path)
    spec_root = Path(root) / ".code-flow" / "specs"
    if not spec_root.is_dir():
        raise SpecResolutionError(str(spec_root), "specs", "缺失 specs 目录")
    candidates: list[SpecCandidate] = []
    ids: dict[str, str] = {}
    for path in sorted(spec_root.rglob("*.md")):
        relative = path.relative_to(spec_root).as_posix()
        if path.name == "_map.md" or relative.startswith("_session/") or relative in excluded:
            continue
        candidate = _candidate_for(path, spec_root, mapping, config_path, stage, normalized_paths)
        if candidate is None:
            continue
        if candidate.spec_id in ids:
            detail = f"重复 id {candidate.spec_id}: {ids[candidate.spec_id]}, {candidate.path}"
            raise SpecResolutionError(str(spec_root), "spec_id", detail)
        ids[candidate.spec_id] = candidate.path
        candidates.append(candidate)
    return tuple(sorted(candidates, key=lambda item: (-item.priority, item.path)))


def _effective_enforcement(candidate: SpecCandidate, rule: SpecRule) -> str:
    if candidate.metadata.enforcement == "advisory" and rule.enforcement == "required":
        return "advisory"
    return rule.enforcement


def _rule_sources(candidates: Sequence[SpecCandidate]) -> dict[str, list[_RuleSource]]:
    grouped: dict[str, list[_RuleSource]] = {}
    for candidate in candidates:
        for rule in candidate.metadata.rules:
            source = _RuleSource(candidate, rule, _effective_enforcement(candidate, rule))
            grouped.setdefault(rule.ref, []).append(source)
    for sources in grouped.values():
        sources.sort(key=lambda item: (-item.candidate.priority, item.candidate.path))
    return grouped


def _resolve_rule(ref: str, sources: Sequence[_RuleSource]) -> tuple[Optional[ResolvedRule], Optional[RuleConflict]]:
    priority = sources[0].candidate.priority
    top = tuple(source for source in sources if source.candidate.priority == priority)
    required = tuple(source for source in top if source.enforcement == "required")
    hashes = {source.rule.text_sha256 for source in required}
    if len(required) > 1 and len(hashes) > 1:
        conflict = RuleConflict(
            ref,
            priority,
            tuple(source.candidate.spec_id for source in required),
            tuple(source.rule.text_sha256 for source in required),
        )
        return None, conflict
    winner = required[0] if required else top[0]
    overridden = tuple(source.candidate.spec_id for source in sources if source is not winner)
    resolved = ResolvedRule(
        ref,
        winner.candidate.spec_id,
        winner.rule.text,
        winner.enforcement,
        winner.candidate.scope,
        priority,
        overridden,
    )
    return resolved, None


def resolve_precedence(candidates: Sequence[SpecCandidate]) -> PrecedenceResolution:
    effective: list[ResolvedRule] = []
    conflicts: list[RuleConflict] = []
    for ref, sources in sorted(_rule_sources(candidates).items()):
        resolved, conflict = _resolve_rule(ref, sources)
        if resolved is not None:
            effective.append(resolved)
        if conflict is not None:
            conflicts.append(conflict)
    return PrecedenceResolution(tuple(candidates), tuple(effective), tuple(conflicts))


def build_candidate_page(candidates: Sequence[SpecCandidate], limit: int) -> CandidatePage:
    if limit <= 0:
        raise SpecResolutionError("<memory>", "limit", "必须大于 0")
    items = tuple(candidates[:limit])
    return CandidatePage(items=items, total=len(candidates), has_more=len(candidates) > limit)
