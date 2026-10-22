#!/usr/bin/env python3
"""Generate the requirement traceability matrix from design §2.5 + manifest.

The matrix is a derived view, never hand-edited: every design scenario is joined
with its manifest scenario/check so priority, exec mode, env, inputs, command,
owner and status all come from data. A scenario without a check is only allowed
when it is explicitly marked ``aspirational``.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
from pathlib import Path
import re
import sys
from typing import IO, Mapping, Optional, Sequence

from cf_acceptance_schema import EXEC_MODES, load_manifest


_SCENARIO_ID_RE = re.compile(r"^[SEB]-\d+$")
_SEPARATOR_RE = re.compile(r"^:?-{2,}:?$")


@dataclass(frozen=True)
class DesignScenario:
    """One scenario declared in design §2.5, independent of the manifest."""

    id: str
    feature: str
    priority: str
    level: str
    boundary: str
    exec: str
    env: str
    inputs: str


def _acceptance_section(text: str) -> str:
    match = re.search(r"(?m)^(#{2,4})\s+2\.5(?:\s+[^\n]*)?$", text)
    if match is None:
        raise ValueError("design §2.5 验收条件缺失")
    level = len(match.group(1))
    tail = text[match.end():]
    end = re.search(rf"(?m)^#{{1,{level}}}\s+", tail)
    return tail[:end.start()] if end else tail


def _table_blocks(text: str) -> list[tuple[list[str], list[list[str]]]]:
    blocks: list[tuple[list[str], list[list[str]]]] = []
    header: Optional[list[str]] = None
    rows: list[list[str]] = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("|"):
            cells = [item.strip() for item in stripped.strip("|").split("|")]
            if all(_SEPARATOR_RE.match(cell.replace(" ", "")) for cell in cells):
                continue
            if header is None:
                header = cells
            else:
                rows.append(cells)
            continue
        if header is not None:
            blocks.append((header, rows))
            header, rows = None, []
    if header is not None:
        blocks.append((header, rows))
    return blocks


def _column(header: Sequence[str], *names: str) -> int:
    for name in names:
        for index, cell in enumerate(header):
            if name.lower() in cell.lower():
                return index
    return -1


def _cell(row: Sequence[str], index: int) -> str:
    return row[index].strip() if 0 <= index < len(row) else ""


def _design_exec(value: str, scenario_id: str) -> str:
    text = value.strip().strip("`")
    if not text or text in {"-", "N/A"}:
        return ""
    normalized = text.lower()
    if normalized not in EXEC_MODES:
        raise ValueError(f"{scenario_id} 执行方式非法: {value}（允许 {', '.join(EXEC_MODES)}）")
    return normalized


def parse_design_scenarios(design_file: str) -> tuple[DesignScenario, ...]:
    """Parse all S-/E-/B- rows under design §2.5 tables."""
    try:
        text = Path(design_file).read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise ValueError(f"design_read_error: {exc}") from exc
    section = _acceptance_section(text)
    scenarios: dict[str, DesignScenario] = {}
    for header, rows in _table_blocks(section):
        id_index = _column(header, "场景id", "场景编号")
        level_index = _column(header, "测试层级")
        if id_index == -1 or level_index == -1:
            continue
        feature_index = _column(header, "功能id", "feature")
        priority_index = _column(header, "优先级", "priority")
        boundary_index = _column(header, "关键真实边界", "真实边界")
        exec_index = _column(header, "执行方式", "exec")
        env_index = _column(header, "环境", "env")
        inputs_index = _column(header, "输入", "inputs")
        for row in rows:
            scenario_id = _cell(row, id_index)
            if not _SCENARIO_ID_RE.match(scenario_id):
                continue
            if scenario_id in scenarios:
                raise ValueError(f"duplicate design scenario id: {scenario_id}")
            scenarios[scenario_id] = DesignScenario(
                id=scenario_id,
                feature=_cell(row, feature_index),
                priority=_cell(row, priority_index).upper(),
                level=_cell(row, level_index),
                boundary=_cell(row, boundary_index),
                exec=_design_exec(_cell(row, exec_index), scenario_id),
                env=_cell(row, env_index),
                inputs=_cell(row, inputs_index),
            )
    if not scenarios:
        raise ValueError("design §2.5 未找到 S-/E-/B- 场景")
    return tuple(scenarios.values())


def _load_manifest(manifest_file: str) -> tuple[Mapping[str, object], dict[str, Mapping[str, object]],
                                                dict[str, Mapping[str, object]]]:
    try:
        data = load_manifest(Path(manifest_file))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError(f"manifest_read_error: {exc}") from exc
    scenarios = {
        str(item["id"]): item
        for item in data.get("scenarios") or ()
        if isinstance(item, Mapping) and isinstance(item.get("id"), str)
    }
    checks = {
        str(item["id"]): item
        for item in data.get("checks") or ()
        if isinstance(item, Mapping) and isinstance(item.get("id"), str)
    }
    return data, scenarios, checks


def _design_inputs(value: str) -> list[str]:
    text = (value or "").strip()
    if not text or text in {"-", "none", "N/A"}:
        return []
    return [item.strip() for item in re.split(r"[,，、;；]", text) if item.strip()]


def _binding(scenario: Mapping[str, object], check: Optional[Mapping[str, object]],
             design: DesignScenario) -> tuple[str, str, str]:
    check_id = scenario.get("check")
    exec_mode = str(scenario.get("exec") or design.exec or "")
    if isinstance(check_id, str) and check_id and check is not None:
        return "check", check_id, exec_mode or "auto"
    if exec_mode == "aspirational":
        return "aspirational", "-", exec_mode
    return "unbound", "-", exec_mode


def _row(design: DesignScenario, scenario: Optional[Mapping[str, object]],
         check: Optional[Mapping[str, object]]) -> dict[str, object]:
    if scenario is None:
        return {
            "id": design.id,
            "feature": design.feature,
            "priority": design.priority,
            "level": design.level,
            "boundary": design.boundary,
            "exec": design.exec,
            "env": design.env or "none",
            "inputs": _design_inputs(design.inputs),
            "check": "-",
            "command": [],
            "owner": "",
            "status": "missing",
            "binding": "missing",
            "in_design": True,
        }
    binding, check_id, exec_mode = _binding(scenario, check, design)
    command = check.get("command") if check else scenario.get("command")
    inputs = check.get("inputs") if check else scenario.get("inputs") or _design_inputs(design.inputs)
    return {
        "id": design.id,
        "feature": design.feature,
        "priority": str(scenario.get("priority") or design.priority),
        "level": str(scenario.get("level") or design.level),
        "boundary": str(scenario.get("boundary") or design.boundary),
        "exec": exec_mode or ("auto" if binding == "check" else ""),
        "env": str(check.get("env", "none")) if check else str(scenario.get("env") or design.env or "none"),
        "inputs": list(inputs) if isinstance(inputs, list) else _design_inputs(str(inputs or "")),
        "check": check_id,
        "command": list(command) if isinstance(command, list) else [],
        "owner": str(scenario.get("owner") or ""),
        "status": str(scenario.get("status") or ("aspirational" if binding == "aspirational" else "")),
        "binding": binding,
        "in_design": True,
    }


def _extra_rows(manifest_scenarios: Mapping[str, Mapping[str, object]],
                checks: Mapping[str, Mapping[str, object]], design_ids: set[str]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for scenario_id in sorted(set(manifest_scenarios) - design_ids):
        scenario = manifest_scenarios[scenario_id]
        check_id = scenario.get("check")
        check = checks.get(check_id) if isinstance(check_id, str) else None
        exec_mode = str(scenario.get("exec") or "")
        binding = "check" if check is not None else ("aspirational" if exec_mode == "aspirational" else "unbound")
        command = check.get("command") if check else scenario.get("command")
        rows.append({
            "id": scenario_id,
            "feature": "",
            "priority": str(scenario.get("priority") or ""),
            "level": str(scenario.get("level") or ""),
            "boundary": str(scenario.get("boundary") or ""),
            "exec": exec_mode,
            "env": str(check.get("env", "none")) if check else str(scenario.get("env") or "none"),
            "inputs": list(check.get("inputs") or []) if check else list(scenario.get("inputs") or []),
            "check": check_id if isinstance(check_id, str) and check is not None else "-",
            "command": list(command) if isinstance(command, list) else [],
            "owner": str(scenario.get("owner") or ""),
            "status": str(scenario.get("status") or ""),
            "binding": binding,
            "in_design": False,
        })
    return rows


def build_traceability(design_file: str, manifest_file: str) -> dict[str, object]:
    """Join design §2.5 scenarios with manifest checks and report binding gaps."""
    design = parse_design_scenarios(design_file)
    _, manifest_scenarios, checks = _load_manifest(manifest_file)
    design_ids = {item.id for item in design}
    violations: list[dict[str, str]] = []
    rows: list[dict[str, object]] = []
    for item in design:
        scenario = manifest_scenarios.get(item.id)
        check_id = scenario.get("check") if scenario is not None else None
        check = checks.get(check_id) if isinstance(check_id, str) else None
        row = _row(item, scenario, check)
        rows.append(row)
        if scenario is None:
            violations.append({
                "code": "missing_in_manifest",
                "scenario": item.id,
                "message": f"{item.id} 在 design §2.5 中声明，但未进入 manifest；请 plan 覆盖该场景。",
            })
        elif row["binding"] == "unbound":
            violations.append({
                "code": "unbound_scenario",
                "scenario": item.id,
                "message": (
                    f"{item.id} 没有可执行 check，且未显式标为 aspirational；"
                    "请登记执行命令或把执行方式改为 aspirational。"
                ),
            })
    extras = _extra_rows(manifest_scenarios, checks, design_ids)
    for row in extras:
        violations.append({
            "code": "extra_in_manifest",
            "scenario": str(row["id"]),
            "message": f"{row['id']} 存在于 manifest，但 design §2.5 未声明；请回填设计或移除场景。",
        })
        if row["binding"] == "unbound":
            violations.append({
                "code": "unbound_scenario",
                "scenario": str(row["id"]),
                "message": f"{row['id']} 没有可执行 check，且未显式标为 aspirational。",
            })
    all_rows = rows + extras
    summary = {
        "design_scenarios": len(design),
        "manifest_scenarios": len(manifest_scenarios),
        "bound": sum(1 for row in all_rows if row["binding"] == "check"),
        "aspirational": sum(1 for row in all_rows if row["binding"] == "aspirational"),
        "unbound": sum(1 for row in all_rows if row["binding"] == "unbound"),
        "missing": sum(1 for row in all_rows if row["binding"] == "missing"),
    }
    return {
        "decision": "block" if violations else "pass",
        "generated": True,
        "design_file": str(design_file),
        "manifest_file": str(manifest_file),
        "summary": summary,
        "scenarios": all_rows,
        "violations": violations,
    }


def _md(value: object) -> str:
    text = "" if value is None else str(value)
    if not text:
        return "-"
    return text.replace("|", "\\|").replace("\n", " ")


def _md_inputs(value: object) -> str:
    if isinstance(value, list):
        return _md(", ".join(str(item) for item in value))
    return _md(value)


def _md_command(value: object) -> str:
    if isinstance(value, list):
        return _md(json.dumps(value, ensure_ascii=False))
    return _md(value)


def render_markdown(report: Mapping[str, object]) -> str:
    """Render the generated matrix; input is always build_traceability output."""
    summary = report.get("summary") if isinstance(report.get("summary"), Mapping) else {}
    lines = [
        "> 由 `cf_traceability.py` 从 design §2.5 + manifest 生成，不手工维护。",
        ">",
        (
            f"> 场景 {summary.get('design_scenarios', 0)} / 绑定 check {summary.get('bound', 0)}"
            f" / aspirational {summary.get('aspirational', 0)}"
            f" / 未绑定 {summary.get('unbound', 0)} / 缺失 {summary.get('missing', 0)}"
        ),
        "",
        "| 场景ID | 优先级 | 测试层级 | 执行方式 | 环境 | 输入 | 追溯 check | 执行命令 | 负责任务 | 状态 |",
        "|--------|--------|---------|---------|------|------|-----------|---------|---------|------|",
    ]
    for row in report.get("scenarios") or ():
        if not isinstance(row, Mapping):
            continue
        lines.append(
            "| {id} | {priority} | {level} | {exec} | {env} | {inputs} | {check} | {command} | {owner} | {status} |".format(
                id=_md(row.get("id")),
                priority=_md(row.get("priority")),
                level=_md(row.get("level")),
                exec=_md(row.get("exec")),
                env=_md(row.get("env")),
                inputs=_md_inputs(row.get("inputs")),
                check=_md(row.get("check")),
                command=_md_command(row.get("command")),
                owner=_md(row.get("owner")),
                status=_md(row.get("status")),
            )
        )
    if report.get("violations"):
        lines.extend(["", "**阻断项**", ""])
        for violation in report["violations"]:
            if isinstance(violation, Mapping):
                lines.append(f"- `{violation.get('code')}` {violation.get('scenario')}: {violation.get('message')}")
    return "\n".join(lines) + "\n"


def main(argv: Optional[Sequence[str]] = None, stdout: IO[str] = sys.stdout) -> int:
    parser = argparse.ArgumentParser(prog="cf_traceability.py")
    parser.add_argument("--design", required=True)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        report = build_traceability(args.design, args.manifest)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        stdout.write(json.dumps({"decision": "block", "error": str(exc)}, ensure_ascii=False))
        return 2
    if args.json:
        stdout.write(json.dumps(report, ensure_ascii=False))
    else:
        stdout.write(render_markdown(report))
    return 0 if report["decision"] == "pass" else 3


if __name__ == "__main__":
    raise SystemExit(main())


def build_traceability_from_scenarios(scenarios_file: str, manifest_file: str) -> dict[str, object]:
    """Join the scenario source with manifest checks (0.9 source model)."""
    from cf_scenarios import parse_scenarios
    source = parse_scenarios(scenarios_file)
    manifest_scenarios, checks = _load_manifest(manifest_file)[1:]
    source_ids = {str(item["id"]) for item in source["scenarios"]}
    violations: list[dict[str, str]] = []
    rows: list[dict[str, object]] = []
    for item in source["scenarios"]:
        scenario_id = str(item["id"])
        row = manifest_scenarios.get(scenario_id)
        required = [str(value) for value in item.get("checks", [])] or (
            [str(row.get("check"))] if row is not None and isinstance(row.get("check"), str) else []
        )
        check_id = required[0] if required else None
        check = checks.get(check_id) if check_id else None
        missing_checks = [value for value in required if value not in checks]
        exec_mode = str(item.get("exec") or "")
        if row is None:
            binding, status = "missing", "missing"
            violations.append({"code": "missing_in_manifest", "scenario": scenario_id,
                               "message": f"{scenario_id} 在场景源中声明，但未进入 manifest"})
        elif missing_checks:
            binding, status = "unbound", str(row.get("status") or "planned")
            violations.append({"code": "missing_check", "scenario": scenario_id,
                               "message": f"{scenario_id} 引用了不存在的 check: {', '.join(missing_checks)}"})
        elif required and all(value in checks for value in required):
            binding, status = "check", str(row.get("status") or "planned")
        elif exec_mode == "aspirational":
            binding, status = "aspirational", "aspirational"
        else:
            binding, status = "unbound", str(row.get("status") or "planned")
            violations.append({"code": "unbound_scenario", "scenario": scenario_id,
                               "message": f"{scenario_id} 没有可执行 check，且未显式 aspirational"})
        rows.append({
            "id": scenario_id,
            "feature": "",
            "priority": str(item.get("priority") or ""),
            "level": str(item.get("level") or ""),
            "boundary": str(item.get("boundary") or ""),
            "exec": exec_mode,
            "env": str(check.get("env", "none")) if check else str(item.get("env") or "none"),
            "inputs": list(check.get("inputs") or []) if check else [],
            "check": check_id if isinstance(check_id, str) and check is not None else "-",
            "command": list(check.get("command") or []) if check else [],
            "owner": str(row.get("owner") or "") if row else "",
            "status": status,
            "binding": binding,
            "in_design": False,
        })
    extras = _extra_rows(manifest_scenarios, checks, source_ids)
    for row in extras:
        violations.append({"code": "extra_in_manifest", "scenario": str(row["id"]),
                           "message": f"{row['id']} 存在于 manifest，但场景源未声明"})
        if row["binding"] == "unbound":
            violations.append({"code": "unbound_scenario", "scenario": str(row["id"]),
                               "message": f"{row['id']} 没有可执行 check，且未显式 aspirational"})
    all_rows = rows + extras
    summary = {
        "design_scenarios": len(source["scenarios"]),
        "manifest_scenarios": len(manifest_scenarios),
        "bound": sum(1 for row in all_rows if row["binding"] == "check"),
        "aspirational": sum(1 for row in all_rows if row["binding"] == "aspirational"),
        "unbound": sum(1 for row in all_rows if row["binding"] == "unbound"),
        "missing": sum(1 for row in all_rows if row["binding"] == "missing"),
    }
    return {
        "decision": "block" if violations else "pass",
        "generated": True,
        "source": str(scenarios_file),
        "design_file": str(scenarios_file),
        "manifest_file": str(manifest_file),
        "summary": summary,
        "scenarios": all_rows,
        "violations": violations,
    }
