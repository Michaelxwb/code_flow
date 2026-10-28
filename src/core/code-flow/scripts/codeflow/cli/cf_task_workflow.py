"""Executable task handoffs used by every platform command."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import fnmatch
import json
import os
from pathlib import Path
import re
from typing import IO, Mapping, Optional, Sequence
import shutil
import sys
import time

from codeflow.cli.cf_acceptance_manifest import record_manual_evidence
from codeflow.acceptance.cf_acceptance_schema import load_manifest, verified_evidence
from codeflow.core.cf_exec_base import execution_session
from codeflow.core import cf_git
from codeflow.cli.cf_spec_context import (ContextError, DEFAULT_ACTIVE_EXCLUDES, Decision, SpecContext,
                             apply_decision, load_active_task, load_context, save_context,
                             start_active_task)
from codeflow.spec.cf_stage_gate import evidence_deferral_kind
from codeflow.spec.cf_spec_context_model import context_sha256
from codeflow.task.cf_task_runtime import is_non_execution_error, run_done_gate
from codeflow.task.cf_requirement_verification import (
    VERIFY_LAYERS, VERIFY_PROFILES, collect_requirement_bindings, collect_review_bindings,
    demand_tasks as _demand_tasks, e2e_preflight as _e2e_preflight,
    parse_verify_layers, parse_verify_profile, pending_manual_rules as _pending_manual_rules,
    stale_functional_rows as _stale_functional_rows, verify_layers,
)
from codeflow.spec.cf_workflow_service import (FINISHED_STATUSES, require_active_task,
                                 block_task, check_startable, complete_requirement_verification,
                                 cleanup_session_projections, complete_task,
                                 locate_task_file, provisional_task, read_task_section,
                                 remove_session_projection, resume_task, task_truth_issues)
from codeflow.spec.cf_workflow_transaction import recover_transition


def finish_task(root: str, directory: str, task_file: str, task_id: str) -> dict[str, object]:
    require_active_task(root, task_id, directory, task_file)
    gate = run_done_gate(root, directory, task_id=task_id)
    if gate.decision == "provisional":
        transition = provisional_task(root, directory, task_file, task_id, gate.message)
        return {
            "decision": "provisional",
            "reason": gate.message,
            "missing_checks": list(gate.missing_checks),
            "next": gate.next_action,
            "env_blocked_details": list(gate.env_blocked_details),
            "deferred_review": gate.deferred_review,
            "deferred_requirement": gate.deferred_requirement,
            "deferred_budget": gate.deferred_budget,
            "deferred_heavy": gate.deferred_heavy,
            "evidence": gate.evidence,
            **transition,
        }
    if gate.decision != "pass":
        return {"decision": "block", "reason": gate.message, "evidence": gate.evidence,
                "env_blocked_details": list(gate.env_blocked_details)}
    completed = complete_task(root, directory, task_file, task_id, True)
    # 完成后清理本任务的 Spec Session 投影（瞬时文件，避免往期规则被后续会话读到）
    result = {
        "decision": "pass",
        "deferred_review": gate.deferred_review,
        "deferred_requirement": gate.deferred_requirement,
        "deferred_budget": gate.deferred_budget,
        "deferred_heavy": gate.deferred_heavy,
        "session_projection": remove_session_projection(root, task_file),
        **completed,
    }
    hints = []
    deferred_total = gate.deferred_review + gate.deferred_requirement + gate.deferred_budget
    if deferred_total:
        hints.append(f"{deferred_total} verifier(s) deferred; run cf-task:verify-e2e for the requirement directory")
    if gate.deferred_heavy:
        hints.append(f"{gate.deferred_heavy} heavy validator(s) deferred; archive / cf-validate runs them")
    if hints:
        result["deferred_hint"] = " | ".join(hints)
    return result


_CAPABILITY_LINE = re.compile(r"^- \*\*(?:Capability|Demo)\*\*:[ \t]*(.*)$")


def _normalize_capability(value: str) -> str:
    return " ".join(value.split()).casefold()


def _task_capability(task_file: Path, task_id: str) -> str:
    """Read the user-demonstrable capability declared by one TASK section."""
    try:
        section = read_task_section(str(task_file), task_id)
    except ValueError:
        return ""
    for line in section.splitlines():
        match = _CAPABILITY_LINE.match(line)
        if match:
            return " ".join(match.group(1).split())
    return ""


def _unique_ids(values: Sequence[str]) -> list[str]:
    seen: set[str] = set()
    chosen: list[str] = []
    for value in values:
        task_id = value.strip()
        if task_id and task_id not in seen:
            seen.add(task_id)
            chosen.append(task_id)
    return chosen


def _batch_selection(directory: Path, tasks: Sequence[str],
                     capability: str) -> tuple[list[tuple[Path, str, str]], str]:
    """Resolve --batch IDs or a --capability name to TASK file/status tuples."""
    available = _demand_tasks(directory)
    by_id = {task_id: (task_file, status) for task_file, task_id, status in available}
    if capability.strip():
        wanted = _normalize_capability(capability)
        selected = [
            (task_file, task_id, status)
            for task_file, task_id, status in available
            if _normalize_capability(_task_capability(task_file, task_id)) == wanted
        ]
        if not selected:
            known = sorted({_task_capability(f, t) for f, t, _ in available} - {""})
            raise ValueError(
                f"unknown_capability: {capability.strip()}; available: {', '.join(known) or 'none'}"
            )
        return selected, "capability"
    chosen = _unique_ids(tasks)
    if not chosen:
        raise ValueError("batch_empty: pass --batch TASK-... or --capability <name>")
    unknown = [task_id for task_id in chosen if task_id not in by_id]
    if unknown:
        raise ValueError(f"unknown_tasks: {', '.join(unknown)}")
    return [(by_id[task_id][0], task_id, by_id[task_id][1]) for task_id in chosen], "batch"


def _batch_working_changes(root: str) -> tuple[str, ...]:
    """Current business changes, ignoring the paths the active marker excludes."""
    return tuple(sorted(
        path for path in cf_git.changed_files(root)
        if not any(fnmatch.fnmatchcase(path, pattern) for pattern in DEFAULT_ACTIVE_EXCLUDES)
    ))


def _batch_active_task(root: str) -> str:
    if not (Path(root) / ".code-flow/.active-task.json").exists():
        return ""
    return load_active_task(root).task_id


def _ensure_batch_marker(root: str, directory: str, task_id: str) -> bool:
    """Open a transient marker for one batch task; returns True when created.

    A pre-existing marker is only accepted for the same TASK. Other TASKs are
    rejected: silently switching identity would let a batch finish arbitrary
    work that was never started.
    """
    marker = Path(root) / ".code-flow/.active-task.json"
    if marker.exists():
        active = load_active_task(root)
        if active.task_id != task_id:
            raise ValueError(f"active_mismatch: marker={active.task_id} requested={task_id}")
        if active.status != "active":
            raise ValueError(f"active_not_ready: {active.task_id} is {active.status}")
        return False
    context = load_context(str(Path(directory) / "spec-context.yml"))
    start_active_task(root, directory, task_id, context_sha256(context), _batch_working_changes(root))
    return True


def _abandon_batch_marker(root: str) -> bool:
    """Drop a batch marker without changing the Markdown view.

    A failed TASK must stay open (draft/in-progress) and must not claim done;
    the marker only holds the single active slot, so it cannot be left behind
    while the rest of the batch continues.
    """
    marker = Path(root) / ".code-flow/.active-task.json"
    if not marker.exists():
        return False
    from codeflow.cli.cf_spec_context import doctor_active_task

    doctor_active_task(root, "", abandon=True)
    return True


def _task_evidence_counts(evidence: Sequence[Mapping[str, object]]) -> tuple[int, int]:
    executed = reused = 0
    for item in evidence:
        if evidence_deferral_kind(item) in ("review_stage", "heavy"):
            continue
        if is_non_execution_error(item.get("error_code")):
            continue
        details = item.get("details")
        details = details if isinstance(details, Mapping) else {}
        if details.get("cache_reused"):
            reused += 1
        else:
            executed += 1
    return executed, reused


def _acceptance_task_evidence(directory: str, task_id: str) -> list[dict[str, object]]:
    """Project the TASK's persisted manifest rows into per-check evidence."""
    manifest = Path(directory) / ".acceptance-manifest.json"
    if not manifest.is_file():
        return []
    try:
        data = load_manifest(manifest)
    except (OSError, ValueError):
        return []
    items: list[dict[str, object]] = []
    for row in data.get("scenarios") or ():
        if not isinstance(row, Mapping):
            continue
        owner = row.get("owner")
        if isinstance(owner, str) and owner and owner != task_id:
            continue
        record = row.get("evidence")
        if not isinstance(record, Mapping):
            continue
        scenario_id = str(row.get("id", ""))
        check_id = str(row.get("check") or scenario_id)
        verified = row.get("status") == "verified"
        items.append({
            "verifier_ref": check_id,
            "check_id": check_id,
            "status": "verified" if verified else "unverified",
            "error_code": None if verified else "acceptance_failed",
            "details": {"scenario": scenario_id, "cache_reused": bool(record.get("cache_reused"))},
        })
    return items


