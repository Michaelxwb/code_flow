"""Validate test registration against a bounded, real collection command."""
from __future__ import annotations

import json
from pathlib import Path
import re
import shlex
import time
from typing import Mapping, Sequence

from codeflow.acceptance.cf_acceptance_schema import scenario_check_ids
from codeflow.core.cf_exec_base import run_command


REGISTRATION_FIELDS = ("suite", "test_ids", "markers", "collect")


class CollectionError(ValueError):
    def __init__(self, code: str, details: Mapping[str, object]) -> None:
        super().__init__(code)
        self.code = code
        self.details = dict(details)


def _pytest_markers(argv: Sequence[str]) -> list[str]:
    positions = [index for index, value in enumerate(argv[:-1]) if value == "-m" and argv[index + 1] != "pytest"]
    expression = argv[positions[-1] + 1] if positions else ""
    markers = [value.strip() for value in expression.split(" and ")] if expression else []
    if any(not re.fullmatch(r"[a-zA-Z_][a-zA-Z0-9_]*", value) for value in markers):
        raise ValueError("check_collection_marker_expression_invalid")
    return markers


def _pytest_collection(output: str, argv: Sequence[str]) -> list[dict[str, object]]:
    markers = _pytest_markers(argv)
    return [{"id": line.strip(), "markers": markers,
             "capabilities": ["browser"] if "browser" in markers else []}
            for line in output.splitlines() if re.fullmatch(r"[^\s]+\.py::[^\s]+", line.strip())]


def _objects(value: object) -> list[Mapping[str, object]]:
    if not isinstance(value, list) or not all(isinstance(item, Mapping) for item in value):
        raise ValueError("check_collection_invalid_playwright_structure")
    return value


def _browser_projects(config: Mapping[str, object]) -> set[str]:
    projects: set[str] = set()
    for project in _objects(config.get("projects", [])):
        metadata = project.get("metadata", {})
        capabilities = metadata.get("capabilities", []) if isinstance(metadata, Mapping) else None
        if not isinstance(capabilities, list) or not all(isinstance(value, str) for value in capabilities):
            raise ValueError("check_collection_invalid_project_capabilities")
        if "browser" in capabilities:
            projects.add(str(project.get("name", "")).lower())
    return projects | {"chromium", "firefox", "webkit", "browser"}


def _playwright_spec(spec: Mapping[str, object], suite: Mapping[str, object], report_root: Path,
                     root: str, projects: set[str]) -> list[dict[str, object]]:
    file = spec.get("file", suite.get("file", ""))
    tags = spec.get("tags", [])
    if not isinstance(file, str) or not isinstance(tags, list) or not all(isinstance(value, str) for value in tags):
        raise ValueError("check_collection_invalid_playwright_spec")
    if type(spec.get("line")) is not int:
        raise ValueError("check_collection_invalid_playwright_location")
    file = (report_root / file).resolve().relative_to(Path(root).resolve()).as_posix()
    tests: list[dict[str, object]] = []
    for case in _objects(spec.get("tests", [])):
        project = case.get("projectName", "")
        if not isinstance(project, str):
            raise ValueError("check_collection_invalid_playwright_project")
        tests.append({"id": f"{file}:{spec['line']}@{project}", "markers": [tag.lstrip("@") for tag in tags],
                      "capabilities": ["browser"] if project.lower() in projects else []})
    return tests


def _playwright_collection(data: Mapping[str, object], root: str) -> list[dict[str, object]]:
    tests: list[dict[str, object]] = []
    config = data.get("config", {})
    if not isinstance(config, Mapping) or not isinstance(config.get("rootDir", root), str):
        raise ValueError("check_collection_invalid_playwright_config")
    report_root = Path(str(config.get("rootDir", root)))
    projects = _browser_projects(config)
    pending = list(_objects(data.get("suites", [])))
    while pending:
        suite = pending.pop()
        if not isinstance(suite, Mapping):
            raise ValueError("check_collection_invalid_playwright_suite")
        pending.extend(_objects(suite.get("suites", [])))
        for spec in _objects(suite.get("specs", [])):
            tests.extend(_playwright_spec(spec, suite, report_root, root, projects))
    return tests


