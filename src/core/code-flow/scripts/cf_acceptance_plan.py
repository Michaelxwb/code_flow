"""E2E precision and scope for a TASK start.

Plan locks E2E quality fields; Start must turn them into a concrete execution
scope. A TASK writes tests only for its owned E2E scenarios and runs its owned
scenarios plus the global smoke set. Unrelated E2E journeys stay deferred
instead of turning every small change into a full-suite run.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Mapping

from cf_acceptance_schema import load_manifest, scenario_check_ids, validate_execution_baseline

_PLACEHOLDERS = frozenset(("", "-", "n/a", "na", "none", "无", "todo", "tbd", "待定"))


def _meaningful(value: object) -> bool:
    return str(value or "").strip().lower() not in _PLACEHOLDERS


def _task_scenario_ids(task_file: str, task_id: str) -> set[str]:
    text = Path(task_file).read_text(encoding="utf-8")
    section = re.search(
        rf"(?ms)^##\s+{re.escape(task_id)}:.*?(?=^##\s+TASK-|\Z)", text
    )
    if section is None:
        raise ValueError(f"task_not_found: {task_id}")
    refs = re.search(
        r"(?m)^- \*\*Acceptance-Refs\*\*:[ \t]*([^\n]*)", section.group(0)
    )
    if refs is None:
        return set()
    return set(re.findall(r"\b(?:S|E|B)-\d+\b", refs.group(1)))


def _item(row: Mapping[str, object]) -> dict[str, object]:
    return {
        **{field: row[field] for field in ("level", "env", "components", "steps", "expected", "expected_refs", "assertions",
                                          "preconditions", "defer_reason", "defer_owner", "target_phase", "features", "tags")
           if field in row},
        "id": str(row.get("id", "")),
        "title": str(row.get("title", "")),
        "owner": row.get("owner") if isinstance(row.get("owner"), str) else "",
        "priority": row.get("priority") if isinstance(row.get("priority"), str) else "",
        "exec": row.get("exec") if isinstance(row.get("exec"), str) else "",
        "boundary": str(row.get("boundary", "")),
        "why_e2e": str(row.get("why_e2e", "")),
        "trigger_paths": list(row.get("trigger_paths") or []),
        "smoke": bool(row.get("smoke")),
        "check": row.get("check") if isinstance(row.get("check"), str) else "",
        "checks": scenario_check_ids(row),
        "command": list(row.get("command") or []) if isinstance(row.get("command"), list) else [],
    }


def _quality_errors(items: list[dict[str, object]]) -> list[dict[str, object]]:
    errors: list[dict[str, object]] = []
    for item in items:
        scenario_id = str(item.get("id", ""))
        priority = str(item.get("priority", "")).upper()
        if priority not in ("P0", "P1"):
            errors.append({
                "code": "e2e_priority_not_critical",
                "scenario": scenario_id,
                "message": "E2E 只允许 P0/P1 关键旅程；请改为 component/contract/integration。",
            })
        if not _meaningful(item.get("why_e2e")):
            errors.append({
                "code": "e2e_justification_missing",
                "scenario": scenario_id,
                "message": "E2E 必须说明为什么低层测试无法覆盖。",
            })
        if not _meaningful(item.get("boundary")):
            errors.append({
                "code": "e2e_boundary_missing",
                "scenario": scenario_id,
                "message": "E2E 必须声明真实边界。",
            })
        if str(item.get("exec", "")).lower() == "aspirational":
            errors.append({
                "code": "e2e_aspirational",
                "scenario": scenario_id,
                "message": "aspirational E2E 不能进入 TASK 执行范围。",
            })
        trigger_paths = [
            str(path) for path in item.get("trigger_paths", []) or [] if _meaningful(path)
        ]
        if not item.get("smoke") and not trigger_paths:
            errors.append({
                "code": "e2e_trigger_paths_missing",
                "scenario": scenario_id,
                "message": "非 smoke E2E 必须声明触发路径，避免小改动跑全量。",
            })
    return errors


def _group_scenarios(data: Mapping[str, object], owned_ids: set[str], task_id: str
                     ) -> tuple[list[dict[str, object]], list[dict[str, object]], list[dict[str, object]]]:
    owned: list[dict[str, object]] = []
    smoke: list[dict[str, object]] = []
    deferred: list[dict[str, object]] = []
    for row in data.get("scenarios", []) or []:
        if not isinstance(row, Mapping):
            continue
        kind = str(row.get("kind") or row.get("level") or "").lower()
        if kind != "e2e":
            continue
        item = _item(row)
        scenario_id = str(item["id"])
        scenario_owner = str(item.get("owner") or "")
        if scenario_id in owned_ids and (not scenario_owner or scenario_owner == task_id):
            owned.append(item)
        elif item["smoke"]:
            smoke.append(item)
        else:
            deferred.append(item)
    return owned, smoke, deferred


def _scoped_quality(data: Mapping[str, object], scheduled: list[dict[str, object]], root: Path
                    ) -> tuple[list[dict[str, object]], list[dict[str, object]], bool]:
    errors = _quality_errors(scheduled)
    if data.get("scenarios_file"):
        from cf_scenario_quality import quality_report
        strict = [{**item, "level": "e2e", "owner": item.get("defer_owner") or item.get("owner", "")}
                  for item in scheduled]
        errors = quality_report(strict)["errors"]
        from cf_check_registration import validate_registration
        errors.extend(validate_registration(str(root), scheduled, data.get("checks", []))["errors"])
    warnings: list[dict[str, object]] = []
    gate_required = data.get("e2e_gate") in (1, True, "required")
    if errors and not gate_required:
        # Existing projects upgraded mid-flight remain startable, but every
        # legacy E2E is surfaced for re-planning instead of being silently
        # treated as a scoped critical journey.
        warnings.extend({**item, "code": f"legacy_{item['code']}"} for item in errors)
        warnings.append({
            "code": "legacy_e2e_plan",
            "message": "旧 manifest 未声明 why_e2e/trigger_paths；先用 plan --verify-plan 重新锁定。",
        })
        errors = []
    return errors, warnings, gate_required


def build_e2e_plan(
    manifest_file: str,
    task_file: str,
    task_id: str,
    validate_baseline: bool = True,
) -> dict[str, object]:
    path = Path(manifest_file)
    owned_ids = _task_scenario_ids(task_file, task_id)
    if not path.is_file():
        return {
            "task": task_id,
            "manifest": str(path),
            "owned": [],
            "smoke": [],
            "scheduled": [],
            "deferred_count": 0,
            "deferred_ids": [],
            "quality": {"ok": True, "errors": [], "warnings": [], "gate": "none"},
        }
    data = load_manifest(path)
    if validate_baseline:
        validate_execution_baseline(path, data)
    owned, smoke, deferred = _group_scenarios(data, owned_ids, task_id)
    scheduled = [*owned, *[item for item in smoke if item["id"] not in owned_ids]]
    root = next((parent.parent for parent in path.parents if parent.name == ".code-flow"), path.parent)
    errors, warnings, gate_required = _scoped_quality(data, scheduled, root)
    if not owned and not smoke:
        warnings.append({
            "code": "no_scheduled_e2e",
            "message": "本 TASK 没有需要编写或执行的 E2E；不要把其他场景补进来。",
        })
    return {
        "task": task_id,
        "manifest": str(path),
        "owned": owned,
        "smoke": smoke,
        "scheduled": scheduled,
        "deferred_count": len(deferred),
        "deferred_ids": [str(item["id"]) for item in deferred],
        "quality": {
            "ok": not errors,
            "errors": errors,
            "warnings": warnings,
            "gate": "required" if gate_required else "legacy",
        },
    }
