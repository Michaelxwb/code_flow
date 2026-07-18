#!/usr/bin/env python3
"""E-02/B-06 integration coverage for persisted Spec Context."""

import json
from dataclasses import replace
import hashlib
from pathlib import Path
import subprocess
import sys

import pytest
import yaml


SCRIPTS = Path(__file__).resolve().parents[1] / "src" / "core" / "code-flow" / "scripts"
sys.path.insert(0, str(SCRIPTS))

from cf_spec_context import (
    apply_artifact_ref,
    apply_decision,
    ArtifactRef,
    BindingInput,
    ContextError,
    Decision,
    bind_specs,
    load_context,
    new_context,
    refresh_missing_specs,
    refresh_context,
    RuleStageStatus,
    save_context,
)
from cf_spec_resolver import resolve_candidates


SPEC = """---
id: scripts-rules
description: Script rules
stages: [design, plan, code]
enforcement: required
verifiers:
  - rule: RULE-scripts-001
    type: manual
    config:
      checklist: review stdout
      owner: maintainers
---

# Script Rules

## Rules
- [RULE-scripts-001] Hook stdout must stay JSON.
"""


def _project(tmp_path: Path) -> tuple[Path, Path, Path]:
    flow = tmp_path / ".code-flow"
    spec_path = flow / "specs" / "scripts" / "rules.md"
    spec_path.parent.mkdir(parents=True)
    spec_path.write_text(SPEC, encoding="utf-8")
    config = {
        "path_mapping": {
            "scripts": {
                "patterns": ["src/*.py"],
                "specs": [{"path": "scripts/rules.md"}],
            }
        }
    }
    (flow / "config.yml").write_text(yaml.safe_dump(config), encoding="utf-8")
    task_dir = flow / "tasks" / "2026-07-16" / "context-test"
    task_dir.mkdir(parents=True)
    context_path = task_dir / "spec-context.yml"
    return tmp_path, spec_path, context_path


def _bound_context(tmp_path: Path) -> tuple[Path, Path, Path]:
    root, spec_path, context_path = _project(tmp_path)
    candidate = resolve_candidates(str(root), "design", ["src/hook.py"])[0]
    context = new_context("context-test", (("test", "E-02/B-06"),))
    context = bind_specs(context, (BindingInput(candidate, "path+agent", "changes hook"),))
    save_context(str(context_path), context)
    return root, spec_path, context_path


def test_e_02_deleted_spec_marks_binding_missing_and_rules_stale(tmp_path: Path) -> None:
    root, spec_path, context_path = _bound_context(tmp_path)
    before = load_context(str(context_path))
    spec_path.unlink()

    refreshed = refresh_missing_specs(before, str(root))
    save_context(str(context_path), refreshed)
    loaded = load_context(str(context_path))

    binding = loaded.bindings[0]
    assert binding.status == "missing"
    assert binding.path == "scripts/rules.md"
    assert {status.status for status in binding.rules[0].stage_status.values()} == {"stale"}
    assert not list(context_path.parent.glob(".spec-context.yml.*.tmp"))


def _run_decision(context_path: Path, payload: dict[str, object]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(SCRIPTS / "cf_spec_context.py"),
            "decision",
            "--task-dir",
            str(context_path.parent),
            "--json",
        ],
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        check=False,
    )


def _decision(confirmed_by: str = "user:jahan") -> dict[str, object]:
    return {
        "spec_id": "scripts-rules",
        "rule_ref": "RULE-scripts-001",
        "stage": "design",
        "batch": False,
        "decision": {
            "kind": "not_applicable",
            "reason": "This task does not change stdout behavior.",
            "confirmed_by": confirmed_by,
            "confirmed_at": "2026-07-16T12:00:00+08:00",
            "source": "codex:session-1:message-9",
            "expires_at": None,
        },
    }


def test_b_06_cli_rejects_batch_and_agent_self_confirmation(tmp_path: Path) -> None:
    _, _, context_path = _bound_context(tmp_path)
    batch_payload = _decision()
    batch_payload["batch"] = True

    batch = _run_decision(context_path, batch_payload)
    agent = _run_decision(context_path, _decision("agent:codex"))

    assert batch.returncode == 3
    assert json.loads(batch.stdout)["error"]["code"] == "batch_confirmation_forbidden"
    assert agent.returncode == 3
    assert json.loads(agent.stdout)["error"]["code"] == "agent_confirmation_forbidden"
    assert batch.stderr == ""
    assert agent.stderr == ""


