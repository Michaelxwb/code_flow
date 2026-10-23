#!/usr/bin/env python3
"""Lock and validate plan Acceptance Coverage entries."""

from __future__ import annotations

import argparse
import os
import hashlib
import json
import shlex
from datetime import datetime, timezone
from pathlib import Path
import re
import sys
from typing import IO, Callable, Mapping, Optional, Sequence

from cf_acceptance_schema import (
    EXEC_MODES, load_manifest, scenario_check_ids, validate_checks, validate_scenarios,
)


_ROW_RE = re.compile(r"^\|\s*([SEB]-\d+)\s*\|(.+?)\|$")

_MANIFEST_SCHEMA = 3
_LEGACY_MANIFEST_SCHEMAS = (2,)


def _kind(level: str) -> str:
    """Map test level to execution kind.

    - functional: auto-executed in Done Gate (unit, integration)
    - e2e: deferred until explicit --verify-e2e (needs external dependencies)
    - manual: user confirmation required, never auto-executed

    层级单元格允许带注解（如 `E2E（Playwright）`、`e2e/chrome`、`manual(chrome)`），
    取分隔符前的词元判定；避免带注解的 E2E 被误判为 functional 而每任务执行。
    """
    head = level.strip().lower()
    for separator in ("(", "（", "[", "/", ",", "，", " ", "—", "-"):
        head = head.split(separator, 1)[0]
    head = head.strip()
    if head in ("manual", "手工", "手动"):
        return "manual"
    if head in ("e2e", "端到端", "end"):
        return "e2e"
    return "functional"


_EXEC_ALIASES = {
    "auto": "auto",
    "automatic": "auto",
    "自动化": "auto",
    "manual": "manual",
    "手工": "manual",
    "手动": "manual",
    "deferred": "deferred",
    "延期": "deferred",
    "aspirational": "aspirational",
    "愿望": "aspirational",
    "意向": "aspirational",
}

_COLUMN_NAMES = {
    "source": ("来源设计", "来源", "source"),
    "level": ("测试层级", "测试级别", "level"),
    "boundary": ("关键真实边界", "真实边界", "boundary"),
    "owner": ("负责任务", "负责任任务", "负责人", "owner"),
    "status": ("状态", "status"),
    "command": ("执行命令", "命令", "command"),
    "cwd": ("工作目录", "cwd"),
    "timeout": ("超时", "timeout"),
    "depends": ("依赖", "depends"),
    "priority": ("优先级", "priority"),
    "exec": ("执行方式", "exec"),
    "env": ("环境", "env"),
    "inputs": ("输入", "inputs"),
    "why_e2e": ("E2E理由", "E2E 理由", "为什么E2E", "why_e2e"),
    "trigger_paths": ("触发路径", "影响路径", "trigger_paths"),
    "smoke": ("冒烟", "常驻冒烟", "smoke"),
}


def _column_indexes(cells: Sequence[str]) -> dict[str, int]:
    """Map table headers to field offsets (fields omit the leading 场景ID cell)."""
    indexes: dict[str, int] = {}
    for key, names in _COLUMN_NAMES.items():
        for index, cell in enumerate(cells[1:]):
            lowered = cell.strip().lower()
            if any(name.lower() in lowered for name in names):
                indexes[key] = index
                break
    return indexes


def _column_value(fields: Sequence[str], columns: Mapping[str, int], key: str, fallback: int) -> str:
    """Prefer named headers; only headerless legacy tables use positional fallback."""
    index = columns.get(key, -1) if columns else fallback
    return fields[index].strip() if 0 <= index < len(fields) else ""


def _metadata_cell(fields: Sequence[str], columns: Mapping[str, int], key: str) -> str:
    index = columns.get(key, -1)
    return fields[index].strip() if 0 <= index < len(fields) else ""


def _parse_priority(cell: str) -> str:
    value = (cell or "").strip().strip("`").upper()
    return value if value and value not in {"-", "N/A"} else ""


def _parse_exec(cell: str) -> str:
    value = (cell or "").strip().strip("`")
    if not value or value in {"-", "N/A"}:
        return ""
    normalized = _EXEC_ALIASES.get(value.lower(), value.lower())
    if normalized not in EXEC_MODES:
        raise ValueError(f"未知执行方式: {value}（允许 {', '.join(EXEC_MODES)}）")
    return normalized


def _parse_bool(cell: str, scenario_id: str = "") -> Optional[bool]:
    value = (cell or "").strip().strip("`").lower()
    if not value or value in {"-", "n/a", "none"}:
        return None
    if value in {"true", "yes", "y", "1", "是", "冒烟", "smoke"}:
        return True
    if value in {"false", "no", "n", "0", "否", "不是"}:
        return False
    raise ValueError(f"{scenario_id} 布尔列取值非法: {cell}")


