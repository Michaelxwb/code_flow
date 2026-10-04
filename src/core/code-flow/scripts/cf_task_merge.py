#!/usr/bin/env python3
"""Deterministic merges for shared demand-state files across parallel worktrees.

Parallel workers each finish in their own worktree; their branches touch the
same demand files (task markdown, ``spec-context.yml``,
``.acceptance-manifest.json``), so a plain git rebase/merge always conflicts on
them. The rules here apply the documented deterministic priority
(cf-task:start 4.4) programmatically:

- task markdown: the merging TASK owns its section (branch wins); the
  Acceptance Coverage table unions rows by scenario id with status priority;
  every other section comes from main (the accumulating side).
- ``spec-context.yml``: bindings/rules union; stage evidence unions by identity;
  a stage verified on either side stays verified; decisions prefer non-null.
- ``.acceptance-manifest.json``: scenarios union by id (verified / higher
  revision wins); run history unions and dedupes by (run_id, revision).

Only pure text/dict transformations live here; git orchestration stays in
``cf_task_parallel.py``.
"""

from __future__ import annotations

import json
import re
from typing import Mapping, Optional

import yaml

from cf_acceptance_evidence import line_status


_COVERAGE_ROW_RE = re.compile(r"^\s*(?:\|\s*|[-*]\s+)([SEB]-\d+)(?=\s*[:|])")
_SECTION_SPLIT_RE = re.compile(r"(?m)(?=^## )")

# Coverage/contract cell statuses: a verified row always wins; deferred states
# outrank still-planned ones so done tasks keep their e2e_deferred/manual_pending.
_SCENARIO_PRIORITY = {
    "verified": 100,
    "e2e_deferred": 60,
    "manual_pending": 60,
    "unverified": 50,
    "failed": 50,
    "incomplete": 50,
    "not_configured": 50,
    "pending": 20,
    "tbd": 20,
    "planned": 10,
    "": 0,
}

_RULE_STATUS_PRIORITY = {
    "verified": 60,
    "applied": 50,
    "not_applicable": 40,
    "waived": 40,
    "unverified": 30,
    "pending": 20,
    "stale": 10,
    "conflict": 10,
}


def _as_dicts(value: object) -> list[dict]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _keyed(items: list[dict], key: str) -> dict:
    result = {}
    for item in items:
        value = item.get(key)
        if isinstance(value, str) and value:
            result[value] = item
    return result


# --- task markdown -----------------------------------------------------------


def _section_key(first_line: str) -> str:
    heading = first_line.strip().lstrip("#").strip()
    if heading.startswith("Acceptance Coverage"):
        return "@coverage"
    match = re.match(r"(TASK-\d+):", heading)
    return match.group(1) if match else heading


def _split_sections(text: str) -> tuple[str, list[tuple[str, str]]]:
    parts = _SECTION_SPLIT_RE.split(text)
    preamble, blocks = parts[0], parts[1:]
    sections: list[tuple[str, str]] = []
    for block in blocks:
        lines = block.splitlines()
        if lines:
            sections.append((_section_key(lines[0]), block))
    return preamble, sections


def _scenario_status(line: str, scenario_id: str) -> str:
    return line_status(line, scenario_id) or ""


def _merge_coverage(main_block: str, branch_block: str) -> str:
    if not branch_block:
        return main_block
    lines = main_block.splitlines()
    trailing = len(main_block) - len(main_block.rstrip("\n"))
    row_index: dict[str, int] = {}
    last_table = -1
    for index, line in enumerate(lines):
        scenario_id = _COVERAGE_ROW_RE.match(line)
        if scenario_id:
            row_index[scenario_id.group(1)] = index
        if line.strip().startswith("|"):
            last_table = index
    insert_at = last_table if last_table >= 0 else len(lines) - 1
    for line in branch_block.splitlines():
        match = _COVERAGE_ROW_RE.match(line)
        if not match:
            continue
        scenario_id = match.group(1)
        if scenario_id in row_index:
            current = lines[row_index[scenario_id]]
            if _SCENARIO_PRIORITY.get(_scenario_status(line, scenario_id), 0) > \
                    _SCENARIO_PRIORITY.get(_scenario_status(current, scenario_id), 0):
                lines[row_index[scenario_id]] = line
        else:
            insert_at += 1
            lines.insert(insert_at, line)
            row_index[scenario_id] = insert_at
    return "\n".join(lines) + "\n" * trailing


