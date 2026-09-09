#!/usr/bin/env python3
"""S-05/S-07/E-05 E2E coverage for active diff runtime gates."""

from pathlib import Path
import subprocess
import sys

import yaml


SCRIPTS = Path(__file__).resolve().parents[1] / "src/core/code-flow/scripts"
sys.path.insert(0, str(SCRIPTS))

from cf_spec_context import BindingInput, Decision, apply_decision, bind_specs, complete_active_task, load_active_task, load_context, new_context, save_context, start_active_task
from cf_spec_resolver import resolve_candidates
from cf_spec_router import route_prompt
from cf_spec_session import context_sha256
from cf_task_runtime import evaluate_scope, run_done_gate


def _git(root: Path, *args: str) -> None:
    subprocess.run(("git", *args), cwd=root, check=True, capture_output=True)


def _spec(spec_id: str, rule: str, pattern: str) -> str:
    return f"""---
id: {spec_id}
description: runtime rule
stages: [code, review]
enforcement: required
verifiers:
  - rule: {rule}
    type: regex
    config:
      pattern: '{pattern}'
      files: '*.py'
---
# Rule
## Rules
- [{rule}] Runtime constraint.
"""


def _repo(tmp_path: Path, activate: bool = True) -> tuple[Path, Path]:
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "test@example.com")
    _git(tmp_path, "config", "user.name", "Test")
    app = tmp_path / "src/app.py"
    app.parent.mkdir()
    app.write_text("VALUE = 1\n", encoding="utf-8")
    specs = tmp_path / ".code-flow/specs"
    (specs / "app").mkdir(parents=True)
    (specs / "db").mkdir()
    (specs / "app/rules.md").write_text(_spec("app-runtime", "RULE-app-001", "^print\\("), encoding="utf-8")
    (specs / "db/rules.md").write_text(_spec("db-runtime", "RULE-db-001", "^DROP "), encoding="utf-8")
    config = {"path_mapping": {
        "app": {"patterns": ["src/*"], "specs": [{"path": "app/rules.md"}]},
        "db": {"patterns": ["db/*"], "specs": [{"path": "db/rules.md"}]},
    }}
    (tmp_path / ".code-flow/config.yml").write_text(yaml.safe_dump(config), encoding="utf-8")
    task_dir = tmp_path / ".code-flow/tasks/demo"
    task_dir.mkdir(parents=True)
    candidate = resolve_candidates(str(tmp_path), "code", ["src/app.py"])[0]
    context = bind_specs(new_context("demo", (("test", "runtime"),)), (BindingInput(candidate, "plan", "app task"),))
    save_context(str(task_dir / "spec-context.yml"), context)
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-qm", "initial")
    if activate:
        start_active_task(str(tmp_path), ".code-flow/tasks/demo", "TASK-001", "ctx")
    return tmp_path, task_dir


def test_s_05_required_violation_blocks_done_until_verified(tmp_path: Path) -> None:
    root, task_dir = _repo(tmp_path)
    app = root / "src/app.py"
    app.write_text("print('bad')\n", encoding="utf-8")
    blocked = run_done_gate(str(root), str(task_dir))
    assert blocked.decision == "block"
    assert blocked.evidence[0]["error_code"] == "regex_violation"
    app.write_text("VALUE = 2\n", encoding="utf-8")
    passed = run_done_gate(str(root), str(task_dir))
    assert passed.decision == "pass"
    assert load_context(str(task_dir / "spec-context.yml")).bindings[0].rules[0].stage_status["code"].status == "verified"


def test_s_07_e_05_new_path_pauses_and_adds_pending_binding(tmp_path: Path) -> None:
    root, task_dir = _repo(tmp_path)
    model = root / "db/model.py"
    model.parent.mkdir()
    model.write_text("MODEL = 1\n", encoding="utf-8")
    result = evaluate_scope(str(root), str(task_dir))
    context = load_context(str(task_dir / "spec-context.yml"))
    assert result.decision == "pause"
    assert result.new_specs == ("db-runtime",)
    assert {item.spec_id for item in context.bindings} == {"app-runtime", "db-runtime"}
    assert next(item for item in context.bindings if item.spec_id == "db-runtime").rules[0].stage_status["code"].status == "pending"
    assert "局部 Plan" in result.message and "Align" in result.message


