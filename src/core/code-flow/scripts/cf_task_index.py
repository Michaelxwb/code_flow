#!/usr/bin/env python3
"""Programmatic task-file index: parse TASK statuses/depends, compute DAG batches.

Single worktrees allow one active TASK at a time, so "parallel" below means
*independently developable* (no dependency path between them) — not
simultaneously activatable, a distinction `cf-task:graph` used to blur.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import IO, Mapping, Optional, Sequence


from cf_task_state import FINISHED_STATUSES as _DONE_STATUSES


@dataclass(frozen=True)
class TaskNode:
    task_id: str
    status: str
    depends: tuple[str, ...]


def parse_task_file(task_file: str) -> tuple[TaskNode, ...]:
    """Parse every `## TASK-xxx` section into status/depends nodes.

    Unknown statuses are preserved verbatim (e.g. `verified` from the E2E
    flow) — the parser never rejects them, completion checks treat done and
    verified as finished.
    """
    try:
        text = Path(task_file).read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise ValueError(f"task_read_error: {exc}") from exc
    nodes: list[TaskNode] = []
    matches = list(re.finditer(r"(?m)^## (TASK-\d+):[^\n]*$", text))
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        section = text[match.start():end]
        status_match = re.search(r"(?m)^- \*\*Status\*\*:[ \t]*([^\n]+)", section)
        status = status_match.group(1).strip() if status_match else "draft"
        depends_match = re.search(r"(?m)^- \*\*Depends\*\*:[ \t]*([^\n]*)", section)
        depends: tuple[str, ...] = ()
        if depends_match:
            depends = tuple(
                part.strip()
                for part in re.split(r"[,，\s]+", depends_match.group(1).strip())
                if re.fullmatch(r"TASK-\d+", part.strip())
            )
        nodes.append(TaskNode(match.group(1), status, depends))
    if not nodes:
        raise ValueError("no TASK sections found")
    return tuple(nodes)


def task_batches(nodes: Sequence[TaskNode]) -> list[list[str]]:
    """Topological batches over unfinished TASKs; unknown deps and cycles raise."""
    ids = {node.task_id for node in nodes}
    for node in nodes:
        unknown = [dep for dep in node.depends if dep not in ids]
        if unknown:
            raise ValueError(f"unknown depends: {node.task_id} -> {', '.join(unknown)}")
    pending = {node.task_id for node in nodes if node.status not in _DONE_STATUSES}
    finished = {node.task_id for node in nodes if node.status in _DONE_STATUSES}
    deps = {node.task_id: set(node.depends) for node in nodes}
    batches: list[list[str]] = []
    while pending:
        ready = sorted(task for task in pending if deps[task] <= finished)
        if not ready:
            raise ValueError(f"dependency cycle among: {', '.join(sorted(pending))}")
        batches.append(ready)
        finished.update(ready)
        pending.difference_update(ready)
    return batches


def dependency_components(nodes: Sequence[TaskNode]) -> list[list[str]]:
    """Connected dependency components; different components are independent."""
    parent = {node.task_id: node.task_id for node in nodes}

    def find(task: str) -> str:
        while parent[task] != task:
            parent[task] = parent[parent[task]]
            task = parent[task]
        return task

    for node in nodes:
        for dep in node.depends:
            left, right = find(node.task_id), find(dep)
            if left != right:
                parent[left] = right
    groups: dict[str, list[str]] = {}
    for node in nodes:
        groups.setdefault(find(node.task_id), []).append(node.task_id)
    return [sorted(members) for members in groups.values()]


def independent_groups(nodes: Sequence[TaskNode]) -> list[list[str]]:
    """Compatibility alias: groups are independent of each other, not within."""
    return dependency_components(nodes)


def index_data(task_file: str) -> dict[str, object]:
    nodes = parse_task_file(task_file)
    return {
        "tasks": [
            {"id": node.task_id, "status": node.status, "depends": list(node.depends)}
            for node in nodes
        ],
        "batches": task_batches(nodes),
        "independent_groups": independent_groups(nodes),
        "dependency_components": dependency_components(nodes),
        "note": "batches 组内无依赖；dependency_components 仅组间独立（independent_groups 为兼容别名）；单 worktree 一次仅激活一个 TASK",
    }


def main(argv: Optional[Sequence[str]] = None, stdout: IO[str] = sys.stdout) -> int:
    parser = argparse.ArgumentParser(prog="cf_task_index.py")
    parser.add_argument("--task-file", required=True)
    parser.add_argument("--dag", action="store_true", help="输出拓扑批次与独立分组")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        data = index_data(args.task_file)
    except (OSError, ValueError) as exc:
        stdout.write(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 2
    if args.json or args.dag:
        stdout.write(json.dumps(data, ensure_ascii=False))
    else:
        lines = ["TASK 索引:"]
        for item in data["tasks"]:
            lines.append(f"  - {item['id']}: {item['status']} (依赖: {', '.join(item['depends']) or '无'})")
        for index, batch in enumerate(data["batches"], 1):
            lines.append(f"批次 {index}（可独立开发）: {', '.join(batch)}")
        stdout.write("\n".join(lines) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
