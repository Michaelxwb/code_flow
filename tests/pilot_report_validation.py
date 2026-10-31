"""Conservative validation for a fluxion pilot report under construction.

Completeness checks do not authenticate measurements or establish equivalence.
Until those checks exist, neither acceptance conclusion is granted.
"""
from __future__ import annotations

import math
from statistics import median
from typing import Any


def validate_report(report: dict[str, Any]) -> dict[str, Any]:
    """Reject unsupported conclusions, including reports labelled synthetic."""
    errors = []
    if report.get("source") != "fluxion":
        errors.append("source must be real fluxion, not synthetic or missing")
    if not report.get("measurements"):
        errors.append("real measurement records are missing")
    if not report.get("coverage_evidence"):
        errors.append("replacement and defect-injection evidence is missing")
    errors.append("measurement provenance and coverage equivalence are not yet verified")
    return {"performance_pass": False, "coverage_pass": False, "errors": errors}


def _validate_sample(sample: object, mode: str) -> str:
    if not isinstance(sample, dict):
        return "sample must be an object"
    elapsed = sample.get("elapsed_ms")
    result = sample.get("result")
    if isinstance(elapsed, bool) or not isinstance(elapsed, (int, float)) or not math.isfinite(elapsed) or elapsed <= 0:
        return "elapsed time must be finite and positive"
    if sample.get("exit_code") != 0 or not isinstance(result, dict) or result.get("decision") != "pass":
        return "sample did not pass"
    counts = (result.get("executed"), result.get("reused"))
    if counts != ((1, 0) if mode == "cold" else (0, 1)):
        return "execution counts do not match mode"
    argv = sample.get("argv")
    if not isinstance(argv, list) or not argv or not all(isinstance(item, str) and item for item in argv):
        return "sample command is missing"
    return ""


def _validate_raw_phase(report: dict[str, Any], phase: str) -> tuple[dict[str, float], list[str]]:
    errors: list[str] = []
    medians: dict[str, float] = {}
    if report.get("source") != "fluxion" or report.get("phase") != phase or report.get("origin") == "synthetic":
        errors.append(f"{phase}: source or phase is invalid")
    runs = report.get("runs")
    if not isinstance(runs, list):
        return medians, errors + [f"{phase}: raw runs are missing"]
    for mode in ("cold", "reuse"):
        samples = [item for item in runs if isinstance(item, dict) and item.get("mode") == mode]
        valid_repeats = all(type(item.get("repeat")) is int for item in samples)
        if len(samples) != 3 or not valid_repeats or {item["repeat"] for item in samples} != {1, 2, 3}:
            errors.append(f"{phase}/{mode}: exactly three numbered runs required")
            continue
        failures = [_validate_sample(item, mode) for item in samples]
        if any(failures):
            errors.extend(f"{phase}/{mode}: {failure}" for failure in failures if failure)
            continue
        medians[mode] = median(float(item["elapsed_ms"]) for item in samples)
    if len(runs) != 6:
        errors.append(f"{phase}: unexpected number of raw runs")
    return medians, errors


def _command_signature(sample: object) -> tuple[tuple[str, ...], tuple[str, ...]] | None:
    if not isinstance(sample, dict):
        return None
    argv, result = sample.get("argv"), sample.get("result")
    if not isinstance(argv, list) or not all(isinstance(item, str) for item in argv) or not isinstance(result, dict):
        return None
    rows = result.get("results")
    if not isinstance(rows, list) or len(rows) != 1 or not isinstance(rows[0], dict):
        return None
    config = rows[0].get("check_config")
    command = config.get("command") if isinstance(config, dict) else None
    if not isinstance(command, list) or not command or not all(isinstance(item, str) for item in command):
        return None
    if "--manifest" not in argv or argv.index("--manifest") + 1 >= len(argv):
        return None
    index = argv.index("--manifest")
    return tuple(argv[:index] + argv[index + 2:]), tuple(command)


def validate_raw_comparison(old: dict[str, Any], new: dict[str, Any]) -> dict[str, Any]:
    """Check consistency of one recorded comparison, without authenticating its origin."""
    old_medians, errors = _validate_raw_phase(old, "old")
    new_medians, new_errors = _validate_raw_phase(new, "new")
    errors.extend(new_errors)
    for field in ("fluxion_commit", "manifest_sha256", "platform", "python", "uv"):
        if not isinstance(old.get(field), str) or not old[field] or old[field] != new.get(field):
            errors.append(f"identity mismatch or missing: {field}")
    runs = [item for report in (old, new) for item in (report.get("runs") if isinstance(report.get("runs"), list) else [])
            if isinstance(item, dict)]
    signatures = [_command_signature(item) for item in runs]
    if not signatures or None in signatures or len(set(signatures)) != 1:
        errors.append("actual check or runner commands differ or are missing")
    return {"medians_ms": {"old": old_medians, "new": new_medians}, "errors": errors}
