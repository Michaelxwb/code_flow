#!/usr/bin/env python3
"""Lock and validate plan Acceptance Coverage entries."""

from __future__ import annotations

import argparse
import os
import json
from datetime import datetime, timezone
from pathlib import Path
import re
import sys
from typing import IO, Mapping, Optional, Sequence

from codeflow.acceptance.cf_acceptance_manifest_core import (
    IMMUTABLE_SCENARIO_FIELDS,
    contract_commands as _contract_commands,
    coverage_execution,
    extract_manifest,
    kind as _kind,
    legacy_kind as _legacy_kind,
    validate_manifest,
)
from codeflow.acceptance.cf_acceptance_schema import load_manifest, scenario_check_ids


_RUNTIME_SCENARIO_FIELDS = ("status", "revision", "evidence", "runs", "stale_checks")

_CHECK_CONFIG_FIELDS = ("env", "env_scope", "parallel_safe", "profile", "inputs", "preflight", "accepted_risk",
                        "suite", "test_ids", "markers", "collect")


def _manifest_source(task_file: str, output: str, scenarios_file: str) -> str:
    if scenarios_file:
        return scenarios_file
    if Path(output).is_file():
        try:
            stored = json.loads(Path(output).read_text(encoding="utf-8"))
            recorded = stored.get("scenarios_file") if isinstance(stored, Mapping) else None
        except (OSError, ValueError, TypeError) as exc:
            sys.stderr.write(f"acceptance relock source unavailable: {exc}\n")
            recorded = None
        if isinstance(recorded, str) and recorded.strip():
            return str((Path(output).parent / recorded).resolve())
    candidate = Path(task_file).with_suffix(".scenarios.md")
    return str(candidate) if candidate.is_file() else ""


def _project_source_checks(manifest: dict[str, object], scenarios_file: str) -> None:
    if scenarios_file:
        from codeflow.cli.cf_scenarios import parse_scenarios
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


def write_manifest(task_file: str, output: str, scenarios_file: str = "", *,
                   register_checks: bool = False, registration_file: str = "") -> dict[str, object]:
    scenarios_file = _manifest_source(task_file, output, scenarios_file)
    manifest = extract_manifest(task_file, scenarios_file=scenarios_file)
    _project_source_checks(manifest, scenarios_file)
    target = Path(output)
    if scenarios_file:
        source_path = Path(scenarios_file).resolve()
        try:
            manifest["scenarios_file"] = str(source_path.relative_to(target.parent.resolve()))
        except ValueError:
            manifest["scenarios_file"] = str(source_path)
    # Re-lock explicitly opts into current quality; reading old plans does not.
    manifest["e2e_gate"] = 1
    manifest["quality_schema"] = 2
    _preserve_check_config(target, manifest)
    if register_checks or registration_file:
        from codeflow.acceptance.cf_acceptance_registration import register_checks as configure
        from codeflow.evidence.cf_evidence_store import discover_project_root
        root = discover_project_root(task_file)
        manifest["registration"] = configure(manifest, str(root), registration_file)
    _preserve_runtime_state(task_file, target, manifest)
    for scenario in manifest.get("scenarios", []):
        if isinstance(scenario, dict) and scenario.get("status") in ("verified", "failed") and not scenario.get("evidence"):
            scenario["status"] = "planned"
    try:
        manifest["task_file"] = str(Path(task_file).resolve().relative_to(target.parent.resolve()))
    except ValueError:
        manifest["task_file"] = str(Path(task_file).resolve())
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest


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
            from codeflow.acceptance.cf_acceptance_risk import risk_scenario_ids
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
    """Keep history per scenario; changed contracts become visibly stale."""
    if not target.is_file():
        return
    try:
        previous = load_manifest(target)
    except (OSError, ValueError) as exc:
        manifest["relock"] = {"warnings": [f"previous_manifest_invalid: {exc}"]}
        return
    previous_task = previous.get("task_file")
    if previous_task and (target.parent / str(previous_task)).resolve() != Path(task_file).resolve():
        manifest["relock"] = {"warnings": ["previous_manifest_task_mismatch"]}
        return
    stored = {item["id"]: item for item in previous["scenarios"]}
    current_ids = {item["id"] for item in manifest["scenarios"]}
    report: dict[str, object] = {"preserved": [], "stale": [], "removed": sorted(set(stored) - current_ids)}
    for item in manifest.get("scenarios", []):
        old = stored.get(item.get("id"))
        if not isinstance(old, dict):
            continue
        for key in _RUNTIME_SCENARIO_FIELDS:
            if key in old:
                item[key] = old[key]
        changed = _scenario_contract(old, previous) != _scenario_contract(item, manifest)
        if changed and any(key in old for key in ("evidence", "runs")):
            item["status"] = "stale"
            item["stale_checks"] = scenario_check_ids(item)
            report["stale"].append(item["id"])
        else:
            report["preserved"].append(item["id"])
    manifest["relock"] = report


