#!/usr/bin/env python3
"""Execute manifest scenarios with deterministic ordering and evidence."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import IO, Mapping, Optional, Sequence

from cf_exec_base import execution_key, run_command, invalidate_executions
from cf_acceptance_schema import load_manifest, validate_execution_baseline
from cf_acceptance_evidence import persist_results


def _run(
    item: Mapping[str, object], root: Path, include_e2e: bool = False, deadline: Optional[float] = None,
    only_e2e: bool = False,
) -> dict[str, object]:
    scenario_id = str(item.get("id", "unknown"))
    kind = str(item.get("kind", "functional"))
    if only_e2e and kind != "e2e":
        return {"id": scenario_id, "kind": kind, "status": "not_included"}
    if kind == "manual":
        return {"id": scenario_id, "kind": kind, "status": "manual_pending"}
    if kind == "e2e" and not include_e2e and not only_e2e:
        return {"id": scenario_id, "kind": kind, "status": "e2e_deferred"}
    command = item.get("command")
    if not isinstance(command, list) or not command or not all(isinstance(value, str) for value in command):
        return {"id": scenario_id, "kind": kind, "status": "not_configured"}
    timeout = item.get("timeout", 60)
    timeout_value = float(timeout) if isinstance(timeout, (int, float)) else 60.0
    cwd = item.get("cwd", ".") if isinstance(item.get("cwd", "."), str) else "."
    outcome = run_command(command, str(root / cwd), timeout_value, deadline)
    if outcome["status"] == "deadline_exceeded":
        return {"id": scenario_id, "kind": kind, "status": "incomplete", "error": "deadline_exceeded"}
    if outcome["status"] == "timeout":
        return {"id": scenario_id, "kind": kind, "status": "failed", "error": "timeout",
                "output": str(outcome.get("stdout", ""))}
    if outcome["status"] == "spawn_error":
        return {"id": scenario_id, "kind": kind, "status": "failed", "error": str(outcome.get("stderr", ""))}
    if outcome["returncode"] == 0:
        return {"id": scenario_id, "kind": kind, "status": "passed", "exit_code": 0}
    output = (str(outcome.get("stdout", "")) + str(outcome.get("stderr", ""))).strip()[-4000:]
    return {"id": scenario_id, "kind": kind, "status": "failed", "exit_code": outcome["returncode"], "output": output}


def _ordered(items: list[Mapping[str, object]]) -> list[Mapping[str, object]]:
    by_id = {str(item.get("id")): item for item in items}
    pending = set(by_id)
    ordered: list[Mapping[str, object]] = []
    while pending:
        ready: list[str] = []
        for item_id in by_id:
            if item_id not in pending:
                continue
            deps = by_id[item_id].get("depends_on", [])
            dep_ids = [str(dep) for dep in deps] if isinstance(deps, list) else []
            unknown = [dep for dep in dep_ids if dep not in by_id]
            if unknown:
                raise ValueError(f"acceptance scenario dependency missing: {', '.join(unknown)}")
            if all(dep not in pending for dep in dep_ids):
                ready.append(item_id)
        if not ready:
            raise ValueError("acceptance scenario dependency cycle")
        ordered.extend(by_id[item_id] for item_id in ready)
        pending.difference_update(ready)
    return ordered


def _executable(items: list[Mapping[str, object]]) -> bool:
    """Draft completeness vs execution gate: at least one scenario must be
    executable — a functional scenario with a registered command, or a
    manual / e2e scenario with its own confirmation/deferral path. Zero
    executable scenarios must block execution acceptance, never pass it."""
    for item in items:
        command = item.get("command")
        if isinstance(command, list) and command and all(isinstance(value, str) for value in command):
            return True
        if str(item.get("kind", "")) in ("manual", "e2e"):
            return True
    return False


def _owned(items: list[Mapping[str, object]], owner: str) -> list[Mapping[str, object]]:
    """Keep scenarios owned by the active TASK; ownerless legacy scenarios stay
    included so old manifests keep working. Cross-TASK depends_on edges are
    pruned: single-TASK ordering is enforced here, whole-demand ordering at
    the final (archive/E2E) gate."""
    if not owner:
        return items
    kept = [
        item for item in items
        if not isinstance(item.get("owner"), str) or not item.get("owner") or item.get("owner") == owner
    ]
    kept_ids = {str(item.get("id")) for item in kept}
    pruned: list[Mapping[str, object]] = []
    for item in kept:
        if not isinstance(item, dict):
            pruned.append(item)
            continue
        deps = item.get("depends_on")
        if isinstance(deps, list):
            item = {**item, "depends_on": [dep for dep in deps if str(dep) in kept_ids]}
        pruned.append(item)
    return pruned


def _run_unique(
    ordered: list[Mapping[str, object]], root: Path, include_e2e: bool, deadline: Optional[float] = None,
    only_e2e: bool = False,
) -> list[dict[str, object]]:
    """Reuse identical execution semantics within a dependency-free batch."""
    cache: dict[str, Mapping[str, object]] = {}
    results: list[dict[str, object]] = []
    for item in ordered:
        scenario_id = str(item.get("id", "unknown"))
        command = item.get("command")
        key: Optional[str] = None
        if isinstance(command, list) and command and all(isinstance(value, str) for value in command):
            key = execution_key(command, str(root / str(item.get("cwd", "."))), float(item.get("timeout", 60)))
            key += json.dumps([item.get("kind", "functional"), include_e2e, only_e2e])
        if item.get("depends_on"):
            cache.clear()
            invalidate_executions()
        if key is not None and key in cache:
            shared = dict(cache[key])
            shared["id"] = scenario_id
            results.append(shared)
            continue
        result = _run(item, root, include_e2e, deadline, only_e2e)
        if key is not None:
            cache[key] = result
        results.append(result)
    return results


def run_manifest(
    manifest_file: str,
    root: str,
    write_evidence: bool = False,
    include_e2e: bool = False,
    owner: str = "",
    deadline: Optional[float] = None,
    only_e2e: bool = False,
) -> dict[str, object]:
    data = load_manifest(Path(manifest_file))
    validate_execution_baseline(Path(manifest_file), data)
    scenarios = data["scenarios"]
    _ordered(scenarios)  # Validate the complete DAG before owner filtering.
    items = _owned(scenarios, owner)
    ordered = _ordered(items)
    results = _run_unique(ordered, Path(root), include_e2e or only_e2e, deadline, only_e2e)
    if write_evidence:
        persist_results(Path(manifest_file), data, results)
    if not _executable(items):
        return {"decision": "block", "results": results, "error": "no_executable_scenarios"}
    allowed = ("passed", "manual_pending", "e2e_deferred", "not_included")
    decision = "pass" if all(item["status"] in allowed for item in results) else "block"
    error = ""
    if decision == "block":
        pending = sorted({str(item["id"]) for item in results if item["status"] == "incomplete"})
        failed = sorted({str(item["id"]) for item in results if item["status"] not in (*allowed, "incomplete")})
        error = ",".join((["incomplete:" + ",".join(pending)] if pending else []) + (["failed:" + ",".join(failed)] if failed else [])) or "acceptance scenario failed"
    outcome: dict[str, object] = {"decision": decision, "results": results}
    if error:
        outcome["error"] = error
    return outcome


def main(argv: Optional[Sequence[str]] = None, stdout: IO[str] = sys.stdout) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--root", required=True)
    parser.add_argument("--write-evidence", action="store_true")
    parser.add_argument("--include-e2e", action="store_true", help="Execute E2E scenarios (deferred by default)")
    parser.add_argument("--only-e2e", action="store_true", help="Execute only E2E scenarios; functional/manual are reported not_included")
    parser.add_argument("--owner", default="", help="Only execute scenarios owned by this TASK (plus ownerless legacy ones)")
    parser.add_argument("--deadline", type=float, default=0.0, help="Absolute monotonic deadline propagated from the entry gate (0 = unbounded)")
    args = parser.parse_args(argv)
    try:
        result = run_manifest(args.manifest, args.root, args.write_evidence, args.include_e2e, args.owner, args.deadline or None, args.only_e2e)
        stdout.write(json.dumps(result, ensure_ascii=False))
        return 0 if result["decision"] == "pass" else 3
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        stdout.write(json.dumps({"decision": "block", "error": str(exc)}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
