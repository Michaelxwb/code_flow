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
- ``spec-context.yml``: bindings/rules union; only each rule's latest stage
  state and latest evidence entry survive. When the post-merge input hash is
  supplied, a verified state whose recorded hash no longer matches is
  downgraded to ``stale`` (old proof is retained for audit).
- ``.acceptance-manifest.json``: checks union by id; the same check id with a
  different command/cwd/timeout/env/inputs fails closed, as does a scenario
  mapped to two different checks. Scenarios union by id (verified / higher
  revision wins); run history unions and dedupes by (run_id, revision).

Only pure text/dict transformations live here; git orchestration stays in
``cf_task_parallel.py``.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
import re
from typing import Mapping, Optional, Sequence

import yaml

from codeflow.acceptance.cf_acceptance_evidence import line_status


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

# Manifest v3 execution identity: equal IDs must describe the same execution.
_CHECK_IDENTITY_FIELDS = (
    "command", "cwd", "timeout", "env", "env_scope", "preflight", "parallel_safe", "profile", "inputs",
)


class MergeConflictError(ValueError):
    """Deterministic state merge refused because two sides disagree.

    ``conflicts`` is a tuple of JSON-ready records so callers (parallel merge)
    can surface the exact check/scenario and fields without parsing prose.
    """

    def __init__(self, code: str, message: str,
                 conflicts: Sequence[Mapping[str, object]] = ()) -> None:
        super().__init__(message)
        self.code = code
        self.conflicts = tuple(dict(item) for item in conflicts)


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


def _evidence_time(item: Mapping[str, object]) -> float:
    value = item.get("executed_at")
    if not isinstance(value, str) or not value.strip():
        return 0.0
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return 0.0
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.timestamp()


def _latest_evidence(status: Mapping[str, object]) -> Optional[dict]:
    evidence = _as_dicts(status.get("evidence"))
    if not evidence:
        return None
    # Timestamp wins; equal/missing timestamps keep list order (last entry).
    return max(enumerate(evidence), key=lambda pair: (_evidence_time(pair[1]), pair[0]))[1]


def _latest_status_time(status: Mapping[str, object]) -> float:
    evidence = _as_dicts(status.get("evidence"))
    return max((_evidence_time(item) for item in evidence), default=0.0)


def _choose_stage(main: object, branch: object) -> dict:
    if not isinstance(main, dict):
        return dict(branch) if isinstance(branch, dict) else {}
    if not isinstance(branch, dict):
        return dict(main)
    main_time = _latest_status_time(main)
    branch_time = _latest_status_time(branch)
    if branch_time != main_time:
        return dict(branch if branch_time > main_time else main)
    main_status = str(main.get("status", ""))
    branch_status = str(branch.get("status", ""))
    if _RULE_STATUS_PRIORITY.get(branch_status, 0) > _RULE_STATUS_PRIORITY.get(main_status, 0):
        return dict(branch)
    return dict(main)


def _merge_stage(main: object, branch: object, input_hash: Optional[str]) -> object:
    stage = _choose_stage(main, branch)
    if not stage:
        return stage
    if isinstance(main, dict) and isinstance(branch, dict):
        stage["refs"] = _merge_refs(main.get("refs"), branch.get("refs"))
        stage["decision"] = main.get("decision") or branch.get("decision")
        stage["evidence"] = _single_latest_evidence(stage, main, branch)
    else:
        stage["evidence"] = _single_latest_evidence(stage, stage, stage)
    return _downgrade_stale(stage, input_hash)


def _single_latest_evidence(chosen: Mapping[str, object], main: Mapping[str, object],
                            branch: Mapping[str, object]) -> list[dict]:
    latest = _latest_evidence(chosen)
    if latest is None:
        latest = _latest_evidence(main) or _latest_evidence(branch)
    return [latest] if latest is not None else []


