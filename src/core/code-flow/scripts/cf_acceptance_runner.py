#!/usr/bin/env python3
"""Execute manifest scenarios with deterministic ordering, checkpoints and resume.

Execution is scheduled per check: a check result is persisted as soon as it
completes, so an interrupted run resumes from the first unfinished/failed check
instead of starting over. Independent parallel-safe checks may overlap;
`depends_on` edges serialize them. A global deadline or a failure budget stops
new work and reports unrun checks as `incomplete`, never as failed/verified.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import tempfile
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from datetime import datetime, timezone
from pathlib import Path
import sys
from typing import IO, Mapping, Optional, Sequence

from cf_exec_base import (
    execution_key,
    invalidate_executions,
    remaining_seconds,
    run_command,
    worktree_fingerprint,
)
from cf_check_inputs import check_input_hashes, match_path
from cf_acceptance_schema import load_manifest, validate_execution_baseline
from cf_acceptance_evidence import persist_results
from cf_evidence_store import EvidenceStore
from cf_worktree_env import (
    SharedEnvLockTimeout,
    check_environment,
    effective_parallel_safe,
    env_scope,
    is_isolated,
    preflight_commands,
    resolve_run_id,
    shared_env_lock,
    worktree_namespace,
)

DEFAULT_JOBS = 4


class AcceptanceInterrupted(KeyboardInterrupt):
    """A checkpointed run was interrupted; carries the partial, truthful payload."""

    def __init__(self, payload: Mapping[str, object]) -> None:
        super().__init__("acceptance run interrupted")
        self.payload = dict(payload)


def _scenario_cwd(root: Path, item: Mapping[str, object]) -> str:
    cwd = item.get("cwd", ".") if isinstance(item.get("cwd", "."), str) else "."
    return str(root / cwd)


def _scenario_timeout(item: Mapping[str, object]) -> float:
    timeout = item.get("timeout", 60)
    return float(timeout) if isinstance(timeout, (int, float)) else 60.0


def _included(item: Mapping[str, object], include_e2e: bool, only_e2e: bool) -> bool:
    """Whether the scenario would actually execute under the current flags."""
    kind = str(item.get("kind", "functional"))
    mode = str(item.get("exec", ""))
    if kind == "manual" or mode in ("manual", "aspirational"):
        return False
    deferred = kind == "e2e" or mode == "deferred"
    if only_e2e:
        return deferred
    if deferred:
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
    if row.get("check") != item.get("check"):
        return False
    if row.get("check_config") and item.get("check_config") and row.get("check_config") != item.get("check_config"):
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


def _command_outcome(
    item: Mapping[str, object], root: Path, deadline: Optional[float],
    env: Optional[Mapping[str, str]] = None,
) -> dict[str, object]:
    """Execute one command identity and normalize its execution status."""
    command = item.get("command")
    if not isinstance(command, list) or not command or not all(isinstance(value, str) for value in command):
        return {"status": "not_configured"}
    timeout_value = _scenario_timeout(item)
    cwd = item.get("cwd", ".") if isinstance(item.get("cwd", "."), str) else "."
    outcome = run_command(command, str(root / cwd), timeout_value, deadline, env=env)
    if outcome["status"] == "deadline_exceeded":
        return {"status": "incomplete", "error": "deadline_exceeded"}
    if outcome["status"] == "timeout":
        return {"status": "failed", "error": "timeout",
                "output": str(outcome.get("stdout", ""))}
    if outcome["status"] == "spawn_error":
        return {"status": "failed", "error": str(outcome.get("stderr", ""))}
    if outcome["returncode"] == 0:
        return {"status": "passed", "exit_code": 0}
    output = (str(outcome.get("stdout", "")) + str(outcome.get("stderr", ""))).strip()[-4000:]
    return {"status": "failed", "exit_code": outcome["returncode"], "output": output}


def _run(
    item: Mapping[str, object], root: Path, include_e2e: bool = False, deadline: Optional[float] = None,
    only_e2e: bool = False, env: Optional[Mapping[str, str]] = None,
) -> dict[str, object]:
    scenario_id = str(item.get("id", "unknown"))
    kind = str(item.get("kind", "functional"))
    mode = str(item.get("exec", ""))
    if mode == "aspirational":
        return {"id": scenario_id, "kind": kind, "status": "not_included", "reason": "aspirational"}
    if kind == "manual" or mode == "manual":
        return {"id": scenario_id, "kind": kind, "status": "manual_pending"}
    deferred = kind == "e2e" or mode == "deferred"
    if only_e2e and not deferred:
        return {"id": scenario_id, "kind": kind, "status": "not_included"}
    if deferred and not include_e2e and not only_e2e:
        return {"id": scenario_id, "kind": kind, "status": "e2e_deferred"}
    outcome = _command_outcome(item, root, deadline, env)
    return {"id": scenario_id, "kind": kind, **outcome}


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
        checks = item.get("checks")
        if isinstance(checks, list) and checks and all(isinstance(value, str) for value in checks):
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


def _group_key(
    item: Mapping[str, object], root: Path, include_e2e: bool, only_e2e: bool
) -> Optional[str]:
    """Schema2 compatibility: identical independent commands share one run."""
    if item.get("depends_on") or not _included(item, include_e2e, only_e2e):
        return None
    return _identity_key(item, root, include_e2e, only_e2e)


def _unit_dependencies(
    units: list[dict[str, object]], scenario_unit: Mapping[str, str],
    by_id: Mapping[str, dict[str, object]],
) -> None:
    """Serialize a check when a scenario or the check itself declares depends_on."""
    for unit in units:
        wanted: list[str] = []
        check = unit.get("check")
        raw = check.get("depends_on", []) if isinstance(check, Mapping) else []
        if isinstance(raw, list):
            wanted.extend(str(dep) for dep in raw)
        for item in unit["scenarios"]:
            deps = item.get("depends_on", [])
            if isinstance(deps, list):
                wanted.extend(str(dep) for dep in deps)
        resolved: list[str] = []
        for dep in wanted:
            target = by_id.get(dep)
            if target is None:
                target = by_id.get(scenario_unit.get(dep, ""))
            if target is not None and target["id"] != unit["id"] and target["id"] not in resolved:
                resolved.append(str(target["id"]))
        unit["deps"] = resolved


def _build_units(
    items: Sequence[Mapping[str, object]], root: Path, check_map: Mapping[str, Mapping[str, object]],
    include_e2e: bool, only_e2e: bool,
) -> tuple[list[dict[str, object]], dict[str, str]]:
    """Group scenarios into check units (v3) or command-identity units (schema2)."""
    units: list[dict[str, object]] = []
    by_id: dict[str, dict[str, object]] = {}
    command_units: dict[str, dict[str, object]] = {}
    scenario_unit: dict[str, str] = {}
    for item in items:
        scenario_id = str(item.get("id"))
        check_id = item.get("check")
        if isinstance(check_id, str) and check_id in check_map:
            unit = by_id.get(check_id)
            if unit is None:
                unit = {"id": check_id, "check": check_map[check_id], "scenarios": [], "deps": []}
                by_id[check_id] = unit
                units.append(unit)
            unit["scenarios"].append(item)
            scenario_unit[scenario_id] = check_id
            continue
        key = _group_key(item, root, include_e2e, only_e2e)
        unit = command_units.get(key) if key is not None else None
        if unit is None:
            identity = (
                "command:" + hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]
                if key is not None else f"scenario:{scenario_id}"
            )
            unit = {"id": identity, "check": None, "scenarios": [], "deps": []}
            units.append(unit)
            by_id[identity] = unit
            if key is not None:
                command_units[key] = unit
        unit["scenarios"].append(item)
        scenario_unit[scenario_id] = str(unit["id"])
    _unit_dependencies(units, scenario_unit, by_id)
    return units, scenario_unit


def _unit_layers(units: Sequence[Mapping[str, object]]) -> list[list[Mapping[str, object]]]:
    """Stable dependency levels: every layer can run concurrently."""
    remaining = list(units)
    done: set[str] = set()
    layers: list[list[Mapping[str, object]]] = []
    while remaining:
        ready = [
            unit for unit in remaining
            if all(str(dep) in done for dep in unit.get("deps", []))
        ]
        if not ready:
            raise ValueError("acceptance check dependency cycle")
        layers.append(ready)
        done.update(str(unit["id"]) for unit in ready)
        remaining = [unit for unit in remaining if str(unit["id"]) not in done]
    return layers


def _unit_active(unit: Mapping[str, object], include_e2e: bool, only_e2e: bool) -> list[Mapping[str, object]]:
    return [
        item for item in unit["scenarios"]
        if _included(item, include_e2e, only_e2e)
    ]


def _unit_reusable(
    unit: Mapping[str, object], rows: Mapping[str, Mapping[str, object]], fingerprint: str,
    use_cache: bool, include_e2e: bool, only_e2e: bool, checkpoint: _Checkpoint,
) -> bool:
    """A check is reusable only when every active scenario is still fresh."""
    if not use_cache or not fingerprint or unit.get("deps"):
        return False
    active = _unit_active(unit, include_e2e, only_e2e)
    if not active:
        return False
    if checkpoint.reusable(unit):
        return True
    return all(_reusable(rows.get(str(item.get("id"))), item, fingerprint) for item in active)


def _reuse_results(
    unit: Mapping[str, object], root: Path, include_e2e: bool, only_e2e: bool, deadline: Optional[float],
    checkpoint: _Checkpoint,
) -> list[dict[str, object]]:
    checkpoint_reused = checkpoint.reusable(unit)
    results: list[dict[str, object]] = []
    for item in unit["scenarios"]:
        if not _included(item, include_e2e, only_e2e):
            results.append(_run(item, root, include_e2e, deadline, only_e2e))
            continue
        results.append({
            "id": str(item.get("id", "unknown")),
            "kind": str(item.get("kind", "functional")),
            "status": "passed",
            "exit_code": 0,
            "cache_reused": True,
            "checkpoint_reused": checkpoint_reused,
        })
    return results


def _accepted_risk(check: Optional[Mapping[str, object]]) -> Optional[dict[str, object]]:
    """A failed check may be archived as accepted risk only with a live, user-owned record."""
    if not isinstance(check, Mapping):
        return None
    risk = check.get("accepted_risk")
    if not isinstance(risk, Mapping):
        return None
    for field in ("owner", "reason", "confirmed_by", "confirmed_at", "source", "expires_at"):
        if not isinstance(risk.get(field), str) or not str(risk.get(field)).strip():
            return None
    expires = str(risk.get("expires_at")).strip()
    try:
        deadline = datetime.fromisoformat(expires.replace("Z", "+00:00"))
    except ValueError:
        return None
    if deadline.tzinfo is None:
        deadline = deadline.replace(tzinfo=timezone.utc)
    if deadline <= datetime.now(timezone.utc):
        return None
    return dict(risk)


def _apply_outcome(
    unit: Mapping[str, object], outcome: Mapping[str, object], root: Path,
    include_e2e: bool, only_e2e: bool, deadline: Optional[float],
) -> list[dict[str, object]]:
    """Project one check outcome onto every scenario that declares it."""
    check_id = str(unit["id"]) if unit.get("check") is not None else ""
    status = str(outcome.get("status"))
    results: list[dict[str, object]] = []
    for item in unit["scenarios"]:
        if not _included(item, include_e2e, only_e2e):
            results.append(_run(item, root, include_e2e, deadline, only_e2e))
            continue
        if status == "env_blocked":
            results.append(_env_blocked_result(item, check_id, outcome.get("missing", [])))
            continue
        result = {"id": str(item.get("id", "unknown")), "kind": str(item.get("kind", "functional"))}
        result.update({key: value for key, value in outcome.items() if key not in ("id", "kind")})
        if status == "failed":
            risk = _accepted_risk(unit.get("check"))
            if risk is not None:
                result["status"] = "accepted_risk"
                result["risk"] = risk
        if check_id and status in ("failed", "incomplete"):
            result["check_id"] = check_id
        results.append(result)
    return results


def _unit_preflight(
    check: Mapping[str, object], root: Path, env: Optional[Mapping[str, str]], deadline: Optional[float]
) -> Optional[dict[str, object]]:
    missing = _preflight_failures(check, root, env, deadline)
    if not missing:
        return None
    if any(str(entry.get("reason")) == "deadline_exceeded" for entry in missing):
        return {"status": "incomplete", "error": "deadline_exceeded"}
    return {"status": "env_blocked", "missing": missing}


def _execute_check(
    check: Mapping[str, object], root: Path, env: Mapping[str, str], deadline: Optional[float]
) -> dict[str, object]:
    gated = _unit_preflight(check, root, env, deadline)
    if gated is not None:
        return gated
    return _command_outcome(check, root, deadline, env)


def _execute_unit(
    unit: Mapping[str, object], root: Path, include_e2e: bool, only_e2e: bool,
    deadline: Optional[float], namespace: Optional[Mapping[str, str]],
) -> dict[str, object]:
    check = unit.get("check")
    if check is None:
        return _command_outcome(unit["scenarios"][0], root, deadline, None)
    if not _unit_active(unit, include_e2e, only_e2e):
        return {"status": "not_included"}
    env = check_environment(check, str(root), namespace)
    if is_isolated(check):
        return _execute_check(check, root, env, deadline)
    # Shared services cannot be partitioned: every worktree serializes on the
    # same lock, with a stale timeout so a crashed owner cannot stall a batch.
    remaining = remaining_seconds(deadline)
    if remaining is not None and remaining <= 0:
        return {"status": "incomplete", "error": "deadline_exceeded"}
    try:
        with shared_env_lock(str(root), wait=remaining):
            return _execute_check(check, root, env, deadline)
    except SharedEnvLockTimeout as exc:
        return {"status": "incomplete", "error": "shared_env_lock_timeout", "detail": str(exc)}


def _parallel_safe(unit: Mapping[str, object]) -> bool:
    check = unit.get("check")
    return isinstance(check, Mapping) and effective_parallel_safe(check)


def _unit_command(unit: Mapping[str, object]) -> tuple[list[str], str, float]:
    """Command identity used to validate a checkpoint entry on resume."""
    check = unit.get("check")
    source = check if isinstance(check, Mapping) else unit["scenarios"][0]
    command = source.get("command")
    argv = [str(value) for value in command] if isinstance(command, list) else []
    cwd = source.get("cwd", ".")
    return argv, cwd if isinstance(cwd, str) else ".", _scenario_timeout(source)


def _atomic_checkpoint(path: Path, payload: Mapping[str, object]) -> None:
    """Checkpoint files are replaced atomically, like every other evidence file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except OSError:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def _checkpoint_path(manifest_file: str, root: str) -> Path:
    from cf_evidence_store import requirement_key
    digest = hashlib.sha256(str(Path(manifest_file).resolve()).encode("utf-8")).hexdigest()[:16]
    requirement = requirement_key(Path(manifest_file).resolve().parent)
    return EvidenceStore(root, requirement).directory.parent / "_checkpoints" / f"acceptance-{digest}.json"


