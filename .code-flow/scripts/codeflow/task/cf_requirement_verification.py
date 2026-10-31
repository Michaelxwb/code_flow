"""Shared requirement verification for CLI and parallel batch orchestration."""
from __future__ import annotations

from pathlib import Path
import re
import sys
import time
from typing import Mapping, Optional, Sequence

from codeflow.acceptance.cf_acceptance_manifest_core import validate_execution_baseline
from codeflow.acceptance.cf_acceptance_risk import accepted_risk
from codeflow.acceptance.cf_acceptance_schema import load_manifest, scenario_check_ids, verified_evidence
from codeflow.acceptance.cf_acceptance_selection import select_owned, select_profile
from codeflow.cli.cf_acceptance_runner import run_manifest
from codeflow.cli.cf_task_index import project_task_nodes
from codeflow.core import cf_git
from codeflow.core.cf_exec_base import record_report, report_session, worktree_fingerprint
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


def _summarize_verifier(evidence: VerificationEvidence, summary: list[dict[str, object]]) -> str:
    summary.append({"check_id": evidence.verifier_ref, "status": evidence.status, "error_code": evidence.error_code})
    if evidence.status == "verified":
        return "reused" if (evidence.details or {}).get("cache_reused") else "executed"
    if evidence.error_code in _ENV_ERROR_CODES:
        return "env_blocked"
    return "incomplete" if evidence.error_code == "verifier_timeout" else "failed"


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
    started = time.monotonic()
    scope = _review_scope(root)
    preflight_ms = (time.monotonic() - started) * 1000
    planning_ms = evidence_ms = 0.0
    for spec_id in sorted(targets):
        info = targets[spec_id]
        started = time.monotonic()
        metadata = load_spec_metadata(str(Path(root) / ".code-flow/specs" / str(info["path"])))
        planning_ms += (time.monotonic() - started) * 1000
        result = run_all_verifiers(metadata, scope, (confirmations or {}).get(spec_id), stage=None)
        started = time.monotonic()
        _store_requirement_evidence(metadata, scope, result, directory)
        evidence_ms += (time.monotonic() - started) * 1000
        by_rule: dict[str, VerificationEvidence] = {}
        for evidence in result.evidence:
            rule_ref = evidence.verifier_ref.split("#", 1)[-1]
            by_rule[rule_ref] = evidence
            category = _summarize_verifier(evidence, summaries)
            executed += category == "executed"
            reused += category == "reused"
            env_blocked += category == "env_blocked"
            incomplete += category == "incomplete"
            if category == "failed":
                failures.append(evidence.verifier_ref)
        for rule_ref, entries in info["rules"].items():
            evidence = by_rule.get(rule_ref)
            if evidence is None:
                continue
            for ctx_path, _context in entries:
                evidence_by_context.setdefault(ctx_path, []).append(evidence)
    started = time.monotonic()
    failures.extend(_update_requirement_contexts(evidence_by_context, scope))
    evidence_ms += (time.monotonic() - started) * 1000
    record_report({"kind": "spec_phases", "timings": {"planning_ms": planning_ms,
                  "preflight_ms": preflight_ms, "evidence_ms": evidence_ms}})
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
        "files": list(details.get("files") or ()),
        "timings": details.get("timings"),
        "observations": details.get("observations", []),
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
            from codeflow.task.cf_validation_service import validation_scope
            files = (tuple(sorted(cf_git.tracked_files(root))) if profile == "full"
                     else validation_scope(root))
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


def _validation_report(result: dict[str, object], layer: Mapping[str, object],
                       layers: Sequence[str]) -> dict[str, object]:
    view = layer.get("validation") or {}
    observations = view.get("observations") or []
    result["scope"] = {"layers": list(layers), "files": view.get("files", [])}
    result["selection_reason"] = ("validator_trigger_matches_selected_files" if observations
                                  else "no_validator_selected")
    result["reuse_reason"] = "matching_validation_cache" if layer.get("reused") else "no_reused_results"
    result["execution_identities"] = [item["identity"] for item in observations]
    result["input_change_category"] = sorted({item["input_change_category"] for item in observations})
    result["summary"] = (f"validators: executed {int(layer.get('executed') or 0)}, "
                         f"reused {int(layer.get('reused') or 0)}")
    if view.get("timings") is not None:
        result["timings"] = dict(view["timings"])
        result["timings_scope"] = ["validators"]
    return result


