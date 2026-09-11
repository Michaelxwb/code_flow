#!/usr/bin/env python3
"""Lock and validate plan Acceptance Coverage entries."""

from __future__ import annotations

import argparse
import hashlib
import json
import shlex
from pathlib import Path
import re
import sys
from typing import IO, Mapping, Optional, Sequence

from cf_acceptance_schema import load_manifest, validate_scenarios


_ROW_RE = re.compile(r"^\|\s*([SEB]-\d+)\s*\|(.+?)\|$")

_MANIFEST_SCHEMA = 2


def _kind(level: str) -> str:
    """Map test level to execution kind.

    - functional: auto-executed in Done Gate (unit, integration)
    - e2e: deferred until explicit --verify-e2e (needs external dependencies)
    - manual: user confirmation required, never auto-executed
    """
    normalized = level.strip().lower()
    if normalized == "manual":
        return "manual"
    if normalized == "e2e":
        return "e2e"  # Keep as separate kind, not functional
    return "functional"


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
    immutable = [
        {key: item[key] for key in ("id", "source", "level", "kind", "boundary", "owner", "command", "cwd", "timeout", "depends_on")}
        for item in rows
    ]
    payload = json.dumps(immutable, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def extract_manifest(task_file: str) -> dict[str, object]:
    path = Path(task_file)
    text = path.read_text(encoding="utf-8")
    rows: list[dict[str, object]] = []
    in_table = False
    seen: set[str] = set()
    for line in text.splitlines():
        if line.startswith("## Acceptance Coverage"):
            in_table = True
            continue
        if in_table and line.startswith("## "):
            break
        if not in_table:
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
        depends = [item.strip() for item in (fields[8] if len(fields) > 8 else "").split(",") if item.strip()]
        rows.append({
            "id": match.group(1),
            "source": fields[0],
            "level": fields[1],
            "kind": _kind(fields[1]),
            "boundary": fields[2],
            "owner": fields[3],
            "status": fields[4],
            "command": _parse_command(fields[5], match.group(1)) if len(fields) > 5 else None,
            "cwd": (fields[6] if len(fields) > 6 else "").strip() or ".",
            "timeout": _parse_float(fields[7], 60.0) if len(fields) > 7 else 60.0,
            "depends_on": depends,
        })
    if not rows:
        raise ValueError("Acceptance Coverage 缺失或为空")
    validate_scenarios(rows)
    return {"schema": _MANIFEST_SCHEMA, "task_file": str(path), "task_sha256": _manifest_hash(rows), "scenarios": rows}


def write_manifest(task_file: str, output: str) -> dict[str, object]:
    manifest = extract_manifest(task_file)
    target = Path(output)
    try:
        manifest["task_file"] = str(Path(task_file).resolve().relative_to(target.parent.resolve()))
    except ValueError:
        manifest["task_file"] = str(Path(task_file).resolve())
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest


_IMMUTABLE_SCENARIO_FIELDS = (
    "id", "source", "level", "kind", "boundary", "owner", "command", "cwd", "timeout", "depends_on",
)


def validate_manifest(task_file: str, manifest_file: str) -> tuple[bool, str]:
    try:
        manifest = load_manifest(Path(manifest_file))
        expected = extract_manifest(task_file)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return False, f"acceptance_manifest_invalid: {exc}"
    if manifest.get("schema") != _MANIFEST_SCHEMA or manifest.get("task_sha256") != expected["task_sha256"]:
        return False, "acceptance_manifest_drift"
    stored_task = manifest.get("task_file", "")
    if not stored_task or (Path(manifest_file).parent / stored_task).resolve() != Path(task_file).resolve():
        return False, "acceptance_manifest_task_mismatch"
    if not isinstance(manifest.get("scenarios"), list):
        return False, "acceptance_manifest_scenarios_changed"
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
            if item.get("kind") != "manual":
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
    parser = argparse.ArgumentParser()
    parser.add_argument("--task-file", required=True)
    parser.add_argument("--output", default="")
    parser.add_argument("--verify-plan", action="store_true")
    parser.add_argument("--task-dir", default="")
    parser.add_argument("--record-manual", action="store_true")
    parser.add_argument("--scenario-id", default="")
    parser.add_argument("--confirmed-by", default="")
    parser.add_argument("--evidence", default="")
    args = parser.parse_args(argv)
    try:
        if args.record_manual:
            if not args.output or not args.scenario_id or not args.evidence:
                raise ValueError("--record-manual requires --output, --scenario-id and --evidence")
            record_manual_evidence(args.output, args.scenario_id, args.confirmed_by, args.evidence)
            stdout.write(json.dumps({"ok": True, "scenario": args.scenario_id}, ensure_ascii=False))
            return 0
        if args.verify_plan:
            if not args.task_dir:
                raise ValueError("--verify-plan requires --task-dir")
            from cf_spec_context import load_context
            from cf_spec_gate import result_to_data, validate_plan_coverage, validate_stage

            context = load_context(str(Path(args.task_dir) / "spec-context.yml"))
            gate = validate_stage(context, "plan")
            coverage = validate_plan_coverage(context, args.task_file)
            result = {
                "decision": "block" if gate.decision == "block" or coverage.decision == "block" else "pass",
                "gate": result_to_data(gate),
                "coverage": result_to_data(coverage),
            }
            stdout.write(json.dumps(result, ensure_ascii=False))
            return 0 if result["decision"] == "pass" else 3
        if not args.output:
            raise ValueError("--output is required unless --verify-plan is used")
        manifest = write_manifest(args.task_file, args.output)
        stdout.write(json.dumps({"ok": True, "scenarios": len(manifest["scenarios"])}, ensure_ascii=False))
        return 0
    except (OSError, ValueError) as exc:
        stdout.write(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