class _Checkpoint:
    """Per-check completion sidecar, separate from the user's manifest.

    The manifest is only rewritten when a run finishes, so an interrupt cannot
    leave partially-verified rows. Resume reads passed checks whose command
    identity and worktree freshness still match and reuses them.
    """

    def __init__(self, path: Path, fingerprint: str, enabled: bool, resume: bool,
                 fingerprints: Optional[Mapping[str, str]] = None) -> None:
        self.path = path
        self.fingerprint = fingerprint
        self.fingerprints = dict(fingerprints or {})
        self.enabled = enabled
        self.entries: dict[str, Mapping[str, object]] = {}
        if not enabled:
            return
        if resume:
            self.entries = self._read()
        else:
            self._write()  # a fresh run must not inherit an older run's progress

    def _read(self) -> dict[str, Mapping[str, object]]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        checks = data.get("checks") if isinstance(data, Mapping) else None
        if not isinstance(checks, Mapping):
            return {}
        return {
            str(key): value for key, value in checks.items() if isinstance(value, Mapping)
        }

    def _write(self) -> None:
        if not self.enabled:
            return
        payload = {
            "schema": 1,
            "fingerprint": self.fingerprint,
            "fingerprints": self.fingerprints,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "checks": self.entries,
        }
        _atomic_checkpoint(self.path, payload)

    def fingerprint_for(self, unit: Mapping[str, object]) -> str:
        if unit.get("check") is not None:
            return self.fingerprints.get(str(unit.get("id")), self.fingerprint)
        return self.fingerprint

    def reusable(self, unit: Mapping[str, object]) -> bool:
        if not self.enabled:
            return False
        entry = self.entries.get(str(unit.get("id")))
        if not isinstance(entry, Mapping):
            return False
        command, cwd, timeout = _unit_command(unit)
        try:
            recorded_timeout = float(entry.get("timeout", 60))
        except (TypeError, ValueError):
            return False
        return (
            entry.get("status") == "passed"
            and entry.get("fingerprint") == self.fingerprint_for(unit)
            and entry.get("command") == command
            and str(entry.get("cwd", ".")) == cwd
            and recorded_timeout == timeout
        )

    def record(self, unit: Mapping[str, object], outcome: Mapping[str, object]) -> None:
        if not self.enabled:
            return
        if outcome.get("status") != "passed":
            self.forget(unit)
            return
        command, cwd, timeout = _unit_command(unit)
        self.entries[str(unit["id"])] = {
            "status": "passed",
            "fingerprint": self.fingerprint_for(unit),
            "command": command,
            "cwd": cwd,
            "timeout": timeout,
        }
        self._write()

    def forget(self, unit: Mapping[str, object]) -> None:
        if not self.enabled:
            return
        if self.entries.pop(str(unit["id"]), None) is not None:
            self._write()


