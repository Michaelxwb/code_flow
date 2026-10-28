"""Shared requirement verification for CLI and parallel batch orchestration."""
from __future__ import annotations

from pathlib import Path
import re
import sys
from typing import Mapping, Optional, Sequence

from codeflow.acceptance.cf_acceptance_manifest_core import validate_execution_baseline
from codeflow.acceptance.cf_acceptance_risk import accepted_risk
from codeflow.acceptance.cf_acceptance_schema import load_manifest, scenario_check_ids, verified_evidence
from codeflow.acceptance.cf_acceptance_selection import select_owned, select_profile
from codeflow.cli.cf_acceptance_runner import run_manifest
from codeflow.cli.cf_task_index import project_task_nodes
from codeflow.core import cf_git
from codeflow.core.cf_exec_base import worktree_fingerprint
from codeflow.spec.cf_active_task import load_active_task
from codeflow.spec.cf_spec_context_model import ContextError, SpecContext, context_sha256, load_context, save_context
from codeflow.spec.cf_spec_metadata import SpecMetadata, load_spec_metadata
from codeflow.spec.cf_spec_verify import (VerificationEvidence, VerificationResult, VerificationScope, run_all_verifiers,
                                          store_verification_evidence)
from codeflow.spec.cf_stage_gate import validate_stage
from codeflow.spec.cf_workflow_service import FINISHED_STATUSES, complete_requirement_verification
from codeflow.spec.cf_workflow_transaction import recover_transition
from codeflow.task.cf_task_doc import TaskDocumentError, parse_task_document
from codeflow.task.cf_task_runtime import integrate_verification_evidence


def demand_tasks(directory: Path) -> list[tuple[Path, str, str]]:
    tasks = []
    seen = set()
    for task_file in sorted(directory.glob("*.md")):
        if task_file.name.endswith((".design.md", ".prd.md", ".scenarios.md")):
            continue
        try:
            text = task_file.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            raise ValueError(f"task_read_error: {exc}") from exc
        try:
            document = parse_task_document(text, source=str(task_file))
        except TaskDocumentError as exc:
            if exc.code == "task_document_empty":
                continue
            raise ValueError(str(exc)) from exc
        for node in project_task_nodes(document):
            if node.task_id in seen:
                raise ValueError(f"duplicate task id: {node.task_id}")
            seen.add(node.task_id)
            tasks.append((task_file, node.task_id, node.status))
    if not tasks:
        raise ValueError("no TASK sections found")
    return tasks


def _head_token(root: str) -> str:
    try:
        return "head:" + cf_git.run_git(root, ("rev-parse", "HEAD")).strip()
    except cf_git.GitError:
        return "head:none"


def _review_scope(root: str) -> VerificationScope:
    files = set(cf_git.tracked_files(root))
    try:
        files.update(cf_git.changed_files(root))
    except cf_git.GitError:
        pass
    return VerificationScope(root, tuple(sorted(files)), _head_token(root))


def collect_requirement_bindings(directory: Path,
                                 stages: Sequence[str] = ("review",)) -> dict[str, dict[str, object]]:
    """收集需求目录下全部 task context 中指定阶段的绑定。

    返回 spec_id -> {"path": spec 相对路径, "rules": {rule_ref: [(context_path, context), ...]}}。
    读取失败 fail-closed（报告文件与原因），不允许静默跳过。
    """
    allowed = set(stages)
    targets: dict[str, dict[str, object]] = {}
    for ctx_path in sorted(directory.rglob("spec-context.yml")):
        try:
            context = load_context(str(ctx_path))
        except (ContextError, OSError, ValueError) as exc:
            raise ValueError(f"review_context_unreadable: {ctx_path}: {exc}") from exc
        for binding in context.bindings:
            for rule in binding.rules:
                if rule.verifier_stage not in allowed:
                    continue
                entry = targets.setdefault(binding.spec_id, {"path": binding.path, "rules": {}})
                entry["rules"].setdefault(rule.ref, []).append((ctx_path, context))
    return targets


def collect_review_bindings(directory: Path) -> dict[str, dict[str, object]]:
    """review 层绑定（manual 确认与待确认清单专用）。"""
    return collect_requirement_bindings(directory, ("review",))