def _parse_collection(output: str, config: Mapping[str, object], root: str) -> list[Mapping[str, object]]:
    fmt = config.get("format", "json")
    if fmt == "pytest":
        return _pytest_collection(output, config["argv"])
    try:
        data = json.loads(output)
    except json.JSONDecodeError as exc:
        raise ValueError("check_collection_invalid_json") from exc
    if not isinstance(data, Mapping):
        raise ValueError("check_collection_invalid_tests")
    tests = _playwright_collection(data, root) if fmt == "playwright" else data.get("tests")
    if fmt not in ("json", "pytest", "playwright") or not isinstance(tests, list):
        raise ValueError("check_collection_invalid_format")
    for test in tests:
        if not isinstance(test, Mapping) or not isinstance(test.get("id"), str):
            raise ValueError("check_collection_invalid_tests")
        for field in ("capabilities", "markers"):
            values = test.get(field, [])
            if not isinstance(values, list) or not all(isinstance(value, str) for value in values):
                raise ValueError("check_collection_invalid_tests")
    return tests


def _finding(code: str, scenario: str, check: str, message: str) -> dict[str, str]:
    return {"code": code, "scenario": scenario, "check_id": check, "message": message}


def _execution_argv(root: str, check: Mapping[str, object]) -> list[str]:
    command = check.get("command")
    if not isinstance(command, list) or not all(isinstance(value, str) for value in command):
        return []
    expanded = list(command)
    for _ in range(4):
        if not expanded or Path(expanded[0]).name not in ("npm", "pnpm", "yarn"):
            return expanded
        offset = 2 if len(expanded) > 1 and expanded[1] == "run" else 1
        if len(expanded) <= offset:
            return []
        package = Path(root) / str(check.get("cwd", ".")) / "package.json"
        data = json.loads(package.read_text(encoding="utf-8"))
        script = data.get("scripts", {}).get(expanded[offset])
        if not isinstance(script, str):
            return []
        lexer = shlex.shlex(script, posix=True, punctuation_chars=True)
        lexer.whitespace_split = True
        tokens = list(lexer)
        if any(value in ("&&", "||", ";", "|", ">", ">>", "&") for value in tokens):
            raise ValueError("check_execution_script_requires_direct_command")
        expanded = tokens + [value for value in expanded[offset + 1:] if value != "--"]
    return []


def _execution_matches(root: str, check: Mapping[str, object], selected: Sequence[Mapping[str, object]]) -> bool:
    from codeflow.acceptance.cf_check_inputs import match_path
    argv = _execution_argv(root, check)
    if not argv or not selected or any(value in argv for value in ("-k", "-g", "--grep", "--grep-invert")):
        return False
    pytest = any(Path(value).name in ("pytest", "py.test") for value in argv)
    markers = _pytest_markers(argv) if pytest else []
    if markers and any(not set(markers) <= set(item.get("markers", [])) for item in selected):
        return False
    selectors: list[str] = []
    for value in argv:
        normalized = value.replace("\\", "/").removeprefix("./")
        if normalized.startswith(str(Path(root).resolve()) + "/"):
            normalized = normalized[len(str(Path(root).resolve())) + 1:]
        if re.fullmatch(r"[\w./*?:-]+\.(?:py|[cm]?[jt]sx?)(?::[\w:\[\].-]+)?", normalized):
            selectors.append(normalized)
    if selectors:
        return all(any(match_path(str(item["id"]).split("@", 1)[0], selector)
                       or match_path(str(item["id"]).split("@", 1)[0].split(":", 1)[0], selector)
                       for selector in selectors) for item in selected)
    if pytest:
        return bool(markers)
    return any(Path(value).name in ("playwright", "cypress") for value in argv)


def _collected(root: str, check: Mapping[str, object], deadline: float | None = None) -> dict[str, Mapping[str, object]]:
    config = check.get("collect")
    if not isinstance(config, Mapping):
        raise ValueError("check_collection_missing")
    argv = config.get("argv")
    if not isinstance(argv, list) or not argv or not all(isinstance(item, str) for item in argv):
        raise ValueError("check_collection_invalid")
    timeout = config.get("timeout", 10)
    if isinstance(timeout, bool) or not isinstance(timeout, (float, int)) or not 0 < timeout <= 60:
        raise ValueError("check_collection_timeout_invalid")
    directory = (Path(root) / str(check.get("cwd", "."))).resolve()
    if directory != Path(root).resolve() and Path(root).resolve() not in directory.parents:
        raise ValueError("check_collection_outside_project")
    result = run_command(argv, str(directory), float(timeout), deadline)
    if result.get("status") != "ok" or result.get("returncode") != 0:
        raise CollectionError("check_collection_failed", {"command": argv, "cwd": str(directory),
            "exit_code": result.get("returncode"), "status": result.get("status"),
            "output": (str(result.get("stdout", "")) + str(result.get("stderr", "")))[-4000:]})
    output = str(result.get("stdout", ""))
    if len(output.encode()) > 2_000_000:
        raise ValueError("check_collection_too_large")
    tests = _parse_collection(output, config, root)
    if len({item["id"] for item in tests}) != len(tests):
        raise ValueError("check_collection_duplicate_test")
    return {str(item["id"]): item for item in tests}


