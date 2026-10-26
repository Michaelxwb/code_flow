"""Extract and validate plan Acceptance Coverage manifests.

This low-level acceptance module owns manifest extraction, immutable-field
hashing and drift validation. The path-frozen CLI entry
(`codeflow.cli.cf_acceptance_manifest`) only parses arguments and prints output.
"""

from __future__ import annotations

import hashlib
import json
import re
import shlex
from pathlib import Path
from typing import Callable, Mapping, Optional, Sequence

from codeflow.acceptance.cf_acceptance_schema import (
    EXEC_MODES, load_manifest, scenario_check_ids, validate_checks, validate_scenarios,
)
from codeflow.core.cf_markdown import column_index, frontmatter_block, table_cells
from codeflow.task.cf_task_doc import TaskDocumentError, parse_task_document


_ROW_RE = re.compile(r"^\|\s*([SEB]-\d+)\s*\|(.+?)\|$")

_MANIFEST_SCHEMA = 3
_LEGACY_MANIFEST_SCHEMAS = (2,)


def kind(level: str) -> str:
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
        index = column_index(cells[1:], *names)
        if index >= 0:
            indexes[key] = index
    return indexes


def _column_value(fields: Sequence[str], columns: Mapping[str, int], key: str, fallback: int) -> str:
    """Prefer named headers; only headerless legacy tables use positional fallback."""
    index = columns.get(key, -1) if columns else fallback
    return fields[index].strip() if 0 <= index < len(fields) else ""


def coverage_execution(coverage: str, scenario: str) -> tuple[str, str]:
    """Return (kind, exec mode) for one Acceptance Coverage table row."""
    columns: dict[str, int] = {}
    for line in coverage.splitlines():
        cells = table_cells(line)
        if not cells:
            continue
        header = _column_indexes(cells)
        if "level" in header:
            columns = header
        if cells[0] == scenario:
            fields = cells[1:]
            return (kind(_column_value(fields, columns, "level", 1)),
                    _parse_exec(_column_value(fields, columns, "exec", 9)))
    return "", ""


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
        for key in ("why_e2e", "trigger_paths", "smoke", "components", "steps", "expected",
                    "expected_refs", "assertions", "preconditions", "defer_reason", "defer_owner", "target_phase", "features", "tags"):
            if key in item:
                entry[key] = item[key]
        immutable.append(entry)
    payload = json.dumps(immutable, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def legacy_kind(level: str) -> str:
    """v1 精确匹配：仅用于识别旧版锁定的 manifest，不做新语义判定。"""
    normalized = level.strip().lower()
    if normalized == "manual":
        return "manual"
    if normalized == "e2e":
        return "e2e"
    return "functional"


def contract_commands(text: str) -> dict[str, str]:
    """Acceptance Contract 表的执行命令（Coverage 表无命令列时的注册回退）。

    Coverage 模板长期只有 6 列，命令实际写在 TASK 段落 Contract 表；提取器只
    读 Coverage 会让新需求 finish 必现 no_executable_scenarios。这里按场景 ID
    回退读取 Contract 的“执行命令”列（按表头定位，兼容列序差异），与 Coverage
    第 7 列（argv JSON）等价。
    """
    commands: dict[str, str] = {}
    try:
        document = parse_task_document(text)
    except TaskDocumentError as exc:
        if exc.code == "task_document_empty":
            return commands
        raise
    for section in document.tasks:
        contract = re.search(
            r"(?ms)^### Acceptance Contract[^\n]*\n(.*?)(?=^### |^## |\Z)", section.body
        )
        if contract is None:
            continue
        command_idx = -1
        for line in contract.group(1).splitlines():
            cells = table_cells(line)
            if not cells:
                continue
            if command_idx == -1:
                match_column = column_index(cells, "命令")
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


_SCENARIO_SOURCE_FIELDS = ("why_e2e", "trigger_paths", "smoke", "components", "steps", "expected", "assertions",
                           "expected_refs", "preconditions", "defer_reason", "target_phase", "features", "tags")


def _source_contract(scenarios_file: str,
                     text: Optional[str] = None) -> tuple[dict[str, object], dict[str, set[str]]]:
    import yaml
    from codeflow.cli.cf_scenarios import ScenarioError, parse_scenarios

    try:
        source = parse_scenarios(scenarios_file, text=text)
        raw_text = Path(scenarios_file).read_text(encoding="utf-8") if text is None else text
        block = frontmatter_block(raw_text)
        if block is None:
            if raw_text.startswith("---"):
                raise ScenarioError("scenario_source_invalid_frontmatter", "frontmatter 缺少闭合 ---")
            block = raw_text
        raw = yaml.safe_load(block) or {}
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
    return source, explicit


def _merge_scenario_source(rows: list[dict[str, object]], scenarios_file: str,
                           text: Optional[str] = None) -> None:
    """Merge E2E precision fields from the canonical scenario source.

    The Acceptance Coverage table is a projection. Quality fields live in the
    scenario source so a plan cannot silently lose its E2E justification when
    the table is regenerated. Only additive fields are merged; a populated
    Coverage cell is never overwritten by a default value.
    """
    if not scenarios_file:
        return
    source, explicit = _source_contract(scenarios_file, text)
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
                      "why_e2e", "trigger_paths", "smoke", "env", "components", "steps", "expected",
                      "expected_refs", "assertions", "preconditions", "defer_reason", "target_phase", "features", "tags"):
            if field in provided:
                row[field] = scenario.get(field)
        if "owner" in provided:
            row["defer_owner"] = scenario.get("owner", "")
        row["kind"] = kind(str(row.get("level", "")))
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
                  scenarios_file: str = "", merge_source: bool = True, *,
                  text: Optional[str] = None, scenario_text: Optional[str] = None) -> dict[str, object]:
    path = Path(task_file)
    text = path.read_text(encoding="utf-8") if text is None else text
    contract_command_cells = contract_commands(text) if contract_fallback else {}
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
        header = table_cells(line)
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
            command_cell = contract_command_cells.get(match.group(1), "")
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
        _merge_scenario_source(rows, scenarios_file, scenario_text)
    validate_scenarios(rows)
    checks = _derive_checks(rows)
    return {"schema": _MANIFEST_SCHEMA, "task_file": str(path), "task_sha256": _manifest_hash(rows),
            "checks": checks, "scenarios": rows}


