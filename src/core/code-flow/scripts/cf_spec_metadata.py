#!/usr/bin/env python3
"""Schema-v1 Spec metadata parser and deterministic content hashes."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
from typing import Mapping, Optional

import yaml


ALLOWED_STAGES = frozenset(("prd", "design", "plan", "code", "review"))
ALLOWED_ENFORCEMENT = frozenset(("required", "advisory"))
ALLOWED_VERIFIERS = frozenset(("document", "regex", "ast", "command", "test", "manual"))
_ID_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_RULE_ID_RE = re.compile(r"^RULE-[a-z0-9]+(?:-[a-z0-9]+)*-\d{3}$")
_EXPLICIT_RULE_RE = re.compile(r"^\[(RULE-[a-z0-9-]+-\d{3})\]\s+(.+)$")
_FRONTMATTER_RE = re.compile(r"\A---[ \t]*\r?\n(.*?)\r?\n---[ \t]*(?:\r?\n|$)", re.DOTALL)
_SECTION_RE = re.compile(r"^##\s+(Rules|Anti-Patterns|Patterns|Examples)\s*$")
_H2_RE = re.compile(r"^##\s+")
_BULLET_RE = re.compile(r"^\s*-\s+(.+\S|\S)\s*$")


class SpecMetadataError(ValueError):
    """A schema error with a stable field and source location."""

    def __init__(self, path: str, field: str, line: int, message: str) -> None:
        self.path = path
        self.field = field
        self.line = max(1, line)
        self.message = message
        super().__init__(f"{path}:{self.line}: metadata_error {field}: {message}")


@dataclass(frozen=True)
class SpecHashes:
    file_sha256: str
    metadata_sha256: str
    rules_sha256: str

    def values(self) -> tuple[str, str, str]:
        return (self.file_sha256, self.metadata_sha256, self.rules_sha256)


@dataclass(frozen=True)
class SpecVerifier:
    rule: str
    type: str
    config: Mapping[str, object]


@dataclass(frozen=True)
class SpecRule:
    ref: str
    text: str
    section: str
    enforcement: str
    text_sha256: str
    line: int


@dataclass(frozen=True)
class SpecMetadata:
    id: str
    description: str
    stages: tuple[str, ...]
    enforcement: str
    owner: Optional[str]
    checks: tuple[Mapping[str, object], ...]
    verifiers: tuple[SpecVerifier, ...]
    rules: tuple[SpecRule, ...]
    hashes: SpecHashes
    path: str


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _normalized_text(text: str) -> str:
    return " ".join(text.split())


def _canonical_json(value: object, path: str, field: str, line: int) -> bytes:
    try:
        text = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError) as exc:
        raise SpecMetadataError(path, field, line, f"无法规范化: {exc}") from exc
    return text.encode("utf-8")


def _field_line(frontmatter: str, key: str) -> int:
    pattern = re.compile(rf"^\s*{re.escape(key)}\s*:")
    for number, line in enumerate(frontmatter.splitlines(), start=2):
        if pattern.match(line):
            return number
    return 1


def _verifier_field_line(frontmatter: str, index: int, key: str) -> int:
    current = -1
    for number, line in enumerate(frontmatter.splitlines(), start=2):
        if re.match(r"^\s*-\s+rule\s*:", line):
            current += 1
        if current == index and re.match(rf"^\s+{re.escape(key)}\s*:", line):
            return number
    return _field_line(frontmatter, "verifiers")


def _split_frontmatter(content: str, path: str) -> tuple[Mapping[str, object], str, str]:
    match = _FRONTMATTER_RE.match(content)
    if not match:
        raise SpecMetadataError(path, "frontmatter", 1, "缺失或未闭合 YAML frontmatter")
    raw = match.group(1)
    try:
        loaded = yaml.safe_load(raw) or {}
    except yaml.YAMLError as exc:
        mark = getattr(exc, "problem_mark", None)
        line = (mark.line + 2) if mark is not None else 1
        raise SpecMetadataError(path, "frontmatter", line, f"YAML 解析失败: {exc}") from exc
    if not isinstance(loaded, dict):
        raise SpecMetadataError(path, "frontmatter", 2, "顶层必须是 mapping")
    if not all(isinstance(key, str) for key in loaded):
        raise SpecMetadataError(path, "frontmatter", 2, "所有顶层 key 必须是字符串")
    return loaded, raw, content[match.end():]


def _required_string(meta: Mapping[str, object], key: str, path: str, raw: str) -> str:
    value = meta.get(key)
    if not isinstance(value, str) or not value.strip():
        raise SpecMetadataError(path, key, _field_line(raw, key), "必须是非空字符串")
    return value.strip()


def _validate_stages(meta: Mapping[str, object], path: str, raw: str) -> tuple[str, ...]:
    value = meta.get("stages")
    line = _field_line(raw, "stages")
    if not isinstance(value, list) or not value or not all(isinstance(item, str) for item in value):
        raise SpecMetadataError(path, "stages", line, "必须是非空字符串列表")
    stages = tuple(item.strip() for item in value)
    invalid = sorted(set(stages) - ALLOWED_STAGES)
    if invalid or len(set(stages)) != len(stages):
        detail = f"非法或重复 stage: {invalid or list(stages)}"
        raise SpecMetadataError(path, "stages", line, detail)
    return stages


def _validate_checks(meta: Mapping[str, object], path: str, raw: str) -> tuple[Mapping[str, object], ...]:
    value = meta.get("checks", [])
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise SpecMetadataError(path, "checks", _field_line(raw, "checks"), "必须是 mapping 列表")
    return tuple(value)


def _parse_verifiers(meta: Mapping[str, object], path: str, raw: str) -> tuple[SpecVerifier, ...]:
    value = meta.get("verifiers", [])
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise SpecMetadataError(path, "verifiers", _field_line(raw, "verifiers"), "必须是 mapping 列表")
    result: list[SpecVerifier] = []
    seen: set[str] = set()
    for index, item in enumerate(value):
        rule = item.get("rule")
        kind = item.get("type")
        config = item.get("config")
        if not isinstance(rule, str) or not _RULE_ID_RE.fullmatch(rule):
            line = _verifier_field_line(raw, index, "rule")
            raise SpecMetadataError(path, f"verifiers[{index}].rule", line, "必须是稳定 RULE ID")
        if kind not in ALLOWED_VERIFIERS:
            line = _verifier_field_line(raw, index, "type")
            raise SpecMetadataError(path, f"verifiers[{index}].type", line, f"不支持 type: {kind!r}")
        if not isinstance(config, dict):
            line = _verifier_field_line(raw, index, "config")
            raise SpecMetadataError(path, f"verifiers[{index}].config", line, "必须是 mapping")
        if rule in seen:
            raise SpecMetadataError(path, "verifiers", _field_line(raw, "verifiers"), f"重复 verifier: {rule}")
        seen.add(rule)
        result.append(SpecVerifier(rule=rule, type=kind, config=config))
    return tuple(result)


def _domain_from_path(path: str) -> str:
    source = Path(path)
    parts = source.parts
    if "specs" in parts:
        index = parts.index("specs")
        candidate = parts[index + 1] if index + 1 < len(parts) - 1 else source.stem
    else:
        candidate = source.parent.name or source.stem
    normalized = re.sub(r"[^a-z0-9]+", "-", candidate.lower()).strip("-")
    return normalized or "spec"


def _entry_details(section: str) -> tuple[str, str]:
    if section in ("Rules", "Anti-Patterns"):
        return "RULE", "required"
    if section == "Patterns":
        return "PATTERN", "advisory"
    return "EXAMPLE", "informational"


def _parse_rules(body: str, path: str, line_offset: int) -> tuple[SpecRule, ...]:
    domain = _domain_from_path(path)
    counters = {"RULE": 0, "PATTERN": 0, "EXAMPLE": 0}
    rules: list[SpecRule] = []
    section = ""
    fence = ""
    used: set[str] = set()
    for relative_line, line in enumerate(body.splitlines(), start=1):
        number = relative_line + line_offset
        stripped = line.strip()
        if not fence and stripped.startswith(("```", "~~~")):
            marker = stripped[:3]
            fence = marker
            continue
        if fence and stripped.startswith(fence):
            fence = ""
            continue
        heading = _SECTION_RE.match(line) if not fence else None
        if heading:
            section = heading.group(1)
            continue
        if not fence and _H2_RE.match(line):
            section = ""
            continue
        bullet = _BULLET_RE.match(line) if section and not fence else None
        if not bullet:
            continue
        prefix, enforcement = _entry_details(section)
        counters[prefix] += 1
        ref = f"{prefix}-{domain}-{counters[prefix]:03d}"
        text = bullet.group(1).strip()
        explicit = _EXPLICIT_RULE_RE.match(text) if prefix == "RULE" else None
        if prefix == "RULE" and text.startswith("[RULE-") and not explicit:
            raise SpecMetadataError(path, "rules", number, "显式 Rule ID 必须是 RULE-<domain>-NNN")
        if explicit:
            ref, text = explicit.group(1), explicit.group(2).strip()
        while ref in used and not explicit:
            counters[prefix] += 1
            ref = f"{prefix}-{domain}-{counters[prefix]:03d}"
        if ref in used:
            raise SpecMetadataError(path, "rules", number, f"重复规则 ID: {ref}")
        used.add(ref)
        normalized = _normalized_text(text)
        rules.append(SpecRule(ref, normalized, section, enforcement, _sha256(normalized.encode()), number))
    return tuple(rules)


def _validate_links(
    rules: tuple[SpecRule, ...], verifiers: tuple[SpecVerifier, ...], path: str, raw: str
) -> None:
    required = {rule.ref for rule in rules if rule.enforcement == "required"}
    linked = {verifier.rule for verifier in verifiers}
    missing = sorted(required - linked)
    unknown = sorted(linked - required)
    line = _field_line(raw, "verifiers")
    if missing:
        raise SpecMetadataError(path, "verifiers", line, f"required Rule 缺 verifier: {', '.join(missing)}")
    if unknown:
        raise SpecMetadataError(path, "verifiers", line, f"verifier 引用未知 required Rule: {', '.join(unknown)}")


def parse_spec_metadata(content: str, path: str = "<memory>", raw_bytes: Optional[bytes] = None) -> SpecMetadata:
    meta, raw_frontmatter, body = _split_frontmatter(content, path)
    spec_id = _required_string(meta, "id", path, raw_frontmatter)
    if not _ID_RE.fullmatch(spec_id):
        raise SpecMetadataError(path, "id", _field_line(raw_frontmatter, "id"), "必须是 kebab-case")
    description = _required_string(meta, "description", path, raw_frontmatter)
    stages = _validate_stages(meta, path, raw_frontmatter)
    enforcement = _required_string(meta, "enforcement", path, raw_frontmatter)
    if enforcement not in ALLOWED_ENFORCEMENT:
        line = _field_line(raw_frontmatter, "enforcement")
        raise SpecMetadataError(path, "enforcement", line, f"必须是 {sorted(ALLOWED_ENFORCEMENT)}")
    owner = meta.get("owner")
    if owner is not None and (not isinstance(owner, str) or not owner.strip()):
        raise SpecMetadataError(path, "owner", _field_line(raw_frontmatter, "owner"), "必须是非空字符串")
    checks = _validate_checks(meta, path, raw_frontmatter)
    verifiers = _parse_verifiers(meta, path, raw_frontmatter)
    body_line_offset = raw_frontmatter.count("\n") + 3
    rules = _parse_rules(body, path, body_line_offset)
    _validate_links(rules, verifiers, path, raw_frontmatter)
    required_rules = [(rule.ref, rule.text) for rule in rules if rule.enforcement == "required"]
    source_bytes = raw_bytes if raw_bytes is not None else content.encode("utf-8")
    hashes = SpecHashes(
        file_sha256=_sha256(source_bytes),
        metadata_sha256=_sha256(_canonical_json(meta, path, "frontmatter", 1)),
        rules_sha256=_sha256(_canonical_json(required_rules, path, "rules", 1)),
    )
    return SpecMetadata(spec_id, description, stages, enforcement, owner, checks, verifiers, rules, hashes, path)


def load_spec_metadata(path: str) -> SpecMetadata:
    try:
        raw = Path(path).read_bytes()
    except OSError as exc:
        raise SpecMetadataError(path, "file", 1, f"读取失败: {exc}") from exc
    try:
        content = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise SpecMetadataError(path, "encoding", 1, f"必须是 UTF-8: {exc}") from exc
    return parse_spec_metadata(content, path=path, raw_bytes=raw)
