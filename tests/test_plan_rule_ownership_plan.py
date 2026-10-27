"""Acceptance tests for shared Rule references and a unique plan owner."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "src" / "core" / "code-flow" / "scripts"
sys.path.insert(0, str(SCRIPTS))

from codeflow.cli.cf_spec_gate import validate_plan_coverage
from codeflow.cli.cf_spec_session import project_task_session
from codeflow.spec.cf_spec_context_model import (
    ArtifactRef, ContextSource, RuleBinding, RuleStageStatus, SpecBinding, SpecContext,
    load_context, save_context,
)
from codeflow.spec.cf_spec_metadata import SpecHashes

RULE = "shared-rules#RULE-shared-001"


def _context(tmp_path: Path) -> tuple[Path, SpecContext]:
    directory = tmp_path / ".code-flow" / "tasks" / "demo"
    directory.mkdir(parents=True)
    artifact = directory / "evidence.md"
    artifact.write_text("## Plan\n- [RULE-shared-001] Applied to the plan.\n", encoding="utf-8")
    ref = ArtifactRef("evidence.md", "Plan", "RULE-shared-001", hashlib.sha256(artifact.read_bytes()).hexdigest())
    status = RuleStageStatus("applied", (ref,), None, ())
    rule = RuleBinding("RULE-shared-001", "Shared rule", "a" * 64,
                       "required", RULE, {"plan": status})
    binding = SpecBinding("shared-rules", "shared/rules.md", SpecHashes("b" * 64, "c" * 64, "d" * 64),
                          "test", "shared ownership", "required", ("plan",), (rule,))
    context = SpecContext(1, "demo", "required", "2026-10-27T00:00:00+00:00",
                          (ContextSource("test", "ownership"),), (binding,))
    save_context(str(directory / "spec-context.yml"), context)
    return directory, load_context(str(directory / "spec-context.yml"))


def _section(task_id: str, refs: str, owner: str | None, *, verifier: bool = True) -> str:
    ownership = "" if owner is None else f"- **Rule-Owner-Refs**: {owner}\n"
    checklist = "- [ ] RULE-shared-001 verifier: verify the rule\n" if verifier else "- [ ] Implement the scenario\n"
    return (f"## {task_id}: Example\n- **Spec-Refs**: {refs}\n{ownership}"
            f"- **Acceptance-Refs**: S-01\n### Checklist\n{checklist}"
            "### Acceptance Contract\n| S-01 | integration | real context | rule applies |\n\n")


def _write_task(directory: Path, *sections: str) -> Path:
    target = directory / "demo.md"
    target.write_text("# Tasks\n\n" + "".join(sections), encoding="utf-8")
    return target


def _cli_gate(directory: Path, task_file: Path) -> tuple[int, dict[str, object]]:
    process = subprocess.run(
        ["node", str(ROOT / "src" / "cli.js"), "spec", "gate", "--task-dir", str(directory),
         "--stage", "plan", "--artifact", str(task_file), "--json"],
        cwd=ROOT, capture_output=True, text=True, timeout=15, check=False,
    )
    return process.returncode, json.loads(process.stdout)


def test_s01_shared_rule_references_keep_one_owner(tmp_path: Path) -> None:
    directory, context = _context(tmp_path)
    first = _section("TASK-001", RULE, RULE)
    second = _section("TASK-002", RULE, "N/A", verifier=False)
    second += f"```md\n- **Rule-Owner-Refs**: {RULE}\n```\n"
    task = _write_task(directory, first, second)

    result = validate_plan_coverage(context, str(task))
    assert result.decision == "pass", result.errors
    for task_id in ("TASK-001", "TASK-002"):
        projection = project_task_session(context, str(task), task_id)
        assert projection.included_rules == projection.total_rules == 1
        assert RULE in projection.text


def test_e01_missing_and_duplicate_owners_fail_closed(tmp_path: Path) -> None:
    cases = (
        (RULE, "N/A", "N/A", "plan_owner_missing"),
        (RULE, RULE, RULE, "plan_owner_duplicate"),
        ("N/A", RULE, "N/A", "plan_owner_not_referenced"),
        (RULE, "unknown#RULE-unknown-001", "N/A", "plan_owner_ref_unknown"),
        (RULE, "TBD", "N/A", "plan_owner_refs_invalid"),
        (RULE, "", "N/A", "plan_owner_refs_invalid"),
        (RULE, f"N/A, {RULE}", "N/A", "plan_owner_refs_invalid"),
        (RULE, f"{RULE}, {RULE}", "N/A", "plan_owner_refs_invalid"),
        ("TBD", RULE, "N/A", "plan_spec_refs_invalid"),
        ("unknown#RULE-unknown-001", "N/A", "N/A", "plan_spec_ref_unknown"),
        (RULE, None, "N/A", "plan_owner_missing"),
    )
    for index, (first_refs, first_owner, second_owner, expected) in enumerate(cases):
        directory, context = _context(tmp_path / str(index))
        task = _write_task(directory, _section("TASK-001", first_refs, first_owner),
                           _section("TASK-002", RULE, second_owner, verifier=False))
        result = validate_plan_coverage(context, str(task))
        assert result.decision == "block"
        assert expected in {issue.code for issue in result.errors}, (index, result.errors)

    directory, context = _context(tmp_path / "duplicate-field")
    section = _section("TASK-001", RULE, RULE)
    section = section.replace("### Checklist", f"- **Rule-Owner-Refs**: {RULE}\n### Checklist")
    result = validate_plan_coverage(context, str(_write_task(directory, section)))
    assert result.decision == "block"
    assert "duplicate_rule_owner_refs" in {issue.code for issue in result.errors}

    directory, context = _context(tmp_path / "owner-checklist")
    section = _section("TASK-001", RULE, RULE, verifier=False)
    result = validate_plan_coverage(context, str(_write_task(directory, section)))
    assert "plan_checklist_missing" in {issue.code for issue in result.errors}

    directory, context = _context(tmp_path / "owner-contract")
    section = _section("TASK-001", RULE, RULE).split("### Acceptance Contract", 1)[0]
    result = validate_plan_coverage(context, str(_write_task(directory, section)))
    assert "plan_acceptance_missing" in {issue.code for issue in result.errors}


def test_s02_legacy_plans_and_task_projections_remain_compatible(tmp_path: Path) -> None:
    directory, context = _context(tmp_path)
    first = _section("TASK-001", RULE, None)
    task = _write_task(directory, first)
    assert validate_plan_coverage(context, str(task)).decision == "pass"
    code, payload = _cli_gate(directory, task)
    assert code == 0 and payload["decision"] == "pass"

    task = _write_task(directory, first, _section("TASK-002", RULE, None))
    result = validate_plan_coverage(context, str(task))
    assert result.decision == "block"
    assert {issue.code for issue in result.errors} == {"plan_owner_duplicate"}
    code, payload = _cli_gate(directory, task)
    assert code == 3 and payload["decision"] == "block"
    for task_id in ("TASK-001", "TASK-002"):
        assert project_task_session(context, str(task), task_id).included_rules == 1
