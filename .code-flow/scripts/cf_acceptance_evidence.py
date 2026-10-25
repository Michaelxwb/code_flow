"""Append execution history without erasing the user's acceptance contract."""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping, Optional, Sequence
from uuid import uuid4

from cf_evidence_store import EvidenceStore, discover_project_root, git_commit
from cf_acceptance_schema import check_outcome, load_manifest, recorded_check_hash, scenario_check_ids

STATES = frozenset(("planned", "pending", "tbd", "verified", "unverified", "stale", "failed", "incomplete", "not_configured", "e2e_deferred", "env_blocked", "manual_pending", "accepted_risk"))
_EVIDENCE_STATUS = {
    "passed": "passed",
    "failed": "failed",
    "incomplete": "incomplete",
    "not_configured": "not_configured",
    "e2e_deferred": "deferred",
    "env_blocked": "env_blocked",
    "accepted_risk": "accepted_risk",
}


def scenario_line(line: str, scenario_id: str) -> bool:
    return bool(re.match(rf"^\s*(?:\|\s*|[-*]\s+){re.escape(scenario_id)}(?=\s*[:|])", line))


def line_status(line: str, scenario_id: str) -> str:
    if not scenario_line(line, scenario_id):
        return ""
    if line.lstrip().startswith("|"):
        cells = [cell.strip().lower() for cell in line.strip().strip("|").split("|")]
        return next((cell for cell in reversed(cells) if cell in STATES), "")
    match = re.match(r"^\s*[-*]\s+[^:]+:\s*([a-z0-9_]+)\b", line, re.I)
    return match.group(1).lower() if match and match.group(1).lower() in STATES else ""


def _status_line(line: str, scenario_id: str, status: str) -> str:
    if not scenario_line(line, scenario_id):
        return line
    if line.lstrip().startswith("|"):
        cells = line.split("|")
        for index in range(len(cells) - 1, 0, -1):
            if cells[index].strip().lower() in STATES:
                cells[index] = f" {status} "
                return "|".join(cells)
        return line.rstrip().rstrip("|") + f"| {status} |"
    prefix = r"(^\s*[-*]\s+[^:]+:\s*)"
    if line_status(line, scenario_id):
        return re.sub(prefix + r"(?:" + "|".join(sorted(STATES)) + r")\b", rf"\g<1>{status}", line, count=1, flags=re.I)
    return re.sub(prefix, rf"\g<1>{status} — ", line, count=1)


def _patch_section(section: str, scenario_id: str, status: str, record: str) -> str:
    contract = re.search(r"(?ms)^### Acceptance Contract[^\n]*\n(.*?)(?=^### |^## |\Z)", section)
    if contract:
        body = "\n".join(_status_line(line, scenario_id, status) for line in contract.group(1).splitlines()) + "\n"
        section = section[:contract.start(1)] + body + section[contract.end(1):]
    evidence = re.search(r"(?ms)^### Acceptance Evidence[^\n]*\n(.*?)(?=^### |^## |\Z)", section)
    if evidence:
        body = evidence.group(1)
        if record not in body.splitlines():
            body = body.rstrip() + "\n" + record + "\n\n"
        section = section[:evidence.start(1)] + body + section[evidence.end(1):]
    else:
        section = section.rstrip() + "\n\n### Acceptance Evidence\n" + record + "\n"
    return section


def sync_task_evidence(task: Path, scenario_id: str, confirmed_by: str, evidence: str, owner: str = "", status: str = "verified") -> str:
    """Sync one scenario's status into the task file; returns what was written.

    - owner + TASK section → contract/evidence + coverage
    - ownerless legacy scenario → coverage only (a scenario with neither owner
      nor coverage has no truthful place to attribute evidence; first-TASK
      attribution corrupted unrelated contracts, so it is skipped)
    """
    text = task.read_text(encoding="utf-8")
    record = f"- {scenario_id}: {status} — {evidence} (confirmed_by: {confirmed_by})"
    if owner:
        task_pattern = re.escape(owner)
        match = re.search(rf"(?ms)^##\s+{task_pattern}:.*?(?=^## |\Z)", text)
        if match is None:
            raise ValueError(f"acceptance owner missing: {owner}")
        section = _patch_section(match.group(0), scenario_id, status, record)
        text = text[:match.start()] + section + text[match.end():]
    coverage = re.search(r"(?ms)^## Acceptance Coverage[^\n]*\n(.*?)(?=^## |\Z)", text)
    if coverage:
        body = "\n".join(_status_line(line, scenario_id, status) for line in coverage.group(1).splitlines()) + "\n"
        text = text[:coverage.start(1)] + body + text[coverage.end(1):]
    elif not owner:
        return "skipped_no_owner"
    from cf_spec_context import _atomic_text
    _atomic_text(task, text)
    return "synced"