def _scenario_contract(row: Mapping[str, object], manifest: Mapping[str, object]) -> dict[str, object]:
    ids = scenario_check_ids(row)
    checks = {item["id"]: item for item in manifest.get("checks", [])}
    return {"scenario": {key: row.get(key) for key in IMMUTABLE_SCENARIO_FIELDS},
            "checks": {key: checks.get(key) for key in ids}}


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
    from codeflow.acceptance.cf_acceptance_evidence import sync_task_evidence
    sync_task_evidence(task_file, scenario_id, confirmed_by, evidence, owner)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog=os.environ.get("CF_RUNTIME_COMMAND") or None)
    parser.add_argument("--task-file", default="")
    parser.add_argument("--output", default="")
    parser.add_argument("--scenarios-file", default="")
    parser.add_argument("--register-checks", action="store_true",
                        help="collect pytest/Playwright tests and register checks before writing")
    parser.add_argument("--registration-file", default="",
                        help="JSON check registration overrides for custom collectors")
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
    return parser


def main(argv: Optional[Sequence[str]] = None, stdout: IO[str] = sys.stdout) -> int:
    args = _parser().parse_args(argv)
    try:
        if (args.project or args.verify_plan) and not args.task_file:
            raise ValueError(f"{'--project' if args.project else '--verify-plan'} requires --task-file")
        if args.verify_plan and (args.register_checks or args.registration_file):
            raise ValueError("--verify-plan is read-only; register checks while writing the manifest")
        if (args.accept_risk or args.record_manual) and (args.register_checks or args.registration_file):
            raise ValueError("check registration requires writing the manifest")
        if args.project:
            stdout.write(json.dumps(_write_manifest_action(args), ensure_ascii=False))
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
            from codeflow.acceptance.cf_plan_quality import verify_plan
            result = verify_plan(args.task_dir, args.task_file, args.require_scenarios)
            stdout.write(json.dumps(result, ensure_ascii=False))
            return 0 if result["decision"] == "pass" else 3
        stdout.write(json.dumps(_write_manifest_action(args), ensure_ascii=False))
        return 0
    except (OSError, ValueError) as exc:
        stdout.write(json.dumps({"ok": False, "error": str(exc),
            **({"registration": exc.report} if hasattr(exc, "report") else {})}, ensure_ascii=False))
        return 2


def _write_manifest_action(args: argparse.Namespace) -> dict[str, object]:
    output = args.output or (str(Path(args.task_file).with_name(".acceptance-manifest.json")) if args.project else "")
    if not output:
        raise ValueError("--output is required unless --verify-plan is used")
    if not args.task_file:
        raise ValueError("--task-file is required")
    manifest = write_manifest(args.task_file, output, args.scenarios_file,
        register_checks=args.register_checks, registration_file=args.registration_file)
    return {"ok": True, "manifest": output, "scenarios": len(manifest["scenarios"]),
            "checks": len(manifest["checks"]),
            "projected_scenarios": sum(1 for row in manifest["scenarios"] if row.get("checks")),
            "relock": manifest.get("relock", {}), "registration": manifest.get("registration", {})}