def test_b_06_cli_persists_only_complete_user_confirmation(tmp_path: Path) -> None:
    _, _, context_path = _bound_context(tmp_path)

    result = _run_decision(context_path, _decision())

    assert result.returncode == 0
    assert json.loads(result.stdout) == {"ok": True, "status": "not_applicable"}
    assert result.stderr == ""
    loaded = load_context(str(context_path))
    status = loaded.bindings[0].rules[0].stage_status["design"]
    assert status.status == "not_applicable"
    assert status.decision is not None
    assert status.decision.confirmed_by == "user:jahan"
    assert status.decision.source == "codex:session-1:message-9"


def test_b_06_missing_confirmation_field_is_explicit_error(tmp_path: Path) -> None:
    _, _, context_path = _bound_context(tmp_path)
    payload = _decision()
    decision = payload["decision"]
    assert isinstance(decision, dict)
    decision.pop("source")

    result = _run_decision(context_path, payload)

    assert result.returncode == 3
    error = json.loads(result.stdout)["error"]
    assert error["code"] == "invalid_decision"
    assert error["field"] == "decision.source"


def test_context_rejects_unknown_schema_version(tmp_path: Path) -> None:
    path = tmp_path / "spec-context.yml"
    path.write_text("version: 99\ntask: future\n", encoding="utf-8")

    with pytest.raises(ContextError) as caught:
        load_context(str(path))

    assert caught.value.code == "unsupported_version"


def test_s_14_metadata_only_refresh_preserves_rule_state(tmp_path: Path) -> None:
    root, spec_path, context_path = _bound_context(tmp_path)
    before = load_context(str(context_path))
    spec_path.write_text(SPEC.replace("description: Script rules", "description: Updated script rules"), encoding="utf-8")

    result = refresh_context(before, str(root))

    assert [change.kind for change in result.changes] == ["metadata_changed"]
    after = result.context.bindings[0]
    assert after.hashes.metadata_sha256 != before.bindings[0].hashes.metadata_sha256
    assert after.hashes.rules_sha256 == before.bindings[0].hashes.rules_sha256
    assert {status.status for status in after.rules[0].stage_status.values()} == {"pending"}


def test_reapplying_artifact_slot_replaces_stale_hash(tmp_path: Path) -> None:
    root, unused_spec, context_path = _bound_context(tmp_path)
    del unused_spec
    artifact = root / "plan.md"
    artifact.write_text("first plan", encoding="utf-8")
    context = load_context(str(context_path))
    first = ArtifactRef("plan.md", "TASK-001", "RULE-scripts-001", hashlib.sha256(artifact.read_bytes()).hexdigest())
    context = apply_artifact_ref(context, "scripts-rules", "RULE-scripts-001", "plan", first)
    binding = context.bindings[0]
    rule = binding.rules[0]
    stages = dict(rule.stage_status)
    stages["plan"] = replace(stages["plan"], refs=(first, first))
    context = replace(context, bindings=(replace(binding, rules=(replace(rule, stage_status=stages),)),))

    artifact.write_text("revised plan", encoding="utf-8")
    second = replace(first, artifact_sha256=hashlib.sha256(artifact.read_bytes()).hexdigest())
    context = apply_artifact_ref(context, "scripts-rules", "RULE-scripts-001", "plan", second)
    status = context.bindings[0].rules[0].stage_status["plan"]

    assert status.refs == (second,)
    assert refresh_context(context, str(root)).changes == ()


def test_s_06_e_04_rule_change_marks_only_rule_stale(tmp_path: Path) -> None:
    root, spec_path, context_path = _bound_context(tmp_path)
    before = load_context(str(context_path))
    spec_path.write_text(
        SPEC.replace("Hook stdout must stay JSON.", "Hook stdout must be one JSON object."),
        encoding="utf-8",
    )

    result = refresh_context(before, str(root))

    assert [(change.kind, change.rule_ref) for change in result.changes] == [
        ("rule_changed", "RULE-scripts-001")
    ]
    rule = result.context.bindings[0].rules[0]
    assert rule.summary == "Hook stdout must be one JSON object."
    assert {status.status for status in rule.stage_status.values()} == {"stale"}