def _failure(status: str) -> bool:
    return status in ("failed", "not_configured")


class _UnitEngine:
    """Schedule check units, checkpointing each completion for resume."""

    def __init__(
        self, units: Sequence[Mapping[str, object]], root: Path, include_e2e: bool, only_e2e: bool,
        deadline: Optional[float], namespace: Optional[Mapping[str, str]],
        rows: Mapping[str, Mapping[str, object]], fingerprint: str, use_cache: bool,
        max_failures: int, checkpoint: _Checkpoint, jobs: int,
        fingerprints: Optional[Mapping[str, str]] = None,
    ) -> None:
        self.units = list(units)
        self.root = root
        self.include_e2e = include_e2e
        self.only_e2e = only_e2e
        self.deadline = deadline
        self.namespace = namespace
        self.rows = rows
        self.fingerprint = fingerprint
        self.fingerprints = dict(fingerprints or {})
        self.use_cache = use_cache
        self.max_failures = max_failures
        self.checkpoint = checkpoint
        self.jobs = max(1, jobs or DEFAULT_JOBS)
        self.results_by_id: dict[str, dict[str, object]] = {}
        self.completed: set[str] = set()
        self.failures = 0
        self.executed = 0
        self.reused = 0
        self.stop_reason = ""
        self.interrupted = False

    def run(self) -> tuple[dict[str, dict[str, object]], dict[str, object]]:
        try:
            for layer in _unit_layers(self.units):
                if self.stop_reason:
                    break
                self._run_layer(layer)
        except KeyboardInterrupt:
            self.interrupted = True
            self.stop_reason = "interrupted"
        self._fill_unfinished()
        state = {
            "executed": self.executed,
            "reused": self.reused,
            "interrupted": self.interrupted,
            "stopped_reason": self.stop_reason,
        }
        return self.results_by_id, state

    def _run_layer(self, layer: Sequence[Mapping[str, object]]) -> None:
        placeholders = [unit for unit in layer if not self._active(unit)]
        for unit in placeholders:
            self._record(unit, self._placeholder_results(unit))
        parallel = [unit for unit in layer if self._active(unit) and _parallel_safe(unit)]
        serial = [unit for unit in layer if self._active(unit) and not _parallel_safe(unit)]
        self._run_parallel(parallel)
        for unit in serial:
            self._run_one(unit)

    def _active(self, unit: Mapping[str, object]) -> bool:
        return bool(_unit_active(unit, self.include_e2e, self.only_e2e))

    def _can_start(self) -> bool:
        if self.stop_reason:
            return False
        if self.max_failures and self.failures >= self.max_failures:
            self._stop("max_failures_exceeded")
            return False
        if self._deadline_expired():
            self._stop("deadline_exceeded")
            return False
        return True

    def _stop(self, reason: str) -> None:
        if not self.stop_reason:
            self.stop_reason = reason

    def _deadline_expired(self) -> bool:
        remaining = remaining_seconds(self.deadline)
        return remaining is not None and remaining <= 0

    def _run_one(self, unit: Mapping[str, object]) -> None:
        if not self._can_start():
            return
        self._run_unit(unit)

    def _run_unit(self, unit: Mapping[str, object]) -> None:
        fingerprint = self.checkpoint.fingerprint_for(unit)
        if _unit_reusable(unit, self.rows, fingerprint, self.use_cache,
                          self.include_e2e, self.only_e2e, self.checkpoint):
            results = _reuse_results(unit, self.root, self.include_e2e, self.only_e2e,
                                     self.deadline, self.checkpoint)
            self.checkpoint.record(unit, {"status": "passed"})
            self.reused += len(_unit_active(unit, self.include_e2e, self.only_e2e))
            self._record(unit, self._with_input_hash(unit, results))
            return
        if unit.get("deps"):
            invalidate_executions()
        outcome = _execute_unit(unit, self.root, self.include_e2e, self.only_e2e,
                                self.deadline, self.namespace)
        self.executed += 1
        self._complete(unit, outcome)

    def _with_input_hash(self, unit: Mapping[str, object],
                         results: Sequence[Mapping[str, object]]) -> list[dict[str, object]]:
        value = self.checkpoint.fingerprint_for(unit)
        return [{**dict(result), "input_hash": value} for result in results]

    def _complete(self, unit: Mapping[str, object], outcome: Mapping[str, object]) -> None:
        results = _apply_outcome(unit, outcome, self.root, self.include_e2e,
                                 self.only_e2e, self.deadline)
        self._record(unit, self._with_input_hash(unit, results))
        self.checkpoint.record(unit, outcome)
        status = str(outcome.get("status"))
        if _failure(status):
            self.failures += 1
            if self.max_failures and self.failures >= self.max_failures:
                self._stop("max_failures_exceeded")
        if status == "incomplete" and outcome.get("error") == "deadline_exceeded":
            self._stop("deadline_exceeded")

    def _run_parallel(self, units: Sequence[Mapping[str, object]]) -> None:
        runnable = []
        for unit in units:
            if not self._can_start():
                break
            runnable.append(unit)
        if not runnable:
            return
        if len(runnable) == 1:
            self._run_unit(runnable[0])
            return
        workers = min(len(runnable), self.jobs)
        pool = ThreadPoolExecutor(max_workers=workers)
        pending: dict[Future, Mapping[str, object]] = {}
        cursor = 0
        interrupted = False
        try:
            while cursor < len(runnable) and len(pending) < workers:
                pending[pool.submit(self._execute, runnable[cursor])] = runnable[cursor]
                cursor += 1
            while pending:
                done, _ = wait(tuple(pending), return_when=FIRST_COMPLETED)
                for future in done:
                    unit = pending.pop(future)
                    self.executed += 1
                    self._complete(unit, future.result())
                while (not self.stop_reason and cursor < len(runnable)
                       and len(pending) < workers and self._can_start()):
                    unit = runnable[cursor]
                    cursor += 1
                    pending[pool.submit(self._execute, unit)] = unit
        except KeyboardInterrupt:
            self._drain_done(pending)
            interrupted = True
            raise
        finally:
            pool.shutdown(wait=not interrupted, cancel_futures=interrupted)

    def _drain_done(self, pending: dict[Future, Mapping[str, object]]) -> None:
        """A signal can arrive after a check finished but before it was recorded."""
        for future in tuple(pending):
            if not future.done() or future.cancelled():
                continue
            if future.exception() is not None:
                continue
            unit = pending.pop(future)
            self.executed += 1
            self._complete(unit, future.result())

    def _execute(self, unit: Mapping[str, object]) -> dict[str, object]:
        return _execute_unit(unit, self.root, self.include_e2e, self.only_e2e,
                             self.deadline, self.namespace)

    def _placeholder_results(self, unit: Mapping[str, object]) -> list[dict[str, object]]:
        return [
            _run(item, self.root, self.include_e2e, self.deadline, self.only_e2e)
            for item in unit["scenarios"]
        ]

    def _record(self, unit: Mapping[str, object], results: Sequence[Mapping[str, object]]) -> None:
        for result in results:
            self.results_by_id[str(result.get("id"))] = dict(result)
        self.completed.add(str(unit["id"]))

    def _fill_unfinished(self) -> None:
        reason = self.stop_reason or "incomplete"
        outcome = {"status": "incomplete", "error": reason}
        for unit in self.units:
            if str(unit["id"]) in self.completed:
                continue
            results = _apply_outcome(unit, outcome, self.root, self.include_e2e,
                                     self.only_e2e, self.deadline)
            for result in results:
                self.results_by_id.setdefault(str(result.get("id")), dict(result))