def test_gate_re_run_keeps_marker_hash_stable(tmp_path: Path) -> None:
    """PostToolUse edit path must not drift the active marker hash (friction 1)."""
    root, task_dir = _repo(tmp_path, activate=False)
    ctx_path = task_dir / "spec-context.yml"
    context = load_context(str(ctx_path))
    marker_hash = context_sha256(context)
    (task_dir / "demo.md").write_text(
        "# Tasks\n\n## TASK-001: Build\n- **Source**: demo.design.md#3\n"
        "- **Spec-Refs**: app-runtime#RULE-app-001\n"
        "### Acceptance Contract\n| S-04 | E2E | real | assert |\n",
        encoding="utf-8",
    )
    start_active_task(str(root), ".code-flow/tasks/demo", "TASK-001", marker_hash)

    app = root / "src/app.py"
    app.write_text("VALUE = 4\n", encoding="utf-8")
    first = run_done_gate(str(root), str(task_dir))
    after_edit = context_sha256(load_context(str(ctx_path)))
    second = run_done_gate(str(root), str(task_dir))
    after_rerun = context_sha256(load_context(str(ctx_path)))

    assert first.decision == "pass" and second.decision == "pass"
    assert after_edit == marker_hash, "edit + gate must not drift the marker hash"
    assert after_rerun == after_edit, "re-running the gate must not rewrite the context"
    assert route_prompt(str(root), ("src/app.py",), "test").mode == "task"


def _manual_repo(tmp_path: Path) -> tuple[Path, Path]:
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "test@example.com")
    _git(tmp_path, "config", "user.name", "Test")
    app = tmp_path / "src/app.py"
    app.parent.mkdir()
    app.write_text("VALUE = 1\n", encoding="utf-8")
    specs = tmp_path / ".code-flow/specs/app"
    specs.mkdir(parents=True)
    (specs / "rules.md").write_text(
        "---\nid: manual-runtime\ndescription: manual rule\nstages: [code]\nenforcement: required\n"
        "verifiers:\n  - rule: RULE-manual-001\n    type: manual\n    config:\n"
        "      checklist: review the change\n      owner: maintainers\n"
        "---\n# Rule\n## Rules\n- [RULE-manual-001] Change must be reviewed by a human owner.\n",
        encoding="utf-8",
    )
    config = {"path_mapping": {"app": {"patterns": ["src/*"], "specs": [{"path": "app/rules.md"}]}}}
    (tmp_path / ".code-flow/config.yml").write_text(yaml.safe_dump(config), encoding="utf-8")
    task_dir = tmp_path / ".code-flow/tasks/demo"
    task_dir.mkdir(parents=True)
    candidate = resolve_candidates(str(tmp_path), "code", ["src/app.py"])[0]
    context = bind_specs(new_context("demo", (("test", "manual"),)), (BindingInput(candidate, "plan", "app task"),))
    save_context(str(task_dir / "spec-context.yml"), context)
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-qm", "initial")
    return tmp_path, task_dir


def test_cheap_gate_skips_command_verifiers(tmp_path: Path) -> None:
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "test@example.com")
    _git(tmp_path, "config", "user.name", "Test")
    app = tmp_path / "src/app.py"
    app.parent.mkdir()
    app.write_text("VALUE = 1\n", encoding="utf-8")
    specs = tmp_path / ".code-flow/specs/app"
    specs.mkdir(parents=True)
    (specs / "rules.md").write_text(
        "---\nid: cmd-runtime\ndescription: command rule\nstages: [code]\nenforcement: required\n"
        "verifiers:\n  - rule: RULE-cmd-001\n    type: test\n    config:\n"
        '      argv: [python3, -c, "import sys; sys.exit(1)"]\n      timeout: 10\n'
        "---\n# Rule\n## Rules\n- [RULE-cmd-001] Must pass the command.\n",
        encoding="utf-8",
    )
    config = {"path_mapping": {"app": {"patterns": ["src/*"], "specs": [{"path": "app/rules.md"}]}}}
    (tmp_path / ".code-flow/config.yml").write_text(yaml.safe_dump(config), encoding="utf-8")
    task_dir = tmp_path / ".code-flow/tasks/demo"
    task_dir.mkdir(parents=True)
    candidate = resolve_candidates(str(tmp_path), "code", ["src/app.py"])[0]
    context = bind_specs(new_context("demo", (("test", "cheap"),)), (BindingInput(candidate, "plan", "app"),))
    save_context(str(task_dir / "spec-context.yml"), context)
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-qm", "initial")
    start_active_task(str(tmp_path), ".code-flow/tasks/demo", "TASK-001", "ctx")

    full = run_done_gate(str(tmp_path), str(task_dir))
    cheap = run_done_gate(str(tmp_path), str(task_dir), cheap=True)

    assert full.evidence and full.evidence[0]["status"] == "unverified"
    assert cheap.evidence, "cheap gate must not run command/test verifiers"
    assert all(item["error_code"] == "skipped_in_cheap_gate" for item in cheap.evidence)
    assert all(item["status"] == "unverified" for item in cheap.evidence)
    assert all(item["diff_sha256"] == cheap.evidence[0]["diff_sha256"] for item in cheap.evidence)


