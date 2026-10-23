"""Validated acceptance records shared by execution and lifecycle gates."""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Mapping


EXEC_MODES = ("auto", "manual", "deferred", "aspirational")


def verified_evidence(row: Mapping[str, object], fingerprint: str = "") -> bool:
    evidence = row.get("evidence")
    if row.get("status") != "verified" or not isinstance(evidence, dict):
        return False
    if row.get("kind") != "manual" and row.get("exec") != "manual":
        if fingerprint and evidence.get("fingerprint") != fingerprint:
            return False
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
        check = item.get("check")
        if check is not None and not isinstance(check, str):
            raise ValueError(f"invalid scenario {scenario_id}:check")
        checks = item.get("checks")
        if checks is not None and (not isinstance(checks, list) or not all(isinstance(x, str) for x in checks)):
            raise ValueError(f"invalid scenario {scenario_id}:checks")
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
        _validate_scenario_metadata(scenario_id, item)
    for item in value:
        unknown = set(item.get("depends_on", [])) - seen
        if unknown:
            raise ValueError(f"acceptance scenario dependency missing: {', '.join(sorted(unknown))}")
    return value


def _validate_scenario_metadata(scenario_id: str, item: Mapping[str, object]) -> None:
    """Execution metadata mirrors design §2.5 and manifest v3 checks."""
    priority = item.get("priority")
    if priority is not None and (not isinstance(priority, str) or not priority.strip()):
        raise ValueError(f"invalid scenario {scenario_id}:priority")
    exec_mode = item.get("exec")
    if exec_mode is not None and (not isinstance(exec_mode, str) or exec_mode not in EXEC_MODES):
        raise ValueError(f"invalid scenario {scenario_id}:exec")
    env = item.get("env")
    if env is not None and (not isinstance(env, str) or not env.strip()):
        raise ValueError(f"invalid scenario {scenario_id}:env")
    inputs = item.get("inputs")
    if inputs is not None and (
        not isinstance(inputs, list) or not all(isinstance(value, str) and value for value in inputs)
    ):
        raise ValueError(f"invalid scenario {scenario_id}:inputs")


def validate_checks(value: object) -> list[dict[str, object]]:
    """Validate the manifest v3 checks array (execution identity)."""
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError("invalid manifest checks: expected list")
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, dict):
            raise ValueError("invalid check: expected object")
        check_id = item.get("id")
        if not isinstance(check_id, str) or not check_id.strip():
            raise ValueError("check id missing")
        if check_id in seen:
            raise ValueError(f"duplicate check id: {check_id}")
        seen.add(check_id)
        command = item.get("command")
        if not isinstance(command, list) or not command or not all(isinstance(x, str) for x in command):
            raise ValueError(f"invalid check {check_id}:command")
        cwd = item.get("cwd", ".")
        if not isinstance(cwd, str):
            raise ValueError(f"invalid check {check_id}:cwd")
        timeout = item.get("timeout", 60)
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or timeout <= 0:
            raise ValueError(f"invalid check {check_id}:timeout")
        _validate_check_environment(check_id, item)
    return value


_ENV_SCOPES = ("shared", "isolated")


def _validate_check_environment(check_id: str, item: Mapping[str, object]) -> None:
    """env/env_scope/preflight/parallel_safe describe how a check may run."""
    env = item.get("env", "none")
    if not isinstance(env, str) or not env.strip():
        raise ValueError(f"invalid check {check_id}:env")
    scope = item.get("env_scope", "shared")
    if not isinstance(scope, str) or scope not in _ENV_SCOPES:
        raise ValueError(f"invalid check {check_id}:env_scope")
    if "parallel_safe" in item and not isinstance(item["parallel_safe"], bool):
        raise ValueError(f"invalid check {check_id}:parallel_safe")
    preflight = item.get("preflight", [])
    if not isinstance(preflight, list):
        raise ValueError(f"invalid check {check_id}:preflight")
    for entry in preflight:
        if isinstance(entry, str):
            if not entry.strip():
                raise ValueError(f"invalid check {check_id}:preflight")
        elif isinstance(entry, list):
            if not entry or not all(isinstance(token, str) and token for token in entry):
                raise ValueError(f"invalid check {check_id}:preflight")
        else:
            raise ValueError(f"invalid check {check_id}:preflight")


def load_manifest(path: Path) -> dict[str, object]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("invalid acceptance manifest: expected object")
    validate_scenarios(data.get("scenarios"))
    if "checks" in data:
        validate_checks(data.get("checks"))
    check_ids = {
        item.get("id") for item in data.get("checks", [])
        if isinstance(item, dict)
    } if isinstance(data.get("checks"), list) else set()
    for scenario in data.get("scenarios", []):
        if not isinstance(scenario, dict):
            continue
        single = scenario.get("check")
        if isinstance(single, str) and single and single not in check_ids:
            raise ValueError(f"scenario {scenario.get('id')} references missing check: {single}")
        multiple = scenario.get("checks")
        if isinstance(multiple, list):
            unknown = [str(value) for value in multiple if str(value) not in check_ids]
            if unknown:
                raise ValueError(
                    f"scenario {scenario.get('id')} references missing checks: {', '.join(unknown)}"
                )
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