def extract_manifest(task_file: str, kind_fn: Callable[[str], str] = kind,
                     contract_fallback: bool = True,
                     scenarios_file: str = "", merge_source: bool = True, *,
                     task_text: Optional[str] = None,
                     scenario_text: Optional[str] = None) -> dict[str, object]:
    return _extract_rows(task_file, kind_fn, contract_fallback, scenarios_file, merge_source,
                         text=task_text, scenario_text=scenario_text)


IMMUTABLE_SCENARIO_FIELDS = (
    "id", "source", "level", "kind", "boundary", "owner", "command", "cwd", "timeout", "depends_on", "check",
    "priority", "exec", "env", "inputs", "why_e2e", "trigger_paths", "smoke",
    "components", "steps", "expected", "expected_refs", "assertions", "preconditions", "defer_reason", "defer_owner",
    "target_phase", "features", "tags",
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
                for field in IMMUTABLE_SCENARIO_FIELDS:
                    if field in target:
                        item[field] = target[field]
    manifest["task_sha256"] = expected["task_sha256"]
    manifest_file.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def validate_manifest(task_file: str, manifest_file: str,
                      allow_missing_e2e_gate: bool = False, *,
                      task_text: Optional[str] = None,
                      manifest: Optional[dict[str, object]] = None,
                      scenario_file: str = "",
                      scenario_text: Optional[str] = None) -> tuple[bool, str]:
    try:
        manifest = load_manifest(Path(manifest_file)) if manifest is None else manifest
        stored_source = manifest.get("scenarios_file")
        source_path = ""
        if isinstance(stored_source, str) and stored_source.strip():
            candidate = Path(manifest_file).parent / stored_source
            if not candidate.is_file():
                return False, "acceptance_manifest_scenarios_missing"
            source_path = str(candidate)
        else:
            fallback = Path(task_file).with_suffix(".scenarios.md")
            if scenario_file and fallback.is_file() and fallback.resolve() == Path(scenario_file).resolve():
                source_path = scenario_file
        expected = extract_manifest(task_file, scenarios_file=source_path, task_text=task_text,
                                    scenario_text=scenario_text if source_path else None)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return False, f"acceptance_manifest_invalid: {exc}"
    schema = manifest.get("schema")
    if schema != _MANIFEST_SCHEMA and schema not in _LEGACY_MANIFEST_SCHEMAS:
        return False, "acceptance_manifest_drift"
    if manifest.get("task_sha256") != expected["task_sha256"]:
        # 旧版规则（无 Contract 回退 + _kind 精确匹配）锁定的 manifest：兼容升级。
        legacy = extract_manifest(task_file, legacy_kind, contract_fallback=False, merge_source=False,
                                  task_text=task_text)
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
        for field in IMMUTABLE_SCENARIO_FIELDS:
            if field in ("check", "checks") and "checks" not in current:
                continue
            if field in _OPTIONAL_SCENARIO_FIELDS and field not in current:
                continue
            if current.get(field) != item.get(field):
                return False, f"acceptance_manifest_field_changed:{item['id']}:{field}"
    text = Path(task_file).read_text(encoding="utf-8") if task_text is None else task_text
    for scenario in expected["scenarios"]:
        owner = scenario["owner"]
        section = re.search(rf"(?ms)^##\s+{re.escape(owner)}:.*?(?=^##\s+TASK-|\Z)", text)
        refs = re.search(r"(?m)^- \*\*Acceptance-Refs\*\*:[ \t]*([^\n]*)", section.group(0)) if section else None
        if not refs or scenario["id"] not in re.findall(r"\b[SEB]-\d+\b", refs.group(1)):
            return False, "acceptance_manifest_owner_missing"
    return True, ""