def _finish_batch_task(root: str, directory: str, task_file: str, task_id: str) -> dict[str, object]:
    """Run one TASK inside the shared batch execution session."""
    activated = _ensure_batch_marker(root, directory, task_id)
    try:
        gate = run_done_gate(root, directory, task_id=task_id)
        evidence = [*gate.evidence, *_acceptance_task_evidence(directory, task_id)]
        executed, reused = _task_evidence_counts(evidence)
        if gate.decision == "pass":
            completed = complete_task(root, directory, task_file, task_id, True)
            result = {
                **completed,
                "task": task_id,
                "decision": "pass",
                "status": "done",
                "activated": activated,
                "executed": executed,
                "reused": reused,
                "evidence": evidence,
                "session_projection": remove_session_projection(root, task_file),
            }
            return result
        result = {
            "task": task_id,
            "decision": gate.decision,
            "status": "unchanged",
            "reason": gate.message,
            "activated": activated,
            "executed": executed,
            "reused": reused,
            "missing_checks": list(gate.missing_checks),
            "next": gate.next_action,
            "evidence": evidence,
        }
        result["marker_cleared"] = _abandon_batch_marker(root)
        return result
    except Exception:
        _abandon_batch_marker(root)
        raise


def _aggregate_batch_checks(
    results: Sequence[Mapping[str, object]],
) -> tuple[list[dict[str, object]], int, int]:
    """Fold per-task evidence into one entry per check (executed once, reused N)."""
    checks: dict[str, dict[str, object]] = {}
    order: list[str] = []
    for result in results:
        task = str(result.get("task", ""))
        evidence = result.get("evidence")
        if not isinstance(evidence, Sequence):
            continue
        for item in evidence:
            if not isinstance(item, Mapping):
                continue
            kind = evidence_deferral_kind(item)
            if kind in ("review_stage", "heavy"):
                continue
            check_id = str(item.get("verifier_ref") or item.get("check_id") or "")
            if not check_id:
                continue
            entry = checks.get(check_id)
            if entry is None:
                entry = {"check_id": check_id, "status": "verified", "tasks": [],
                         "executions": 0, "reused": 0}
                checks[check_id] = entry
                order.append(check_id)
            if task and task not in entry["tasks"]:
                entry["tasks"].append(task)
            if item.get("status") != "verified":
                entry["status"] = "failed"
            if is_non_execution_error(item.get("error_code")):
                continue
            if entry["executions"] == 0:
                entry["executions"] = 1
            else:
                entry["reused"] = int(entry["reused"]) + 1
    aggregated = [checks[check_id] for check_id in order]
    executed = sum(1 for item in aggregated if int(item["executions"]) > 0)
    reused = sum(int(item["reused"]) for item in aggregated)
    return aggregated, executed, reused