def _confirmed_manual(spec_id: str, entries: Sequence[tuple[Path, SpecContext]],
                      rule_ref: str) -> Optional[Mapping[str, object]]:
    """从任意绑定该 rule 的 context 读取有效的用户确认记录（按 rule 自身 stage）。"""
    for _, context in entries:
        for binding in context.bindings:
            if binding.spec_id != spec_id:
                continue
            for rule in binding.rules:
                if rule.ref != rule_ref:
                    continue
                status = rule.stage_status.get(rule.verifier_stage or "code")
                decision = status.decision if status is not None else None
                if (status is not None and status.status == "verified"
                        and decision is not None and decision.kind == "manual_verification"):
                    return {
                        "reason": decision.reason,
                        "confirmed_by": decision.confirmed_by,
                        "confirmed_at": decision.confirmed_at,
                        "source": decision.source,
                    }
    return None


def pending_manual_rules(
    root: str, targets: Mapping[str, Mapping[str, object]]
) -> tuple[list[dict[str, object]], dict[str, dict[str, Mapping[str, object]]]]:
    """收集 review 层 manual 规则：待用户确认清单 + 已确认项的 verifier 入参。"""
    pending: list[dict[str, object]] = []
    confirmations: dict[str, dict[str, Mapping[str, object]]] = {}
    for spec_id in sorted(targets):
        info = targets[spec_id]
        metadata = load_spec_metadata(str(Path(root) / ".code-flow/specs" / str(info["path"])))
        manual = {item.rule: item for item in metadata.verifiers if item.type == "manual"}
        for rule_ref, entries in sorted(info["rules"].items()):
            confirmation = _confirmed_manual(spec_id, entries, rule_ref)
            if confirmation is not None:
                confirmations.setdefault(spec_id, {})[rule_ref] = confirmation
            elif rule_ref in manual:
                verifier = manual[rule_ref]
                pending.append({
                    "ref": f"{spec_id}#{rule_ref}",
                    "spec_id": spec_id,
                    "checklist": verifier.config.get("checklist", ""),
                    "owner": verifier.config.get("owner", ""),
                    "bound_contexts": len(entries),
                })
    return pending, confirmations


def _manual_confirmations(root: str, targets: Mapping[str, Mapping[str, object]]) -> dict[str, dict[str, Mapping[str, object]]]:
    """收集各 manual rule 自身 stage 上已记录的用户确认（verifier 入参）。"""
    confirmations: dict[str, dict[str, Mapping[str, object]]] = {}
    for spec_id in sorted(targets):
        info = targets[spec_id]
        metadata = load_spec_metadata(str(Path(root) / ".code-flow/specs" / str(info["path"])))
        manual_refs = {item.rule for item in metadata.verifiers if item.type == "manual"}
        for rule_ref, entries in sorted(info["rules"].items()):
            if rule_ref not in manual_refs:
                continue
            confirmation = _confirmed_manual(spec_id, entries, rule_ref)
            if confirmation is not None:
                confirmations.setdefault(spec_id, {})[rule_ref] = confirmation
    return confirmations


def _store_requirement_evidence(metadata: SpecMetadata, scope: VerificationScope,
                                result: VerificationResult, directory: str) -> None:
    try:
        from codeflow.evidence.cf_evidence_store import requirement_key
        store_verification_evidence(metadata, scope, result, requirement=requirement_key(directory))
    except (OSError, ValueError) as exc:
        sys.stderr.write(f"cf_task_workflow: verifier evidence sidecar failed: {exc}\n")


def _update_requirement_contexts(evidence_by_context: Mapping[Path, list[VerificationEvidence]],
                                 scope: VerificationScope) -> list[str]:
    # Integrate all specs before writing each context to avoid stale overwrites.
    for ctx_path in sorted(evidence_by_context, key=str):
        context = load_context(str(ctx_path))
        updated, _ = integrate_verification_evidence(context, evidence_by_context[ctx_path])
        if updated != context:
            save_context(str(ctx_path), updated)
    failures = []
    for ctx_path in sorted(evidence_by_context):
        gate = validate_stage(load_context(str(ctx_path)), "review", diff_sha256=scope.diff_sha256)
        failures.extend(f"{issue.spec_id}#{issue.rule_ref}" for issue in gate.errors)
    return failures