def _parse_inputs(cell: str, scenario_id: str = "") -> list[str]:
    text = (cell or "").strip().strip("`")
    if not text or text in {"-", "none", "N/A", "TBD", "tbd"}:
        return []
    if text.startswith("["):
        try:
            value = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{scenario_id} 输入列不是合法 JSON 数组: {exc}") from exc
        if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
            raise ValueError(f"{scenario_id} 输入列必须是字符串数组")
        return list(value)
    return [item.strip() for item in re.split(r"[,，、;；]", text) if item.strip()]


def _row_metadata(fields: Sequence[str], columns: Mapping[str, int], scenario_id: str) -> dict[str, object]:
    """Only emit optional fields when explicitly present, preserving schema2/legacy rows."""
    metadata: dict[str, object] = {}
    priority = _parse_priority(_metadata_cell(fields, columns, "priority"))
    if priority:
        metadata["priority"] = priority
    exec_mode = _parse_exec(_metadata_cell(fields, columns, "exec"))
    if exec_mode:
        metadata["exec"] = exec_mode
    env = _metadata_cell(fields, columns, "env").strip("`")
    if env and env not in {"-", "N/A"}:
        metadata["env"] = env
    inputs = _parse_inputs(_metadata_cell(fields, columns, "inputs"), scenario_id)
    if inputs:
        metadata["inputs"] = inputs
    why_e2e = _metadata_cell(fields, columns, "why_e2e").strip("`")
    if why_e2e and why_e2e not in {"-", "N/A", "n/a", "TBD", "tbd"}:
        metadata["why_e2e"] = why_e2e
    trigger_paths = _parse_inputs(_metadata_cell(fields, columns, "trigger_paths"), scenario_id)
    if trigger_paths:
        metadata["trigger_paths"] = trigger_paths
    smoke = _parse_bool(_metadata_cell(fields, columns, "smoke"), scenario_id)
    if smoke is not None:
        metadata["smoke"] = smoke
    return metadata


def _merge_check_config(check: dict[str, object], env: str, inputs: Sequence[str]) -> None:
    """Same execution identity must not declare conflicting env/inputs."""
    check_id = str(check.get("id", ""))
    if env:
        current = str(check.get("env", "none"))
        if current != "none" and current != env:
            raise ValueError(f"check configuration conflict: {check_id} env {current} != {env}")
        check["env"] = env
    if inputs:
        current = list(check.get("inputs") or [])
        if current and current != list(inputs):
            raise ValueError(f"check configuration conflict: {check_id} inputs {current} != {list(inputs)}")
        check["inputs"] = list(inputs)


def _parse_command(cell: str, scenario_id: str) -> Optional[list[str]]:
    """Parse the optional 命令 column: argv JSON array preferred, else shell words.

    Empty / `-` / `planned` → None (not yet registered, not executable).
    """
    text = (cell or "").strip()
    if not text or text in {"-", "planned", "pending", "TBD", "tbd"}:
        return None
    if text.startswith("["):
        try:
            value = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{scenario_id} 命令列不是合法 argv JSON: {exc}") from exc
        if not isinstance(value, list) or not value or not all(isinstance(item, str) for item in value):
            raise ValueError(f"{scenario_id} 命令列必须是 argv 字符串数组")
        return list(value)
    return shlex.split(text)


def _parse_float(cell: str, default: float) -> float:
    try:
        return float((cell or "").strip() or default)
    except (TypeError, ValueError):
        return default