def _ordered_results(
    items: Sequence[Mapping[str, object]], results_by_id: Mapping[str, Mapping[str, object]]
) -> list[dict[str, object]]:
    """Stable output order independent of parallel completion order."""
    results: list[dict[str, object]] = []
    for item in items:
        scenario_id = str(item.get("id", "unknown"))
        result = results_by_id.get(scenario_id)
        if result is None:
            result = {"id": scenario_id, "kind": str(item.get("kind", "functional")),
                      "status": "incomplete", "error": "not_scheduled"}
        results.append(dict(result))
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
        elif any(value in ("failed", "not_configured") for value in statuses):
            status = "failed"
        elif any(value == "incomplete" for value in statuses):
            status = "incomplete"
        elif any(value == "env_blocked" for value in statuses):
            status = "env_blocked"
        elif any(value == "accepted_risk" for value in statuses):
            status = "accepted_risk"
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


def _check_input_fingerprints(
    root: str, check_map: Mapping[str, Mapping[str, object]], fallback: str
) -> dict[str, dict[str, str]]:
    """Per-check content identity; checks without inputs inherit repo scope."""
    outcomes = check_input_hashes(root, check_map, fallback)
    result: dict[str, dict[str, str]] = {}
    for check_id, check in check_map.items():
        outcome = outcomes.get(check_id, {})
        result[check_id] = {
            "input_hash": str(outcome.get("input_hash") or fallback),
            "scope": str(outcome.get("scope") or ("repo" if not check.get("inputs") else "empty")),
        }
    return result


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
    allowed = ("passed", "manual_pending", "e2e_deferred", "not_included", "accepted_risk")
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