def _run_batch_tasks(root: str, directory: str,
                     selected: Sequence[tuple[Path, str, str]]) -> list[dict[str, object]]:
    results: list[dict[str, object]] = []
    with execution_session():
        for task_file, task_id, status in selected:
            if status in FINISHED_STATUSES:
                results.append({"task": task_id, "decision": "pass", "status": "already_done",
                                "reason": "already_done", "activated": False,
                                "executed": 0, "reused": 0, "evidence": []})
                continue
            blockers = check_startable(str(task_file), task_id)
            if blockers:
                results.append({"task": task_id, "decision": "block", "status": status,
                                "reason": "start_blocked", "blockers": blockers,
                                "activated": False, "executed": 0, "reused": 0, "evidence": []})
                continue
            try:
                results.append(_finish_batch_task(root, directory, str(task_file), task_id))
            except (OSError, ValueError) as exc:
                results.append({"task": task_id, "decision": "block", "status": status,
                                "reason": "batch_task_error", "error": str(exc),
                                "activated": False, "executed": 0, "reused": 0, "evidence": []})
    return results


def _batch_payload(results: Sequence[Mapping[str, object]], selected: Sequence[tuple[Path, str, str]],
                   mode: str, capability: str) -> dict[str, object]:
    checks, executed, reused = _aggregate_batch_checks(results)
    decisions = {str(item.get("decision")) for item in results}
    decision = "block" if "block" in decisions else "provisional" if "provisional" in decisions else "pass"
    failed = [str(item["task"]) for item in results if item.get("decision") == "block"]
    first_reason = next(
        (str(item.get("reason", "")) for item in results if item.get("decision") != "pass"), ""
    )
    return {
        "decision": decision,
        "action": "finish-batch",
        "reason": "batch_failed: " + ", ".join(failed) if failed else first_reason,
        "selection": {"mode": mode, "tasks": [item[1] for item in selected],
                      "capability": capability.strip() or None},
        "results": list(results),
        "evidence": checks,
        "executed": executed,
        "reused": reused,
        "failed": failed,
        "env_blocked": sum(
            1 for item in results if str(item.get("reason", "")).startswith("env")
        ),
        "incomplete": sum(1 for item in results if item.get("decision") == "provisional"),
    }