def _requirements(row: Mapping[str, object]) -> tuple[bool, set[str]]:
    browser = str(row.get("level", row.get("kind", ""))).lower() == "e2e"
    markers: set[str] = set()
    if row.get("smoke"):
        markers.add("smoke")
    if row.get("level") == "capacity" or "capacity" in row.get("tags", []):
        markers.add("capacity")
    return browser, markers


def _registration_issues(root: str, row: Mapping[str, object], check: Mapping[str, object],
                          collected: Mapping[str, Mapping[str, object]]) -> list[dict[str, str]]:
    scenario, check_id = str(row.get("id", "")), str(check.get("id", ""))
    browser, markers = _requirements(row)
    errors: list[dict[str, str]] = []
    test_ids = check.get("test_ids", [])
    if not isinstance(test_ids, list) or not test_ids or not all(isinstance(value, str) for value in test_ids):
        return [_finding("check_test_ids_missing", scenario, check_id, "check 必须登记具体测试 ID")]
    selected = [collected[value] for value in test_ids if value in collected]
    if len(selected) != len(test_ids):
        errors.append(_finding("check_test_not_collected", scenario, check_id, "登记的测试 ID 未全部被真实收集"))
    try:
        matches = _execution_matches(root, check, selected)
    except (OSError, ValueError) as exc:
        errors.append(_finding("check_execution_config_invalid", scenario, check_id, str(exc)))
        matches = False
    if not matches:
        errors.append(_finding("check_execution_selection_mismatch", scenario, check_id,
                               "实际执行命令必须选择登记用例；不可验证的 grep/-k 过滤请改用具体测试 ID"))
    if browser and (check.get("suite") != "browser" or any("browser" not in item.get("capabilities", []) for item in selected)):
        errors.append(_finding("e2e_check_not_browser", scenario, check_id, "E2E check 必须属于 browser 套件并收集到浏览器能力用例"))
    for marker in sorted(markers):
        if marker not in check.get("markers", []) or any(marker not in item.get("markers", []) for item in selected):
            code = "capacity_check_not_marked" if marker == "capacity" else "smoke_check_not_registered"
            errors.append(_finding(code, scenario, check_id, f"check 与真实收集用例必须包含 {marker} 标记"))
    return errors


def validate_registration(root: str, scenarios: Sequence[Mapping[str, object]],
                           checks: Sequence[Mapping[str, object]]) -> dict[str, object]:
    by_id = {str(check["id"]): check for check in checks}
    cache: dict[str, dict[str, Mapping[str, object]] | Exception] = {}
    errors: list[dict[str, object]] = []
    deadline = time.monotonic() + 60
    runnable_smoke = runnable_browser = 0
    for row in scenarios:
        browser, markers = _requirements(row)
        if not browser and not markers:
            continue
        ids = scenario_check_ids(row)
        row_errors: list[dict[str, object]] = []
        if not ids:
            row_errors.append(_finding("scenario_check_missing", str(row["id"]), "", "需要可执行 check 绑定"))
        for check_id in ids:
            check = by_id.get(check_id)
            if check is None:
                row_errors.append(_finding("unknown_check", str(row["id"]), check_id, "引用的 check 不存在"))
                continue
            if check_id not in cache:
                try:
                    cache[check_id] = _collected(root, check, deadline)
                except (OSError, ValueError) as exc:
                    cache[check_id] = exc
            collected = cache[check_id]
            if isinstance(collected, Exception):
                detail = collected.details if isinstance(collected, CollectionError) else {}
                row_errors.append({**_finding(str(collected), str(row["id"]), check_id, "无法验证测试收集与套件登记"), **detail})
            else:
                row_errors.extend(_registration_issues(root, row, check, collected))
        errors.extend(row_errors)
        runnable_smoke += int(bool(row.get("smoke")) and not row_errors)
        runnable_browser += int(browser and not row_errors)
    return {"ok": not errors, "errors": errors, "runnable_smoke_count": runnable_smoke,
            "runnable_browser_count": runnable_browser, "collected_checks": len(cache)}
