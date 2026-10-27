"""Author check registration through real collection before locking a plan."""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Mapping

from codeflow.acceptance.cf_acceptance_schema import scenario_check_ids
from codeflow.acceptance.cf_check_registration import (
    REGISTRATION_FIELDS, CollectionError, register_check, registration_required,
)


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


def register_checks(manifest: dict[str, object], root: str, file: str = "") -> dict[str, object]:
    checks = manifest.get("checks", [])
    overrides = _overrides(file, {str(check["id"]) for check in checks})
    report: dict[str, object] = {"ok": True, "registered": [], "errors": []}
    deadline = time.monotonic() + 60
    for check in checks:
        check_id = str(check["id"])
        rows = [row for row in manifest["scenarios"] if check_id in scenario_check_ids(row)
                and (registration_required(row) or check_id in overrides)]
        if not rows:
            continue
        check.update(overrides.get(check_id, {}))
        try:
            issues = register_check(root, check, rows, deadline)
            if issues:
                raise RegistrationError({"ok": False, "errors": issues})
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
