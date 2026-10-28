"""Project one TASK's bound Spec rules into a session document."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Mapping, Optional

from codeflow.spec.cf_spec_context_model import RuleBinding, SpecContext, context_sha256
from codeflow.task.cf_task_doc import task_section, task_spec_refs


@dataclass(frozen=True)
class SessionProjection:
    text: str
    included_rules: int
    total_rules: int
    truncated: bool


def _task_section(text: str, task_id: str) -> str:
    return task_section(text, task_id).body


def _refs(section: str) -> tuple[str, ...]:
    return task_spec_refs(section)


def _rule_index(context: SpecContext) -> Mapping[str, RuleBinding]:
    return {
        f"{binding.spec_id}#{rule.ref}": rule
        for binding in context.bindings
        for rule in binding.rules
    }


def _acceptance_contract(section: str) -> str:
    match = re.search(r"(?ms)^### Acceptance Contract\s*$\n(.*?)(?=^### |^## |\Z)", section)
    if match is None:
        raise ValueError("acceptance_contract_missing")
    return match.group(1).strip()


def _rule_line(ref: str, rule: RuleBinding, compact: bool = False) -> str:
    hashes = f"rule_sha256={rule.text_sha256} verifier={rule.verifier_ref}"
    if compact:
        return f"- `{ref}` {hashes}\n"
    artifacts = sorted({item.artifact for status in rule.stage_status.values() for item in status.refs})
    return f"- `{ref}`: {rule.summary}\n  - {hashes}; artifacts={','.join(artifacts) or 'none'}\n"


def _reference_header(section: str) -> str:
    lines = re.findall(r"(?m)^- \*\*(?:Source|Design-Refs|Acceptance-Refs)\*\*:[ \t]*[^\n]*", section)
    return "".join(line + "\n" for line in lines)


def project_task_session(
    context: SpecContext, task_file: str, task_id: str, max_chars: int = 12000,
    *, context_hash: Optional[str] = None,
) -> SessionProjection:
    section = _task_section(Path(task_file).read_text(encoding="utf-8"), task_id)
    refs = _refs(section)
    index = _rule_index(context)
    missing = tuple(ref for ref in refs if ref not in index)
    if missing:
        raise ValueError(f"unknown_spec_refs: {', '.join(missing)}")
    acceptance = _acceptance_contract(section)
    header = (f"# {task_id} Spec Context\n\n- Context-SHA256: `{context_hash or context_sha256(context)}`\n"
              + _reference_header(section) + "\n## Required Rules\n")
    footer = f"\n## Acceptance Contract\n{acceptance}\n"
    lines: list[str] = []
    for ref in refs:
        candidate = _rule_line(ref, index[ref])
        if len(header + "".join(lines) + candidate + footer) > max_chars:
            break
        lines.append(candidate)
    truncated = len(lines) < len(refs) or len(header + "".join(lines) + footer) > max_chars
    if truncated:
        footer = "\n> 投影超过预算；完整 Context 保留在需求目录，请拆分 TASK。\n" + footer
    text = (header + "".join(lines) + footer)[:max_chars]
    return SessionProjection(text, len(lines), len(refs), truncated)