def merge_task_markdown(main_text: str, branch_text: str, task_id: str) -> str:
    """Merge the task file: own TASK section from branch, coverage union, rest main."""
    main_preamble, main_sections = _split_sections(main_text)
    _, branch_sections = _split_sections(branch_text)
    branch_map = dict(branch_sections)
    ordered: list[str] = []
    seen: set[str] = set()
    for key, block in main_sections:
        seen.add(key)
        if key == task_id:
            block = branch_map.get(task_id, block)
        elif key == "@coverage":
            block = _merge_coverage(block, branch_map.get("@coverage", ""))
        ordered.append(block)
    for key, block in branch_sections:
        if key not in seen:
            ordered.append(block)
    return main_preamble + "".join(ordered)


# --- spec-context.yml --------------------------------------------------------


def _merge_sources(main: object, branch: object) -> list[dict]:
    merged, seen = [], set()
    for item in _as_dicts(main) + _as_dicts(branch):
        key = (item.get("type"), item.get("ref"))
        if key not in seen:
            seen.add(key)
            merged.append(item)
    return merged


def _merge_refs(main: object, branch: object) -> list[dict]:
    merged, seen = [], set()
    for item in _as_dicts(main) + _as_dicts(branch):
        key = (item.get("artifact"), item.get("section_id"),
               item.get("item_id"), item.get("artifact_sha256"))
        if key not in seen:
            seen.add(key)
            merged.append(item)
    return merged


def _evidence_key(item: Mapping[str, object]) -> tuple:
    if item.get("error_code") == "skipped_in_cheap_gate":
        third = None
    else:
        third = item.get("diff_sha256")
    return (item.get("verifier_ref"), item.get("result_sha256"), third)


def _merge_evidence(main: object, branch: object) -> list[dict]:
    merged, seen = [], set()
    for item in _as_dicts(main) + _as_dicts(branch):
        key = _evidence_key(item)
        if key not in seen:
            seen.add(key)
            merged.append(item)
    return merged


def _pick_rule_status(main: str, branch: str) -> str:
    if _RULE_STATUS_PRIORITY.get(main, 0) >= _RULE_STATUS_PRIORITY.get(branch, 0):
        return main
    return branch


def _merge_stage(main: object, branch: object) -> object:
    if not isinstance(main, dict):
        return branch
    if not isinstance(branch, dict):
        return main
    merged = dict(main)
    merged["refs"] = _merge_refs(main.get("refs"), branch.get("refs"))
    merged["evidence"] = _merge_evidence(main.get("evidence"), branch.get("evidence"))
    merged["decision"] = main.get("decision") or branch.get("decision")
    merged["status"] = _pick_rule_status(
        str(main.get("status", "")), str(branch.get("status", ""))
    )
    return merged


def _merge_stage_status(main: object, branch: object) -> dict:
    main_map = main if isinstance(main, dict) else {}
    branch_map = branch if isinstance(branch, dict) else {}
    return {
        stage: _merge_stage(main_map.get(stage), branch_map.get(stage))
        for stage in sorted(set(main_map) | set(branch_map))
    }


def _merge_rule(main: dict, branch: dict) -> dict:
    merged = dict(main)
    merged["stage_status"] = _merge_stage_status(
        main.get("stage_status"), branch.get("stage_status")
    )
    return merged


def _merge_by_ref(main: object, branch: object) -> list[dict]:
    main_by = _keyed(_as_dicts(main), "ref")
    branch_by = _keyed(_as_dicts(branch), "ref")
    merged: list[dict] = []
    for ref in sorted(set(main_by) | set(branch_by)):
        a, b = main_by.get(ref), branch_by.get(ref)
        if a and b:
            merged.append(_merge_rule(a, b))
        else:
            merged.append(a or b)
    return merged