def _run_requirement_verifiers(
    root: str,
    directory: str,
    targets: dict[str, dict[str, object]],
    confirmations: Optional[Mapping[str, Mapping[str, Mapping[str, object]]]] = None,
) -> dict[str, object]:
    """执行需求级全量 verifier（code+review 按 spec/rule 去重），证据写回全部相关 context。"""
    executed = reused = env_blocked = incomplete = 0
    failures: list[str] = []
    summaries: list[dict[str, object]] = []
    evidence_by_context: dict[Path, list[VerificationEvidence]] = {}
    scope = _review_scope(root)
    for spec_id in sorted(targets):
        info = targets[spec_id]
        metadata = load_spec_metadata(str(Path(root) / ".code-flow/specs" / str(info["path"])))
        result = run_all_verifiers(metadata, scope, (confirmations or {}).get(spec_id), stage=None)
        _store_requirement_evidence(metadata, scope, result, directory)
        by_rule: dict[str, VerificationEvidence] = {}
        for evidence in result.evidence:
            rule_ref = evidence.verifier_ref.split("#", 1)[-1]
            by_rule[rule_ref] = evidence
            summaries.append({
                "check_id": evidence.verifier_ref,
                "status": evidence.status,
                "error_code": evidence.error_code,
            })
            if evidence.status != "verified":
                if evidence.error_code in _ENV_ERROR_CODES:
                    env_blocked += 1
                elif evidence.error_code == "verifier_timeout":
                    incomplete += 1
                else:
                    failures.append(evidence.verifier_ref)
            elif (evidence.details or {}).get("cache_reused"):
                reused += 1
            else:
                executed += 1
        for rule_ref, entries in info["rules"].items():
            evidence = by_rule.get(rule_ref)
            if evidence is None:
                continue
            for ctx_path, _context in entries:
                evidence_by_context.setdefault(ctx_path, []).append(evidence)
    failures.extend(_update_requirement_contexts(evidence_by_context, scope))
    return {"executed": executed, "reused": reused, "failed": sorted(set(failures)),
            "env_blocked": env_blocked, "incomplete": incomplete, "evidence": summaries}


VERIFY_LAYERS = ("validators", "review", "e2e")
VERIFY_PROFILES = ("smoke", "changed", "full")
_ENV_ERROR_CODES = frozenset(("env_blocked", "environment_unavailable", "command_unavailable"))


def parse_verify_layers(value: Optional[str]) -> tuple[str, ...]:
    if value is None or not value.strip():
        return VERIFY_LAYERS
    chosen: set[str] = set()
    for item in value.split(","):
        name = item.strip()
        if not name:
            continue
        if name not in VERIFY_LAYERS:
            raise ValueError(f"unknown verify layer: {name}; allowed: {', '.join(VERIFY_LAYERS)}")
        chosen.add(name)
    if not chosen:
        raise ValueError(f"--layers requires at least one of: {', '.join(VERIFY_LAYERS)}")
    return tuple(name for name in VERIFY_LAYERS if name in chosen)


def parse_verify_profile(value: Optional[str], default: str = "changed") -> str:
    profile = (value or default).strip()
    if profile not in VERIFY_PROFILES:
        raise ValueError(f"unknown verify profile: {profile}; allowed: {', '.join(VERIFY_PROFILES)}")
    return profile


def _layer_result(decision: str, *, reason: str = "", executed: int = 0, reused: int = 0,
                  failed: Optional[Sequence[str]] = None, env_blocked: int = 0, incomplete: int = 0,
                  evidence: Optional[Sequence[Mapping[str, object]]] = None,
                  **extra: object) -> dict[str, object]:
    result: dict[str, object] = {
        "decision": decision,
        "reason": reason,
        "executed": executed,
        "reused": reused,
        "failed": list(failed or ()),
        "env_blocked": env_blocked,
        "incomplete": incomplete,
        "evidence": list(evidence or ()),
    }
    result.update(extra)
    return result


def _nothing_to_verify() -> dict[str, object]:
    return _layer_result("pass", reason="nothing_to_verify")


def _validation_view(details: Mapping[str, object]) -> dict[str, object]:
    return {
        "decision": details.get("decision"),
        "reason": details.get("reason", ""),
        "reused": details.get("reused", 0),
        "failures": details.get("failures", []),
    }