def _run_record(row: Mapping[str, object], result: Mapping[str, object], run_id: str,
                executed_at: str, fingerprint: str, commit: str,
                check_config: Optional[Mapping[str, object]] = None) -> dict[str, object]:
    source = check_config if isinstance(check_config, Mapping) else row
    command = source.get("command")
    if not isinstance(command, list):
        command = []
    timeout = source.get("timeout", 60)
    cwd = source.get("cwd", ".")
    state = str(result.get("status"))
    exit_code = result.get("exit_code")
    return {
        "run_id": run_id,
        "check_id": str(row.get("check") or row.get("id")),
        "scenario_id": str(row.get("id")),
        "command": command,
        "cwd": cwd if isinstance(cwd, str) else ".",
        "timeout": timeout if isinstance(timeout, (int, float)) else 60,
        "input_hash": fingerprint if isinstance(fingerprint, str) else "",
        "exit_code": exit_code if isinstance(exit_code, int) else (0 if state == "passed" else 1),
        "status": _EVIDENCE_STATUS[state],
        "executed_at": executed_at,
        "source": str(result.get("source") or "local"),
        "commit": commit,
        "run_url": str(result.get("run_url") or ""),
    }


def _outcome_mapping(result: Mapping[str, object], field: str) -> Mapping[str, object]:
    value = result.get(field)
    return value if isinstance(value, Mapping) else {}


def _store_evidence_runs(path: Path, rows: Mapping[str, Mapping[str, object]],
                         results: Sequence[Mapping[str, object]], run_id: str,
                         executed_at: str, fingerprint: str) -> dict[str, int]:
    from cf_evidence_store import requirement_key
    project = discover_project_root(path.parent)
    store = EvidenceStore(project, requirement_key(path.parent))
    commit = git_commit(project)
    created = duplicates = 0
    for result in results:
        state = str(result.get("status"))
        if state not in _EVIDENCE_STATUS:
            continue
        if result.get("cache_reused") is True and result.get("checkpoint_reused") is not True:
            continue
        row = rows.get(str(result.get("id")))
        if row is None:
            continue
        result_fingerprint = str(result.get("input_hash") or fingerprint)
        raw_ids = result.get("check_ids")
        check_ids = [str(value) for value in raw_ids] if isinstance(raw_ids, list) else []
        check_id = str(row.get("check") or row.get("id"))
        if not check_ids:
            check_ids = [check_id]
        check_hashes = _outcome_mapping(result, "check_hashes")
        check_reused = _outcome_mapping(result, "check_reused")
        check_checkpoint = _outcome_mapping(result, "checkpoint_reused_checks")
        configs = _outcome_mapping(result, "check_configs")
        for item_id in check_ids:
            checkpointed = check_checkpoint.get(item_id, result.get("checkpoint_reused"))
            item_hash = str(check_hashes.get(item_id) or result_fingerprint)
            if check_reused.get(item_id) is True:
                if checkpointed is not True:
                    continue
                if any(
                    run.get("input_hash") == item_hash
                    and run.get("status") in ("passed", "verified")
                    for run in store.list_runs(item_id)
                ):
                    continue
            config = configs.get(item_id)
            record = _run_record(
                row, check_outcome(result, item_id), run_id, executed_at, item_hash, commit,
                config if isinstance(config, Mapping) else None,
            )
            record["check_id"] = item_id
            outcome = store.write_run(item_id, record)
            created += outcome["status"] == "created"
            duplicates += outcome["status"] == "duplicate"
    return {"created": created, "duplicates": duplicates}


def _restore_checkpoint(row: dict[str, object], result: Mapping[str, object], run_key: str,
                        executed_at: str, fingerprint: str) -> Optional[tuple[dict[str, object], str]]:
    if result["status"] != "passed" or row.get("status") == "verified":
        return None
    row["revision"] = int(row.get("revision", 0)) + 1
    record: dict[str, object] = {
        "id": result["id"],
        "kind": str(result.get("kind", "functional")),
        "status": "passed",
        "exit_code": 0,
        "cache_reused": True,
        "checkpoint_reused": True,
        "revision": row["revision"],
        "run_id": run_key,
        "executed_at": executed_at,
        "command": row.get("command"),
        "cwd": row.get("cwd", "."),
        "timeout": row.get("timeout", 60),
    }
    if fingerprint:
        record["fingerprint"] = fingerprint
    for key in ("check_ids", "check_hashes", "check_results", "check_reused", "checkpoint_reused_checks", "check_configs", "input_hash", "risk"):
        if key in result:
            record[key] = result[key]
    row["status"] = "verified"
    row.pop("stale_checks", None)
    return record, "verified"