def _merge_binding(main: dict, branch: dict) -> dict:
    merged = dict(main)
    merged["rules"] = _merge_by_ref(main.get("rules"), branch.get("rules"))
    return merged


def _merge_bindings(main: object, branch: object) -> list[dict]:
    main_by = _keyed(_as_dicts(main), "spec_id")
    branch_by = _keyed(_as_dicts(branch), "spec_id")
    merged: list[dict] = []
    for spec_id in sorted(set(main_by) | set(branch_by)):
        a, b = main_by.get(spec_id), branch_by.get(spec_id)
        if a and b:
            merged.append(_merge_binding(a, b))
        else:
            merged.append(a or b)
    return merged


def merge_context_docs(main: Mapping[str, object], branch: Mapping[str, object]) -> dict:
    merged = dict(main)
    merged["updated_at"] = max(
        str(main.get("updated_at", "")), str(branch.get("updated_at", ""))
    )
    merged["sources"] = _merge_sources(main.get("sources"), branch.get("sources"))
    merged["bindings"] = _merge_bindings(main.get("bindings"), branch.get("bindings"))
    return merged


def merge_context_text(main_text: str, branch_text: str) -> str:
    try:
        main_doc = yaml.safe_load(main_text) or {}
        branch_doc = yaml.safe_load(branch_text) or {}
    except yaml.YAMLError as exc:
        raise ValueError(f"spec-context.yml 解析失败: {exc}") from exc
    if not isinstance(main_doc, dict) or not isinstance(branch_doc, dict):
        raise ValueError("spec-context.yml must be a mapping on both sides")
    merged = merge_context_docs(main_doc, branch_doc)
    return yaml.safe_dump(merged, sort_keys=False, allow_unicode=True)


# --- .acceptance-manifest.json ----------------------------------------------


def _merge_runs(main: object, branch: object) -> list[dict]:
    merged, seen = [], set()
    for item in _as_dicts(main) + _as_dicts(branch):
        key = (item.get("run_id"), item.get("revision"))
        if key not in seen:
            seen.add(key)
            merged.append(item)
    merged.sort(key=lambda item: (int(item.get("revision", 0) or 0), str(item.get("run_id", ""))))
    return merged


def _choose_scenario(main: dict, branch: dict) -> dict:
    main_status = str(main.get("status", ""))
    branch_status = str(branch.get("status", ""))
    if main_status == "verified" and branch_status != "verified":
        return main
    if branch_status == "verified" and main_status != "verified":
        return branch
    main_revision = int(main.get("revision", 0) or 0)
    branch_revision = int(branch.get("revision", 0) or 0)
    return main if main_revision >= branch_revision else branch


def _merge_scenario(main: dict, branch: dict) -> dict:
    merged = dict(_choose_scenario(main, branch))
    merged["runs"] = _merge_runs(main.get("runs"), branch.get("runs"))
    return merged


def _merge_scenarios(main: object, branch: object) -> list[dict]:
    main_rows = _as_dicts(main)
    branch_by = _keyed(_as_dicts(branch), "id")
    merged: list[dict] = []
    seen: set = set()
    for row in main_rows:
        scenario_id = row.get("id")
        seen.add(scenario_id)
        if scenario_id in branch_by:
            merged.append(_merge_scenario(row, branch_by[scenario_id]))
        else:
            merged.append(row)
    for row in _as_dicts(branch):
        if row.get("id") not in seen:
            merged.append(row)
    return merged


def merge_manifest_docs(main: Mapping[str, object], branch: Mapping[str, object]) -> dict:
    merged = dict(main)
    merged["scenarios"] = _merge_scenarios(main.get("scenarios"), branch.get("scenarios"))
    return merged


def merge_manifest_text(main_text: str, branch_text: str) -> str:
    main_doc = json.loads(main_text)
    branch_doc = json.loads(branch_text)
    if not isinstance(main_doc, dict) or not isinstance(branch_doc, dict):
        raise ValueError("acceptance manifest must be an object on both sides")
    merged = merge_manifest_docs(main_doc, branch_doc)
    return json.dumps(merged, ensure_ascii=False, indent=2) + "\n"
