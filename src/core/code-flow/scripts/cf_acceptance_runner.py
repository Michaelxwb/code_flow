#!/usr/bin/env python3
"""Execute manifest scenarios with deterministic ordering and evidence."""

from __future__ import annotations

import argparse
import os
import json
from pathlib import Path
import sys
from typing import IO, Mapping, Optional, Sequence

from cf_exec_base import execution_key, run_command, invalidate_executions, worktree_fingerprint
from cf_acceptance_schema import load_manifest, validate_execution_baseline
from cf_acceptance_evidence import persist_results
from cf_worktree_env import (
    check_environment,
    effective_parallel_safe,
    env_scope,
    is_isolated,
    preflight_commands,
    resolve_run_id,
    worktree_namespace,
)


def _scenario_cwd(root: Path, item: Mapping[str, object]) -> str:
    cwd = item.get("cwd", ".") if isinstance(item.get("cwd", "."), str) else "."
    return str(root / cwd)


def _scenario_timeout(item: Mapping[str, object]) -> float:
    timeout = item.get("timeout", 60)
    return float(timeout) if isinstance(timeout, (int, float)) else 60.0


def _included(item: Mapping[str, object], include_e2e: bool, only_e2e: bool) -> bool:
    """Whether the scenario would actually execute under the current flags."""
    kind = str(item.get("kind", "functional"))
    if kind == "manual":
        return False
    if only_e2e:
        return kind == "e2e"
    if kind == "e2e":
        return include_e2e
    return True


def _reusable(row: Optional[Mapping[str, object]], item: Mapping[str, object], fingerprint: str) -> bool:
    """A verified scenario whose stored evidence matches current identity+content.

    Reuse is content-addressed (like the validation cache): same command/cwd/
    timeout AND unchanged non-ignored worktree. Scenarios with `depends_on`
    never reuse (dependency side effects are not captured by the fingerprint),
    failures are never stored, and `--no-cache` disables reuse entirely.
    """
    if not fingerprint or not isinstance(row, Mapping):
        return False
    if item.get("depends_on"):
        return False
    if row.get("status") != "verified":
        return False
    evidence = row.get("evidence")
    if not isinstance(evidence, Mapping):
        return False
    if evidence.get("status") != "passed" or evidence.get("exit_code") != 0:
        return False
    if evidence.get("fingerprint") != fingerprint:
        return False
    if evidence.get("command") != item.get("command"):
        return False
    if str(evidence.get("cwd", ".")) != str(item.get("cwd", ".")):
        return False
    return float(evidence.get("timeout", 60)) == _scenario_timeout(item)