def _combine_acceptance_timing(result: dict[str, object], layer: Mapping[str, object],
                               started: float) -> None:
    acceptance = layer.get("acceptance")
    if not isinstance(acceptance, Mapping) or not isinstance(acceptance.get("timings"), Mapping):
        return
    incoming = acceptance["timings"]
    current = result.get("timings")
    if not isinstance(current, dict):
        current = {key: 0.0 for key in ("planning_ms", "preflight_ms", "execution_ms", "evidence_ms")}
        result["timings"] = current
        result["timings_scope"] = []
    for key in ("planning_ms", "preflight_ms", "execution_ms", "evidence_ms"):
        current[key] = float(current.get(key, 0)) + float(incoming.get(key, 0))
    current["elapsed_ms"] = (time.monotonic() - started) * 1000
    result["timings_scope"].append("e2e")
    reasons = {"e2e": acceptance.get("selection_reason", "unknown")}
    if "selection_reason" in result:
        reasons["validators"] = result["selection_reason"]
    result["selection_reasons"] = reasons
    result["selection_reason"] = "multiple_layer_policies" if len(reasons) > 1 else reasons["e2e"]
    result["selected_check_ids"] = acceptance.get("selected_check_ids", [])
    result.setdefault("execution_identities", []).extend(acceptance.get("execution_identities", []))
    categories = acceptance.get("input_change_category") or {}
    result["input_change_categories"] = {"validators": result.get("input_change_category", []), "e2e": categories}
    result["input_change_category"] = sorted(set(result.get("input_change_category", [])) | set(categories.values()))
    summaries = [str(value) for value in (result.get("summary"), acceptance.get("summary")) if value]
    result["summary"] = "; ".join(summaries)
    result["reuse_reason"] = "evidence_reused" if result.get("reused") else "no_reused_results"
    if "scope" not in result:
        result["scope"] = {"layers": result.get("selected_layers", []), "acceptance": acceptance.get("scope", {})}


def _verify_validators(root: str, directory: str, profile: str) -> dict[str, object]:
    """Development checks use the active baseline without completing the TASK."""
    started = time.monotonic()
    files: Optional[Sequence[str]] = None
    try:
        if (Path(root) / ".code-flow/.active-task.json").exists():
            active = load_active_task(root)
            if (Path(root) / active.task_dir).resolve() != Path(directory).resolve():
                raise ValueError("active_task_directory_mismatch")
            context = load_context(str(Path(directory) / "spec-context.yml"))
            if active.context_sha256 != context_sha256(context):
                raise ValueError("active_context_hash_mismatch: run code-flow spec refresh/doctor")
            from codeflow.task.cf_validation_service import validation_scope
            files = validation_scope(root)
        layer = _validators_layer(root, profile, files)
    except (OSError, ValueError) as exc:
        layer = _layer_result("block", reason="validation_context_invalid", detail=str(exc))
    result = _aggregate_layers({"validators": layer}, profile, ("validators",))
    _validation_report(result, layer, ("validators",))
    if "timings" in result:
        result["timings"]["elapsed_ms"] = (time.monotonic() - started) * 1000
    return result


def _review_layer(root: str, directory: str) -> dict[str, object]:
    started = time.monotonic()
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
    record_report({"kind": "spec_phases", "timings": {"planning_ms": (time.monotonic() - started) * 1000}})
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
        elif (row.get("status") == "verified" and row.get("kind", "functional") != "e2e"
              and row.get("exec") != "deferred"):
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
               fail_fast: bool = False, jobs: int = 0,
               partial_ids: Optional[Sequence[str]] = None) -> dict[str, object]:
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
            only_e2e=(partial_ids is not None and profile == "smoke") or (
                not (stale or unverified) and profile not in ("full", "smoke")),
            profile=profile, resume=resume, deadline=deadline,
            max_failures=max_failures, fail_fast=fail_fast, jobs=jobs,
            force_ids=tuple(partial_ids) if partial_ids is not None else tuple(stale or unverified),
            only_scenarios=partial_ids,
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