def test_scope_expansion_re_syncs_marker_hash(tmp_path: Path) -> None:
    """Toolchain-initiated scope expansion must re-sync the marker, not drift it."""
    root, task_dir = _repo(tmp_path, activate=False)
    ctx_path = str(task_dir / "spec-context.yml")
    marker_hash = context_sha256(load_context(ctx_path))
    start_active_task(str(root), ".code-flow/tasks/demo", "TASK-001", marker_hash)
    model = root / "db/model.py"
    model.parent.mkdir()
    model.write_text("MODEL = 1\n", encoding="utf-8")

    result = evaluate_scope(str(root), str(task_dir))

    assert result.decision == "pause"  # db-runtime is required -> pause
    assert load_active_task(str(root)).context_sha256 == context_sha256(
        load_context(ctx_path)
    ), "scope expansion must re-sync the active marker hash"


def test_pending_manual_rule_blocks_done_gate(tmp_path: Path) -> None:
    root, task_dir = _manual_repo(tmp_path)
    start_active_task(str(root), ".code-flow/tasks/demo", "TASK-001", "ctx")
    result = run_done_gate(str(root), str(task_dir))
    assert result.decision == "block"
    assert result.evidence[0]["error_code"] == "manual_confirmation_missing"


def test_manual_verification_decision_survives_done_gate(tmp_path: Path) -> None:
    root, task_dir = _manual_repo(tmp_path)
    ctx_path = str(task_dir / "spec-context.yml")
    context = load_context(ctx_path)
    decision = Decision(
        "manual_verification",
        "Reviewed frontend quality against the checklist.",
        "user:jahan",
        "2026-08-04T10:00:00+08:00",
        "conversation:manual-review",
        None,
    )
    context = apply_decision(context, "manual-runtime", "RULE-manual-001", "code", decision)
    save_context(ctx_path, context)
    start_active_task(str(root), ".code-flow/tasks/demo", "TASK-001", "ctx")

    result = run_done_gate(str(root), str(task_dir))

    status = load_context(ctx_path).bindings[0].rules[0].stage_status["code"]
    assert result.decision == "pass"
    assert status.status == "verified", "recorded human confirmation must not be downgraded"
    assert status.decision == decision


def test_not_applicable_decision_survives_done_gate(tmp_path: Path) -> None:
    root, task_dir = _manual_repo(tmp_path)
    ctx_path = str(task_dir / "spec-context.yml")
    context = load_context(ctx_path)
    decision = Decision(
        "not_applicable",
        "Frontend-only rule; this backend change does not touch frontend.",
        "user:jahan",
        "2026-08-04T10:00:00+08:00",
        "conversation:na-review",
        None,
    )
    context = apply_decision(context, "manual-runtime", "RULE-manual-001", "code", decision)
    save_context(ctx_path, context)
    start_active_task(str(root), ".code-flow/tasks/demo", "TASK-001", "ctx")

    result = run_done_gate(str(root), str(task_dir))

    status = load_context(ctx_path).bindings[0].rules[0].stage_status["code"]
    assert result.decision == "pass"
    assert status.status == "not_applicable", "human N/A decision must not be clobbered by the gate"
    assert status.decision == decision


def test_rename_during_active_task_does_not_crash_done_gate(tmp_path: Path) -> None:
    root, task_dir = _repo(tmp_path)
    _git(root, "mv", "src/app.py", "src/app2.py")

    result = run_done_gate(str(root), str(task_dir))

    assert result.decision == "pass"
    assert not (root / ".code-flow" / ".active-task.lock").exists()


def test_mid_task_commit_allows_complete(tmp_path: Path) -> None:
    root, task_dir = _repo(tmp_path)
    app = root / "src/app.py"
    app.write_text("VALUE = 2\n", encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "mid-task")
    head = subprocess.check_output(("git", "rev-parse", "HEAD"), cwd=root, text=True).strip()

    completed = complete_active_task(str(root), True)

    assert completed.baseline.head != head, "TASK-002: baseline head 必须冻结，不得 rebase"
    assert completed.baseline.last_seen_head == head
    assert not (root / ".code-flow" / ".active-task.json").exists()


def test_done_gate_budget_exhaustion_is_visible_in_evidence(tmp_path: Path) -> None:
    root, task_dir = _repo(tmp_path)
    app = root / "src/app.py"
    app.write_text("print('x')\n", encoding="utf-8")

    result = run_done_gate(str(root), str(task_dir), budget=0.0)

    assert result.decision == "block"
    assert any(item.get("error_code") == "verifier_budget_exhausted" for item in result.evidence)
    assert load_context(str(task_dir / "spec-context.yml")).bindings[0].rules[0].stage_status["code"].status == "unverified"