def _run_counts(results: Sequence[Mapping[str, object]]) -> tuple[int, list[str]]:
    incomplete = sum(1 for item in results if item["status"] == "incomplete")
    failed = sorted(str(item["id"]) for item in results if item["status"] in ("failed", "not_configured"))
    return incomplete, failed


def _payload(
    items: Sequence[Mapping[str, object]], check_list: Sequence[Mapping[str, object]],
    check_map: Mapping[str, Mapping[str, object]], results: Sequence[Mapping[str, object]],
    state: Mapping[str, object],
) -> dict[str, object]:
    decision, error = _decision(results)
    if state.get("interrupted") and decision == "pass":
        decision, error = "block", "interrupted"
    incomplete, failed = _run_counts(results)
    outcome: dict[str, object] = {
        "decision": decision,
        "results": list(results),
        "executed": int(state.get("executed", 0)),
        "reused": int(state.get("reused", 0)),
        "incomplete": incomplete,
        "failed": failed,
    }
    if state.get("interrupted"):
        outcome["interrupted"] = True
    if state.get("stopped_reason"):
        outcome["stopped_reason"] = str(state["stopped_reason"])
    if check_list:
        outcome["checks"] = _check_summary(check_list, items, results)
    env_blocked = sum(1 for item in results if item["status"] == "env_blocked")
    outcome["env_blocked"] = env_blocked
    accepted = [item for item in results if item["status"] == "accepted_risk"]
    if accepted:
        outcome["accepted_risk"] = len(accepted)
        outcome["accepted_risk_details"] = [
            {
                "scenario": item.get("id"),
                "check_id": item.get("check_id") or item.get("id"),
                "risk": item.get("risk"),
            }
            for item in accepted
        ]
    if env_blocked:
        outcome["env_blocked_details"] = _env_blocked_details(check_map, results)
    if error:
        outcome["error"] = error
    return outcome


