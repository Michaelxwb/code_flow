#!/usr/bin/env python3
"""Execute manifest scenarios with deterministic ordering and evidence."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys
from typing import IO, Mapping, Optional, Sequence


def _run(item: Mapping[str, object], root: Path, include_e2e: bool = False) -> dict[str, object]:
    scenario_id = str(item.get("id", "unknown"))
    kind = str(item.get("kind", "functional"))
    if kind == "manual":
        return {"id": scenario_id, "kind": kind, "status": "manual_pending"}
    if kind == "e2e" and not include_e2e:
        return {"id": scenario_id, "kind": kind, "status": "e2e_deferred"}
    command = item.get("command")
    if not isinstance(command, list) or not command or not all(isinstance(value, str) for value in command):
        return {"id": scenario_id, "kind": kind, "status": "not_configured"}
    timeout = item.get("timeout", 60)
    timeout_value = float(timeout) if isinstance(timeout, (int, float)) else 60.0
    cwd = item.get("cwd", ".") if isinstance(item.get("cwd", "."), str) else "."
    try:
        result = subprocess.run(command, cwd=str(root / cwd), capture_output=True, timeout=timeout_value, check=False)
    except subprocess.TimeoutExpired:
        return {"id": scenario_id, "kind": kind, "status": "failed", "error": "timeout"}
    except OSError as exc:
        return {"id": scenario_id, "kind": kind, "status": "failed", "error": str(exc)}
    return {"id": scenario_id, "kind": kind, "status": "passed" if result.returncode == 0 else "failed", "exit_code": result.returncode}


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


def run_manifest(manifest_file: str, root: str, write_evidence: bool = False, include_e2e: bool = False) -> dict[str, object]:
    data = json.loads(Path(manifest_file).read_text(encoding="utf-8"))
    scenarios = data.get("scenarios", [])
    if not isinstance(scenarios, list):
        raise ValueError("invalid scenarios")
    items = [item for item in scenarios if isinstance(item, Mapping)]
    ordered = _ordered(items)
    results = [_run(item, Path(root), include_e2e) for item in ordered]
    configured = any(isinstance(item.get("command"), list) for item in items)
    allowed = ("passed", "manual_pending", "e2e_deferred", "not_configured") if not configured else ("passed", "manual_pending", "e2e_deferred")
    decision = "pass" if all(item["status"] in allowed for item in results) else "block"
    if write_evidence:
        for item, result in zip(ordered, results):
            if isinstance(item, dict) and result["status"] == "passed":
                item["status"] = "verified"
                item["evidence"] = result
        Path(manifest_file).write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        task_file = data.get("task_file")
        if isinstance(task_file, str) and task_file:
            from cf_acceptance_manifest import _sync_task_evidence

            task_path = Path(task_file)
            if not task_path.is_absolute():
                task_path = Path(manifest_file).parent / task_path
            for item, result in zip(ordered, results):
                if result["status"] == "passed":
                    owner = item.get("owner") if isinstance(item.get("owner"), str) else ""
                    _sync_task_evidence(task_path, str(result["id"]), "runner", "automated command passed", owner)
    return {"decision": decision, "results": results}


def main(argv: Optional[Sequence[str]] = None, stdout: IO[str] = sys.stdout) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--root", required=True)
    parser.add_argument("--write-evidence", action="store_true")
    parser.add_argument("--include-e2e", action="store_true", help="Execute E2E scenarios (deferred by default)")
    args = parser.parse_args(argv)
    try:
        result = run_manifest(args.manifest, args.root, args.write_evidence, args.include_e2e)
        stdout.write(json.dumps(result, ensure_ascii=False))
        return 0 if result["decision"] == "pass" else 3
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        stdout.write(json.dumps({"decision": "block", "error": str(exc)}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