def _evidence_input_hash(evidence: Mapping[str, object]) -> Optional[str]:
    for key in ("input_hash", "diff_sha256"):
        value = evidence.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _downgrade_stale(stage: dict, input_hash: Optional[str]) -> dict:
    """A verified proof is only valid for the input hash it ran against."""
    if not input_hash or stage.get("status") != "verified":
        return stage
    latest = _latest_evidence(stage)
    recorded = _evidence_input_hash(latest) if latest is not None else None
    if recorded != input_hash:
        stage["status"] = "stale"
    return stage


def _merge_stage_status(main: object, branch: object, input_hash: Optional[str]) -> dict:
    main_map = main if isinstance(main, dict) else {}
    branch_map = branch if isinstance(branch, dict) else {}
    return {
        stage: _merge_stage(main_map.get(stage), branch_map.get(stage), input_hash)
        for stage in sorted(set(main_map) | set(branch_map))
    }


def _merge_rule(main: dict, branch: dict, input_hash: Optional[str]) -> dict:
    merged = dict(main)
    merged["stage_status"] = _merge_stage_status(
        main.get("stage_status"), branch.get("stage_status"), input_hash
    )
    return merged


def _merge_by_ref(main: object, branch: object, input_hash: Optional[str]) -> list[dict]:
    main_by = _keyed(_as_dicts(main), "ref")
    branch_by = _keyed(_as_dicts(branch), "ref")
    merged: list[dict] = []
    for ref in sorted(set(main_by) | set(branch_by)):
        a, b = main_by.get(ref), branch_by.get(ref)
        if a and b:
            merged.append(_merge_rule(a, b, input_hash))
        else:
            merged.append(a or b)
    return merged


def _merge_binding(main: dict, branch: dict, input_hash: Optional[str]) -> dict:
    merged = dict(main)
    merged["rules"] = _merge_by_ref(main.get("rules"), branch.get("rules"), input_hash)
    return merged


def _merge_bindings(main: object, branch: object, input_hash: Optional[str]) -> list[dict]:
    main_by = _keyed(_as_dicts(main), "spec_id")
    branch_by = _keyed(_as_dicts(branch), "spec_id")
    merged: list[dict] = []
    for spec_id in sorted(set(main_by) | set(branch_by)):
        a, b = main_by.get(spec_id), branch_by.get(spec_id)
        if a and b:
            merged.append(_merge_binding(a, b, input_hash))
        else:
            merged.append(a or b)
    return merged


def _each_stage(doc: Mapping[str, object]):
    for binding in _as_dicts(doc.get("bindings")):
        for rule in _as_dicts(binding.get("rules")):
            stage_status = rule.get("stage_status")
            if not isinstance(stage_status, dict):
                continue
            for stage, status in list(stage_status.items()):
                if isinstance(status, dict):
                    yield stage_status, stage, status


def _compact_context(doc: dict) -> dict:
    """Keep only the latest evidence entry for every rule/stage."""
    for stage_status, stage, status in _each_stage(doc):
        stage_status[stage] = {
            **status,
            "evidence": _single_latest_evidence(status, status, status),
        }
    return doc


def _downgrade_context(doc: dict, input_hash: Optional[str]) -> dict:
    if not input_hash:
        return doc
    for stage_status, stage, status in _each_stage(doc):
        stage_status[stage] = _downgrade_stale(dict(status), input_hash)
    return doc


def merge_context_docs(main: Mapping[str, object], branch: Mapping[str, object],
                       input_hash: Optional[str] = None) -> dict:
    """Union metadata but keep only each rule's latest state/evidence.

    ``input_hash`` is the post-merge execution input fingerprint. Verified
    states whose recorded hash differs are downgraded to ``stale``.
    """
    merged = dict(main)
    merged["updated_at"] = max(
        str(main.get("updated_at", "")), str(branch.get("updated_at", ""))
    )
    merged["sources"] = _merge_sources(main.get("sources"), branch.get("sources"))
    merged["bindings"] = _merge_bindings(main.get("bindings"), branch.get("bindings"), None)
    _compact_context(merged)
    return _downgrade_context(merged, input_hash)


