"""Validated acceptance records shared by execution and lifecycle gates."""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Mapping


def verified_evidence(row: Mapping[str, object]) -> bool:
    evidence = row.get("evidence")
    if row.get("status") != "verified" or not isinstance(evidence, dict):
        return False
    if row.get("kind") != "manual":
        return evidence.get("status") == "passed" and evidence.get("exit_code") == 0
    author, detail = evidence.get("confirmed_by"), evidence.get("evidence")
    agents = {"agent", "assistant", "codex", "claude", "opencode", "costrict"}
    return (isinstance(author, str) and bool(author.strip())
            and author.strip().lower().split(":", 1)[0] not in agents
            and isinstance(detail, str) and bool(detail.strip()))


def validate_scenarios(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list):
        raise ValueError("invalid manifest scenarios: expected list")
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, dict):
            raise ValueError("invalid scenario: expected object")
        scenario_id = item.get("id")
        if not isinstance(scenario_id, str) or not scenario_id.strip():
            raise ValueError("scenario id missing")
        if scenario_id in seen:
            raise ValueError(f"duplicate scenario id: {scenario_id}")
        seen.add(scenario_id)
        for field in ("kind", "owner", "cwd"):
            if field in item and not isinstance(item[field], str):
                raise ValueError(f"invalid scenario {scenario_id}:{field}")
        command = item.get("command")
        if command is not None and (not isinstance(command, list) or not all(isinstance(x, str) for x in command)):
            raise ValueError(f"invalid scenario {scenario_id}:command")
        timeout = item.get("timeout", 60)
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or timeout <= 0:
            raise ValueError(f"invalid scenario {scenario_id}:timeout")
        deps = item.get("depends_on", [])
        if not isinstance(deps, list) or not all(isinstance(x, str) for x in deps):
            raise ValueError(f"invalid scenario {scenario_id}:depends_on")
        if "runs" in item and not isinstance(item["runs"], list):
            raise ValueError(f"invalid scenario {scenario_id}:runs")
        revision = item.get("revision", 0)
        if isinstance(revision, bool) or not isinstance(revision, int) or revision < 0:
            raise ValueError(f"invalid scenario {scenario_id}:revision")
    for item in value:
        unknown = set(item.get("depends_on", [])) - seen
        if unknown:
            raise ValueError(f"acceptance scenario dependency missing: {', '.join(sorted(unknown))}")
    return value


def load_manifest(path: Path) -> dict[str, object]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("invalid acceptance manifest: expected object")
    validate_scenarios(data.get("scenarios"))
    if "task_file" in data and not isinstance(data["task_file"], str):
        raise ValueError("invalid acceptance manifest: task_file")
    return data


def validate_execution_baseline(path: Path, data: Mapping[str, object]) -> None:
    """Legacy standalone manifests remain usable; locked plans must match."""
    task_name = data.get("task_file")
    if not isinstance(task_name, str) or not task_name:
        return
    task = Path(task_name)
    task = task if task.is_absolute() else path.parent / task
    if not task.is_file():
        raise ValueError(f"acceptance task file missing: {task}")
    if "## Acceptance Coverage" in task.read_text(encoding="utf-8"):
        from cf_acceptance_manifest import validate_manifest
        valid, reason = validate_manifest(str(task), str(path))
        if not valid:
            raise ValueError(reason)
