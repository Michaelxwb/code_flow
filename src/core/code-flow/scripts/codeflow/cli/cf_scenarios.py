#!/usr/bin/env python3
"""Canonical acceptance scenario source (`<requirement>.scenarios.md`).

Scenarios are user journeys, not frontend/backend design sections. This module
parses the single source, validates it, merges multi-design references by
global ID, and derives scenario state from executable checks.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import IO, Mapping, Optional, Sequence

import yaml

from codeflow.core.cf_markdown import frontmatter_block


SCHEMA_VERSION = 1
SCENARIO_ID = re.compile(r"^[SEB]-\d+$")
PRIORITIES = ("P0", "P1", "P2")
LEVELS = ("unit", "component", "contract", "integration", "system", "capacity", "e2e", "manual")
EXEC_MODES = ("auto", "deferred", "manual", "aspirational")
E2E_CRITICAL_PRIORITIES = ("P0", "P1")
E2E_RATIO_WARNING = 0.3
_PLACEHOLDERS = frozenset(("", "-", "n/a", "na", "none", "无", "todo", "tbd", "待定"))


class ScenarioError(ValueError):
    """Stable parse/merge failure with a machine-readable code."""

    def __init__(self, code: str, message: str, details: Optional[Mapping[str, object]] = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = dict(details) if details else {}


def _frontmatter_text(text: str) -> str:
    """YAML body for `yaml.safe_load`; unclosed delimiters fail closed."""
    block = frontmatter_block(text)
    if block is not None:
        return block
    if text.startswith("---"):
        raise ScenarioError("scenario_source_invalid_frontmatter", "frontmatter 缺少闭合 ---")
    return text


def _mapping(value: object, field: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ScenarioError("invalid_scenario_source", f"{field} 必须是 mapping")
    return value


def _string_list(value: object, field: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ScenarioError("invalid_scenario_source", f"{field} 必须是字符串列表")
    return tuple(item.strip() for item in value if item.strip())


def _boolean(value: object, field: str, default: bool = False) -> bool:
    if value is None:
        return default
    if not isinstance(value, bool):
        raise ScenarioError("invalid_scenario_source", f"{field} 必须是布尔值")
    return value


def _meaningful(value: object) -> bool:
    return str(value or "").strip().lower() not in _PLACEHOLDERS


def _validate_one(item: Mapping[str, object]) -> dict[str, object]:
    scenario_id = item.get("id")
    if not isinstance(scenario_id, str) or not SCENARIO_ID.fullmatch(scenario_id):
        raise ScenarioError("invalid_scenario_id", f"非法场景 ID: {scenario_id!r}")
    priority = str(item.get("priority", "P1")).upper()
    if priority not in PRIORITIES:
        raise ScenarioError("invalid_priority", f"{scenario_id}: priority 非法: {priority!r}")
    level = str(item.get("level", "integration")).lower()
    if level not in LEVELS:
        raise ScenarioError("invalid_level", f"{scenario_id}: level 非法: {level!r}")
    exec_mode = str(item.get("exec", "auto")).lower()
    if exec_mode not in EXEC_MODES:
        raise ScenarioError("invalid_exec", f"{scenario_id}: exec 非法: {exec_mode!r}")
    try:
        from codeflow.acceptance.cf_scenario_quality import validate_extensions
        extra = validate_extensions(item)
    except ValueError as exc:
        raise ScenarioError("invalid_scenario_contract", f"{scenario_id}: {exc}") from exc
    return {
        **extra,
        "id": scenario_id,
        "title": str(item.get("title", "")).strip(),
        "priority": priority,
        "level": level,
        "exec": exec_mode,
        "env": extra["env"],
        "components": list(_string_list(item.get("components"), f"{scenario_id}.components")),
        "boundary": str(item.get("boundary", "")).strip(),
        "preconditions": list(_string_list(item.get("preconditions"), f"{scenario_id}.preconditions")),
        "steps": list(_string_list(item.get("steps"), f"{scenario_id}.steps")),
        "expected": list(_string_list(item.get("expected"), f"{scenario_id}.expected")),
        "design_refs": list(_string_list(item.get("design_refs"), f"{scenario_id}.design_refs")),
        "rules": list(_string_list(item.get("rules"), f"{scenario_id}.rules")),
        "checks": list(_string_list(item.get("checks"), f"{scenario_id}.checks")),
        "sources": list(_string_list(item.get("sources"), f"{scenario_id}.sources")),
        "why_e2e": str(item.get("why_e2e", "")).strip(),
        "trigger_paths": list(_string_list(item.get("trigger_paths"), f"{scenario_id}.trigger_paths")),
        "smoke": _boolean(item.get("smoke"), f"{scenario_id}.smoke"),
    }


def parse_scenarios(path: object, *, text: Optional[str] = None) -> dict[str, object]:
    """Parse and validate one scenarios source file."""
    target = Path(path)
    try:
        raw = target.read_text(encoding="utf-8") if text is None else text
    except (OSError, UnicodeError) as exc:
        raise ScenarioError("scenario_source_unreadable", str(exc), {"path": str(target)}) from exc
    try:
        data = yaml.safe_load(_frontmatter_text(raw))
    except yaml.YAMLError as exc:
        raise ScenarioError("scenario_source_invalid_yaml", str(exc), {"path": str(target)}) from exc
    document = _mapping(data, "scenarios")
    schema = document.get("schema")
    if isinstance(schema, bool) or schema not in (None, SCHEMA_VERSION):
        raise ScenarioError("unsupported_scenario_schema", str(document.get("schema")))
    raw = document.get("scenarios")
    if not isinstance(raw, list) or not raw:
        raise ScenarioError("scenarios_missing", "scenarios 必须是非空列表")
    seen: set[str] = set()
    scenarios: list[dict[str, object]] = []
    for item in raw:
        scenario = _validate_one(_mapping(item, "scenarios[]"))
        if scenario["id"] in seen:
            raise ScenarioError("duplicate_scenario_id", str(scenario["id"]))
        seen.add(scenario["id"])
        scenarios.append(scenario)
    return {
        "schema": SCHEMA_VERSION,
        "requirement": str(document.get("requirement", target.parent.name)),
        "source": str(target),
        "scenarios": scenarios,
    }


def _definition(scenario: Mapping[str, object]) -> dict[str, object]:
    fields = ("title", "priority", "level", "exec", "env", "components", "boundary",
              "preconditions", "steps", "expected", "rules", "why_e2e", "trigger_paths", "smoke")
    from codeflow.acceptance.cf_scenario_quality import EXTRA_FIELDS
    return {field: scenario.get(field) for field in (*fields, *EXTRA_FIELDS)}


def merge_scenarios(sets: Sequence[Mapping[str, object]]) -> list[dict[str, object]]:
    """Union scenario sets by global ID; reject conflicting definitions."""
    merged: dict[str, dict[str, object]] = {}
    for source in sets:
        for raw in source.get("scenarios", []) or []:
            scenario = _validate_one(_mapping(raw, "scenarios[]"))
            current = merged.get(str(scenario["id"]))
            if current is None:
                merged[str(scenario["id"])] = scenario
                continue
            if _definition(current) != _definition(scenario):
                fields = [key for key in _definition(current) if _definition(current)[key] != _definition(scenario)[key]]
                raise ScenarioError(
                    "design_scenario_conflict",
                    f"{scenario['id']} 定义冲突: {', '.join(fields)}",
                    {"scenario": scenario["id"], "fields": fields},
                )
            current["sources"] = sorted(set(current.get("sources", [])) | set(scenario.get("sources", [])))
            current["design_refs"] = sorted(set(current.get("design_refs", [])) | set(scenario.get("design_refs", [])))
            current["checks"] = sorted(set(current.get("checks", [])) | set(scenario.get("checks", [])))
    return [merged[key] for key in sorted(merged)]


def _quality_issue(code: str, scenario: str, field: str, message: str) -> dict[str, object]:
    return {"code": code, "scenario": scenario, "field": field, "message": message}


def validate_e2e_quality(scenarios: Sequence[Mapping[str, object]]) -> dict[str, object]:
    """Validate semantic acceptance contracts through one shared quality gate."""
    from codeflow.acceptance.cf_scenario_quality import quality_report
    return quality_report(scenarios)


def scenario_status(scenario: Mapping[str, object], checks: Mapping[str, str]) -> str:
    """Derive scenario state from all required checks (AND semantics)."""
    required = [str(item) for item in scenario.get("checks", [])]
    if not required:
        return "aspirational" if scenario.get("exec") == "aspirational" else "designed"
    states = [checks.get(check_id, "designed") for check_id in required]
    for bad in ("failed", "env_blocked", "incomplete"):
        if bad in states:
            return bad
    if all(state in ("passed", "verified") for state in states):
        return "verified"
    return "designed"


def main(argv: Optional[Sequence[str]] = None, stdout: IO[str] = sys.stdout) -> int:
    parser = argparse.ArgumentParser(prog=os.environ.get("CF_RUNTIME_COMMAND") or None)
    sub = parser.add_subparsers(dest="action", required=True)
    for name in ("parse", "merge"):
        command = sub.add_parser(name)
        command.add_argument("--file", action="append", required=True)
        command.add_argument("--quality", action="store_true",
                             help="run the E2E precision gate against the scenario source")
        command.add_argument("--json", action="store_true")
    migrate = sub.add_parser("migrate")
    migrate.add_argument("--task-file", required=True)
    migrate.add_argument("--output", default="")
    migrate.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.action == "migrate":
            from codeflow.cli.cf_acceptance_manifest import extract_manifest
            coverage = extract_manifest(args.task_file)["scenarios"]
            result = migrate_from_coverage(coverage)
            if args.output:
                text = "---\n" + yaml.safe_dump(result, sort_keys=False, allow_unicode=True) + "---\n"
                Path(args.output).write_text(text, encoding="utf-8")
            stdout.write(json.dumps(result, ensure_ascii=False))
            return 0
        sets = [parse_scenarios(path) for path in args.file]
        if args.action == "parse" and len(sets) > 1:
            raise ScenarioError("invalid_action", "parse 只接受一个文件；多文件用 merge")
        result = sets[0] if args.action == "parse" else {"schema": SCHEMA_VERSION, "scenarios": merge_scenarios(sets)}
        if args.quality:
            quality = validate_e2e_quality(result["scenarios"])
            result = {**result, "ok": quality["ok"], "quality": quality}
        stdout.write(json.dumps(result, ensure_ascii=False))
        return 0 if not args.quality or bool(result.get("ok")) else 3
    except ScenarioError as exc:
        stdout.write(json.dumps({"ok": False, "code": exc.code, "message": exc.message, "details": exc.details}, ensure_ascii=False))
        return 3




def require_source(task_dir: object) -> Path:
    """Return the single scenarios source for a requirement directory."""
    directory = Path(task_dir)
    matches = sorted(directory.glob("*.scenarios.md")) if directory.is_dir() else []
    if not matches:
        raise ScenarioError("scenario_source_missing", f"缺少 <需求>.scenarios.md: {directory}")
    if len(matches) > 1:
        raise ScenarioError("scenario_source_ambiguous", f"多个场景源: {', '.join(path.name for path in matches)}")
    return matches[0]


def reconcile_coverage(scenarios: Sequence[Mapping[str, object]],
                       coverage: Sequence[Mapping[str, object]]) -> dict[str, object]:
    """Reconcile canonical scenarios with Acceptance Coverage rows."""
    by_scenario = {str(item.get("id")): item for item in scenarios}
    owners: dict[str, list[str]] = {}
    unknown: list[str] = []
    for row in coverage:
        scenario_id = row.get("scenario_id") or row.get("id")
        if not isinstance(scenario_id, str) or not scenario_id:
            continue
        if scenario_id not in by_scenario:
            unknown.append(scenario_id)
            continue
        owner = row.get("owner")
        if isinstance(owner, str) and owner.strip():
            owners.setdefault(scenario_id, []).append(owner.strip())
    covered = set(owners) | {str(row.get("scenario_id") or row.get("id")) for row in coverage
                              if isinstance(row.get("scenario_id") or row.get("id"), str)}
    missing = sorted(set(by_scenario) - covered)
    duplicate = sorted(key for key, values in owners.items() if len(set(values)) > 1)
    unowned = sorted(set(by_scenario) - set(owners))
    return {
        "ok": not missing and not unknown and not duplicate and not unowned,
        "missing": missing,
        "unknown": sorted(unknown),
        "duplicate_owner": duplicate,
        "unowned": unowned,
    }


def load_requirement_scenarios(task_dir: object, allow_legacy: bool = False) -> dict[str, object]:
    """Load the requirement source, or an explicit deprecated legacy marker."""
    directory = Path(task_dir)
    try:
        source = require_source(directory)
    except ScenarioError as exc:
        if exc.code != "scenario_source_missing" or not allow_legacy:
            raise
        return {"schema": SCHEMA_VERSION, "requirement": directory.name,
                "source": "", "scenarios": [], "deprecated": True}
    return parse_scenarios(source)


def audit_scenario_source(scenarios: Sequence[Mapping[str, object]],
                          coverage: Sequence[Mapping[str, object]],
                          manifest_ids: Optional[Sequence[str]] = None) -> dict[str, object]:
    """Three-way audit: scenarios, coverage, manifest."""
    report = reconcile_coverage(scenarios, coverage)
    scenario_ids = {str(item.get("id")) for item in scenarios}
    coverage_ids = {str(item.get("scenario_id") or item.get("id")) for item in coverage}
    manifest = {str(item) for item in manifest_ids} if manifest_ids is not None else None
    report["manifest_missing"] = sorted(scenario_ids - manifest) if manifest is not None else []
    report["manifest_unknown"] = sorted(manifest - scenario_ids) if manifest is not None else []
    report["coverage_unknown"] = sorted(coverage_ids - scenario_ids)
    report["ok"] = bool(report["ok"] and not report["coverage_unknown"]
                        and not report["manifest_missing"] and not report["manifest_unknown"])
    return report


def migrate_from_coverage(coverage: Sequence[Mapping[str, object]]) -> dict[str, object]:
    """Build an initial scenarios source from legacy Acceptance Coverage."""
    scenarios: list[dict[str, object]] = []
    invalid: list[str] = []
    for row in coverage:
        scenario_id = str(row.get("scenario_id") or row.get("id") or "")
        if not SCENARIO_ID.fullmatch(scenario_id):
            invalid.append(scenario_id)
            continue
        priority = str(row.get("priority") or "P1").upper()
        level = str(row.get("level") or "integration").lower()
        if priority not in PRIORITIES:
            priority = "P1"
        if level not in LEVELS:
            level = "integration"
        scenarios.append({
            "id": scenario_id,
            "title": str(row.get("title") or scenario_id),
            "priority": priority,
            "level": level,
            "exec": "auto",
            "env": "none",
            "components": [],
            "boundary": str(row.get("boundary") or ""),
            "preconditions": [],
            "steps": [],
            "expected": [],
            "design_refs": [],
            "rules": [],
            "checks": [],
            "sources": ["legacy-coverage"],
        })
    return {"schema": SCHEMA_VERSION, "scenarios": scenarios, "migrated": True, "invalid": invalid}