def merge_context_text(main_text: str, branch_text: str,
                       input_hash: Optional[str] = None) -> str:
    try:
        main_doc = yaml.safe_load(main_text) or {}
        branch_doc = yaml.safe_load(branch_text) or {}
    except yaml.YAMLError as exc:
        raise ValueError(f"spec-context.yml 解析失败: {exc}") from exc
    if not isinstance(main_doc, dict) or not isinstance(branch_doc, dict):
        raise ValueError("spec-context.yml must be a mapping on both sides")
    merged = merge_context_docs(main_doc, branch_doc, input_hash)
    return yaml.safe_dump(merged, sort_keys=False, allow_unicode=True)


def stale_context_text(text: str, input_hash: str) -> tuple[str, list[str]]:
    """Downgrade verified rules whose evidence hash no longer matches."""
    try:
        doc = yaml.safe_load(text) or {}
    except yaml.YAMLError as exc:
        raise ValueError(f"spec-context.yml 解析失败: {exc}") from exc
    if not isinstance(doc, dict):
        raise ValueError("spec-context.yml must be a mapping")
    before = _stale_statuses(doc)
    if not input_hash:
        return text, []
    _downgrade_context(doc, input_hash)
    stale = sorted(set(_stale_statuses(doc)) - set(before))
    if not stale:
        return text, []
    return yaml.safe_dump(doc, sort_keys=False, allow_unicode=True), stale


def _stale_statuses(doc: Mapping[str, object]) -> list[str]:
    refs: list[str] = []
    for binding in _as_dicts(doc.get("bindings")):
        spec_id = str(binding.get("spec_id", ""))
        for rule in _as_dicts(binding.get("rules")):
            for stage, status in (rule.get("stage_status") or {}).items():
                if isinstance(status, Mapping) and status.get("status") == "stale":
                    refs.append(f"{spec_id}#{rule.get('ref')}.{stage}")
    return refs


# --- .acceptance-manifest.json ----------------------------------------------


def _normalized_check_field(field: str, value: object) -> object:
    if field == "timeout":
        return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else value
    if field == "inputs":
        return sorted(str(item) for item in value) if isinstance(value, list) else value
    if field == "preflight":
        return sorted(str(item) for item in value) if isinstance(value, list) else value
    if field == "command":
        return [str(item) for item in value] if isinstance(value, list) else value
    return value


def _check_identity(check: Mapping[str, object]) -> dict[str, object]:
    defaults = {
        "command": [], "cwd": ".", "timeout": 60, "env": "none",
        "env_scope": "shared", "preflight": [], "parallel_safe": False,
        "profile": "changed", "inputs": [],
    }
    return {
        field: _normalized_check_field(field, check.get(field, defaults[field]))
        for field in _CHECK_IDENTITY_FIELDS
    }


def _check_conflict(check_id: str, main: Mapping[str, object],
                    branch: Mapping[str, object]) -> Optional[dict[str, object]]:
    main_identity = _check_identity(main)
    branch_identity = _check_identity(branch)
    fields = [
        field for field in _CHECK_IDENTITY_FIELDS
        if main_identity.get(field) != branch_identity.get(field)
    ]
    if not fields:
        return None
    return {
        "check_id": check_id,
        "fields": fields,
        "main": {field: main_identity.get(field) for field in fields},
        "branch": {field: branch_identity.get(field) for field in fields},
    }


def _check_conflicts(main: object, branch: object) -> list[dict[str, object]]:
    main_by = _keyed(_as_dicts(main), "id")
    branch_by = _keyed(_as_dicts(branch), "id")
    conflicts: list[dict[str, object]] = []
    for check_id in sorted(set(main_by) & set(branch_by)):
        conflict = _check_conflict(check_id, main_by[check_id], branch_by[check_id])
        if conflict is not None:
            conflicts.append(conflict)
    # A check id can change when config changes; the same command identity must
    # still not silently take two different environments.
    main_cmd = {
        (tuple(item.get("command") or []), str(item.get("cwd", ".")), float(item.get("timeout", 60))): item
        for item in _as_dicts(main)
    }
    for item in _as_dicts(branch):
        key = (tuple(item.get("command") or []), str(item.get("cwd", ".")), float(item.get("timeout", 60)))
        other = main_cmd.get(key)
        if other is None or str(other.get("id")) == str(item.get("id")):
            continue
        conflict = _check_conflict(str(other.get("id", "")), other, item)
        if conflict is not None:
            conflicts.append(conflict)
    return conflicts


