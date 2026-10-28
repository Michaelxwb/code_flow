"""Stage Gate decisions and plan coverage for Spec Context."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import re
from typing import Mapping, Optional

from codeflow.spec.cf_spec_context_model import Decision, RuleBinding, RuleStageStatus, SpecBinding, SpecContext
from codeflow.task.cf_task_doc import (
    TaskDocumentError, TaskSection, parse_task_document, task_rule_owner_refs, task_spec_refs,
)


@dataclass(frozen=True)
class GateIssue:
    code: str
    spec_id: str
    rule_ref: str
    stage: str
    message: str


@dataclass(frozen=True)
class GateResult:
    decision: str
    errors: tuple[GateIssue, ...]
    warnings: tuple[GateIssue, ...]
    affected_refs: tuple[str, ...]


def _parse_time(value: str) -> Optional[datetime]:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def _decision_valid(decision: Optional[Decision]) -> bool:
    if decision is None:
        return False
    return all((decision.reason, decision.confirmed_by, decision.confirmed_at, decision.source))


def _waiver_issue(decision: Optional[Decision], now: datetime) -> Optional[str]:
    if not _decision_valid(decision) or decision is None or not decision.expires_at:
        return "waiver_invalid"
    expires = _parse_time(decision.expires_at)
    if expires is None:
        return "waiver_invalid"
    return "waiver_expired" if expires <= now else None


def _evidence_issue(rule: RuleBinding, status: RuleStageStatus, diff_sha256: Optional[str]) -> Optional[str]:
    if not status.evidence:
        return "evidence_missing"
    for evidence in status.evidence:
        if evidence.get("status") != "verified":
            continue
        if evidence.get("rule_text_sha256") != rule.text_sha256:
            continue
        evidence_diff = evidence.get("diff_sha256")
        if evidence_diff is not None and diff_sha256 is not None and evidence_diff != diff_sha256:
            continue
        result_hash = evidence.get("result_sha256")
        if isinstance(result_hash, str) and result_hash:
            return None
    return "stale_evidence"


def _cheap_skip(status: RuleStageStatus) -> bool:
    """Latest evidence is a cheap-gate skip (command/test verifier deferred)."""
    if not status.evidence:
        return False
    latest = status.evidence[-1]
    return isinstance(latest, Mapping) and latest.get("error_code") == "skipped_in_cheap_gate"


def evidence_deferral_kind(evidence: Optional[Mapping[str, object]]) -> str:
    """Classify a deferral without trusting the legacy catch-all error code.

    Only ``review_stage`` (and heavy validators, represented outside the Spec
    Gate) may be skipped by ``allow_deferred_skips``. Budget/env exhaustion is
    never a pass: those checks were not executed for this task.
    """
    if not isinstance(evidence, Mapping):
        return ""
    details = evidence.get("details")
    details = details if isinstance(details, Mapping) else {}
    code = evidence.get("error_code")
    if code == "verifier_budget_exhausted":
        return "budget"
    if code == "env_blocked":
        return "env"
    if code == "deferred_to_review":
        declared = details.get("deferral_kind")
        if declared in ("review_stage", "heavy", "budget", "env"):
            return str(declared)
        reason = details.get("reason")
        if reason in ("out_of_task_scope", "review_stage"):
            return "review_stage"
        if reason in ("budget", "over_finish_budget"):
            return "budget"
        if reason in ("env", "env_blocked"):
            return "env"
        # Unknown legacy deferrals are not provably review-stage: fail closed.
        return "unknown"
    declared = details.get("deferral_kind")
    if declared in ("review_stage", "heavy", "budget", "env"):
        return str(declared)
    return ""


def _deferred_skip(status: RuleStageStatus, allowed: frozenset[str] = frozenset(("review_stage", "heavy"))) -> bool:
    """Latest evidence is a legitimate deferral (requirement-level review/heavy)."""
    if not status.evidence:
        return False
    latest = status.evidence[-1]
    return evidence_deferral_kind(latest if isinstance(latest, Mapping) else None) in allowed


def _status_issue(
    rule: RuleBinding,
    status: RuleStageStatus,
    now: datetime,
    diff_sha256: Optional[str],
    allow_cheap_skips: bool = False,
    allow_deferred_skips: bool = False,
) -> Optional[str]:
    if status.status == "applied":
        return None
    if status.status == "verified":
        return _evidence_issue(rule, status, diff_sha256)
    if allow_cheap_skips and status.status == "unverified" and _cheap_skip(status):
        # 轻量门禁（stop 阶段）：命令类 verifier 未执行属预期，留给 finish 全量门禁。
        return None
    if allow_deferred_skips and status.status == "unverified" and _deferred_skip(status):
        # finish 门禁：范围外/超预算 verifier 已标记延后，需求级 verify-e2e 全量补跑。
        return None
    if status.status == "not_applicable":
        return None if _decision_valid(status.decision) else "decision_invalid"
    if status.status == "waived":
        return _waiver_issue(status.decision, now)
    return status.status


def _binding_issues(
    binding: SpecBinding,
    stage: str,
    now: datetime,
    diff_sha256: Optional[str],
    allow_cheap_skips: bool = False,
    allow_deferred_skips: bool = False,
) -> tuple[list[GateIssue], list[GateIssue]]:
    errors: list[GateIssue] = []
    warnings: list[GateIssue] = []
    for rule in binding.rules:
        status = rule.stage_status.get(stage)
        if status is None:
            continue
        if stage in ("code", "review") and getattr(rule, "verifier_stage", "code") != stage:
            continue
        if rule.enforcement == "advisory" and status.status == "pending":
            continue
        code = "missing_spec" if binding.status == "missing" else _status_issue(
            rule, status, now, diff_sha256, allow_cheap_skips, allow_deferred_skips
        )
        if stage in ("code", "review") and status.status == "applied":
            code = "rule_execution_evidence_missing"
        if code is None:
            continue
        issue = GateIssue(code, binding.spec_id, rule.ref, stage, f"{binding.spec_id}#{rule.ref}: {code}")
        target = errors if rule.enforcement == "required" else warnings
        target.append(issue)
    return errors, warnings


def validate_stage(
    context: SpecContext,
    stage: str,
    artifact: str = "",
    task_id: str = "",
    now: Optional[datetime] = None,
    diff_sha256: Optional[str] = None,
    allow_cheap_skips: bool = False,
    allow_deferred_skips: bool = False,
    root: str = "",
    task_dir: str = "",
) -> GateResult:
    del artifact, task_id
    current = now or datetime.now(timezone.utc)
    errors: list[GateIssue] = []
    warnings: list[GateIssue] = []
    for binding in context.bindings:
        binding_errors, binding_warnings = _binding_issues(
            binding, stage, current, diff_sha256, allow_cheap_skips, allow_deferred_skips
        )
        errors.extend(binding_errors)
        warnings.extend(binding_warnings)
    if root:
        from codeflow.spec.cf_rule_readiness import applied_findings
        errors.extend(GateIssue(str(item["code"]), "", "", stage, str(item["message"]))
                      for item in applied_findings(context, root, stage, task_dir=task_dir))
    refs = tuple(sorted({f"{item.spec_id}#{item.rule_ref}" for item in (*errors, *warnings)}))
    return GateResult("block" if errors else "pass", tuple(errors), tuple(warnings), refs)


def _task_sections(text: str) -> Mapping[str, TaskSection]:
    return {task.id: task for task in parse_task_document(text).tasks}


def _plan_issue(code: str, binding: SpecBinding, rule: RuleBinding, message: str) -> GateIssue:
    return GateIssue(code, binding.spec_id, rule.ref, "plan", message)


def _task_plan_issue(code: str, task: TaskSection, ref: str, message: str) -> GateIssue:
    spec_id, _, rule_ref = ref.partition("#")
    return GateIssue(code, spec_id, rule_ref, "plan", f"{task.id}: {message}")


def _plan_task_refs(task: TaskSection, known: set[str]) -> tuple[tuple[str, ...], list[GateIssue]]:
    try:
        refs = task_spec_refs(task)
    except ValueError as exc:
        return (), [_task_plan_issue("plan_spec_refs_invalid", task, "", str(exc))]
    issues = [_task_plan_issue("plan_spec_ref_unknown", task, ref, f"未绑定的 Spec-Ref: {ref}")
              for ref in refs if ref not in known]
    return refs, issues


def _plan_task_owners(task: TaskSection, refs: tuple[str, ...], known: set[str]) -> tuple[tuple[str, ...], list[GateIssue]]:
    try:
        declared = task_rule_owner_refs(task) or ()
    except ValueError as exc:
        return (), [_task_plan_issue("plan_owner_refs_invalid", task, "", str(exc))]
    owners: list[str] = []
    issues: list[GateIssue] = []
    for ref in declared:
        if ref not in known:
            issues.append(_task_plan_issue("plan_owner_ref_unknown", task, ref, f"未绑定的 owner Rule: {ref}"))
        elif ref not in refs:
            issues.append(_task_plan_issue("plan_owner_not_referenced", task, ref, f"owner 未引用 Rule: {ref}"))
        else:
            owners.append(ref)
    return tuple(owners), issues


def _plan_owners(sections: Mapping[str, TaskSection], context: SpecContext) -> tuple[dict[str, tuple[str, ...]], list[GateIssue]]:
    known = {f"{binding.spec_id}#{rule.ref}" for binding in context.bindings for rule in binding.rules}
    owners: dict[str, list[str]] = {}
    issues: list[GateIssue] = []
    for task in sections.values():
        refs, ref_issues = _plan_task_refs(task, known)
        declared, owner_issues = _plan_task_owners(task, refs, known)
        issues.extend((*ref_issues, *owner_issues))
        for ref in declared:
            owners.setdefault(ref, []).append(task.id)
    return {ref: tuple(tasks) for ref, tasks in owners.items()}, issues


def _rule_plan_issues(
    binding: SpecBinding, rule: RuleBinding, sections: Mapping[str, TaskSection],
    declared_owners: Optional[Mapping[str, tuple[str, ...]]] = None,
) -> tuple[GateIssue, ...]:
    full_ref = f"{binding.spec_id}#{rule.ref}"
    owners = (declared_owners.get(full_ref, ()) if declared_owners is not None
              else tuple(task for task, section in sections.items() if full_ref in section.body))
    if not owners:
        return (_plan_issue("plan_owner_missing", binding, rule, f"{full_ref} 没有责任 TASK"),)
    if len(owners) > 1:
        return (_plan_issue("plan_owner_duplicate", binding, rule, f"{full_ref} 有多个责任 TASK"),)
    section = sections[owners[0]].body
    issues: list[GateIssue] = []
    if rule.verifier_ref == "advisory:none":
        issues.append(_plan_issue("plan_verifier_missing", binding, rule, f"{full_ref} 缺 verifier"))
    checklist = section.partition("### Checklist")[2].partition("### Acceptance Contract")[0]
    if rule.ref not in checklist or "verifier" not in checklist.lower():
        issues.append(_plan_issue("plan_checklist_missing", binding, rule, f"{full_ref} 缺 verifier Checklist"))
    contract = section.partition("### Acceptance Contract")[2]
    if not contract.strip() or not re.search(
        r"(?i)\b(unit|component|contract|integration|system|capacity|e2e|manual)\b", contract
    ):
        issues.append(_plan_issue("plan_acceptance_missing", binding, rule, f"{full_ref} 缺测试层级/真实边界"))
    return tuple(issues)


def validate_plan_coverage(context: SpecContext, artifact: str,
                           *, text: Optional[str] = None) -> GateResult:
    try:
        raw = Path(artifact).read_text(encoding="utf-8") if text is None else text
    except OSError as exc:
        issue = GateIssue("plan_read_error", "", "", "plan", str(exc))
        return GateResult("block", (issue,), (), ())
    try:
        sections = _task_sections(raw)
    except TaskDocumentError as exc:
        issue = GateIssue(exc.code, "", "", "plan", str(exc))
        return GateResult("block", (issue,), (), ())
    explicit = any("Rule-Owner-Refs" in task.fields for task in sections.values())
    declared, errors = _plan_owners(sections, context) if explicit else (None, [])
    for binding in context.bindings:
        for rule in binding.rules:
            if rule.enforcement == "required" and "plan" in rule.stage_status:
                errors.extend(_rule_plan_issues(binding, rule, sections, declared))
    refs = tuple(sorted({f"{item.spec_id}#{item.rule_ref}" for item in errors
                         if item.spec_id and item.rule_ref}))
    return GateResult("block" if errors else "pass", tuple(errors), (), refs)


def _issue_data(issue: GateIssue) -> dict[str, str]:
    return {
        "code": issue.code,
        "spec_id": issue.spec_id,
        "rule_ref": issue.rule_ref,
        "stage": issue.stage,
        "message": issue.message,
    }


def result_to_data(result: GateResult) -> dict[str, object]:
    return {
        "decision": result.decision,
        "errors": [_issue_data(item) for item in result.errors],
        "warnings": [_issue_data(item) for item in result.warnings],
        "affected_refs": list(result.affected_refs),
    }