def _batch_scope(root: str, directory: str, tasks: Sequence[tuple[Path, str, str]], wanted: set[str]
                 ) -> tuple[list[tuple[Path, str, str]], list[str], list[str]]:
    manifest = Path(directory) / ".acceptance-manifest.json"
    if not manifest.is_file():
        return [task for task in tasks if task[1] in wanted], [], []
    data = load_manifest(manifest)
    rows = {str(row["id"]): row for row in data["scenarios"]}
    from codeflow.acceptance.cf_acceptance_selection import changed_paths
    from codeflow.acceptance.cf_check_inputs import match_path
    changes = changed_paths(root)
    checks = {str(item["id"]): item for item in data.get("checks", [])}
    has_explicit_smoke = any(row.get("kind") == "e2e" and row.get("smoke") for row in rows.values())
    selected = {sid for sid, row in rows.items() if row.get("owner") in wanted
                and (row.get("kind") != "e2e" or row.get("smoke") or not has_explicit_smoke)}
    for sid, row in rows.items():
        patterns = list(row.get("trigger_paths") or [])
        for check_id in scenario_check_ids(row):
            check = checks.get(check_id, {})
            patterns.extend(check.get("inputs") or [])
            patterns.extend(check.get("paths") or [])
        affected = any(match_path(path, str(pattern)) for path in changes for pattern in patterns)
        if (row.get("kind") == "e2e" and row.get("smoke")
                and (set(row.get("depends_on", [])) & selected or affected)):
            selected.add(sid)
    pending = list(selected)
    while pending:
        for dependency in rows[pending.pop()].get("depends_on", []):
            if dependency in rows and dependency not in selected:
                selected.add(dependency)
                pending.append(dependency)
    owners = wanted | {str(rows[sid].get("owner")) for sid in selected if rows[sid].get("owner")}
    scoped = [task for task in tasks if task[1] in owners]
    ready = {task_id for _, task_id, status in scoped if status in FINISHED_STATUSES}
    return scoped, sorted(selected), sorted(owners - ready)


def _verify_layers(root: str, directory: str, layers: Optional[str] = None,
                  profile: Optional[str] = None,
                  only_tasks: Optional[Sequence[str]] = None,
                  resume: bool = True, deadline: Optional[float] = None,
                  max_failures: int = 0, fail_fast: bool = False,
                  jobs: int = 0) -> dict[str, object]:
    """Run chosen layers; only_tasks limits the batch smoke gate to merged TASKs."""
    started = time.monotonic()
    recover_transition(root)
    selected = parse_verify_layers(layers)
    resolved_profile = parse_verify_profile(profile)
    if selected == ("validators",) and only_tasks is None:
        return _verify_validators(root, directory, resolved_profile)
    tasks = demand_tasks(Path(directory))
    if only_tasks is not None:
        wanted = {str(task_id) for task_id in only_tasks}
        known = {task_id for _, task_id, _ in tasks}
        if wanted - known:
            return {"decision": "block", "reason": "unknown_tasks", "tasks": sorted(wanted - known)}
        tasks, partial_ids, not_ready = _batch_scope(root, directory, tasks, wanted)
        if not_ready:
            return {"decision": "block", "reason": "not_ready", "tasks": not_ready,
                    "scope": {"type": "partial", "tasks": sorted(wanted)}, "requirement_verified": False}
    else:
        partial_ids = None
    unfinished = [task_id for _, task_id, status in tasks if status not in FINISHED_STATUSES]
    if unfinished:
        return {"decision": "block", "reason": "unfinished_tasks", "tasks": unfinished}
    if (Path(root) / ".code-flow/.active-task.json").exists():
        return {"decision": "block", "reason": "finish_active_task_first"}
    requirement_gate = only_tasks is None and set(selected) == set(VERIFY_LAYERS)
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
                max_failures=max_failures, fail_fast=fail_fast, jobs=jobs, partial_ids=partial_ids,
            )
    result = _aggregate_layers(layer_results, resolved_profile, selected)
    if "validators" in layer_results:
        _validation_report(result, layer_results["validators"], selected)
    if "e2e" in layer_results:
        _combine_acceptance_timing(result, layer_results["e2e"], started)
    if only_tasks is not None:
        result["scope"] = {**result.get("scope", {}), "type": "partial", "tasks": sorted(wanted),
                           "scenarios": partial_ids}
        result["requirement_verified"] = False
    if (requirement_gate and resolved_profile == "full" and result["decision"] == "pass"
            and (result.get("reason") != "nothing_to_verify" or not _acceptance_required(tasks))):
        return complete_requirement_verification(root, directory, tasks, result)
    return result