def _merge_checks(main: object, branch: object) -> list[dict]:
    main_rows = _as_dicts(main)
    branch_by = _keyed(_as_dicts(branch), "id")
    merged: list[dict] = []
    seen: set = set()
    conflicts: list[dict[str, object]] = []
    for row in main_rows:
        check_id = row.get("id")
        seen.add(check_id)
        other = branch_by.get(check_id) if isinstance(check_id, str) else None
        if other is not None:
            conflict = _check_conflict(str(check_id), row, other)
            if conflict is not None:
                conflicts.append(conflict)
            merged.append({**other, **row})
        else:
            merged.append(row)
    for row in _as_dicts(branch):
        if row.get("id") not in seen:
            merged.append(row)
    if conflicts:
        detail = ", ".join(
            f"{item['check_id']}({','.join(str(field) for field in item['fields'])})"
            for item in conflicts
        )
        raise MergeConflictError(
            "check_conflict",
            f"acceptance manifest check 冲突（同 ID 字段不一致）: {detail}",
            conflicts,
        )
    return merged


def _scenario_conflicts(main: object, branch: object) -> list[dict[str, object]]:
    main_by = _keyed(_as_dicts(main), "id")
    branch_by = _keyed(_as_dicts(branch), "id")
    conflicts: list[dict[str, object]] = []
    for scenario_id in sorted(set(main_by) & set(branch_by)):
        main_check = main_by[scenario_id].get("check")
        branch_check = branch_by[scenario_id].get("check")
        if (
            isinstance(main_check, str) and main_check
            and isinstance(branch_check, str) and branch_check
            and main_check != branch_check
        ):
            conflicts.append({
                "scenario_id": scenario_id,
                "fields": ["check"],
                "main": main_check,
                "branch": branch_check,
            })
    return conflicts


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
    if not merged.get("check"):
        merged["check"] = main.get("check") or branch.get("check")
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


def _merged_schema(main: Mapping[str, object], branch: Mapping[str, object]) -> object:
    schema = main.get("schema")
    other = branch.get("schema")
    if isinstance(schema, int) and isinstance(other, int):
        return max(schema, other)
    return schema


def merge_manifest_docs(main: Mapping[str, object], branch: Mapping[str, object]) -> dict:
    merged_checks = _merge_checks(main.get("checks"), branch.get("checks")) if ("checks" in main or "checks" in branch) else None
    conflicts = _scenario_conflicts(main.get("scenarios"), branch.get("scenarios"))
    if conflicts:
        detail = ", ".join(
            f"{item['scenario_id']}({item['main']}->{item['branch']})" for item in conflicts
        )
        raise MergeConflictError(
            "scenario_check_conflict",
            f"scenario→check 映射冲突: {detail}",
            conflicts,
        )
    merged = dict(main)
    if "schema" in main or "schema" in branch:
        merged["schema"] = _merged_schema(main, branch)
    if "checks" in main or "checks" in branch:
        merged["checks"] = _merge_checks(main.get("checks"), branch.get("checks"))
    merged["scenarios"] = _merge_scenarios(main.get("scenarios"), branch.get("scenarios"))
    return merged


def merge_manifest_text(main_text: str, branch_text: str) -> str:
    main_doc = json.loads(main_text)
    branch_doc = json.loads(branch_text)
    if not isinstance(main_doc, dict) or not isinstance(branch_doc, dict):
        raise ValueError("acceptance manifest must be an object on both sides")
    merged = merge_manifest_docs(main_doc, branch_doc)
    return json.dumps(merged, ensure_ascii=False, indent=2) + "\n"
