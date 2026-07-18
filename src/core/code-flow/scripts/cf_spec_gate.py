#!/usr/bin/env python3
"""Fail-closed Stage Gate for required Spec Context rules."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sys
from typing import IO, Mapping, Optional, Sequence

from cf_spec_context import Decision, RuleBinding, RuleStageStatus, SpecBinding, SpecContext, load_context


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


def _evidence_issue(rule: RuleBinding, status: RuleStageStatus) -> Optional[str]:
    if not status.evidence:
        return "evidence_missing"
    for evidence in status.evidence:
        if evidence.get("status") != "verified":
            continue
        if evidence.get("rule_text_sha256") != rule.text_sha256:
            continue
        result_hash = evidence.get("result_sha256")
        if isinstance(result_hash, str) and result_hash:
            return None
    return "stale_evidence"


def _status_issue(rule: RuleBinding, status: RuleStageStatus, now: datetime) -> Optional[str]:
    if status.status == "applied":
        return None
    if status.status == "verified":
        return _evidence_issue(rule, status)
    if status.status == "not_applicable":
        return None if _decision_valid(status.decision) else "decision_invalid"
    if status.status == "waived":
        return _waiver_issue(status.decision, now)
    return status.status


def _binding_issues(binding: SpecBinding, stage: str, now: datetime) -> tuple[list[GateIssue], list[GateIssue]]:
    errors: list[GateIssue] = []
    warnings: list[GateIssue] = []
    for rule in binding.rules:
        status = rule.stage_status.get(stage)
        if status is None:
            continue
        if rule.enforcement == "advisory" and status.status == "pending":
            continue
        code = "missing_spec" if binding.status == "missing" else _status_issue(rule, status, now)
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
) -> GateResult:
    del artifact, task_id
    current = now or datetime.now(timezone.utc)
    errors: list[GateIssue] = []
    warnings: list[GateIssue] = []
    for binding in context.bindings:
        binding_errors, binding_warnings = _binding_issues(binding, stage, current)
        errors.extend(binding_errors)
        warnings.extend(binding_warnings)
    refs = tuple(sorted({f"{item.spec_id}#{item.rule_ref}" for item in (*errors, *warnings)}))
    return GateResult("block" if errors else "pass", tuple(errors), tuple(warnings), refs)


def _task_sections(text: str) -> Mapping[str, str]:
    matches = list(re.finditer(r"(?m)^## (TASK-\d+):[^\n]*$", text))
    sections: dict[str, str] = {}
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        sections[match.group(1)] = text[match.start():end]
    return sections


def _plan_issue(code: str, binding: SpecBinding, rule: RuleBinding, message: str) -> GateIssue:
    return GateIssue(code, binding.spec_id, rule.ref, "plan", message)


def _rule_plan_issues(
    binding: SpecBinding, rule: RuleBinding, sections: Mapping[str, str]
) -> tuple[GateIssue, ...]:
    full_ref = f"{binding.spec_id}#{rule.ref}"
    owners = tuple(task for task, section in sections.items() if full_ref in section)
    if not owners:
        return (_plan_issue("plan_owner_missing", binding, rule, f"{full_ref} 没有责任 TASK"),)
    if len(owners) > 1:
        return (_plan_issue("plan_owner_duplicate", binding, rule, f"{full_ref} 有多个责任 TASK"),)
    section = sections[owners[0]]
    issues: list[GateIssue] = []
    if rule.verifier_ref == "advisory:none":
        issues.append(_plan_issue("plan_verifier_missing", binding, rule, f"{full_ref} 缺 verifier"))
    checklist = section.partition("### Checklist")[2].partition("### Acceptance Contract")[0]
    if rule.ref not in checklist or "verifier" not in checklist.lower():
        issues.append(_plan_issue("plan_checklist_missing", binding, rule, f"{full_ref} 缺 verifier Checklist"))
    contract = section.partition("### Acceptance Contract")[2]
    if not contract.strip() or not re.search(r"\b(unit|integration|E2E|manual)\b", contract):
        issues.append(_plan_issue("plan_acceptance_missing", binding, rule, f"{full_ref} 缺测试层级/真实边界"))
    return tuple(issues)


def validate_plan_coverage(context: SpecContext, artifact: str) -> GateResult:
    try:
        text = Path(artifact).read_text(encoding="utf-8")
    except OSError as exc:
        issue = GateIssue("plan_read_error", "", "", "plan", str(exc))
        return GateResult("block", (issue,), (), ())
    sections = _task_sections(text)
    errors: list[GateIssue] = []
    for binding in context.bindings:
        for rule in binding.rules:
            if rule.enforcement == "required" and "plan" in rule.stage_status:
                errors.extend(_rule_plan_issues(binding, rule, sections))
    refs = tuple(sorted(f"{item.spec_id}#{item.rule_ref}" for item in errors))
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


def _merge_results(first: GateResult, second: GateResult) -> GateResult:
    errors = (*first.errors, *second.errors)
    warnings = (*first.warnings, *second.warnings)
    refs = tuple(sorted(set((*first.affected_refs, *second.affected_refs))))
    return GateResult("block" if errors else "pass", errors, warnings, refs)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="cf_spec_gate.py")
    parser.add_argument("--task-dir", required=True)
    parser.add_argument("--stage", required=True)
    parser.add_argument("--task", default="")
    parser.add_argument("--artifact", default="")
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: Optional[Sequence[str]] = None, stdout: IO[str] = sys.stdout) -> int:
    try:
        args = _parser().parse_args(argv)
        context = load_context(str(Path(args.task_dir) / "spec-context.yml"))
        result = validate_stage(context, args.stage, task_id=args.task)
        if args.stage == "plan" and args.artifact:
            result = _merge_results(result, validate_plan_coverage(context, args.artifact))
        stdout.write(json.dumps(result_to_data(result), ensure_ascii=False))
        return 0 if result.decision == "pass" else 3
    except Exception as exc:
        sys.stderr.write(f"cf_spec_gate error: {exc}\n")
        stdout.write(json.dumps({"decision": "block", "errors": [{"code": "gate_error"}]}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