def _append_spec_reporting(result: dict[str, object], reports: Sequence[Mapping[str, object]],
                           started: float) -> None:
    checks = sorted((dict(item) for item in reports if item.get("kind") == "spec_check"),
                    key=lambda item: str(item.get("check_id", "")))
    if not checks:
        return
    result["spec_checks"] = checks
    spec_executed = sum(1 for item in checks if not item.get("reused"))
    spec_reused = len(checks) - spec_executed
    review = result.get("layers", {}).get("review")
    if isinstance(review, dict):
        result["executed"] += spec_executed - int(review.get("executed", 0))
        result["reused"] += spec_reused - int(review.get("reused", 0))
        review["executed"], review["reused"] = spec_executed, spec_reused
        if isinstance(review.get("review"), dict):
            review["review"].update(executed=spec_executed, reused=spec_reused)
    prefix = str(result.get("summary") or "")
    result["summary"] = (prefix + "; " if prefix else "") + f"spec: executed {spec_executed}, reused {spec_reused}"
    result.setdefault("execution_identities", []).extend(item["identity"] for item in checks if item.get("identity"))
    timings = result.setdefault("timings", {key: 0.0 for key in
                                ("planning_ms", "preflight_ms", "execution_ms", "evidence_ms")})
    timings["execution_ms"] += sum(float(item.get("execution_ms", 0)) for item in checks)
    for report in reports:
        if report.get("kind") == "spec_phases":
            phases = report.get("timings") or {}
            for key in ("planning_ms", "preflight_ms", "evidence_ms"):
                timings[key] += float(phases.get(key, 0))
    timings["elapsed_ms"] = (time.monotonic() - started) * 1000
    result.setdefault("timings_scope", []).append("spec")
    result.setdefault("scope", {"layers": result.get("selected_layers", [])})
    result.setdefault("input_change_category", ["unchanged" if spec_reused else "unproven"])
    if "selection_reason" in result:
        reasons = result.setdefault("selection_reasons", {})
        if not reasons:
            reasons["validators" if "validators" in result.get("timings_scope", []) else "other"] = result["selection_reason"]
        reasons["spec"] = "required_spec_bindings"
        result["selection_reason"] = "multiple_layer_policies"
    else:
        result["selection_reason"] = "required_spec_bindings"
    if any(item.get("reused") for item in checks):
        result["reuse_reason"] = "evidence_reused"
    else:
        result.setdefault("reuse_reason", "no_reused_results")


def verify_layers(root: str, directory: str, layers: Optional[str] = None,
                  profile: Optional[str] = None, only_tasks: Optional[Sequence[str]] = None,
                  resume: bool = True, deadline: Optional[float] = None, max_failures: int = 0,
                  fail_fast: bool = False, jobs: int = 0) -> dict[str, object]:
    started = time.monotonic()
    with report_session() as reports:
        result = _verify_layers(root, directory, layers, profile, only_tasks, resume,
                                deadline, max_failures, fail_fast, jobs)
    _append_spec_reporting(result, reports, started)
    return result
