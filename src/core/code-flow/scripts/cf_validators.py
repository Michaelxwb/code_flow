#!/usr/bin/env python3
"""Validator engine: parse validation.yml, match triggers, execute commands.

L1 domain module. It owns the single interpretation of `.code-flow/validation.yml`
(four states: missing / empty / valid / parse_error), trigger matching,
deadline-bound execution, and the content-fingerprint result cache. Consumers:
`cf_validation` (validate), `cf_task_runtime` (finish), `cf_stop_hook` (Stop),
and `cf_task_workflow` (layer counts). Dependencies stay in L0/L1: `cf_core`,
`cf_exec_base`, and `cf_log`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import fnmatch
import hashlib
import json
import math
import os
from pathlib import Path
import re
import time
from typing import Mapping, NamedTuple, Optional, Sequence

import cf_log
from cf_core import normalize_path
from cf_exec_base import build_argv, remaining_seconds, run_command, worktree_fingerprint

MISSING = "missing"
EMPTY = "empty"
VALID = "valid"
PARSE_ERROR = "parse_error"

VALIDATION_CACHE_FILE = ".validation-cache.json"
MAX_VALIDATION_CACHE_ENTRIES = 256
_BRACE_RE = re.compile(r"\{([^{}]+)\}")


@dataclass(frozen=True)
class ValidatorConfig:
    """Single interpretation of .code-flow/validation.yml."""

    state: str
    validators: tuple[Mapping[str, object], ...] = ()
    error: str = ""
    path: str = ""


class ValidatorRun(NamedTuple):
    failures: list[dict[str, object]]
    truncated: bool
    reused: int


def expand_braces(pattern: str) -> list:
    """Expand one level of `{a,b}` alternation → list of fnmatch patterns."""
    match = _BRACE_RE.search(pattern)
    if not match:
        return [pattern]
    head, tail = pattern[: match.start()], pattern[match.end():]
    out = []
    for option in match.group(1).split(","):
        out.extend(expand_braces(head + option + tail))
    return out


def trigger_matches(trigger: str, rel_path: str) -> bool:
    """fnmatch with brace expansion; `**/` prefix also matches root files."""
    rel_path = normalize_path(rel_path)
    for pattern in expand_braces(trigger or ""):
        candidates = [pattern]
        if pattern.startswith("**/"):
            candidates.append(pattern[3:])
        if any(fnmatch.fnmatch(rel_path, candidate) for candidate in candidates):
            return True
    return False


def _parse_error(path: str, message: str) -> ValidatorConfig:
    cf_log.warn(f"{path}: {message}")
    return ValidatorConfig(PARSE_ERROR, error=message, path=path)


def _classify(path: str, data: object) -> ValidatorConfig:
    if data is None or data == {}:
        return ValidatorConfig(EMPTY, path=path)
    if not isinstance(data, dict):
        return _parse_error(path, "validation.yml must be a YAML mapping")
    validators = data.get("validators")
    if validators is None or validators == []:
        return ValidatorConfig(EMPTY, path=path)
    if not isinstance(validators, list):
        return _parse_error(path, "validators must be a list")
    for index, item in enumerate(validators, 1):
        if not isinstance(item, Mapping):
            return _parse_error(path, f"validator #{index} must be a mapping")
    return ValidatorConfig(VALID, tuple(validators), path=path)


def load_validators(project_root: str) -> ValidatorConfig:
    """Read validation.yml into one of four explicit states (API-01)."""
    path = os.path.join(project_root, ".code-flow", "validation.yml")
    if not os.path.exists(path):
        return ValidatorConfig(MISSING, path=path)
    try:
        import yaml
    except ImportError as exc:
        return _parse_error(path, f"PyYAML unavailable: {exc}")
    try:
        with open(path, "r", encoding="utf-8") as file:
            data = yaml.safe_load(file)
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        return _parse_error(path, str(exc))
    return _classify(path, data)


def package_script_validators(project_root: str) -> tuple[Mapping[str, object], ...]:
    """Existing product policy for a missing/empty validation.yml."""
    package = Path(project_root) / "package.json"
    if not package.is_file():
        return ()
    data = json.loads(package.read_text(encoding="utf-8"))
    scripts = data.get("scripts", {}) if isinstance(data, dict) else {}
    if not isinstance(scripts, dict):
        raise ValueError("invalid package scripts")
    return tuple(
        {"name": name, "trigger": "*", "command": f"npm run {name}", "timeout": 60000}
        for name in ("test", "lint") if isinstance(scripts.get(name), str)
    )


def resolve_validators(
    project_root: str,
) -> tuple[ValidatorConfig, tuple[Mapping[str, object], ...]]:
    """Config state plus the effective validators for this project.

    missing/empty keep the product policy (package.json test/lint fallback);
    parse_error returns no validators so callers must fail closed on state.
    """
    config = load_validators(project_root)
    if config.state == VALID:
        return config, config.validators
    if config.state == PARSE_ERROR:
        return config, ()
    return config, package_script_validators(project_root)


def is_heavy(validator: object) -> bool:
    return isinstance(validator, Mapping) and validator.get("heavy") is True


def _validator_failure(validator: Mapping[str, object], detail: str,
                       incomplete: bool = False) -> dict[str, object]:
    result: dict[str, object] = {
        "name": validator.get("name", "validator"),
        "on_fail": validator.get("on_fail", ""),
        "detail": detail,
    }
    if incomplete:
        result["incomplete"] = True
    return result


def _validator_argv(root: str, validator: Mapping[str, object], matched: list,
                    strict: bool) -> list:
    existing = [name for name in matched if os.path.isfile(os.path.join(root, name))]
    template = str(validator.get("command", ""))
    if "{files}" in template and not existing:
        return []
    argv = build_argv(template, existing)
    if not argv and strict:
        raise ValueError("validator command missing")
    return argv


def _tool_missing(detail: str) -> bool:
    """Recognize 'tool not installed' output so template validators (mypy, npx …)
    do not block projects that have not installed the optional tool yet."""
    lowered = detail.lower()
    markers = (
        "no module named",
        "modulenotfounderror",
        "command not found",
        "is not recognized as an internal or external command",
        "could not determine executable to run",
        "not found in $path",
    )
    return any(marker in lowered for marker in markers)


def _validator_result(root: str, validator: Mapping[str, object], argv: list, sid: str,
                      deadline: Optional[float], strict: bool) -> tuple[list, bool]:
    try:
        timeout = float(validator.get("timeout", 30000)) / 1000.0
    except (ValueError, TypeError):
        if strict:
            return [_validator_failure(validator, "invalid validator timeout")], False
        timeout = 30.0
    if not math.isfinite(timeout) or timeout <= 0:
        return [_validator_failure(validator, "invalid validator timeout")], False
    outcome = run_command(argv, root, timeout, deadline)
    passed = outcome["status"] == "ok" and outcome["returncode"] == 0
    if outcome["status"] == "deadline_exceeded":
        return [_validator_failure(validator, "预算耗尽未执行", True)], True
    timed_out = outcome["status"] == "timeout"
    detail = (f"超时（>{timeout:.0f}s），未完成" if timed_out else
              (str(outcome.get("stdout", "")) + str(outcome.get("stderr", ""))).strip()[-400:])
    if outcome["status"] == "spawn_error":
        if validator.get("skip_if_missing") is True:
            cf_log.degrade(root, "stop_check", f"{validator.get('name')}:tool_missing", sid)
            return [], False
        cf_log.degrade(root, "stop_check", f"{validator.get('name')}:{outcome['stderr']}", sid)
        if not strict:
            return [], False
    elif not passed and not timed_out and validator.get("skip_if_missing") is True and _tool_missing(detail):
        cf_log.degrade(root, "stop_check", f"{validator.get('name')}:tool_missing", sid)
        return [], False
    cf_log.append_event(root, "stop_check",
                        {"trigger": validator.get("trigger", ""),
                         "cmd": str(validator.get("command", ""))[:120], "passed": passed}, sid)
    return ([] if passed else [_validator_failure(validator, detail)]), timed_out


def _tree_fingerprint(project_root: str, validators: Sequence[object]) -> str:
    """工作树内容指纹（内容寻址，忽略 .code-flow），与提交状态无关。

    已提交内容取 blob SHA，未提交/未跟踪内容用工作区文件哈希补齐；未跟踪文件
    只纳入命中任一 validator trigger 的路径（构建/测试产物不使缓存失效）。
    同一内容在提交前后得到相同指纹；返回 "" 表示无法判定（禁用缓存）。
    """
    triggers = [str(item.get("trigger", "")) for item in validators if isinstance(item, Mapping)]
    if triggers:
        untracked_filter = lambda path: any(trigger_matches(trigger, path) for trigger in triggers)
    else:
        untracked_filter = None
    return worktree_fingerprint(project_root, untracked_filter)


def _validation_cache_path(project_root: str) -> Path:
    return Path(project_root) / ".code-flow" / VALIDATION_CACHE_FILE


def _load_validation_cache(project_root: str) -> dict:
    try:
        data = json.loads(_validation_cache_path(project_root).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _save_validation_cache(project_root: str, cache: dict) -> None:
    if len(cache) > MAX_VALIDATION_CACHE_ENTRIES:
        ordered = sorted(
            cache.items(),
            key=lambda item: str(item[1].get("at", "")) if isinstance(item[1], dict) else "",
        )
        cache = dict(ordered[-MAX_VALIDATION_CACHE_ENTRIES:])
    try:
        path = _validation_cache_path(project_root)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(cache, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except OSError:
        return  # 缓存写入失败不影响验证结论


def _cache_key(argv: Sequence[str]) -> str:
    return hashlib.sha256(json.dumps({"argv": list(argv)}, ensure_ascii=False).encode()).hexdigest()


def _run_one(project_root: str, validator: object, files: Sequence[str], sid: str,
             deadline: Optional[float], strict: bool, fingerprint: str,
             cache_data: dict, dirty: list[bool]) -> ValidatorRun:
    if not isinstance(validator, Mapping):
        failures = [_validator_failure({}, "invalid validator record")] if strict else []
        return ValidatorRun(failures, False, 0)
    matched = [path for path in files if trigger_matches(validator.get("trigger", ""), path)]
    if not matched:
        return ValidatorRun([], False, 0)
    remaining = remaining_seconds(deadline)
    if remaining is not None and remaining <= 0:
        return ValidatorRun([_validator_failure(validator, "预算耗尽未执行", True)], True, 0)
    try:
        argv = _validator_argv(project_root, validator, matched, strict)
    except ValueError as exc:
        return ValidatorRun([_validator_failure(validator, f"validator 配置错误: {exc}")], False, 0)
    if not argv:
        return ValidatorRun([], False, 0)
    key = _cache_key(argv)
    if fingerprint:
        entry = cache_data.get(key)
        if isinstance(entry, dict) and entry.get("fingerprint") == fingerprint:
            return ValidatorRun([], False, 1)
    errors, incomplete = _validator_result(project_root, validator, argv, sid, deadline, strict)
    if fingerprint and not errors and not incomplete:
        cache_data[key] = {
            "fingerprint": fingerprint,
            "at": datetime.now(timezone.utc).isoformat(),
            "command": str(validator.get("command", ""))[:200],
        }
        dirty[0] = True
    return ValidatorRun(errors, incomplete, 0)


def run_validators(
    project_root: str,
    config: ValidatorConfig,
    files: Sequence[str],
    sid: str,
    deadline: Optional[float] = None,
    *,
    strict: bool = False,
    cache: bool = True,
) -> ValidatorRun:
    """Match validators, execute argv under one deadline, report unrun work.

    `cache` reuses passing results when the worktree content fingerprint and
    argv are unchanged (failures are never cached). Returns (failures,
    truncated, reused).
    """
    validators = list(config.validators)
    fingerprint = _tree_fingerprint(project_root, validators) if cache and validators else ""
    cache_data = _load_validation_cache(project_root) if fingerprint else {}
    dirty = [False]
    failures: list[dict[str, object]] = []
    truncated = False
    reused = 0
    for validator in validators:
        outcome = _run_one(project_root, validator, files, sid, deadline, strict,
                           fingerprint, cache_data, dirty)
        failures.extend(outcome.failures)
        truncated = truncated or outcome.truncated
        reused += outcome.reused
    if dirty[0]:
        _save_validation_cache(project_root, cache_data)
    return ValidatorRun(failures, truncated, reused)