def test_removed_rule_preserves_explicit_replacement_decision(tmp_path: Path) -> None:
    root, spec_path, context_path = _bound_context(tmp_path)
    context = load_context(str(context_path))
    decision = Decision(
        "not_applicable",
        "Replaced by atomic rules.",
        "user:jahan",
        "2026-07-18T16:30:00+08:00",
        "codex:conversation:rule-optimization",
        None,
    )
    context = apply_decision(context, "scripts-rules", "RULE-scripts-001", "code", decision)
    replacement = SPEC.replace("RULE-scripts-001", "RULE-scripts-002").replace(
        "Hook stdout must stay JSON.", "Hook stdout must be one JSON object."
    )
    spec_path.write_text(replacement, encoding="utf-8")

    first = refresh_context(context, str(root)).context
    second = refresh_context(first, str(root)).context

    removed = next(rule for rule in second.bindings[0].rules if rule.ref == "RULE-scripts-001")
    assert removed.stage_status["code"].status == "not_applicable"
    assert removed.stage_status["code"].decision == decision
    assert removed.stage_status["design"].status == "stale"


TWO_RULE_SPEC = SPEC.replace(
    "  - rule: RULE-scripts-001\n    type: manual",
    "  - rule: RULE-scripts-001\n    type: manual",
).replace(
    "---\n\n# Script Rules",
    "  - rule: RULE-scripts-002\n    type: manual\n    config:\n      checklist: review errors\n      owner: maintainers\n---\n\n# Script Rules",
).replace(
    "- [RULE-scripts-001] Hook stdout must stay JSON.",
    "- [RULE-scripts-001] Hook stdout must stay JSON.\n- [RULE-scripts-002] Errors must be explicit.",
)


def _two_rule_context(tmp_path: Path) -> tuple[Path, Path, object]:
    root, spec_path, context_path = _project(tmp_path)
    spec_path.write_text(TWO_RULE_SPEC, encoding="utf-8")
    candidate = resolve_candidates(str(root), "design", ["src/hook.py"])[0]
    context = bind_specs(
        new_context("context-test", (("test", "E-12"),)),
        (BindingInput(candidate, "path+agent", "changes hook"),),
    )
    save_context(str(context_path), context)
    return root, spec_path, load_context(str(context_path))


def test_e_12_rule_and_artifact_drift_preserve_unrelated_evidence(tmp_path: Path) -> None:
    root, spec_path, context = _two_rule_context(tmp_path)
    artifact = root / "design.md"
    artifact.write_text("original design", encoding="utf-8")
    artifact_hash = hashlib.sha256(artifact.read_bytes()).hexdigest()
    binding = context.bindings[0]
    first, second = binding.rules
    first_stages = dict(first.stage_status)
    first_stages["design"] = RuleStageStatus(
        "verified",
        (ArtifactRef("design.md", "3.5", first.ref, artifact_hash),),
        None,
        ({"result_sha256": "first-evidence"},),
    )
    second_stages = dict(second.stage_status)
    second_stages["design"] = RuleStageStatus(
        "verified", (), None, ({"result_sha256": "second-evidence"},)
    )
    context = replace(
        context,
        bindings=(
            replace(
                binding,
                rules=(
                    replace(first, stage_status=first_stages),
                    replace(second, stage_status=second_stages),
                ),
            ),
        ),
    )
    artifact.write_text("changed design", encoding="utf-8")
    spec_path.write_text(
        TWO_RULE_SPEC.replace("Hook stdout must stay JSON.", "Hook stdout must be one JSON object."),
        encoding="utf-8",
    )

    result = refresh_context(context, str(root), artifact_root=str(root))

    kinds = {(change.kind, change.rule_ref) for change in result.changes}
    assert ("rule_changed", "RULE-scripts-001") in kinds
    assert ("artifact_changed", "RULE-scripts-001") in kinds
    refreshed_first, refreshed_second = result.context.bindings[0].rules
    assert refreshed_first.stage_status["design"].status == "stale"
    assert refreshed_second.stage_status["design"].status == "verified"
    assert refreshed_second.stage_status["design"].evidence == (
        {"result_sha256": "second-evidence"},
    )