def _run(
    item: Mapping[str, object], root: Path, include_e2e: bool = False, deadline: Optional[float] = None,
    only_e2e: bool = False, env: Optional[Mapping[str, str]] = None,
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
    timeout_value = _scenario_timeout(item)
    cwd = item.get("cwd", ".") if isinstance(item.get("cwd", "."), str) else "."
    outcome = run_command(command, str(root / cwd), timeout_value, deadline, env=env)
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


def _preflight_failures(
    check: Mapping[str, object], root: Path, env: Optional[Mapping[str, str]], deadline: Optional[float]
) -> list[dict[str, object]]:
    """Probe declared preflight commands; each failure is a missing dependency."""
    cwd = check.get("cwd", ".") if isinstance(check.get("cwd", "."), str) else "."
    timeout = _scenario_timeout(check)
    failures: list[dict[str, object]] = []
    for argv in preflight_commands(check):
        outcome = run_command(argv, str(root / cwd), timeout, deadline, env=env)
        status = outcome["status"]
        item: dict[str, object] = {
            "command": list(argv),
            "cwd": cwd,
            "timeout": timeout,
            "reason": str(status),
        }
        if status == "deadline_exceeded":
            item["exit_code"] = None
            failures.append(item)
            break
        if status == "timeout":
            item["exit_code"] = None
            item["output"] = str(outcome.get("stdout", ""))[-2000:]
            failures.append(item)
            continue
        if status == "spawn_error":
            item["exit_code"] = None
            item["output"] = str(outcome.get("stderr", ""))[-2000:]
            failures.append(item)
            continue
        if outcome["returncode"] != 0:
            item["exit_code"] = outcome["returncode"]
            output = (str(outcome.get("stdout", "")) + str(outcome.get("stderr", ""))).strip()
            item["output"] = output[-2000:]
            item["reason"] = "exit_code"
            failures.append(item)
    return failures


def _env_blocked_result(
    item: Mapping[str, object], check_id: str, missing: Sequence[Mapping[str, object]]
) -> dict[str, object]:
    return {
        "id": str(item.get("id", "unknown")),
        "kind": str(item.get("kind", "functional")),
        "status": "env_blocked",
        "check_id": check_id,
        "owner": str(item.get("owner", "") or ""),
        "missing": [dict(entry) for entry in missing],
        "error": "env_preflight_failed",
    }


def _gate_check(
    item: Mapping[str, object], check: Optional[Mapping[str, object]], root: Path,
    namespace: Optional[Mapping[str, str]], deadline: Optional[float],
    preflighted: set[str], blocked: dict[str, list[dict[str, object]]],
) -> Optional[dict[str, object]]:
    """Return an env_blocked/incomplete result when a check cannot start."""
    if check is None:
        return None
    check_id = str(check.get("id", item.get("check", "")))
    if check_id not in preflighted:
        preflighted.add(check_id)
        missing = _preflight_failures(check, root, check_environment(check, str(root), namespace), deadline)
        if missing:
            blocked[check_id] = missing
    if check_id not in blocked:
        return None
    missing = blocked[check_id]
    # A global deadline is not an environment defect: report it as unexecuted.
    if any(str(entry.get("reason")) == "deadline_exceeded" for entry in missing):
        return {"id": str(item.get("id", "unknown")), "kind": str(item.get("kind", "functional")),
                "status": "incomplete", "check_id": check_id, "error": "deadline_exceeded"}
    return _env_blocked_result(item, check_id, missing)


def _env_blocked_details(
    checks: Mapping[str, Mapping[str, object]], results: Sequence[Mapping[str, object]]
) -> list[dict[str, object]]:
    details: list[dict[str, object]] = []
    seen: set[str] = set()
    for item in results:
        if item.get("status") != "env_blocked":
            continue
        check_id = str(item.get("check_id") or item.get("id"))
        if check_id in seen:
            continue
        seen.add(check_id)
        check = checks.get(check_id, {})
        details.append({
            "check_id": check_id,
            "owner": str(item.get("owner", "") or ""),
            "command": check.get("command", item.get("command")),
            "missing": [dict(entry) for entry in item.get("missing", [])],
        })
    return details


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


def _identity_key(
    item: Mapping[str, object], root: Path, include_e2e: bool, only_e2e: bool
) -> Optional[str]:
    """Execution identity for within-run dedup, or None when not configured."""
    command = item.get("command")
    if not isinstance(command, list) or not command or not all(isinstance(value, str) for value in command):
        return None
    key = execution_key(command, str(root / str(item.get("cwd", "."))), float(item.get("timeout", 60)))
    return key + json.dumps([item.get("kind", "functional"), include_e2e, only_e2e])


def _cached_result(
    item: Mapping[str, object], scenario_id: str, key: Optional[str],
    rows: Optional[Mapping[str, Mapping[str, object]]], fingerprint: str,
    include_e2e: bool, only_e2e: bool, use_cache: bool,
) -> Optional[dict[str, object]]:
    """Cross-run reuse result when identity+content still match."""
    if not use_cache or key is None or rows is None or not _included(item, include_e2e, only_e2e):
        return None
    if not _reusable(rows.get(scenario_id), item, fingerprint):
        return None
    return {
        "id": scenario_id,
        "kind": str(item.get("kind", "functional")),
        "status": "passed",
        "exit_code": 0,
        "cache_reused": True,
    }


def _run_unique(
    ordered: list[Mapping[str, object]], root: Path, include_e2e: bool, deadline: Optional[float] = None,
    only_e2e: bool = False, rows: Optional[Mapping[str, Mapping[str, object]]] = None,
    fingerprint: str = "", use_cache: bool = True,
    checks: Optional[Mapping[str, Mapping[str, object]]] = None,
    namespace: Optional[Mapping[str, str]] = None,
) -> list[dict[str, object]]:
    """Reuse identical execution semantics within a dependency-free batch.

    Cross-run reuse: a scenario already verified with matching command identity
    and an unchanged worktree fingerprint is reported `passed` with
    `cache_reused: true` instead of re-executing. This is what keeps repeated
    verify-e2e / archive / confirm-manual checkpoints from paying the E2E cost
    again; any content change invalidates it. Preflight runs once per check and
    gates every scenario that shares it.
    """
    cache: dict[str, Mapping[str, object]] = {}
    blocked: dict[str, list[dict[str, object]]] = {}
    preflighted: set[str] = set()
    results: list[dict[str, object]] = []
    for item in ordered:
        scenario_id = str(item.get("id", "unknown"))
        check_id = item.get("check")
        check = checks.get(check_id) if checks and isinstance(check_id, str) else None
        key = _identity_key(item, root, include_e2e, only_e2e)
        if item.get("depends_on"):
            cache.clear()
            invalidate_executions()
        reused = _cached_result(item, scenario_id, key, rows, fingerprint, include_e2e, only_e2e, use_cache)
        if reused is not None:
            results.append(reused)
            continue
        if _included(item, include_e2e, only_e2e):
            gated = _gate_check(item, check, root, namespace, deadline, preflighted, blocked)
            if gated is not None:
                results.append(gated)
                continue
        if key is not None and key in cache:
            shared = dict(cache[key])
            shared["id"] = scenario_id
            results.append(shared)
            continue
        env = check_environment(check, str(root), namespace) if check is not None else None
        result = _run(item, root, include_e2e, deadline, only_e2e, env=env)
        if key is not None:
            cache[key] = result
        results.append(result)
    return results


def _check_summary(checks: Sequence[Mapping[str, object]], scenarios: Sequence[Mapping[str, object]],
                   results: Sequence[Mapping[str, object]]) -> list[dict[str, object]]:
    """Roll scenario results up to their executable checks (v3 manifests)."""
    if not checks:
        return []
    by_id = {str(item.get("id")): item for item in results}
    grouped: dict[str, list[str]] = {}
    for scenario in scenarios:
        check_id = scenario.get("check")
        if isinstance(check_id, str):
            grouped.setdefault(check_id, []).append(str(scenario.get("id")))
    summary: list[dict[str, object]] = []
    for check in checks:
        check_id = str(check.get("id", ""))
        scenario_ids = grouped.get(check_id, [])
        statuses = [str(by_id.get(scenario_id, {}).get("status", "not_included")) for scenario_id in scenario_ids]
        if not statuses:
            status = "not_included"
        elif all(value == "passed" for value in statuses):
            status = "passed"
        elif any(value in ("failed", "incomplete", "not_configured") for value in statuses):
            status = "failed"
        elif any(value == "env_blocked" for value in statuses):
            status = "env_blocked"
        elif any(value == "e2e_deferred" for value in statuses):
            status = "deferred"
        else:
            status = "included"
        summary.append({
            "id": check_id,
            "status": status,
            "scenarios": scenario_ids,
            "env_scope": env_scope(check),
            "parallel_safe": effective_parallel_safe(check),
        })
    return summary


def _check_plan(data: Mapping[str, object]) -> tuple[list[Mapping[str, object]], dict[str, Mapping[str, object]]]:
    """Manifest v3 checks (schema2 manifests have none)."""
    value = data.get("checks")
    checks = value if isinstance(value, list) else []
    mapping = {
        str(check["id"]): check
        for check in checks
        if isinstance(check, Mapping) and "id" in check
    }
    return checks, mapping


def _run_namespace(
    root: str, check_map: Mapping[str, Mapping[str, object]], owner: str,
    items: Sequence[Mapping[str, object]], run_key: str,
) -> Optional[dict[str, str]]:
    """Namespace is only materialized when at least one check is isolated."""
    if not any(is_isolated(check) for check in check_map.values()):
        return None
    return worktree_namespace(str(root), task_id=_task_identity(owner, items), run_id=run_key)


def _task_identity(owner: str, items: Sequence[Mapping[str, object]]) -> str:
    """Owner wins; a single-owner manifest still exposes CF_TASK_ID."""
    if owner:
        return owner
    owners = {
        str(item.get("owner")) for item in items
        if isinstance(item.get("owner"), str) and item.get("owner")
    }
    return owners.pop() if len(owners) == 1 else ""


def _decision(results: Sequence[Mapping[str, object]]) -> tuple[str, str]:
    allowed = ("passed", "manual_pending", "e2e_deferred", "not_included")
    if all(item["status"] in allowed for item in results):
        return "pass", ""
    pending = sorted({str(item["id"]) for item in results if item["status"] == "incomplete"})
    env_blocked = sorted({
        str(item.get("check_id") or item["id"]) for item in results if item["status"] == "env_blocked"
    })
    failed = sorted({
        str(item["id"]) for item in results
        if item["status"] not in (*allowed, "incomplete", "env_blocked")
    })
    segments = (
        ["incomplete:" + ",".join(pending)] if pending else []
    ) + (
        ["env_blocked:" + ",".join(env_blocked)] if env_blocked else []
    ) + (
        ["failed:" + ",".join(failed)] if failed else []
    )
    return "block", ",".join(segments) or "acceptance scenario failed"


def run_manifest(
    manifest_file: str,
    root: str,
    write_evidence: bool = False,
    include_e2e: bool = False,
    owner: str = "",
    deadline: Optional[float] = None,
    only_e2e: bool = False,
    use_cache: bool = True,
    run_id: str = "",
) -> dict[str, object]:
    data = load_manifest(Path(manifest_file))
    validate_execution_baseline(Path(manifest_file), data)
    scenarios = data["scenarios"]
    _ordered(scenarios)  # Validate the complete DAG before owner filtering.
    items = _owned(scenarios, owner)
    if owner and not items:
        # TASK 无自有场景（Acceptance-Refs: N/A / 场景全归他人）：本任务执行验收
        # 视为空集通过；"零可执行场景"阻断只针对整体无场景的 manifest。
        return {"decision": "pass", "results": [], "reason": "no_owned_scenarios"}
    ordered = _ordered(items)
    rows = {
        str(row.get("id")): row
        for row in scenarios
        if isinstance(row, Mapping) and isinstance(row.get("id"), str)
    }
    check_list, check_map = _check_plan(data)
    run_key = resolve_run_id(run_id)
    namespace = _run_namespace(str(root), check_map, owner, items, run_key)
    fingerprint = worktree_fingerprint(str(root)) if use_cache else ""
    results = _run_unique(ordered, Path(root), include_e2e or only_e2e, deadline, only_e2e,
                          rows=rows, fingerprint=fingerprint, use_cache=use_cache,
                          checks=check_map or None, namespace=namespace)
    if write_evidence:
        persist_results(Path(manifest_file), data, results, fingerprint=fingerprint, run_id=run_key)
    if not _executable(items):
        return {"decision": "block", "results": results, "error": "no_executable_scenarios"}
    decision, error = _decision(results)
    outcome: dict[str, object] = {"decision": decision, "results": results}
    if check_list:
        outcome["checks"] = _check_summary(check_list, items, results)
    env_blocked = sum(1 for item in results if item["status"] == "env_blocked")
    outcome["env_blocked"] = env_blocked
    if env_blocked:
        outcome["env_blocked_details"] = _env_blocked_details(check_map, results)
    if error:
        outcome["error"] = error
    return outcome


def main(argv: Optional[Sequence[str]] = None, stdout: IO[str] = sys.stdout) -> int:
    parser = argparse.ArgumentParser(prog=os.environ.get("CF_RUNTIME_COMMAND") or None)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--root", required=True)
    parser.add_argument("--write-evidence", action="store_true")
    parser.add_argument("--include-e2e", action="store_true", help="Execute E2E scenarios (deferred by default)")
    parser.add_argument("--only-e2e", action="store_true", help="Execute only E2E scenarios; functional/manual are reported not_included")
    parser.add_argument("--owner", default="", help="Only execute scenarios owned by this TASK (plus ownerless legacy ones)")
    parser.add_argument("--deadline", type=float, default=0.0, help="Absolute monotonic deadline propagated from the entry gate (0 = unbounded)")
    parser.add_argument("--no-cache", action="store_true", help="Force execution; skip content-fingerprint reuse of already-verified scenarios")
    args = parser.parse_args(argv)
    try:
        result = run_manifest(args.manifest, args.root, args.write_evidence, args.include_e2e, args.owner,
                              args.deadline or None, args.only_e2e, use_cache=not args.no_cache)
        stdout.write(json.dumps(result, ensure_ascii=False))
        return 0 if result["decision"] == "pass" else 3
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        stdout.write(json.dumps({"decision": "block", "error": str(exc)}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
