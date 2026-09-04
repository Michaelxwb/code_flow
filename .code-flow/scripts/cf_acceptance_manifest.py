#!/usr/bin/env python3
"""Lock and validate plan Acceptance Coverage entries."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys
from typing import IO, Mapping, Optional, Sequence


_ROW_RE = re.compile(r"^\|\s*([SEB]-\d+)\s*\|(.+?)\|$")


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


def _manifest_hash(rows: list[dict[str, str]]) -> str:
    immutable = [{key: item[key] for key in ("id", "source", "level", "kind", "boundary", "owner")} for item in rows]
    payload = json.dumps(immutable, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def extract_manifest(task_file: str) -> dict[str, object]:
    path = Path(task_file)
    text = path.read_text(encoding="utf-8")
    rows: list[dict[str, str]] = []
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
        if len(fields) < 5 or match.group(1) in seen:
            continue
        seen.add(match.group(1))
        rows.append({"id": match.group(1), "source": fields[0], "level": fields[1], "kind": _kind(fields[1]), "boundary": fields[2], "owner": fields[3], "status": fields[4]})
    if not rows:
        raise ValueError("Acceptance Coverage 缺失或为空")
    return {"schema": 1, "task_file": str(path), "task_sha256": _manifest_hash(rows), "scenarios": rows}


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


def validate_manifest(task_file: str, manifest_file: str) -> tuple[bool, str]:
    try:
        manifest = json.loads(Path(manifest_file).read_text(encoding="utf-8"))
        expected = extract_manifest(task_file)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return False, f"acceptance_manifest_invalid: {exc}"
    if manifest.get("schema") != 1 or manifest.get("task_sha256") != expected["task_sha256"]:
        return False, "acceptance_manifest_drift"
    actual = {item.get("id") for item in manifest.get("scenarios", []) if isinstance(item, Mapping)}
    required = {item["id"] for item in expected["scenarios"]}
    if actual != required:
        return False, "acceptance_manifest_scenarios_changed"
    text = Path(task_file).read_text(encoding="utf-8")
    for scenario in expected["scenarios"]:
        owner = scenario["owner"]
        section = re.search(rf"(?ms)^##\s+{re.escape(owner)}:.*?(?=^##\s+TASK-|\Z)", text)
        refs = section.group(0).partition("Acceptance-Refs")[2] if section else ""
        if scenario["id"] not in refs:
            return False, "acceptance_manifest_owner_missing"
    return True, ""


def record_manual_evidence(manifest_file: str, scenario_id: str, confirmed_by: str, evidence: str) -> None:
    if not confirmed_by or confirmed_by.lower().split(":", 1)[0] in {"agent", "assistant", "codex", "claude", "opencode", "costrict"}:
        raise ValueError("manual evidence must be confirmed by a user")
    path = Path(manifest_file)
    data = json.loads(path.read_text(encoding="utf-8"))
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
    text = task_file.read_text(encoding="utf-8")
    if owner:
        section_match = re.search(rf"(?ms)^##\s+{re.escape(owner)}:.*?(?=^##\s+TASK-|\Z)", text)
    else:
        section_match = re.search(r"(?ms)^##\s+TASK-\d+:.*?(?=^##\s+TASK-|\Z)", text)
    if section_match is None:
        return
    section = section_match.group(0)
    line = f"- {scenario_id}: verified — {evidence} (confirmed_by: {confirmed_by})"
    contract_match = re.search(r"(?ms)^### Acceptance Contract\s*$\n(.*?)(?=^### |^## |\Z)", section)
    if contract_match and scenario_id in contract_match.group(1) and "verified" not in contract_match.group(1).lower():
        body = contract_match.group(1)
        body = "\n".join((f"{item} — verified" if scenario_id in item else item) for item in body.splitlines())
        section = section[:contract_match.start(1)] + body + section[contract_match.end(1):]
    evidence_match = re.search(r"(?ms)^### Acceptance Evidence\s*$\n(.*?)(?=^### |^## |\Z)", section)
    if evidence_match:
        body = evidence_match.group(1)
        replacement = body.rstrip() + "\n" + line + "\n"
        section = section[:evidence_match.start(1)] + replacement + section[evidence_match.end(1):]
    else:
        section = section.rstrip() + "\n\n### Acceptance Evidence\n" + line + "\n"
    task_file.write_text(text[:section_match.start()] + section + text[section_match.end():], encoding="utf-8")


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