def _validator_execution_count(root: str, selected: Sequence[str], reused: int) -> int:
    from codeflow.core.cf_validators import resolve_validators, trigger_matches

    _config, validators = resolve_validators(root)
    applicable = 0
    for validator in validators:
        if not isinstance(validator, Mapping):
            continue
        trigger = str(validator.get("trigger", ""))
        if any(trigger_matches(trigger, path) for path in selected):
            applicable += 1
    return max(0, applicable - reused)


def _validators_layer(root: str, profile: str,
                      files: Optional[Sequence[str]] = None) -> dict[str, object]:
    try:
        from codeflow.task.cf_validation_service import validate_files

        if files is None:
            files = tuple(sorted(cf_git.tracked_files(root)))
        details = validate_files(root, files, include_heavy=profile == "full")
    except (OSError, ValueError) as exc:
        return _layer_result("block", reason="validation_error", detail=str(exc))
    view = _validation_view(details)
    if details.get("reason") in ("no_changes", "no_validators_configured"):
        return _layer_result("pass", reason="nothing_to_verify", validation=view)
    failures = list(details.get("failures") or ())
    failed = [str(item.get("name", "validator")) for item in failures if not item.get("incomplete")]
    incomplete = sum(1 for item in failures if item.get("incomplete"))
    reused = int(details.get("reused") or 0)
    selected = details.get("files") or ()
    executed = _validator_execution_count(root, selected, reused)
    decision = "pass" if details.get("decision") == "pass" else "block"
    return _layer_result(
        decision,
        reason="" if decision == "pass" else "validation_failed",
        executed=executed,
        reused=reused,
        failed=failed,
        incomplete=incomplete,
        validation=view,
    )


def _verify_validators(root: str, directory: str, profile: str) -> dict[str, object]:
    """Development checks use the active baseline without completing the TASK."""
    files: Optional[Sequence[str]] = None
    try:
        if (Path(root) / ".code-flow/.active-task.json").exists():
            active = load_active_task(root)
            if (Path(root) / active.task_dir).resolve() != Path(directory).resolve():
                raise ValueError("active_task_directory_mismatch")
            context = load_context(str(Path(directory) / "spec-context.yml"))
            if active.context_sha256 != context_sha256(context):
                raise ValueError("active_context_hash_mismatch: run code-flow spec refresh/doctor")
            files = ()  # validate_files resolves all committed/uncommitted task changes.
        layer = _validators_layer(root, profile, files)
    except (OSError, ValueError) as exc:
        layer = _layer_result("block", reason="validation_context_invalid", detail=str(exc))
    return _aggregate_layers({"validators": layer}, profile, ("validators",))


def _review_layer(root: str, directory: str) -> dict[str, object]:
    try:
        review_targets = collect_review_bindings(Path(directory))
        pending_rules, _ = pending_manual_rules(root, review_targets)
    except ValueError as exc:
        return _layer_result("block", reason="manual_review_context_unreadable", detail=str(exc))
    if pending_rules:
        return _layer_result(
            "block",
            reason="manual_confirmation_required",
            manual_rules=pending_rules,
            next=("向用户展示待确认清单并取得明确回复后，运行 confirm-manual 批量写入确认，再重跑 verify；"
                  "Agent 不得代确认。"),
        )
    try:
        all_targets = collect_requirement_bindings(Path(directory), ("code", "review"))
    except ValueError as exc:
        return _layer_result("block", reason="review_context_unreadable", detail=str(exc))
    if not all_targets:
        return _nothing_to_verify()
    confirmations = _manual_confirmations(root, all_targets)
    review = _run_requirement_verifiers(root, directory, all_targets, confirmations)
    blocked = bool(review["failed"] or review["env_blocked"] or review["incomplete"])
    return _layer_result(
        "block" if blocked else "pass",
        reason="review_failed" if blocked else "",
        executed=int(review["executed"]),
        reused=int(review["reused"]),
        failed=review["failed"],
        env_blocked=int(review["env_blocked"]),
        incomplete=int(review["incomplete"]),
        evidence=review["evidence"],
        review={"executed": review["executed"], "reused": review["reused"], "failed": review["failed"]},
    )


