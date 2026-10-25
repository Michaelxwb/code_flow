"""Resolve artifact references and report unfinished rule applications."""
from __future__ import annotations

import hashlib
from pathlib import Path
import re
from typing import Mapping, TYPE_CHECKING

if TYPE_CHECKING:
    from cf_spec_context import SpecContext

_UNRESOLVED = re.compile(r"\b(?:TBD|TODO)\b|待同步|待确认|待定|需同步\s*spec\s*文本", re.I)


def referenced_item(text: str, section_id: str, item_id: str) -> str:
    """Find the item inside its declared section, excluding fenced examples."""
    clean = re.sub(r"```[^\n]*\n[\s\S]*?```|~~~[^\n]*\n[\s\S]*?~~~", "", text)
    headings = list(re.finditer(r"(?m)^(#{1,6})[ \t]+([^\n]+)$", clean))
    section = section_id.lstrip("#§ ").strip()
    pattern = re.compile(rf"(?<![\w.]){re.escape(section)}(?![\w.])")
    if not headings:
        return next((part for part in clean.split("\n\n") if pattern.search(part) and item_id in part), "")
    start = next((entry for entry in headings if pattern.search(entry.group(2))), None)
    if start is None:
        return ""
    end = next((entry.start() for entry in headings
                if entry.start() > start.start() and len(entry.group(1)) <= len(start.group(1))), len(clean))
    lines = clean[start.end():end].splitlines()
    selected: list[str] = []
    for line in lines:
        if item_id in line:
            selected.append(line)
        elif selected and (re.match(r"\s*(?:#{1,6}\s|\|?\s*\[?RULE-|[-*]\s+\[?RULE-)", line)):
            break
        elif selected:
            selected.append(line)
    return "\n".join(selected).strip()


def unresolved_text(text: str) -> bool:
    # A prohibition mentioning TBD is a valid rule, not an unfinished result.
    without_prohibitions = re.sub(
        r"(?:禁止|不得|不能)[^，。;\n]*(?:TBD|TODO|待同步|待确认)[^，。;\n]*", "", text, flags=re.I)
    return bool(_UNRESOLVED.search(without_prohibitions))


def artifact_problem(root: str, artifact: str, section: str, item: str, expected_hash: str = "") -> str:
    base = Path(root).resolve()
    target = (base / artifact).resolve()
    if base not in target.parents:
        return "rule_artifact_outside_project"
    try:
        content = target.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return "rule_artifact_missing"
    if expected_hash and hashlib.sha256(target.read_bytes()).hexdigest() != expected_hash:
        return "rule_artifact_stale"
    selected = referenced_item(content, section, item)
    if not selected:
        return "rule_artifact_reference_missing"
    return "rule_applied_unresolved" if unresolved_text(selected) else ""


def applied_findings(context: SpecContext, root: str, only_stage: str = "") -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    for binding in context.bindings:
        for rule in binding.rules:
            if rule.enforcement != "required":
                continue
            for stage, status in rule.stage_status.items():
                if only_stage and stage != only_stage:
                    continue
                if status.status != "applied":
                    continue
                for ref in status.refs:
                    code = artifact_problem(root, ref.artifact, ref.section_id, ref.item_id, ref.artifact_sha256)
                    if code:
                        findings.append({"code": code, "severity": "block", "path": ref.artifact,
                                         "message": f"{binding.spec_id}#{rule.ref} ({stage}): {code}",
                                         "fix": "完成引用条目并运行 code-flow spec refresh，再执行对应阶段验证"})
    return findings


def convention_findings(root: str, paths: list[str]) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    for relative in paths:
        target = Path(root) / ".code-flow/specs" / relative
        try:
            text = target.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            findings.append({"code": "convention_review_unreadable", "severity": "block", "path": str(target),
                             "message": str(exc), "fix": "修复绑定 Spec 文件后重跑 doctor"})
            continue
        if re.search(r"(?mi)^##\s+(?:Conventions|约定)\s*$", text):
            findings.append({"code": "convention_review_required", "severity": "warn", "path": str(target),
                             "message": "Conventions 尚未成为可验证约束；关键条目应提升为有稳定 ID 的 Rules",
                             "fix": "审查约定与本次设计的一致性；关键约束补充 Rule 和 verifier"})
    return findings