def _scenario_rows(scenarios: Sequence[Mapping[str, object]]) -> dict[str, Mapping[str, object]]:
    return {
        str(row.get("id")): row
        for row in scenarios
        if isinstance(row, Mapping) and isinstance(row.get("id"), str)
    }


def _make_checkpoint(
    manifest_file: str, root: str, fingerprint: str, use_cache: bool, resume: bool,
    fingerprints: Optional[Mapping[str, str]] = None,
) -> _Checkpoint:
    return _Checkpoint(
        _checkpoint_path(manifest_file, root), fingerprint,
        enabled=use_cache and bool(fingerprint), resume=resume,
        fingerprints=fingerprints,
    )


def _changed_paths(root: str) -> set[str]:
    changed: set[str] = set()
    for arguments in (("diff", "--name-only", "HEAD"), ("ls-files", "--others", "--exclude-standard")):
        completed = subprocess.run(("git", "-C", root, *arguments), text=True, capture_output=True, check=False)
        if completed.returncode == 0:
            changed.update(line.strip() for line in completed.stdout.splitlines() if line.strip())
    return changed


def _select_profile(data: Mapping[str, object], root: str, profile: str,
                    force_ids: Sequence[str] = ()) -> dict[str, object]:
    """Return a shallow manifest view filtered by smoke/changed/full."""
    if profile == "full":
        return dict(data)
    checks = {
        str(item.get("id")): item
        for item in data.get("checks", []) or []
        if isinstance(item, Mapping) and isinstance(item.get("id"), str)
    }
    changed = _changed_paths(root)
    scenarios = [item for item in data.get("scenarios", []) or [] if isinstance(item, Mapping)]
    explicit_priority = any(isinstance(item.get("priority"), str) for item in scenarios)
    forced = {str(item) for item in force_ids}
    selected: list[Mapping[str, object]] = []
    has_smoke_profile = any(str((check or {}).get("profile", "")) == "smoke" for check in checks.values())
    has_e2e = any(str(scenario.get("kind", "")) == "e2e" for scenario in scenarios)
    for scenario in scenarios:
        check = checks.get(str(scenario.get("check", "")))
        priority = str(scenario.get("priority", ""))
        if str(scenario.get("id")) in forced:
            selected.append(scenario)
            continue
        if profile == "smoke":
            if explicit_priority:
                if (priority.upper() == "P0" or str((check or {}).get("profile", "")) == "smoke"
                        or str(scenario.get("kind", "")) == "e2e"):
                    selected.append(scenario)
            elif has_smoke_profile:
                if str((check or {}).get("profile", "")) == "smoke":
                    selected.append(scenario)
            elif has_e2e:
                if str(scenario.get("kind", "")) == "e2e":
                    selected.append(scenario)
            else:
                selected.append(scenario)
            continue
        inputs = (check or {}).get("inputs")
        if (not explicit_priority or priority.upper() == "P0" or str((check or {}).get("profile", "")) == "smoke"
                or not inputs or not changed or any(
                    match_path(path, str(pattern)) for pattern in inputs for path in changed
                )):
            selected.append(scenario)
    selected_ids = {str(item.get("id")) for item in selected}
    selected_checks = [
        item for item in data.get("checks", []) or []
        if isinstance(item, Mapping) and any(
            str(scenario.get("check", "")) == str(item.get("id")) for scenario in selected
        )
    ]
    result = dict(data)
    result["scenarios"] = selected
    if "checks" in data:
        result["checks"] = selected_checks
    result["profile"] = profile
    return result


