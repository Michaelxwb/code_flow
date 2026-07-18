#!/usr/bin/env python3
"""Project one TASK's bound rules into a bounded session document."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
import sys
from typing import IO, Mapping, Optional, Sequence

import yaml

from cf_spec_context import RuleBinding, SpecContext, context_to_data, load_context


@dataclass(frozen=True)
class SessionProjection:
    text: str
    included_rules: int
    total_rules: int
    truncated: bool


def context_sha256(context: SpecContext) -> str:
    data = yaml.safe_dump(context_to_data(context), sort_keys=True, allow_unicode=True).encode()
    return hashlib.sha256(data).hexdigest()


def _task_section(text: str, task_id: str) -> str:
    match = re.search(rf"(?m)^## {re.escape(task_id)}:[^\n]*$", text)
    if match is None:
        raise ValueError(f"task_not_found: {task_id}")
    following = re.search(r"(?m)^## TASK-\d+:", text[match.end():])
    end = match.end() + following.start() if following else len(text)
    return text[match.start():end]


def _refs(section: str) -> tuple[str, ...]:
    match = re.search(r"(?m)^- \*\*Spec-Refs\*\*:\s*(.+)$", section)
    if match is None:
        raise ValueError("spec_refs_missing")
    return tuple(item.strip() for item in match.group(1).split(",") if item.strip())


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


def project_task_session(
    context: SpecContext, task_file: str, task_id: str, max_chars: int = 4000
) -> SessionProjection:
    section = _task_section(Path(task_file).read_text(encoding="utf-8"), task_id)
    refs = _refs(section)
    index = _rule_index(context)
    missing = tuple(ref for ref in refs if ref not in index)
    if missing:
        raise ValueError(f"unknown_spec_refs: {', '.join(missing)}")
    acceptance = _acceptance_contract(section)
    header = f"# {task_id} Spec Context\n\n- Context-SHA256: `{context_sha256(context)}`\n\n## Required Rules\n"
    footer = f"\n## Acceptance Contract\n{acceptance}\n"
    lines: list[str] = []
    for ref in refs:
        candidate = _rule_line(ref, index[ref])
        if len(header + "".join(lines) + candidate + footer) > max_chars:
            break
        lines.append(candidate)
    truncated = len(lines) < len(refs)
    if truncated:
        footer = "\n> 投影超过预算；完整 Context 保留在需求目录，请拆分 TASK。\n" + footer
    text = (header + "".join(lines) + footer)[:max_chars]
    return SessionProjection(text, len(lines), len(refs), truncated)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="cf_spec_session.py")
    parser.add_argument("--task-dir", required=True)
    parser.add_argument("--task-file", required=True)
    parser.add_argument("--task", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--budget", type=int, default=4000)
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: Optional[Sequence[str]] = None, stdout: IO[str] = sys.stdout) -> int:
    try:
        args = _parser().parse_args(argv)
        context = load_context(str(Path(args.task_dir) / "spec-context.yml"))
        result = project_task_session(context, args.task_file, args.task, args.budget)
        Path(args.output).write_text(result.text, encoding="utf-8")
        stdout.write(json.dumps(result.__dict__, ensure_ascii=False))
        return 0
    except Exception as exc:
        stdout.write(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
