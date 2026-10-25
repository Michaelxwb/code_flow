"""Shared semantic checks for canonical scenarios and plan projections."""
from __future__ import annotations

import re
from typing import Mapping, Sequence

ENVIRONMENTS = ("none", "local", "local-api", "browser", "external", "staging", "capacity", "ci", "production")
TARGET_PHASES = ("plan", "code", "review", "ci", "release")
EXTRA_FIELDS = ("expected_refs", "assertions", "defer_reason", "owner", "target_phase", "features", "tags")
_PLACEHOLDERS = frozenset(("", "-", "n/a", "na", "none", "无", "todo", "tbd", "待定"))
_VAGUE = re.compile(r"可观|不回归|表现良好|符合预期|适当提升|as expected|significant improvement", re.I)


def meaningful(value: object) -> bool:
    return str(value or "").strip().lower() not in _PLACEHOLDERS


def issue(code: str, row: Mapping[str, object], field: str, message: str) -> dict[str, object]:
    return {"code": code, "scenario": str(row.get("id", "")), "field": field, "message": message}


def validate_extensions(row: Mapping[str, object]) -> dict[str, object]:
    env = str(row.get("env", "none")).lower()
    if env not in ENVIRONMENTS:
        raise ValueError(f"env 非法: {env!r}; allowed: {', '.join(ENVIRONMENTS)}")
    result: dict[str, object] = {"env": env}
    for field in ("features", "tags", "assertions"):
        values = row.get(field, [])
        if not isinstance(values, list) or not all(isinstance(value, str) and value.strip() for value in values):
            raise ValueError(f"{field} 必须是非空字符串列表")
        result[field] = list(values)
    for component in row.get("components", []) or []:
        if not isinstance(component, str) or not re.fullmatch(r"[a-zA-Z][a-zA-Z0-9_.:-]*", component):
            raise ValueError("components 必须使用稳定标识符，不能使用自由描述文本")
    refs = row.get("expected_refs", [])
    if not isinstance(refs, list) or not all(isinstance(value, Mapping) for value in refs):
        raise ValueError("expected_refs 必须是映射列表")
    result["expected_refs"] = [dict(value) for value in refs]
    for field in ("defer_reason", "owner", "target_phase"):
        value = row.get(field, "")
        if not isinstance(value, str):
            raise ValueError(f"{field} 必须是字符串")
        result[field] = value.strip()
    if result["target_phase"] and result["target_phase"] not in TARGET_PHASES:
        raise ValueError("target_phase 非法")
    return result


def browser_boundary(row: Mapping[str, object]) -> bool:
    components = {str(value).lower() for value in row.get("components", []) or []}
    return str(row.get("env", "")).lower() == "browser" or bool(components & {"frontend", "browser"})


def _expected_links(row: Mapping[str, object], index: int) -> bool:
    steps = row.get("steps", []) or []
    for link in row.get("expected_refs", []) or []:
        if not isinstance(link, Mapping) or type(link.get("expected")) is not int or link["expected"] != index:
            continue
        linked_steps = link.get("steps", [])
        assertions = link.get("assertions", [])
        if not isinstance(linked_steps, list) or not isinstance(assertions, list):
            continue
        valid_steps = linked_steps and all(type(value) is int and 1 <= value <= len(steps) for value in linked_steps)
        declared = row.get("assertions", [])
        valid_assertions = assertions and all(isinstance(value, str) and meaningful(value) and value in declared
                                              for value in assertions)
        if (valid_steps or valid_assertions) and (not linked_steps or valid_steps):
            return True
    return False


def expectation_issues(row: Mapping[str, object]) -> list[dict[str, object]]:
    errors: list[dict[str, object]] = []
    for index, expected in enumerate(row.get("expected", []) or [], 1):
        text = str(expected).strip()
        if not meaningful(text) or _VAGUE.search(text):
            errors.append(issue("scenario_expected_nondeterministic", row, "expected",
                                f"expected[{index}] 需要具体可观察结果或量化阈值"))
        if re.search(r"^(若|如果|if\b)", text, re.I) and not row.get("preconditions"):
            errors.append(issue("scenario_expected_nondeterministic", row, "preconditions",
                                "条件式预期必须声明可构造的前置条件"))
        if not _expected_links(row, index):
            errors.append(issue("scenario_expected_reference_missing", row, "expected_refs",
                                f"expected[{index}] 必须引用存在的步骤或稳定断言 ID"))
    return errors


