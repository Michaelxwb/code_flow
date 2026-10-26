"""TASK-002: 0.8 task/scenario status machine and truthful Markdown status."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "src/core/code-flow/scripts"
sys.path.insert(0, str(SCRIPTS))

from cf_spec_context import RuleBinding, RuleStageStatus, SpecBinding, SpecContext
from cf_spec_metadata import SpecHashes
from cf_task_state import FINISHED_STATUSES
from cf_workflow_service import task_truth_issues


def _status(status: str) -> RuleStageStatus:
    return RuleStageStatus(status, (), None, ())


def _context(code: str = "pending", review: str = "pending") -> SpecContext:
    code_rule = RuleBinding(
        "RULE-code-001", "code rule", "a" * 64, "required", "spec#RULE-code-001",
        {"code": _status(code), "review": _status("pending")}, verifier_stage="code",
    )
    review_rule = RuleBinding(
        "RULE-review-001", "review rule", "b" * 64, "required", "spec#RULE-review-001",
        {"code": _status("pending"), "review": _status(review)}, verifier_stage="review",
    )
    binding = SpecBinding(
        "spec", "spec/rules.md", SpecHashes("c" * 64, "d" * 64, "e" * 64),
        "design", "test fixture", "required", ("design", "plan", "code", "review"),
        (code_rule, review_rule),
    )
    return SpecContext(1, "demo", "required", "2026-10-22T00:00:00+00:00", (), (binding,))


def _task(tmp_path: Path, status: str) -> Path:
    path = tmp_path / "demo.md"
    path.write_text(
        "# Tasks\n\n## TASK-001: Demo\n"
        f"- **Status**: {status}\n"
        "- **Acceptance-Refs**: S-01\n",
        encoding="utf-8",
    )
    return path


def test_finished_statuses_exclude_provisional() -> None:
    assert FINISHED_STATUSES == ("done", "verified")
    assert "provisional" not in FINISHED_STATUSES


def test_done_rejects_unverified_required_code_rule(tmp_path: Path) -> None:
    issues = task_truth_issues(str(_task(tmp_path, "done")), "TASK-001", _context(code="pending"))
    assert issues == ("spec#RULE-code-001: pending",)


def test_done_allows_review_rule_to_wait_for_requirement_gate(tmp_path: Path) -> None:
    issues = task_truth_issues(
        str(_task(tmp_path, "done")), "TASK-001", _context(code="verified", review="pending")
    )
    assert issues == (), "done 只要求 code 层；review 层由需求级终验收口"


def test_verified_requires_review_rule_too(tmp_path: Path) -> None:
    issues = task_truth_issues(
        str(_task(tmp_path, "verified")), "TASK-001", _context(code="verified", review="pending")
    )
    assert issues == ("spec#RULE-review-001: pending",)


def test_provisional_is_not_a_truth_claim(tmp_path: Path) -> None:
    issues = task_truth_issues(
        str(_task(tmp_path, "provisional")), "TASK-001", _context(code="pending", review="pending")
    )
    assert issues == (), "provisional 明确表示未完成，不需要再报文档漂移"