def _acceptance_counts(acceptance: Mapping[str, object]) -> dict[str, object]:
    executed = reused = incomplete = env_blocked = 0
    failed: list[str] = []
    evidence: list[dict[str, object]] = []
    for item in acceptance.get("results") or ():
        if not isinstance(item, Mapping):
            continue
        scenario_id = str(item.get("id", ""))
        status = str(item.get("status", ""))
        evidence.append({"check_id": scenario_id, "status": status})
        if status == "incomplete":
            incomplete += 1
        elif status == "env_blocked":
            env_blocked += 1
        elif status in ("failed", "not_configured"):
            failed.append(scenario_id)
        elif status == "passed":
            if item.get("cache_reused"):
                reused += 1
            else:
                executed += 1
    return {"executed": executed, "reused": reused, "failed": sorted(failed),
            "env_blocked": env_blocked, "incomplete": incomplete, "evidence": evidence}


def e2e_preflight(manifest: Path, tasks: Sequence[tuple[Path, str, str]],
                   requirement_gate: bool, profile: str = "changed",
                   root: str = "") -> tuple[Optional[dict[str, object]], Optional[dict[str, object]]]:
    try:
        data = load_manifest(manifest)
        validate_execution_baseline(manifest, data)
    except (OSError, ValueError) as exc:
        return None, _layer_result("block", reason="acceptance_manifest_invalid", detail=str(exc))
    bound_task = (manifest.parent / str(data.get("task_file", ""))).resolve()
    if {task.resolve() for task, _, _ in tasks} != {bound_task}:
        return None, _layer_result("block", reason="acceptance_manifest_task_mismatch")
    owner = ",".join(task for _, task, _ in tasks)
    selected_ids: Optional[set[str]] = None
    if requirement_gate and root and profile != "full":
        selected = select_profile(data, root, profile)["scenarios"]
        selected_ids = {str(item.get("id")) for item in select_owned(selected, owner)}
    data = {**data, "scenarios": select_owned(data["scenarios"], owner)}
    if not requirement_gate:
        if not any(row.get("kind") == "e2e" or row.get("exec") == "deferred" for row in data["scenarios"]):
            return None, _nothing_to_verify()
        return data, None
    functional_required, manual_scenarios = _pending_scenario_rows(data, selected_ids)
    if functional_required:
        return None, _layer_result("block", reason="functional_or_manual_evidence_missing",
                                   scenarios=functional_required)
    if manual_scenarios:
        return None, _layer_result(
            "block", reason="manual_confirmation_required", manual_scenarios=manual_scenarios,
            next=("向用户展示待确认清单并取得明确回复后，运行 confirm-manual 批量写入确认，再重跑 verify；"
                  "Agent 不得代确认。"))
    return data, None


def _pending_scenario_rows(data: Mapping[str, object], selected_ids: Optional[set[str]]
                           ) -> tuple[list[object], list[dict[str, object]]]:
    functional_required: list[object] = []
    manual_scenarios: list[dict[str, object]] = []
    checks = {
        str(item.get("id")): item for item in data.get("checks", [])
        if isinstance(item, Mapping) and item.get("id")
    }
    for row in data["scenarios"]:
        if row.get("exec") == "aspirational":
            continue
        if selected_ids is not None and str(row.get("id")) not in selected_ids:
            continue
        if row.get("status") == "stale":
            # Stale evidence is known-outdated, not missing. The E2E layer
            # re-runs it; preflight must not turn it into a hard archive block.
            continue
        if verified_evidence(row):
            continue
        if row.get("status") == "accepted_risk":
            check_ids = scenario_check_ids(row)
            if check_ids and any(accepted_risk(checks.get(check_id), row) is not None for check_id in check_ids):
                continue
        if row.get("kind") == "manual" or row.get("exec") == "manual":
            manual_scenarios.append({
                "id": row.get("id"),
                "owner": row.get("owner", ""),
                "boundary": row.get("boundary", ""),
            })
        elif row.get("kind", "functional") != "e2e" and row.get("exec") != "deferred":
            functional_required.append(row["id"])
    return functional_required, manual_scenarios