def deferred_issues(row: Mapping[str, object]) -> list[dict[str, object]]:
    if row.get("exec") != "deferred":
        return []
    missing = [field for field in ("defer_reason", "owner", "target_phase") if not meaningful(row.get(field))]
    return [issue("scenario_defer_metadata_missing", row, "exec", "延后信息缺少: " + ", ".join(missing))] if missing else []


def e2e_issues(row: Mapping[str, object]) -> list[dict[str, object]]:
    errors: list[dict[str, object]] = []
    requirements = (("why_e2e", "e2e_justification_missing"), ("boundary", "e2e_boundary_missing"))
    for field, code in requirements:
        if not meaningful(row.get(field)):
            errors.append(issue(code, row, field, "E2E 必须声明真实边界和低层测试不足的理由"))
    for field in ("steps", "expected"):
        if not any(meaningful(value) for value in row.get(field, []) or []):
            errors.append(issue(f"e2e_{field}_missing", row, field, "E2E 必须声明可复现步骤及可观察结果"))
    if str(row.get("priority", "")).upper() not in ("P0", "P1"):
        errors.append(issue("e2e_priority_not_critical", row, "priority", "E2E 只允许 P0/P1"))
    if not browser_boundary(row):
        errors.append(issue("e2e_browser_boundary_missing", row, "components",
                            "浏览器 E2E 必须声明 browser/frontend；API/CLI 全链路使用 system/integration"))
    if browser_boundary(row) and not re.search(r"browser|frontend|浏览器|前端|\bUI\b", str(row.get("boundary", "")), re.I):
        errors.append(issue("scenario_boundary_components_mismatch", row, "boundary",
                            "声明的浏览器组件必须出现在真实边界中"))
    if row.get("exec") == "aspirational":
        errors.append(issue("e2e_aspirational", row, "exec", "aspirational 不能作为 E2E 验收"))
    paths = row.get("trigger_paths", []) or []
    if not row.get("smoke") and not paths:
        errors.append(issue("e2e_trigger_paths_missing", row, "trigger_paths", "非 smoke E2E 必须声明触发路径"))
    if any(not meaningful(value) for value in paths):
        errors.append(issue("e2e_trigger_path_placeholder", row, "trigger_paths", "触发路径不能使用占位值"))
    return errors


def quality_report(scenarios: Sequence[Mapping[str, object]]) -> dict[str, object]:
    errors: list[dict[str, object]] = []
    warnings: list[dict[str, object]] = []
    e2e = [row for row in scenarios if str(row.get("level", "")).lower() == "e2e"]
    signatures: dict[str, str] = {}
    for row in scenarios:
        errors.extend(expectation_issues(row))
        errors.extend(deferred_issues(row))
        if row in e2e:
            errors.extend(e2e_issues(row))
            signature = repr((row.get("steps"), row.get("expected"), row.get("boundary")))
            if signature in signatures:
                warnings.append(issue("duplicate_e2e_journey", row, "steps", f"与 {signatures[signature]} 重复"))
            signatures[signature] = str(row.get("id"))
        elif meaningful(row.get("why_e2e")):
            errors.append(issue("why_e2e_on_non_e2e", row, "why_e2e", "why_e2e 只属于浏览器 E2E"))
    ratio = len(e2e) / len(scenarios) if scenarios else 0.0
    smoke = sum(bool(row.get("smoke")) for row in e2e)
    if ratio > 0.3:
        warnings.append(issue("e2e_ratio_high", {}, "level", f"E2E 占比 {ratio:.0%}；优先下沉低层"))
    if e2e and not smoke:
        warnings.append(issue("e2e_smoke_missing", {}, "smoke", "没有声明 smoke E2E"))
    return {"ok": not errors, "errors": errors, "warnings": warnings, "total": len(scenarios),
            "e2e_count": len(e2e), "e2e_browser_count": sum(browser_boundary(row) for row in e2e),
            "system_count": sum(row.get("level") == "system" for row in scenarios),
            "capacity_count": sum(row.get("level") == "capacity" or "capacity" in row.get("tags", []) for row in scenarios),
            "smoke_count": smoke, "e2e_ratio": round(ratio, 4),
            "runnable_smoke_count": None, "verified_browser_count": None, "registration_status": "not_checked"}