def _manifest_hash(rows: list[dict[str, object]]) -> str:
    immutable = []
    for item in rows:
        entry = {
            key: item[key] for key in
            ("id", "source", "level", "kind", "boundary", "owner", "command", "cwd", "timeout", "depends_on")
        }
        # Optional E2E precision fields are hashed only when present so old
        # manifests keep their historical baseline hash.
        for key in ("why_e2e", "trigger_paths", "smoke"):
            if key in item:
                entry[key] = item[key]
        immutable.append(entry)
    payload = json.dumps(immutable, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _legacy_kind(level: str) -> str:
    """v1 精确匹配：仅用于识别旧版锁定的 manifest，不做新语义判定。"""
    normalized = level.strip().lower()
    if normalized == "manual":
        return "manual"
    if normalized == "e2e":
        return "e2e"
    return "functional"


def _contract_commands(text: str) -> dict[str, str]:
    """Acceptance Contract 表的执行命令（Coverage 表无命令列时的注册回退）。

    Coverage 模板长期只有 6 列，命令实际写在 TASK 段落 Contract 表；提取器只
    读 Coverage 会让新需求 finish 必现 no_executable_scenarios。这里按场景 ID
    回退读取 Contract 的“执行命令”列（按表头定位，兼容列序差异），与 Coverage
    第 7 列（argv JSON）等价。
    """
    commands: dict[str, str] = {}
    for section in re.finditer(r"(?ms)^## TASK-\d+:.*?(?=^## |\Z)", text):
        contract = re.search(
            r"(?ms)^### Acceptance Contract[^\n]*\n(.*?)(?=^### |^## |\Z)", section.group(0)
        )
        if contract is None:
            continue
        command_idx = -1
        for line in contract.group(1).splitlines():
            stripped = line.strip()
            if not stripped.startswith("|"):
                continue
            cells = [cell.strip() for cell in stripped.strip("|").split("|")]
            if command_idx == -1:
                match_column = next((i for i, cell in enumerate(cells) if "命令" in cell), -1)
                if match_column == -1:
                    continue
                command_idx = match_column
                continue
            match = _ROW_RE.match(line)
            if not match or set(match.group(2).replace("|", "").strip()) <= {"-", " "}:
                continue
            if command_idx < len(cells):
                commands.setdefault(match.group(1), cells[command_idx])
    return commands


def _check_id(command: list[str], cwd: str, timeout: float, config: Mapping[str, object] | None = None) -> str:
    payload = json.dumps([command, cwd, timeout, config or {}], ensure_ascii=False, sort_keys=True).encode("utf-8")
    return "CHK-" + hashlib.sha256(payload).hexdigest()[:12]


def _derive_checks(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    """Derive executable checks from scenario command identity (stable IDs)."""
    by_id: dict[str, dict[str, object]] = {}
    by_command: dict[tuple, dict[str, object]] = {}
    for row in rows:
        command = row.get("command")
        if not isinstance(command, list) or not command:
            continue
        cwd = str(row.get("cwd", "."))
        timeout = float(row.get("timeout", 60))
        trigger_paths = [
            str(item) for item in row.get("trigger_paths", []) or [] if str(item).strip()
        ]
        config = {
            "env": row.get("env") if isinstance(row.get("env"), str) else "",
            "inputs": list(row.get("inputs") or []),
        }
        identity = {
            key: row.get(key) for key in
            ("env", "env_scope", "preflight", "parallel_safe", "profile", "inputs")
        }
        command_key = (tuple(command), cwd, timeout)
        previous = by_command.setdefault(command_key, {"env": "", "inputs": []})
        if config["env"] and previous["env"] and config["env"] != previous["env"]:
            raise ValueError(f"check configuration conflict: {row.get('id')} {command_key} env")
        if config["inputs"] and previous["inputs"] and config["inputs"] != previous["inputs"]:
            raise ValueError(f"check configuration conflict: {row.get('id')} {command_key} inputs")
        previous["env"] = previous["env"] or config["env"]
        previous["inputs"] = previous["inputs"] or config["inputs"]
        check_id = _check_id(command, cwd, timeout, identity)
        row["check"] = check_id
        check = by_id.get(check_id)
        if check is None:
            check = {
                "id": check_id,
                "command": list(command),
                "cwd": cwd,
                "timeout": timeout,
                "env": "none",
                "env_scope": "shared",
                "parallel_safe": False,
                "profile": "changed",
                "inputs": [],
                "preflight": [],
                "paths": [],
            }
            by_id[check_id] = check
        env = row.get("env")
        inputs = row.get("inputs")
        _merge_check_config(
            check,
            env if isinstance(env, str) else "",
            inputs if isinstance(inputs, list) else [],
        )
        if trigger_paths:
            check["paths"] = sorted(set(check.get("paths") or []) | set(trigger_paths))
        if row.get("smoke"):
            check["profile"] = "smoke"
    return list(by_id.values())


_SCENARIO_SOURCE_FIELDS = ("why_e2e", "trigger_paths", "smoke")


def _merge_scenario_source(rows: list[dict[str, object]], scenarios_file: str) -> None:
    """Merge E2E precision fields from the canonical scenario source.

    The Acceptance Coverage table is a projection. Quality fields live in the
    scenario source so a plan cannot silently lose its E2E justification when
    the table is regenerated. Only additive fields are merged; a populated
    Coverage cell is never overwritten by a default value.
    """
    if not scenarios_file:
        return
    import yaml
    from cf_scenarios import ScenarioError, _frontmatter, parse_scenarios

    try:
        source = parse_scenarios(scenarios_file)
        raw_text = Path(scenarios_file).read_text(encoding="utf-8")
        raw = yaml.safe_load(_frontmatter(raw_text)) or {}
    except (OSError, UnicodeError, yaml.YAMLError, ScenarioError) as exc:
        code = getattr(exc, "code", "scenario_source_unreadable")
        message = getattr(exc, "message", str(exc))
        raise ValueError(f"scenario_source_invalid: {code}: {message}") from exc
    raw_scenarios = raw.get("scenarios") if isinstance(raw, Mapping) else None
    explicit = {
        str(item.get("id")): set(item)
        for item in raw_scenarios or []
        if isinstance(item, Mapping) and isinstance(item.get("id"), str)
    }
    by_id = {
        str(item.get("id")): item for item in rows
        if isinstance(item, dict) and isinstance(item.get("id"), str)
    }
    for scenario in source["scenarios"]:
        scenario_id = str(scenario.get("id"))
        row = by_id.get(scenario_id)
        if row is None:
            continue
        provided = explicit.get(scenario_id, set())
        # The scenario source is canonical for fields it actually declares.
        # Explicit false/empty values must be able to clear a stale table cell.
        for field in ("level", "priority", "boundary", "exec",
                      "why_e2e", "trigger_paths", "smoke"):
            if field in provided:
                row[field] = scenario.get(field)
        row["kind"] = _kind(str(row.get("level", "")))
        for field in _SCENARIO_SOURCE_FIELDS:
            if field in provided:
                continue
            value = scenario.get(field)
            if value not in (None, "", [], False):
                row[field] = value
        if not row.get("priority") and scenario.get("priority"):
            row["priority"] = scenario["priority"]
        if not row.get("boundary") and scenario.get("boundary"):
            row["boundary"] = scenario["boundary"]


def _extract_rows(task_file: str, kind_fn: Callable[[str], str], contract_fallback: bool = True,
                  scenarios_file: str = "", merge_source: bool = True) -> dict[str, object]:
    path = Path(task_file)
    text = path.read_text(encoding="utf-8")
    contract_commands = _contract_commands(text) if contract_fallback else {}
    rows: list[dict[str, object]] = []
    in_table = False
    seen: set[str] = set()
    columns: dict[str, int] = {}
    for line in text.splitlines():
        if line.startswith("## Acceptance Coverage"):
            in_table = True
            continue
        if in_table and line.startswith("## "):
            break
        if not in_table:
            continue
        if line.strip().startswith("|"):
            header = [item.strip() for item in line.strip().strip("|").split("|")]
            if header and header[0].replace(" ", "") in ("场景ID", "场景编号"):
                columns = _column_indexes(header)
                continue
        match = _ROW_RE.match(line)
        if not match or set(match.group(2).replace("|", "").strip()) <= {"-", " "}:
            continue
        fields = [item.strip() for item in match.group(2).split("|")]
        if match.group(1) in seen:
            raise ValueError(f"duplicate scenario id: {match.group(1)}")
        if len(fields) < 5:
            raise ValueError(f"Acceptance Coverage missing columns: {match.group(1)}")
        seen.add(match.group(1))
        depends_cell = _column_value(fields, columns, "depends", 8)
        depends = [item.strip() for item in depends_cell.split(",") if item.strip()]
        level = _column_value(fields, columns, "level", 1)
        # Legacy coverage tables sometimes append a command cell without a
        # header; keep the positional read when the header has no command column.
        if "command" in columns:
            command_cell = _column_value(fields, columns, "command", 5)
        else:
            command_cell = fields[5].strip() if len(fields) > 5 else ""
        if not command_cell:
            command_cell = contract_commands.get(match.group(1), "")
        row: dict[str, object] = {
            "id": match.group(1),
            "source": _column_value(fields, columns, "source", 0),
            "level": level,
            "kind": kind_fn(level),
            "boundary": _column_value(fields, columns, "boundary", 2),
            "owner": _column_value(fields, columns, "owner", 3),
            "status": _column_value(fields, columns, "status", 4),
            "command": _parse_command(command_cell, match.group(1)),
            "cwd": _column_value(fields, columns, "cwd", 6) or ".",
            "timeout": _parse_float(_column_value(fields, columns, "timeout", 7), 60.0),
            "depends_on": depends,
        }
        row.update(_row_metadata(fields, columns, match.group(1)))
        rows.append(row)
    if not rows:
        raise ValueError("Acceptance Coverage 缺失或为空")
    if merge_source and not scenarios_file:
        candidate = Path(task_file).with_suffix(".scenarios.md")
        if candidate.is_file():
            scenarios_file = str(candidate)
    if merge_source:
        _merge_scenario_source(rows, scenarios_file)
    validate_scenarios(rows)
    checks = _derive_checks(rows)
    return {"schema": _MANIFEST_SCHEMA, "task_file": str(path), "task_sha256": _manifest_hash(rows),
            "checks": checks, "scenarios": rows}


def extract_manifest(task_file: str, kind_fn: Callable[[str], str] = _kind,
                     contract_fallback: bool = True,
                     scenarios_file: str = "", merge_source: bool = True) -> dict[str, object]:
    return _extract_rows(task_file, kind_fn, contract_fallback, scenarios_file, merge_source)


def write_manifest(task_file: str, output: str, scenarios_file: str = "") -> dict[str, object]:
    if not scenarios_file and Path(output).is_file():
        # A re-lock without an explicit source must reuse the path recorded by
        # the previous lock; task stem inference is not enough when the task
        # file and requirement source names differ.
        try:
            stored = json.loads(Path(output).read_text(encoding="utf-8"))
            recorded = stored.get("scenarios_file") if isinstance(stored, Mapping) else None
        except (OSError, ValueError, TypeError):
            recorded = None
        if isinstance(recorded, str) and recorded.strip():
            scenarios_file = str((Path(output).parent / recorded).resolve())
    if not scenarios_file:
        candidate = Path(task_file).with_suffix(".scenarios.md")
        if candidate.is_file():
            scenarios_file = str(candidate)
    manifest = extract_manifest(task_file, scenarios_file=scenarios_file)
    if scenarios_file:
        from cf_scenarios import parse_scenarios
        source = parse_scenarios(scenarios_file)
        rows = {str(item["id"]): item for item in manifest["scenarios"]}
        check_ids = {str(item["id"]) for item in manifest.get("checks", [])}
        for scenario in source["scenarios"]:
            scenario_id = str(scenario["id"])
            row = rows.get(scenario_id)
            if row is None:
                continue
            checks = [str(value) for value in scenario.get("checks", [])]
            unknown = [value for value in checks if value not in check_ids]
            if unknown:
                raise ValueError(f"unknown_check:{scenario_id}:{','.join(unknown)}")
            if checks:
                row["checks"] = checks
    target = Path(output)
    if scenarios_file:
        source_path = Path(scenarios_file).resolve()
        try:
            manifest["scenarios_file"] = str(source_path.relative_to(target.parent.resolve()))
        except ValueError:
            manifest["scenarios_file"] = str(source_path)
    # Every manifest written by this version opts into the E2E precision gate.
    # Old manifests are only read; they keep the legacy warning path until a
    # plan re-lock migrates them.
    manifest["e2e_gate"] = 1
    _preserve_runtime_state(task_file, target, manifest)
    for scenario in manifest.get("scenarios", []):
        if isinstance(scenario, dict) and scenario.get("status") in ("verified", "failed") and not scenario.get("evidence"):
            scenario["status"] = "planned"
    _preserve_check_config(target, manifest)
    try:
        manifest["task_file"] = str(Path(task_file).resolve().relative_to(target.parent.resolve()))
    except ValueError:
        manifest["task_file"] = str(Path(task_file).resolve())
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest


_RUNTIME_SCENARIO_FIELDS = ("status", "revision", "evidence", "runs", "stale_checks")

_CHECK_CONFIG_FIELDS = ("env", "env_scope", "parallel_safe", "profile", "inputs", "preflight", "accepted_risk")


def record_accepted_risk(
    manifest_file: str, check_id: str, owner: str, reason: str, expires_at: str,
    confirmed_by: str, source: str,
) -> dict[str, object]:
    """Attach a user-confirmed, time-boxed risk acceptance to one check."""
    if not all(str(value).strip() for value in (check_id, owner, reason, expires_at, confirmed_by, source)):
        raise ValueError("accepted_risk requires check, owner, reason, expires_at, confirmed_by and source")
    agent_names = {
        "agent", "assistant", "claude", "claude code", "codex", "opencode",
        "costrict", "ai", "bot",
    }
    identity = confirmed_by.strip().lower().split(":", 1)[0]
    if identity in agent_names:
        raise ValueError("accepted_risk must be confirmed by the user, not the agent")
    try:
        deadline = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"invalid expires_at: {expires_at}") from exc
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", expires_at.strip()):
        deadline = deadline.replace(hour=23, minute=59, second=59, microsecond=999999)
    if deadline.tzinfo is None:
        deadline = deadline.replace(tzinfo=timezone.utc)
    now = datetime.now(timezone.utc)
    if deadline <= now:
        raise ValueError("expires_at must be in the future")
    path = Path(manifest_file)
    data = load_manifest(path)
    checks = data.get("checks")
    if not isinstance(checks, list):
        raise ValueError("accepted_risk requires a schema3 manifest with checks")
    for check in checks:
        if isinstance(check, dict) and check.get("id") == check_id:
            from cf_acceptance_risk import risk_scenario_ids
            scenario_ids = risk_scenario_ids(data, check_id, owner.strip())
            if not scenario_ids:
                raise ValueError(f"accepted_risk owner {owner!r} owns no scenario for {check_id}")
            check["accepted_risk"] = {
                "owner": owner.strip(),
                "scenario_ids": scenario_ids,
                "reason": reason.strip(),
                "expires_at": deadline.isoformat(),
                "confirmed_by": confirmed_by.strip(),
                "confirmed_at": now.isoformat(),
                "source": source.strip(),
            }
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            return {"ok": True, "check_id": check_id, "accepted_risk": check["accepted_risk"]}
    raise ValueError(f"unknown check: {check_id}")


def _preserve_check_config(target: Path, manifest: dict[str, object]) -> None:
    """Re-locking the plan must not erase user-authored check environment.

    Check IDs are command identities, so a stored check with the same ID still
    describes the same execution; its env/preflight configuration remains valid.
    """
    if not target.is_file():
        return
    try:
        stored = {
            item.get("id"): item
            for item in load_manifest(target).get("checks", [])
            if isinstance(item, dict) and isinstance(item.get("id"), str)
        }
    except (OSError, ValueError, json.JSONDecodeError):
        return
    checks = manifest.get("checks")
    if not isinstance(checks, list):
        return
    scenarios = manifest.get("scenarios")
    for item in checks:
        if not isinstance(item, dict):
            continue
        old = stored.get(item.get("id"))
        if not isinstance(old, dict):
            continue
        derived_profile = any(
            isinstance(row, dict)
            and "smoke" in row
            and item.get("id") in scenario_check_ids(row)
            for row in (scenarios if isinstance(scenarios, list) else [])
        )
        for key in _CHECK_CONFIG_FIELDS:
            if key == "profile" and derived_profile:
                continue
            if key in old:
                item[key] = old[key]
        if item.get("env_scope", "shared") != "isolated":
            item["parallel_safe"] = False


def _preserve_runtime_state(task_file: str, target: Path, manifest: dict[str, object]) -> None:
    """Re-locking an unchanged plan keeps execution history.

    A plain re-extraction dropped status/revision/evidence/runs, so archive's
    documented re-lock silently un-verified terminal scenarios. Preserve those
    fields only when the existing manifest still validates against the task;
    drift starts clean (stale evidence must not be trusted).
    """
    if not target.is_file():
        return
    try:
        valid, _ = validate_manifest(
            task_file, str(target), allow_missing_e2e_gate=True
        )
    except (OSError, ValueError, json.JSONDecodeError):
        return
    if not valid:
        return
    stored = {
        item.get("id"): item
        for item in load_manifest(target).get("scenarios", [])
        if isinstance(item, dict) and isinstance(item.get("id"), str)
    }
    for item in manifest.get("scenarios", []):
        if not isinstance(item, dict):
            continue
        old = stored.get(item.get("id"))
        if not isinstance(old, dict):
            continue
        for key in _RUNTIME_SCENARIO_FIELDS:
            if key in old:
                item[key] = old[key]


_IMMUTABLE_SCENARIO_FIELDS = (
    "id", "source", "level", "kind", "boundary", "owner", "command", "cwd", "timeout", "depends_on", "check",
    "priority", "exec", "env", "inputs", "why_e2e", "trigger_paths", "smoke",
)

_OPTIONAL_SCENARIO_FIELDS = ("priority", "exec", "env", "inputs", "why_e2e", "trigger_paths", "smoke")


def _heal_legacy_manifest(manifest_file: Path, manifest: dict[str, object], expected: dict[str, object]) -> None:
    """旧版提取规则锁定的 manifest：任务内容未变时原地升级并重锁哈希。

    两种历史规则：`_kind` 精确匹配把带注解的 E2E 锁成 functional；Coverage 无
    命令列时不回退 Contract（command=None）。两类都不改变任务事实，按当前提取
    结果对齐不可变字段并重锁，保留 execution evidence 等运行态字段。
    """
    by_id: dict[str, dict[str, object]] = {}
    scenarios = expected.get("scenarios")
    if isinstance(scenarios, list):
        for item in scenarios:
            if isinstance(item, dict) and isinstance(item.get("id"), str):
                by_id[item["id"]] = item
    current = manifest.get("scenarios")
    if isinstance(current, list):
        for item in current:
            if not isinstance(item, dict):
                continue
            target = by_id.get(item.get("id")) if isinstance(item.get("id"), str) else None
            if target is not None:
                for field in _IMMUTABLE_SCENARIO_FIELDS:
                    if field in target:
                        item[field] = target[field]
    manifest["task_sha256"] = expected["task_sha256"]
    manifest_file.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def validate_manifest(task_file: str, manifest_file: str,
                      allow_missing_e2e_gate: bool = False) -> tuple[bool, str]:
    try:
        manifest = load_manifest(Path(manifest_file))
        stored_source = manifest.get("scenarios_file")
        source_path = ""
        if isinstance(stored_source, str) and stored_source.strip():
            candidate = Path(manifest_file).parent / stored_source
            if not candidate.is_file():
                return False, "acceptance_manifest_scenarios_missing"
            source_path = str(candidate)
        expected = extract_manifest(task_file, scenarios_file=source_path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return False, f"acceptance_manifest_invalid: {exc}"
    schema = manifest.get("schema")
    if schema != _MANIFEST_SCHEMA and schema not in _LEGACY_MANIFEST_SCHEMAS:
        return False, "acceptance_manifest_drift"
    if manifest.get("task_sha256") != expected["task_sha256"]:
        # 旧版规则（无 Contract 回退 + _kind 精确匹配）锁定的 manifest：兼容升级。
        legacy = extract_manifest(task_file, _legacy_kind, contract_fallback=False, merge_source=False)
        if manifest.get("task_sha256") != legacy["task_sha256"]:
            return False, "acceptance_manifest_drift"
        _heal_legacy_manifest(Path(manifest_file), manifest, expected)
    stored_task = manifest.get("task_file", "")
    if not stored_task or (Path(manifest_file).parent / stored_task).resolve() != Path(task_file).resolve():
        return False, "acceptance_manifest_task_mismatch"
    expected_quality = any(
        any(field in scenario for field in ("why_e2e", "trigger_paths", "smoke"))
        for scenario in expected.get("scenarios", []) if isinstance(scenario, Mapping)
    )
    if expected_quality and manifest.get("e2e_gate") != 1 and not allow_missing_e2e_gate:
        return False, "acceptance_manifest_e2e_gate_missing"
    if not isinstance(manifest.get("scenarios"), list):
        return False, "acceptance_manifest_scenarios_changed"
    if schema == _MANIFEST_SCHEMA:
        checks = manifest.get("checks")
        try:
            validate_checks(checks)
        except ValueError as exc:
            return False, f"acceptance_manifest_checks_invalid: {exc}"
        expected_checks = {item["id"]: item for item in expected.get("checks", [])}
        if {item.get("id") for item in checks if isinstance(item, Mapping)} != set(expected_checks):
            return False, "acceptance_manifest_checks_changed"
        stored_checks = {
            item.get("id"): item for item in checks
            if isinstance(item, Mapping) and isinstance(item.get("id"), str)
        }
        for check_id, expected_check in expected_checks.items():
            expected_paths = expected_check.get("paths")
            if expected_paths and stored_checks.get(check_id, {}).get("paths") != expected_paths:
                return False, "acceptance_manifest_check_scope_changed"
    stored = {
        item.get("id"): item
        for item in manifest["scenarios"]
        if isinstance(item, Mapping) and isinstance(item.get("id"), str)
    }
    required = {item["id"] for item in expected["scenarios"]}
    if set(stored) != required:
        return False, "acceptance_manifest_scenarios_changed"
    for item in expected["scenarios"]:
        current = stored[item["id"]]
        for field in _IMMUTABLE_SCENARIO_FIELDS:
            if field in ("check", "checks") and "checks" not in current:
                continue
            if field in _OPTIONAL_SCENARIO_FIELDS and field not in current:
                continue
            if current.get(field) != item.get(field):
                return False, f"acceptance_manifest_field_changed:{item['id']}:{field}"
    text = Path(task_file).read_text(encoding="utf-8")
    for scenario in expected["scenarios"]:
        owner = scenario["owner"]
        section = re.search(rf"(?ms)^##\s+{re.escape(owner)}:.*?(?=^##\s+TASK-|\Z)", text)
        refs = re.search(r"(?m)^- \*\*Acceptance-Refs\*\*:[ \t]*([^\n]*)", section.group(0)) if section else None
        if not refs or scenario["id"] not in re.findall(r"\b[SEB]-\d+\b", refs.group(1)):
            return False, "acceptance_manifest_owner_missing"
    return True, ""


def record_manual_evidence(manifest_file: str, scenario_id: str, confirmed_by: str, evidence: str) -> None:
    if not confirmed_by or confirmed_by.lower().split(":", 1)[0] in {"agent", "assistant", "codex", "claude", "opencode", "costrict"}:
        raise ValueError("manual evidence must be confirmed by a user")
    path = Path(manifest_file)
    data = load_manifest(path)
    scenarios = data.get("scenarios")
    if not isinstance(scenarios, list):
        raise ValueError("invalid manifest scenarios")
    found = False
    owner = ""
    task_file = data.get("task_file")
    for item in scenarios:
        if isinstance(item, dict) and item.get("id") == scenario_id:
            if item.get("kind") != "manual" and item.get("exec") != "manual":
                raise ValueError("scenario is not manual")
            item["status"] = "verified"
            item["evidence"] = {"confirmed_by": confirmed_by, "evidence": evidence}
            found = True
            owner = item.get("owner") if isinstance(item.get("owner"), str) else ""
    if not found:
        raise ValueError("scenario not found")
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if isinstance(task_file, str) and task_file:
        task_path = Path(task_file)
        if not task_path.is_absolute():
            task_path = path.parent / task_path
        _sync_task_evidence(task_path, scenario_id, confirmed_by, evidence, owner)


def _sync_task_evidence(task_file: Path, scenario_id: str, confirmed_by: str, evidence: str, owner: str = "") -> None:
    from cf_acceptance_evidence import sync_task_evidence
    sync_task_evidence(task_file, scenario_id, confirmed_by, evidence, owner)


def main(argv: Optional[Sequence[str]] = None, stdout: IO[str] = sys.stdout) -> int:
    parser = argparse.ArgumentParser(prog=os.environ.get("CF_RUNTIME_COMMAND") or None)
    parser.add_argument("--task-file", default="")
    parser.add_argument("--output", default="")
    parser.add_argument("--scenarios-file", default="")
    parser.add_argument("--verify-plan", action="store_true")
    parser.add_argument("--require-scenarios", action="store_true")
    parser.add_argument("--task-dir", default="")
    parser.add_argument("--record-manual", action="store_true")
    parser.add_argument("--accept-risk", action="store_true")
    parser.add_argument("--project", action="store_true",
                        help="write manifest and project sibling scenarios checks in one step")
    parser.add_argument("--check-id", default="")
    parser.add_argument("--risk-owner", default="")
    parser.add_argument("--risk-reason", default="")
    parser.add_argument("--expires-at", default="")
    parser.add_argument("--scenario-id", default="")
    parser.add_argument("--confirmed-by", default="")
    parser.add_argument("--source", default="")
    parser.add_argument("--evidence", default="")
    args = parser.parse_args(argv)
    try:
        if args.project and not args.task_file:
            raise ValueError("--project requires --task-file")
        if args.verify_plan and not args.task_file:
            raise ValueError("--verify-plan requires --task-file")
        if args.project:
            output = args.output or str(Path(args.task_file).with_name(".acceptance-manifest.json"))
            manifest = write_manifest(args.task_file, output, args.scenarios_file)
            projected = sum(
                1 for item in manifest.get("scenarios", [])
                if isinstance(item, dict) and item.get("checks")
            )
            stdout.write(json.dumps({
                "ok": True,
                "manifest": output,
                "scenarios": len(manifest.get("scenarios", [])),
                "checks": len(manifest.get("checks", [])),
                "projected_scenarios": projected,
            }, ensure_ascii=False))
            return 0
        if args.accept_risk:
            result = record_accepted_risk(
                args.output, args.check_id, args.risk_owner, args.risk_reason,
                args.expires_at, args.confirmed_by, args.source,
            )
            stdout.write(json.dumps(result, ensure_ascii=False))
            return 0
        if args.record_manual:
            if not args.output or not args.scenario_id or not args.evidence:
                raise ValueError("--record-manual requires --output, --scenario-id and --evidence")
            record_manual_evidence(args.output, args.scenario_id, args.confirmed_by, args.evidence)
            stdout.write(json.dumps({"ok": True, "scenario": args.scenario_id}, ensure_ascii=False))
            return 0
        if args.verify_plan:
            if not args.task_dir:
                raise ValueError("--verify-plan requires --task-dir")
            quality: Optional[dict[str, object]] = None
            if args.require_scenarios:
                from cf_scenarios import parse_scenarios, require_source, validate_e2e_quality
                source_path = require_source(args.task_dir)
                source = parse_scenarios(source_path)
                quality = validate_e2e_quality(source["scenarios"])
                if not quality["ok"]:
                    result = {
                        "decision": "block",
                        "reason": "e2e_quality_invalid",
                        "e2e_quality": quality,
                    }
                    stdout.write(json.dumps(result, ensure_ascii=False))
                    return 3
                manifest_path = Path(args.task_dir) / ".acceptance-manifest.json"
                if not manifest_path.is_file():
                    raise ValueError("acceptance_manifest_missing")
                if manifest_path.is_file():
                    locked = load_manifest(manifest_path)
                    rows = {str(item.get("id")): item for item in locked.get("scenarios", [])}
                    check_ids = {str(item.get("id")) for item in locked.get("checks", [])}
                    for scenario in source.get("scenarios", []):
                        sid = str(scenario.get("id"))
                        required = [str(value) for value in scenario.get("checks", [])]
                        unknown = [value for value in required if value not in check_ids]
                        if unknown:
                            raise ValueError(f"unknown_check:{sid}:{','.join(unknown)}")
                        actual = rows.get(sid, {}).get("checks")
                        projected = {str(value) for value in actual} if isinstance(actual, list) else set()
                        if required and projected != set(required):
                            raise ValueError(f"scenario_checks_not_projected:{sid}")
            from cf_spec_context import load_context
            from cf_spec_gate import result_to_data, validate_plan_coverage, validate_stage

            context = load_context(str(Path(args.task_dir) / "spec-context.yml"))
            gate = validate_stage(context, "plan")
            coverage = validate_plan_coverage(context, args.task_file)
            result = {
                "decision": "block" if gate.decision == "block" or coverage.decision == "block" else "pass",
                "gate": result_to_data(gate),
                "coverage": result_to_data(coverage),
                "e2e_quality": quality,
            }
            stdout.write(json.dumps(result, ensure_ascii=False))
            return 0 if result["decision"] == "pass" else 3
        if not args.output:
            raise ValueError("--output is required unless --verify-plan is used")
        if not args.task_file:
            raise ValueError("--task-file is required")
        manifest = write_manifest(args.task_file, args.output, args.scenarios_file)
        stdout.write(json.dumps({"ok": True, "scenarios": len(manifest["scenarios"])}, ensure_ascii=False))
        return 0
    except (OSError, ValueError) as exc:
        stdout.write(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
