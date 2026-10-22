#!/usr/bin/env python3
"""能力级 plan 预算评估：解析 TASK 的 Estimate/Capability，输出合并门禁。

默认 `capability` 粒度要求每个任务 1-2 天、可独立演示；任务数超过 25 或
平均任务时长低于 2h 时返回 `requires_merge=true`，调用方必须先合并再进入
start。`file` 粒度保留旧版 1-3 文件 / 15-60 分钟拆分方式，仅受任务数约束。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import IO, Optional, Sequence


HOURS_PER_DAY = 8.0
DEFAULT_MAX_TASKS = 25
DEFAULT_MIN_AVERAGE_HOURS = 2.0
TASK_SIZES = ("capability", "file")

_ESTIMATE_RE = re.compile(
    r"(?i)(\d+(?:\.\d+)?)\s*(?:[-–]\s*(\d+(?:\.\d+)?))?\s*"
    r"(days?|day|d|hrs?|hours?|hr|h|分钟|minutes?|mins?|m|小时|天)\b"
)


@dataclass(frozen=True)
class PlanTask:
    task_id: str
    title: str
    status: str
    estimate_raw: str
    hours: Optional[float]
    capability: str
    scenario_count: int


def parse_estimate_hours(text: str) -> Optional[float]:
    """把 `1.5d` / `4h` / `90m` / `2-3d` 转成小时；范围取上限，无法解析返回 None。"""
    match = _ESTIMATE_RE.search(text or "")
    if match is None:
        return None
    value = float(match.group(2) or match.group(1))
    unit = match.group(3).lower()
    if unit in ("d", "day", "days", "天"):
        return round(value * HOURS_PER_DAY, 2)
    if unit in ("h", "hr", "hrs", "hour", "hours", "小时"):
        return round(value, 2)
    return round(value / 60.0, 2)


def _field(section: str, name: str) -> str:
    match = re.search(rf"(?m)^- \*\*{name}\*\*:[ \t]*(.*)$", section)
    return match.group(1).strip() if match else ""


def _section_body(section: str, heading: str) -> str:
    match = re.search(rf"(?ms)^### {re.escape(heading)}\s*$\n(.*?)(?=^### |^## |\Z)", section)
    return match.group(1).strip() if match else ""


def _capability(section: str) -> str:
    explicit = _field(section, "Capability") or _field(section, "Demo")
    if explicit:
        return explicit
    for line in _section_body(section, "Description").splitlines():
        stripped = line.strip().lstrip("-* ").strip()
        if stripped:
            return stripped
    return ""


def _scenario_count(section: str) -> int:
    refs = _field(section, "Acceptance-Refs")
    ids = set(re.findall(r"\b(?:S|E|B|RULE)-\d+\b", refs))
    if ids:
        return len(ids)
    contract = _section_body(section, "Acceptance Contract")
    rows = re.findall(r"(?m)^\|[ \t]*((?:S|E|B|RULE)-\d+)[ \t]*\|", contract)
    return len(set(rows))


def parse_plan_tasks(task_file: str) -> tuple[PlanTask, ...]:
    """解析任务文件中的 TASK 段；未知状态保留，缺少 Estimate 记为 None。"""
    try:
        text = Path(task_file).read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise ValueError(f"task_read_error: {exc}") from exc
    matches = list(re.finditer(r"(?m)^## (TASK-\d+):[ \t]*(.*)$", text))
    tasks: list[PlanTask] = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        section = text[match.start():end]
        estimate_raw = _field(section, "Estimate")
        tasks.append(
            PlanTask(
                task_id=match.group(1),
                title=match.group(2).strip(),
                status=_field(section, "Status") or "draft",
                estimate_raw=estimate_raw,
                hours=parse_estimate_hours(estimate_raw),
                capability=_capability(section),
                scenario_count=_scenario_count(section),
            )
        )
    if not tasks:
        raise ValueError("no TASK sections found")
    return tuple(tasks)


def _warning(code: str, message: str, tasks: Sequence[str] = ()) -> dict[str, object]:
    return {"code": code, "message": message, "tasks": list(tasks)}


def _budget_warnings(
    tasks: Sequence[PlanTask],
    total_hours: float,
    average_hours: float,
    task_size: str,
    max_tasks: int,
    minimum_average: float,
) -> list[dict[str, object]]:
    warnings: list[dict[str, object]] = []
    missing_estimate = [task.task_id for task in tasks if task.hours is None]
    if missing_estimate:
        warnings.append(_warning(
            "missing_estimate",
            "以下 TASK 缺少可解析的 Estimate（支持 1.5d / 4h / 90m）："
            + ", ".join(missing_estimate)
            + "；无法评估计划预算，请补齐或合并。",
            missing_estimate,
        ))
    if len(tasks) > max_tasks:
        warnings.append(_warning(
            "task_count_exceeds_budget",
            f"任务数 {len(tasks)} 超过预算上限 {max_tasks}；"
            "请按 1-2 天可演示能力合并后再拆解。",
        ))
    if total_hours > 0 and average_hours < minimum_average:
        warnings.append(_warning(
            "average_task_too_small",
            f"平均任务时长 {average_hours:.1f}h 低于 {minimum_average:.1f}h；"
            "任务粒度过碎，请合并为可独立演示的能力任务。",
        ))
    if task_size == "capability":
        missing_capability = [task.task_id for task in tasks if not task.capability]
        if missing_capability:
            warnings.append(_warning(
                "missing_capability",
                "以下 TASK 缺少 Capability/Demo（用户可演示能力）："
                + ", ".join(missing_capability)
                + "；请补充能力描述或合并。",
                missing_capability,
            ))
    return warnings


def evaluate_plan(
    task_file: str,
    task_size: str = "capability",
    max_tasks: int = DEFAULT_MAX_TASKS,
    min_average_hours: Optional[float] = None,
) -> dict[str, object]:
    """评估任务文件的计划预算，返回可直接 JSON 序列化的结果。"""
    if task_size not in TASK_SIZES:
        raise ValueError(f"unknown_task_size: {task_size}")
    if max_tasks <= 0:
        raise ValueError("max_tasks must be positive")
    tasks = parse_plan_tasks(task_file)
    total_hours = round(sum(task.hours or 0.0 for task in tasks), 2)
    average_hours = round(total_hours / len(tasks), 2)
    minimum_average = 0.0 if task_size == "file" else (
        DEFAULT_MIN_AVERAGE_HOURS if min_average_hours is None else min_average_hours
    )
    if minimum_average < 0:
        raise ValueError("min_average_hours must be non-negative")
    warnings = _budget_warnings(
        tasks, total_hours, average_hours, task_size, max_tasks, minimum_average
    )
    requires_merge = bool(warnings)
    return {
        "ok": True,
        "task_file": str(task_file),
        "task_size": task_size,
        "decision": "merge_required" if requires_merge else "pass",
        "requires_merge": requires_merge,
        "task_count": len(tasks),
        "estimated_task_count": sum(1 for task in tasks if task.hours is not None),
        "total_hours": total_hours,
        "average_hours": average_hours,
        "max_tasks": max_tasks,
        "min_average_hours": minimum_average,
        "warnings": warnings,
        "tasks": [
            {
                "id": task.task_id,
                "title": task.title,
                "status": task.status,
                "estimate": task.estimate_raw,
                "hours": task.hours,
                "capability": task.capability,
                "scenario_count": task.scenario_count,
            }
            for task in tasks
        ],
    }


def _write_text(stdout: IO[str], result: dict[str, object]) -> None:
    stdout.write(
        f"计划预算: {result['task_count']} 任务 / 总计 {result['total_hours']}h"
        f" / 平均 {result['average_hours']}h（{result['task_size']}）\n"
    )
    for warning in result["warnings"]:
        stdout.write(f"  ! {warning['message']}\n")
    stdout.write(f"decision: {result['decision']}\n")


def main(argv: Optional[Sequence[str]] = None, stdout: IO[str] = sys.stdout) -> int:
    parser = argparse.ArgumentParser(prog=os.environ.get("CF_RUNTIME_COMMAND", "cf_task_plan.py"))
    parser.add_argument("--task-file", required=True)
    parser.add_argument("--task-size", choices=TASK_SIZES, default="capability")
    parser.add_argument("--max-tasks", type=int, default=DEFAULT_MAX_TASKS)
    parser.add_argument("--min-average-hours", type=float, default=None)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = evaluate_plan(
            args.task_file,
            task_size=args.task_size,
            max_tasks=args.max_tasks,
            min_average_hours=args.min_average_hours,
        )
    except (OSError, ValueError) as exc:
        stdout.write(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 2
    if args.json:
        stdout.write(json.dumps(result, ensure_ascii=False))
    else:
        _write_text(stdout, result)
    return 0 if result["decision"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
