#!/usr/bin/env python3
"""E-03/E-06/B-07 integration coverage for Stage Gate decisions."""

from datetime import datetime, timezone
from pathlib import Path
import sys
from typing import Optional


SCRIPTS = Path(__file__).resolve().parents[1] / "src" / "core" / "code-flow" / "scripts"
sys.path.insert(0, str(SCRIPTS))

from cf_spec_context import (
    ContextSource,
    Decision,
    RuleBinding,
    RuleStageStatus,
    SpecBinding,
    SpecContext,
)
from cf_spec_gate import validate_stage
from cf_spec_metadata import SpecHashes


def _context(
    status: str,
    *,
    enforcement: str = "required",
    decision: Optional[Decision] = None,
    evidence: tuple[dict[str, object], ...] = (),
) -> SpecContext:
    stage = RuleStageStatus(status, (), decision, evidence)
    rule = RuleBinding(
        "RULE-gate-001",
        "Gate rule",
        "r" * 64,
        enforcement,
        "gate-spec#RULE-gate-001",
        {"design": stage},
    )
    binding = SpecBinding(
        "gate-spec",
        "gate/rules.md",
        SpecHashes("f" * 64, "m" * 64, "s" * 64),
        "path+agent",
        "gate test",
        enforcement,
        ("design",),
        (rule,),
    )
    return SpecContext(
        1,
        "gate-test",
        "required",
        "2026-07-16T00:00:00+00:00",
        (ContextSource("test", "gate"),),
        (binding,),
    )


def test_e_03_required_conflict_blocks_without_mutating_context() -> None:
    context = _context("conflict")

    result = validate_stage(context, "design")

    assert result.decision == "block"
    assert [issue.code for issue in result.errors] == ["conflict"]
    assert result.affected_refs == ("gate-spec#RULE-gate-001",)
    assert context.bindings[0].rules[0].stage_status["design"].status == "conflict"


def test_e_06_required_unverified_blocks_but_advisory_warns() -> None:
    required = validate_stage(_context("unverified"), "design")
    advisory = validate_stage(_context("unverified", enforcement="advisory"), "design")

    assert required.decision == "block"
    assert [issue.code for issue in required.errors] == ["unverified"]
    assert advisory.decision == "pass"
    assert [issue.code for issue in advisory.warnings] == ["unverified"]


def test_advisory_pending_is_not_gate_noise() -> None:
    result = validate_stage(_context("pending", enforcement="advisory"), "design")

    assert result.decision == "pass"
    assert result.warnings == ()
    assert result.affected_refs == ()


def test_e_06_verified_with_stale_evidence_hash_blocks() -> None:
    evidence = (
        {
            "status": "verified",
            "rule_text_sha256": "old-rule-hash",
            "artifact_sha256": None,
            "diff_sha256": "d" * 64,
            "result_sha256": "x" * 64,
        },
    )

    result = validate_stage(_context("verified", evidence=evidence), "design")

    assert result.decision == "block"
    assert [issue.code for issue in result.errors] == ["stale_evidence"]


def test_b_07_expired_waiver_blocks_and_future_waiver_passes() -> None:
    expired = Decision(
        "waived",
        "temporary exception",
        "user:jahan",
        "2026-07-15T10:00:00+08:00",
        "codex:session:message",
        "2026-07-16T10:00:00+08:00",
    )
    future = Decision(
        "waived",
        "temporary exception",
        "user:jahan",
        "2026-07-15T10:00:00+08:00",
        "codex:session:message",
        "2026-07-18T10:00:00+08:00",
    )
    now = datetime(2026, 7, 16, 4, 0, tzinfo=timezone.utc)

    expired_result = validate_stage(_context("waived", decision=expired), "design", now=now)
    future_result = validate_stage(_context("waived", decision=future), "design", now=now)

    assert expired_result.decision == "block"
    assert [issue.code for issue in expired_result.errors] == ["waiver_expired"]
    assert future_result.decision == "pass"