def finish_batch(root: str, directory: str, tasks: Sequence[str] = (),
                 capability: str = "") -> dict[str, object]:
    """Batch Done Gate: one shared execution session for a TASK list/capability.

    Every selected TASK is gated independently, so one failure does not mark
    the others done or block their completion. Code checks shared by the batch
    execute once inside the session; their evidence is folded per check.
    """
    recover_transition(root)
    selected, mode = _batch_selection(Path(directory), tasks, capability)
    active_id = _batch_active_task(root)
    selected_ids = [task_id for _, task_id, _ in selected]
    if active_id and active_id not in selected_ids:
        return {
            "decision": "block",
            "action": "finish-batch",
            "reason": "active_mismatch",
            "detail": f"marker={active_id}; batch={','.join(selected_ids)}",
            "results": [],
        }
    # The active TASK must be consumed before any transient marker is opened.
    selected.sort(key=lambda item: 0 if item[1] == active_id else 1)
    return _batch_payload(_run_batch_tasks(root, directory, selected), selected, mode, capability)


def _complete_requirement_verification(root: str, directory: str,
                                       tasks: Sequence[tuple[Path, str, str]],
                                       result: dict[str, object]) -> dict[str, object]:
    return complete_requirement_verification(root, directory, tasks, result)


def verify_e2e(root: str, directory: str, layers: Optional[str] = None,
               profile: Optional[str] = None, resume: bool = True,
               deadline: Optional[float] = None, max_failures: int = 0,
               fail_fast: bool = False, jobs: int = 0) -> dict[str, object]:
    """Legacy alias: all layers under the explicit full profile."""
    result = verify_layers(root, directory, layers or ",".join(VERIFY_LAYERS), profile or "full",
                           resume=resume, deadline=deadline, max_failures=max_failures,
                           fail_fast=fail_fast, jobs=jobs)
    layer_map = result.get("layers", {})
    if "review" in layer_map:
        review = layer_map["review"]
        result["review"] = review.get("review", {
            "executed": review.get("executed", 0),
            "reused": review.get("reused", 0),
            "failed": review.get("failed", []),
        })
        result["executed"] = review.get("executed", 0)
        result["reused"] = review.get("reused", 0)
        result["failed"] = review.get("failed", [])
    if "validators" in layer_map:
        result["validation"] = layer_map["validators"].get("validation", {
            "decision": layer_map["validators"].get("decision"),
            "reason": layer_map["validators"].get("reason", ""),
            "reused": layer_map["validators"].get("reused", 0),
            "failures": layer_map["validators"].get("failed", []),
        })
    if "e2e" in layer_map:
        for key in ("results", "checks", "error"):
            if key in layer_map["e2e"]:
                result[key] = layer_map["e2e"][key]
    return result


def _archived_risks(directory: Path) -> list[dict[str, object]]:
    """Accepted risks are archived distinctly from verified evidence."""
    manifest = directory / ".acceptance-manifest.json"
    if not manifest.is_file():
        return []
    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return []
    risks = []
    for check in data.get("checks", []) if isinstance(data.get("checks"), list) else []:
        if isinstance(check, Mapping) and isinstance(check.get("accepted_risk"), Mapping):
            risks.append({"check_id": check.get("id"), **dict(check["accepted_risk"])})
    return risks


