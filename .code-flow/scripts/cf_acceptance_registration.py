"""Author check registration through real collection before locking a plan."""
from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Mapping, Sequence

from cf_acceptance_schema import scenario_check_ids, validate_checks
from cf_check_registration import (REGISTRATION_FIELDS, CollectionError, _collected,
                                   _execution_argv, _pytest_markers, _requirements,
                                   _registration_issues)


class RegistrationError(ValueError):
    def __init__(self, report: Mapping[str, object]) -> None:
        self.report = dict(report)
        super().__init__("check_registration_failed")


def _overrides(file: str, ids: set[str]) -> dict[str, Mapping[str, object]]:
    if not file:
        return {}
    data = json.loads(Path(file).read_text(encoding="utf-8"))
    checks = data.get("checks") if isinstance(data, dict) else None
    if not isinstance(checks, dict) or set(checks) - ids:
        raise ValueError("registration_file_invalid_check_ids")
    for check_id, config in checks.items():
        if not isinstance(config, dict) or set(config) - set(REGISTRATION_FIELDS):
            raise ValueError(f"registration_file_invalid_fields:{check_id}")
    return checks


def _collection_config(root: str, check: Mapping[str, object], markers: set[str]) -> dict[str, object]:
    argv = _execution_argv(root, check)
    if any(Path(value).name in ("pytest", "py.test") for value in argv):
        if "-k" in argv:
            raise ValueError("check_execution_selection_mismatch: use concrete pytest node IDs")
        selected_markers = set(_pytest_markers(argv)) | markers
        argv = [value for value in argv if not re.fullmatch(r"-q+|--quiet", value)]
        argv += ["--collect-only", "--verbosity=-1"]
        if selected_markers:
            argv += ["-m", " and ".join(sorted(selected_markers))]
        return {"argv": argv, "format": "pytest", "timeout": 10}
    if any(Path(value).name == "playwright" for value in argv):
        return {"argv": argv + ["--list", "--reporter=json"], "format": "playwright", "timeout": 10}
    raise ValueError("check_collection_inference_unsupported: supply --registration-file")


def _register_check(root: str, check: dict[str, object], rows: Sequence[Mapping[str, object]], deadline: float) -> None:
    validate_checks([check])
    requirements = [_requirements(row) for row in rows]
    browser = any(item[0] for item in requirements)
    markers = set().union(*(item[1] for item in requirements))
    if "collect" not in check:
        check["collect"] = _collection_config(root, check, markers | ({"browser"} if browser else set()))
    collected = _collected(root, check, deadline)
    if not collected:
        raise ValueError("check_collection_empty")
    check.setdefault("test_ids", sorted(collected))
    selected = [collected[value] for value in check["test_ids"] if value in collected]
    actual_markers = set.intersection(*(set(item.get("markers", [])) for item in selected)) if selected else set()
    check.setdefault("markers", sorted(actual_markers))
    if browser and selected and all("browser" in item.get("capabilities", []) for item in selected):
        check.setdefault("suite", "browser")
    validate_checks([check])
    errors = [issue for row in rows for issue in _registration_issues(root, row, check, collected)]
    if errors:
        raise RegistrationError({"ok": False, "errors": errors})


def register_checks(manifest: dict[str, object], root: str, file: str = "") -> dict[str, object]:
    checks = manifest.get("checks", [])
    overrides = _overrides(file, {str(check["id"]) for check in checks})
    report: dict[str, object] = {"ok": True, "registered": [], "errors": []}
    deadline = time.monotonic() + 60
    for check in checks:
        check_id = str(check["id"])
        rows = [row for row in manifest["scenarios"] if check_id in scenario_check_ids(row)
                and (any(_requirements(row)) or check_id in overrides)]
        if not rows:
            continue
        check.update(overrides.get(check_id, {}))
        try:
            _register_check(root, check, rows, deadline)
        except (OSError, ValueError) as exc:
            details = exc.report if isinstance(exc, RegistrationError) else (
                exc.details if isinstance(exc, CollectionError) else {})
            report["errors"].append({"check_id": check_id, "error": str(exc), **details})
        else:
            report["registered"].append(check_id)
    report["ok"] = not report["errors"]
    if not report["ok"]:
        raise RegistrationError(report)
    return report