def _expand_multi_checks(items: Sequence[Mapping[str, object]]) -> tuple[list[dict[str, object]], dict[str, list[str]]]:
    """Expand scenarios with a checks list into one pseudo-scenario per check."""
    expanded: list[dict[str, object]] = []
    aggregates: dict[str, list[str]] = {}
    for item in items:
        checks = item.get("checks")
        if not isinstance(checks, list) or len(checks) <= 1:
            expanded.append(dict(item))
            continue
        scenario_id = str(item.get("id"))
        ids: list[str] = []
        for check_id in checks:
            pseudo = dict(item)
            pseudo["id"] = f"{scenario_id}::{check_id}"
            pseudo["check"] = str(check_id)
            pseudo.pop("checks", None)
            expanded.append(pseudo)
            ids.append(pseudo["id"])
        aggregates[scenario_id] = ids
    return expanded, aggregates


def _aggregate_multi_results(results: Sequence[Mapping[str, object]],
                             aggregates: Mapping[str, Sequence[str]]) -> list[dict[str, object]]:
    """Collapse pseudo-scenario results back to AND semantics on the real ID."""
    if not aggregates:
        return list(results)
    by_id = {str(item.get("id")): item for item in results}
    collapsed: list[dict[str, object]] = []
    consumed: set[str] = set()
    for result in results:
        result_id = str(result.get("id"))
        if "::" in result_id:
            consumed.add(result_id)
            continue
        collapsed.append(dict(result))
    for scenario_id, pseudo_ids in aggregates.items():
        members = [by_id[pseudo] for pseudo in pseudo_ids if pseudo in by_id]
        if not members:
            collapsed.append({"id": scenario_id, "status": "failed", "error": "checks_missing"})
            continue
        states = [str(member.get("status")) for member in members]
        if all(state in ("passed", "verified") for state in states):
            status = "passed"
        elif any(state in ("failed", "not_configured") for state in states):
            status = "failed"
        elif "env_blocked" in states:
            status = "env_blocked"
        elif "incomplete" in states:
            status = "incomplete"
        elif "e2e_deferred" in states:
            status = "e2e_deferred"
        else:
            status = "not_included"
        record = {"id": scenario_id, "status": status}
        if status == "passed":
            record["exit_code"] = 0
        else:
            record["error"] = ",".join(states)
        collapsed.append(record)
    del consumed
    return collapsed


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
    resume: bool = False,
    max_failures: int = 0,
    fail_fast: bool = False,
    jobs: int = 0,
    profile: str = "full",
    force_ids: Sequence[str] = (),
) -> dict[str, object]:
    if profile not in ("smoke", "changed", "full"):
        raise ValueError(f"invalid verify profile: {profile}")
    full_data = load_manifest(Path(manifest_file))
    data = _select_profile(full_data, root, profile, force_ids)
    validate_execution_baseline(Path(manifest_file), full_data)
    scenarios = data["scenarios"]
    _ordered(scenarios)  # Validate the complete DAG before owner filtering.
    items = _owned(scenarios, owner)
    if owner and not items:
        # TASK 无自有场景（Acceptance-Refs: N/A / 场景全归他人）：本任务执行验收
        # 视为空集通过；"零可执行场景"阻断只针对整体无场景的 manifest。
        return {"decision": "pass", "results": [], "reason": "no_owned_scenarios"}
    ordered = _ordered(items)
    expanded, aggregates = _expand_multi_checks(ordered)
    rows = _scenario_rows(scenarios)
    check_list, check_map = _check_plan(data)
    for item in items:
        if isinstance(item, dict):
            item["check_config"] = check_map.get(str(item.get("check", "")), {})
    run_key = resolve_run_id(run_id)
    namespace = _run_namespace(str(root), check_map, owner, items, run_key)
    fingerprint = worktree_fingerprint(str(root), include_untracked=False) if use_cache else ""
    check_fingerprints = _check_input_fingerprints(str(root), check_map, fingerprint) if use_cache else {}
    fingerprints = {
        check_id: value["input_hash"] for check_id, value in check_fingerprints.items()
    }
    limit = 1 if fail_fast else max(0, int(max_failures))
    checkpoint = _make_checkpoint(manifest_file, root, fingerprint, use_cache, resume, fingerprints)
    units, _ = _build_units(expanded, Path(root), check_map, include_e2e or only_e2e, only_e2e)
    engine = _UnitEngine(units, Path(root), include_e2e or only_e2e, only_e2e, deadline,
                         namespace, rows, fingerprint, use_cache, limit, checkpoint, jobs,
                         fingerprints=fingerprints)
    results_by_id, state = engine.run()
    results = _ordered_results(expanded if aggregates else ordered, results_by_id)
    results = _aggregate_multi_results(results, aggregates)
    for result, item in zip(results, ordered):
        if isinstance(result, dict) and isinstance(item, dict) and item.get("check_config"):
            result["check_config"] = item.get("check_config")
    # An interruption keeps the manifest untouched: the checkpoint sidecar is
    # the only progress record, so rows are never partially verified.
    if not state.get("interrupted") and (write_evidence or resume):
        persist_results(Path(manifest_file), full_data, results, fingerprint=fingerprint, run_id=run_key)
    outcome = _payload(items, check_list, check_map, results, state)
    for check in outcome.get("checks", []):
        identity = check_fingerprints.get(str(check.get("id")))
        if identity:
            check["input_hash"] = identity["input_hash"]
            check["input_scope"] = identity["scope"]
    if full_data.get("schema") == 2:
        outcome["schema2_compat"] = True
    if state.get("interrupted"):
        raise AcceptanceInterrupted(outcome)
    if not _executable(items):
        return {"decision": "block", "results": results, "error": "no_executable_scenarios"}
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
    parser.add_argument("--resume", action="store_true", help="Continue from the first unfinished/failed check using persisted checkpoints")
    parser.add_argument("--max-failures", type=int, default=0, help="Stop scheduling after N failed checks (0 = run all)")
    failure_mode = parser.add_mutually_exclusive_group()
    failure_mode.add_argument("--fail-fast", dest="fail_fast", action="store_true", help="Stop after the first failed check")
    failure_mode.add_argument("--continue", dest="fail_fast", action="store_false", help="Keep running after failures (default)")
    parser.set_defaults(fail_fast=False)
    parser.add_argument("--jobs", type=int, default=0, help="Maximum concurrent parallel-safe checks (0 = auto)")
    args = parser.parse_args(argv)
    try:
        result = run_manifest(
            args.manifest, args.root, args.write_evidence, args.include_e2e, args.owner,
            args.deadline or None, args.only_e2e, use_cache=not args.no_cache,
            resume=args.resume, max_failures=args.max_failures, fail_fast=args.fail_fast,
            jobs=args.jobs,
        )
        stdout.write(json.dumps(result, ensure_ascii=False))
        if result.get("interrupted"):
            return 130
        return 0 if result["decision"] == "pass" else 3
    except AcceptanceInterrupted as exc:
        stdout.write(json.dumps(exc.payload, ensure_ascii=False))
        return 130
    except KeyboardInterrupt:
        stdout.write(json.dumps({"decision": "block", "error": "interrupted", "interrupted": True},
                                ensure_ascii=False))
        return 130
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        stdout.write(json.dumps({"decision": "block", "error": str(exc)}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