def archive_requirement(root: str, directory: str) -> dict[str, object]:
    """Runtime archive gate: full verify first, then move the requirement dir."""
    from datetime import date
    from pathlib import Path as _Path

    result = verify_layers(root, directory, layers=",".join(VERIFY_LAYERS), profile="full")
    if result.get("decision") != "pass":
        return {"decision": "block", "reason": "archive_verify_failed", "verify": result}
    source = _Path(directory)
    accepted_risks = _archived_risks(source)
    base = _Path(root) / ".code-flow/tasks/archived" / date.today().isoformat()
    target = base / source.name
    suffix = 2
    while target.exists():
        target = base / f"{source.name}-{suffix}"
        suffix += 1
    base.mkdir(parents=True, exist_ok=True)
    shutil.move(str(source), str(target))
    result = {"decision": "pass", "archived_to": str(target)}
    if accepted_risks:
        result["accepted_risks"] = accepted_risks
    return result


def confirm_manual(root: str, directory: str, refs: Sequence[str], scenarios: Sequence[str],
                   confirmed_by: str, source: str, reason: str = "", evidence: str = "") -> dict[str, object]:
    """用户确认后批量写入 manual 验收记录（review 层 spec 规则 + manifest 场景）。

    只有用户明确确认后才能调用；Agent 不得代确认（agent 身份会被拒绝）。
    """
    owner = confirmed_by.strip()
    if not owner:
        raise ValueError("confirm-manual 需要 --confirmed-by <用户身份>")
    if not source.strip():
        raise ValueError("confirm-manual 需要 --source <用户回复原文>")
    targets = collect_review_bindings(Path(directory))
    pending_rules, confirmations = _pending_manual_rules(root, targets)
    known = {str(item["ref"]) for item in pending_rules}
    for spec_id, by_rule in confirmations.items():
        known.update(f"{spec_id}#{rule_ref}" for rule_ref in by_rule)
    chosen = [ref.strip() for ref in refs if ref.strip()] or sorted(str(item["ref"]) for item in pending_rules)
    unknown = sorted(ref for ref in chosen if ref not in known)
    if unknown:
        raise ValueError(f"unknown_or_not_review_manual_ref: {', '.join(unknown)}")
    reason_text = reason.strip() or "需求级人工验收确认"
    confirmed_at = datetime.now(timezone.utc).isoformat()
    records: dict[Path, SpecContext] = {}
    for ref in chosen:
        spec_id, rule_ref = ref.split("#", 1)
        for ctx_path, _ in targets[spec_id]["rules"][rule_ref]:
            context = records.get(ctx_path) or load_context(str(ctx_path))
            decision = Decision("manual_verification", reason_text, owner, confirmed_at, source.strip(), None)
            records[ctx_path] = apply_decision(context, spec_id, rule_ref, "review", decision)
    for ctx_path in sorted(records, key=str):
        save_context(str(ctx_path), records[ctx_path])
    recorded_scenarios: list[str] = []
    manifest = Path(directory) / ".acceptance-manifest.json"
    if manifest.is_file():
        data = load_manifest(manifest)
        rows = {str(row.get("id")): row for row in data.get("scenarios", [])}
        if scenarios:
            chosen_scenarios = [sid.strip() for sid in scenarios if sid.strip()]
        else:
            chosen_scenarios = [sid for sid, row in rows.items()
                                if row.get("kind") == "manual" and not verified_evidence(row)]
        for sid in chosen_scenarios:
            row = rows.get(sid)
            if row is None or (row.get("kind") != "manual" and row.get("exec") != "manual"):
                raise ValueError(f"unknown_manual_scenario: {sid}")
            if verified_evidence(row):
                continue
            record_manual_evidence(str(manifest), sid, owner, evidence.strip() or source.strip())
            recorded_scenarios.append(sid)
    if not chosen and not recorded_scenarios:
        raise ValueError("no_pending_manual_confirmation")
    return {
        "ok": True,
        "rules": chosen,
        "scenarios": recorded_scenarios,
        "confirmed_by": owner,
        "confirmed_at": confirmed_at,
        "note": "确认已写入 spec-context / manifest；重跑 verify-e2e 完成终验",
    }


def _verify_layers_argument(layers: str, checks: bool) -> Optional[str]:
    """Map the cf-validate compatible ``--checks`` flag onto validators only."""
    if not checks:
        return layers or None
    if layers and parse_verify_layers(layers) != ("validators",):
        raise ValueError("--checks is an alias for --layers validators; pass one of them")
    return "validators"