def stale_functional_rows(data: Mapping[str, object], root: str) -> list[str]:
    """Functional rows claiming verified but recorded against different content."""
    from codeflow.acceptance.cf_acceptance_evidence import stale_scenario_checks
    fingerprint = worktree_fingerprint(root)
    checks = {
        str(item.get("id")): item for item in data.get("checks", [])
        if isinstance(item, Mapping) and item.get("id")
    }
    from codeflow.acceptance.cf_check_inputs import check_input_hashes
    per_check = check_input_hashes(root, checks, fingerprint)
    stale: list[str] = []
    for row in data.get("scenarios", []) or []:
        if not isinstance(row, Mapping):
            continue
        if str(row.get("kind", "functional")) in ("manual", "e2e"):
            continue
        if row.get("status") not in ("verified", "stale"):
            continue
        if stale_scenario_checks(row, per_check, fingerprint):
            stale.append(str(row.get("id")))
    return stale


def _unverified_functional_rows(data: Mapping[str, object]) -> list[str]:
    checks = {
        str(item.get("id")): item for item in data.get("checks", [])
        if isinstance(item, Mapping) and item.get("id")
    }
    rows: list[str] = []
    for row in data.get("scenarios", []) or []:
        if not isinstance(row, Mapping):
            continue
        if str(row.get("kind", "functional")) in ("manual", "e2e") or row.get("exec") in ("manual", "aspirational"):
            continue
        if row.get("status") == "accepted_risk":
            check_ids = scenario_check_ids(row)
            if any(accepted_risk(checks.get(check_id), row) is not None for check_id in check_ids):
                continue
        if not verified_evidence(row):
            rows.append(str(row.get("id")))
    return rows


def _acceptance_required(tasks: Sequence[tuple[Path, str, str]]) -> bool:
    for task_file, task_id, _ in tasks:
        try:
            text = Path(task_file).read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            continue
        section = re.search(rf"(?ms)^##\s+{re.escape(task_id)}:.*?(?=^##\s+TASK-|\Z)", text)
        if section is None:
            continue
        body = section.group(0)
        refs = re.search(r"(?m)^- \*\*Acceptance-Refs\*\*:[ \t]*([^\n]*)", body)
        if refs and refs.group(1).strip().upper() not in ("", "N/A"):
            return True
    return False


def _e2e_layer(root: str, directory: str, tasks: Sequence[tuple[Path, str, str]],
               requirement_gate: bool, profile: str = "changed", resume: bool = True,
               deadline: Optional[float] = None, max_failures: int = 0,
               fail_fast: bool = False, jobs: int = 0) -> dict[str, object]:
    manifest = Path(directory) / ".acceptance-manifest.json"
    if not manifest.exists():
        if _acceptance_required(tasks):
            return _layer_result("block", reason="acceptance_manifest_missing")
        return _nothing_to_verify()
    data, failure = e2e_preflight(manifest, tasks, requirement_gate, profile, root)
    if failure is not None:
        return failure
    stale = stale_functional_rows(data, root) if requirement_gate else []
    unverified = _unverified_functional_rows(data) if requirement_gate else []
    if profile == "smoke":
        # Smoke only needs the E2E subset; functional freshness is handled by
        # the explicit changed/full gate, not by the batch smoke.
        stale = []
        unverified = []
    try:
        acceptance = run_manifest(
            str(manifest), root, write_evidence=True,
            owner=",".join(str(item[1]) for item in tasks),
            include_e2e=bool(stale or unverified) or profile in ("full", "smoke"),
            only_e2e=not (stale or unverified) and profile not in ("full", "smoke"),
            profile=profile, resume=resume, deadline=deadline,
            max_failures=max_failures, fail_fast=fail_fast, jobs=jobs,
            force_ids=tuple(stale or unverified),
        )
    except (OSError, ValueError) as exc:
        return _layer_result("block", reason="acceptance_run_error", detail=str(exc))
    counts = _acceptance_counts(acceptance)
    decision = "pass" if acceptance.get("decision") == "pass" else "block"
    extra: dict[str, object] = {"results": acceptance.get("results", [])}
    for key in ("checks", "error", "env_blocked_details"):
        if key in acceptance:
            extra[key] = acceptance[key]
    return _layer_result(
        decision,
        reason="" if decision == "pass" else "e2e_failed",
        executed=counts["executed"],
        reused=counts["reused"],
        failed=counts["failed"],
        env_blocked=counts["env_blocked"],
        incomplete=counts["incomplete"],
        evidence=counts["evidence"],
        acceptance=acceptance,
        **extra,
    )