def _record_result(row: dict[str, object], result: Mapping[str, object], run_key: str,
                   executed_at: str, fingerprint: str) -> Optional[tuple[dict[str, object], str]]:
    """Apply one result to a manifest row; None means keep the row unchanged."""
    state = str(result["status"])
    if result.get("cache_reused") is True:
        return _restore_checkpoint(row, result, run_key, executed_at, fingerprint)
    # A deferral placeholder (e2e skipped in a non-E2E run) must never
    # downgrade a verified terminal scenario: verify-e2e runs first, then
    # later Done/finish passes would otherwise silently un-verify it.
    if state == "e2e_deferred" and row.get("status") == "verified":
        return None
    # An unavailable environment is not new product evidence: keep a prior
    # verified conclusion, but never promote an unverified row.
    if state == "env_blocked" and row.get("status") == "verified":
        return None
    row["revision"] = int(row.get("revision", 0)) + 1
    status = "verified" if state == "passed" else state
    row["status"] = status
    row.pop("stale_checks", None)
    record = {**result, "revision": row["revision"], "run_id": run_key, "executed_at": executed_at}
    # Identity for cross-run reuse checks: command/cwd/timeout + content
    # fingerprint of the worktree the command actually ran against.
    record["command"] = row.get("command")
    record["cwd"] = row.get("cwd", ".")
    record["timeout"] = row.get("timeout", 60)
    if fingerprint and status == "verified":
        record["fingerprint"] = fingerprint
    return record, status


def stale_scenario_checks(row: Mapping[str, object], hashes: Mapping[str, Mapping[str, object]],
                          fingerprint: str) -> list[str]:
    """Compare every declared check; a missing or unavailable hash is stale."""
    if row.get("status") not in ("verified", "accepted_risk", "stale"):
        return []
    if row.get("kind") == "manual" or row.get("exec") in ("manual", "aspirational"):
        return []
    check_ids = scenario_check_ids(row)
    evidence = row.get("evidence")
    evidence = evidence if isinstance(evidence, Mapping) else {}
    if not check_ids:
        return [] if fingerprint and evidence.get("fingerprint") == fingerprint else [str(row["id"])]
    stale = []
    for check_id in check_ids:
        expected = hashes.get(check_id, {}).get("input_hash")
        actual = recorded_check_hash(row, check_id)
        if not expected or expected != actual:
            stale.append(check_id)
    return stale


def invalidate_manifest_evidence(root: Path, manifest: Path,
                                 fingerprint: str) -> list[dict[str, object]]:
    """Mark outdated conclusions without changing historical execution evidence."""
    from cf_check_inputs import check_input_hashes
    from cf_spec_context import _atomic_text
    data = load_manifest(manifest)
    checks = {str(check["id"]): check for check in data.get("checks", [])}
    hashes = check_input_hashes(str(root), checks, fingerprint)
    changed: list[dict[str, object]] = []
    for row in data["scenarios"]:
        stale = stale_scenario_checks(row, hashes, fingerprint)
        if not stale:
            continue
        row.update(status="stale", stale_checks=stale)
        changed.append({"scenario_id": row["id"], "checks": stale})
    if not changed:
        return []
    _atomic_text(manifest, json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    task_name = data.get("task_file")
    if isinstance(task_name, str) and task_name:
        task = (manifest.parent / task_name).resolve()
        rows = {row["id"]: row for row in data["scenarios"]}
        for item in changed:
            row = rows[item["scenario_id"]]
            sync_task_evidence(task, str(row["id"]), "runtime",
                               "input changed: " + ", ".join(item["checks"]),
                               str(row.get("owner", "")), "stale")
    return changed


def persist_results(path: Path, data: dict[str, object], results: Sequence[Mapping[str, object]],
                    fingerprint: str = "", run_id: str = "") -> None:
    rows = {row["id"]: row for row in data["scenarios"]}
    run_key, executed_at = run_id or uuid4().hex, datetime.now(timezone.utc).isoformat()
    updates = []
    for result in results:
        state = str(result["status"])
        if state in ("not_included", "manual_pending"):
            continue
        row = rows[result["id"]]
        result_fingerprint = str(result.get("input_hash") or fingerprint)
        applied = _record_result(row, result, run_key, executed_at, result_fingerprint)
        if applied is None:
            continue
        record, status = applied
        row["evidence"] = record
        if result.get("cache_reused") is not True:
            runs = row.setdefault("runs", [])
            runs.append(record)
            if len(runs) > 50:
                del runs[:-50]
        updates.append((row, record, status))
    from cf_spec_context import _atomic_text
    _atomic_text(path, json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    _store_evidence_runs(path, rows, results, run_key, executed_at, fingerprint)
    task_name = data.get("task_file")
    if isinstance(task_name, str) and task_name:
        task = Path(task_name) if Path(task_name).is_absolute() else path.parent / task_name
        for row, record, status in updates:
            detail = f"automated command {record['status']}; run_id={run_key}"
            sync_task_evidence(task, str(row["id"]), "runner", detail, str(row.get("owner", "")), status)