def _verification_arguments(parser: argparse.ArgumentParser, action: str) -> None:
    parser.add_argument("--layers", default="", help="verify layers: validators,review,e2e (default all)")
    parser.add_argument("--checks", action="store_true",
                        help="alias for --layers validators (cf-validate compatible entry)")
    default_profile = "full" if action == "verify-e2e" else "changed"
    parser.add_argument("--profile", default="", choices=VERIFY_PROFILES,
                        help=f"verify profile (default {default_profile})")
    parser.add_argument("--resume", action="store_true", default=False, help="resume from the first unfinished check")
    parser.add_argument("--deadline", type=float, default=0.0, help="deadline in seconds from now (0 = unbounded)")
    parser.add_argument("--max-failures", type=int, default=0, help="stop after N failed checks (0 = unlimited)")
    parser.add_argument("--fail-fast", action="store_true", default=False, help="stop after the first failed check")
    parser.add_argument("--jobs", type=int, default=0, help="parallel check workers (0 = automatic)")


def _workflow_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog=os.environ.get("CF_RUNTIME_COMMAND") or None,
                                     allow_abbrev=False)
    actions = parser.add_subparsers(dest="action", required=True)
    for name in ("finish", "block", "resume", "verify", "verify-e2e",
                 "confirm-manual", "cleanup-session", "archive"):
        action = actions.add_parser(name, allow_abbrev=False)
        action.add_argument("--root", default=os.getcwd())
        action.add_argument("--task-dir", required=True)
        action.add_argument("--json", action="store_true")
        if name in ("verify", "verify-e2e"):
            _verification_arguments(action, name)
        if name in ("finish", "block", "resume"):
            action.add_argument("--task", default="")
        if name == "finish":
            action.add_argument("--batch", default="", help="finish multiple TASKs: TASK-001,TASK-002")
            action.add_argument("--capability", default="", help="finish TASKs whose Capability matches")
        if name in ("block", "confirm-manual"):
            action.add_argument("--reason", default="")
        if name == "confirm-manual":
            for flag in ("--refs", "--scenarios", "--confirmed-by", "--source", "--evidence"):
                action.add_argument(flag, default="")
    return parser


def _verify_from_arguments(args: argparse.Namespace, root: str, directory: str) -> dict[str, object]:
    layers = _verify_layers_argument(args.layers, args.checks)
    verify = verify_e2e if args.action == "verify-e2e" else verify_layers
    return verify(root, directory, layers, args.profile or None, resume=args.resume,
                  deadline=(time.monotonic() + args.deadline) if args.deadline else None,
                  max_failures=args.max_failures, fail_fast=args.fail_fast, jobs=args.jobs)


def _dispatch_action(args: argparse.Namespace, root: str, directory: str) -> dict[str, object]:
    if args.action == "archive":
        return archive_requirement(root, directory)
    if args.action in ("verify", "verify-e2e"):
        return _verify_from_arguments(args, root, directory)
    if args.action == "cleanup-session":
        return cleanup_session_projections(root, directory)
    if args.action == "confirm-manual":
        refs = [item.strip() for item in args.refs.split(",") if item.strip()]
        scenarios = [item.strip() for item in args.scenarios.split(",") if item.strip()]
        return confirm_manual(root, directory, refs, scenarios, args.confirmed_by, args.source,
                              args.reason, args.evidence)
    if args.action == "finish" and (args.batch or args.capability):
        return finish_batch(root, directory, [item for item in args.batch.split(",") if item.strip()],
                            args.capability)
    task = locate_task_file(directory, args.task)
    if task is None:
        raise ValueError("task file missing or ambiguous")
    if args.action == "finish":
        return finish_task(root, directory, str(task), args.task)
    if args.action == "block":
        return block_task(root, directory, str(task), args.task, args.reason)
    return resume_task(root, directory, str(task), args.task)


def main(argv: Optional[Sequence[str]] = None, stdout: IO[str] = sys.stdout) -> int:
    args = _workflow_parser().parse_args(argv)
    try:
        root = str(Path(args.root).resolve())
        directory = str((Path(root) / args.task_dir).resolve())
        if Path(root) not in Path(directory).parents:
            raise ValueError("task directory outside project")
        recover_transition(root)
        result = _dispatch_action(args, root, directory)
        stdout.write(json.dumps(result, ensure_ascii=False))
        return 3 if result.get("decision") in ("block", "provisional") else 0
    except (OSError, ValueError) as exc:
        stdout.write(json.dumps({"decision": "block", "error": str(exc)}, ensure_ascii=False))
        return 2