def _aggregate_layers(layer_results: Mapping[str, Mapping[str, object]], profile: str,
                      selected: Sequence[str]) -> dict[str, object]:
    blocking = [(name, layer) for name, layer in layer_results.items() if layer.get("decision") != "pass"]
    every_layer_empty = bool(layer_results) and all(
        layer.get("reason") == "nothing_to_verify" for layer in layer_results.values()
    )
    if blocking:
        first = blocking[0]
        reason = str(first[1].get("reason") or f"{first[0]}_failed")
    elif every_layer_empty:
        reason = "nothing_to_verify"
    else:
        reason = ""
    evidence = [
        {"layer": name, **item}
        for name, layer in layer_results.items()
        for item in layer.get("evidence", [])
        if isinstance(item, Mapping)
    ]
    result: dict[str, object] = {
        "decision": "block" if blocking else "pass",
        "reason": reason,
        "profile": profile,
        "selected_layers": list(selected),
        "layers": dict(layer_results),
        "executed": sum(int(layer.get("executed", 0)) for layer in layer_results.values()),
        "reused": sum(int(layer.get("reused", 0)) for layer in layer_results.values()),
        "failed": sorted({str(item) for layer in layer_results.values()
                          for item in layer.get("failed", [])}),
        "env_blocked": sum(int(layer.get("env_blocked", 0)) for layer in layer_results.values()),
        "incomplete": sum(int(layer.get("incomplete", 0)) for layer in layer_results.values()),
        "evidence": evidence,
        "env_blocked_details": [
            {"layer": name, **item} for name, layer in layer_results.items()
            for item in layer.get("env_blocked_details", []) if isinstance(item, Mapping)
        ],
    }
    for field in ("manual_rules", "manual_scenarios", "scenarios", "next"):
        merged = [layer[field] for layer in layer_results.values() if field in layer]
        if merged:
            result[field] = merged[0] if len(merged) == 1 else merged
    return result


def verify_layers(root: str, directory: str, layers: Optional[str] = None,
                  profile: Optional[str] = None,
                  only_tasks: Optional[Sequence[str]] = None,
                  resume: bool = True, deadline: Optional[float] = None,
                  max_failures: int = 0, fail_fast: bool = False,
                  jobs: int = 0) -> dict[str, object]:
    """Run chosen layers; only_tasks limits the batch smoke gate to merged TASKs."""
    recover_transition(root)
    selected = parse_verify_layers(layers)
    resolved_profile = parse_verify_profile(profile)
    if selected == ("validators",):
        return _verify_validators(root, directory, resolved_profile)
    tasks = demand_tasks(Path(directory))
    if only_tasks is not None:
        wanted = {str(task_id) for task_id in only_tasks}
        known = {task_id for _, task_id, _ in tasks}
        if wanted - known:
            return {"decision": "block", "reason": "unknown_tasks", "tasks": sorted(wanted - known)}
        tasks = [item for item in tasks if item[1] in wanted]
    unfinished = [task_id for _, task_id, status in tasks if status not in FINISHED_STATUSES]
    if unfinished:
        return {"decision": "block", "reason": "unfinished_tasks", "tasks": unfinished}
    if (Path(root) / ".code-flow/.active-task.json").exists():
        return {"decision": "block", "reason": "finish_active_task_first"}
    requirement_gate = set(selected) == set(VERIFY_LAYERS)
    layer_results: dict[str, dict[str, object]] = {}
    for name in selected:
        if name == "validators":
            layer_results[name] = _validators_layer(root, resolved_profile)
        elif name == "review":
            layer_results[name] = _review_layer(root, directory)
        else:
            layer_results[name] = _e2e_layer(
                root, directory, tasks, requirement_gate,
                profile=resolved_profile, resume=resume, deadline=deadline,
                max_failures=max_failures, fail_fast=fail_fast, jobs=jobs,
            )
    result = _aggregate_layers(layer_results, resolved_profile, selected)
    if (requirement_gate and resolved_profile == "full" and result["decision"] == "pass"
            and (result.get("reason") != "nothing_to_verify" or not _acceptance_required(tasks))):
        return complete_requirement_verification(root, directory, tasks, result)
    return result
