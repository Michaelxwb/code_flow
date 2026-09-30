#!/usr/bin/env python3
"""S-05/S-07/E-05 E2E coverage for active diff runtime gates."""

from pathlib import Path
import json
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


def _manual_repo(tmp_path: Path, stages: str = "[code]") -> tuple[Path, Path]:
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "test@example.com")
    _git(tmp_path, "config", "user.name", "Test")
    app = tmp_path / "src/app.py"
    app.parent.mkdir()
    app.write_text("VALUE = 1\n", encoding="utf-8")
    specs = tmp_path / ".code-flow/specs/app"
    specs.mkdir(parents=True)
    (specs / "rules.md").write_text(
        f"---\nid: manual-runtime\ndescription: manual rule\nstages: {stages}\nenforcement: required\n"
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

    assert full.decision == "block"
    assert full.evidence and full.evidence[0]["status"] == "unverified"
    assert cheap.decision == "pass", "cheap 门禁不得因命令类 verifier 未执行而阻断"
    assert cheap.evidence, "cheap gate must not run command/test verifiers"
    assert all(item["error_code"] == "skipped_in_cheap_gate" for item in cheap.evidence)
    assert all(item["status"] == "unverified" for item in cheap.evidence)
    assert all(item["diff_sha256"] == cheap.evidence[0]["diff_sha256"] for item in cheap.evidence)


def _validation_repo(tmp_path: Path, command: str, finish_check: bool = True,
                     heavy: bool = True, heavy_at_finish: bool = False) -> tuple[Path, Path]:
    root, task_dir = _repo(tmp_path, activate=False)
    quoted = command.replace("'", "''")
    (root / ".code-flow/validation.yml").write_text(
        "validators:\n"
        '    - name: "HeavySuite"\n'
        '      trigger: "**/*.py"\n'
        f"      command: '{quoted}'\n"
        "      timeout: 15000\n"
        + ("      heavy: true\n" if heavy else "")
        + '      on_fail: "修复全量测试"\n',
        encoding="utf-8",
    )
    config_path = root / ".code-flow/config.yml"
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    quality: dict = {"enabled": True, "finish_check": finish_check}
    if heavy_at_finish:
        quality["heavy_at_finish"] = True
    config["quality_loop"] = quality
    config_path.write_text(yaml.safe_dump(config), encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "validation config")
    start_active_task(str(root), ".code-flow/tasks/demo", "TASK-001", context_sha256(load_context(str(task_dir / "spec-context.yml"))))
    (root / "src/app.py").write_text("VALUE = 2\n", encoding="utf-8")
    return root, task_dir


def test_finish_defers_heavy_validation_by_default(tmp_path: Path) -> None:
    """heavy validator 默认不在 finish 执行（归档 cf_validation / cf-validate 全量）。"""
    root, task_dir = _validation_repo(tmp_path, 'python3 -c "open(\'.heavy-run\', \'a\').write(\'x\')"')

    cheap = run_done_gate(str(root), str(task_dir), cheap=True)
    assert cheap.decision == "pass"
    assert not (root / ".heavy-run").exists(), "Stop 轻量门禁不得执行 heavy validator"

    full = run_done_gate(str(root), str(task_dir))

    assert full.decision == "pass", full.message
    assert full.deferred_heavy == 1
    assert not (root / ".heavy-run").exists(), "finish 默认不得执行 heavy validator"


def test_finish_runs_heavy_validation_when_enabled(tmp_path: Path) -> None:
    root, task_dir = _validation_repo(
        tmp_path, 'python3 -c "open(\'.heavy-run\', \'a\').write(\'x\')"', heavy_at_finish=True
    )

    full = run_done_gate(str(root), str(task_dir))

    assert full.decision == "pass", full.message
    assert (root / ".heavy-run").read_text(encoding="utf-8") == "x", "heavy_at_finish=true 时必须执行"


def test_finish_validation_failure_blocks_done(tmp_path: Path) -> None:
    root, task_dir = _validation_repo(tmp_path, "python3 -c 'import sys; sys.exit(1)'",
                                      heavy_at_finish=True)

    full = run_done_gate(str(root), str(task_dir))

    assert full.decision == "block"
    assert "finish validation failed" in full.message and "HeavySuite" in full.message


def test_light_validation_failure_blocks_done_by_default(tmp_path: Path) -> None:
    """非 heavy validator 仍在 finish 执行并阻断。"""
    root, task_dir = _validation_repo(tmp_path, "python3 -c 'import sys; sys.exit(1)'", heavy=False)

    full = run_done_gate(str(root), str(task_dir))

    assert full.decision == "block"
    assert "finish validation failed" in full.message and "HeavySuite" in full.message


def test_finish_check_can_be_disabled_by_config(tmp_path: Path) -> None:
    root, task_dir = _validation_repo(tmp_path, "python3 -c 'import sys; sys.exit(1)'",
                                      finish_check=False, heavy_at_finish=True)

    full = run_done_gate(str(root), str(task_dir))

    assert full.decision == "pass", full.message


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


def test_review_manual_rule_defers_done_gate(tmp_path: Path) -> None:
    """spec 声明 review 的 manual 规则不逐任务阻断，延后到需求级终验确认。"""
    root, task_dir = _manual_repo(tmp_path, stages="[design, plan, code, review]")
    start_active_task(str(root), ".code-flow/tasks/demo", "TASK-001", "ctx")

    result = run_done_gate(str(root), str(task_dir))

    assert result.decision == "pass", result.message
    assert result.deferred_review == 1
    status = load_context(str(task_dir / "spec-context.yml")).bindings[0].rules[0].stage_status["review"]
    assert status.status == "pending"


def test_manual_acceptance_scenario_does_not_block_done_gate(tmp_path: Path) -> None:
    """manifest manual 场景不再逐任务阻断；统一在 verify-e2e 由用户确认。"""
    root, task_dir = _manual_repo(tmp_path, stages="[design, plan, code, review]")
    (task_dir / ".acceptance-manifest.json").write_text(
        json.dumps({"scenarios": [{"id": "S-01", "kind": "manual"}]}), encoding="utf-8"
    )
    start_active_task(str(root), ".code-flow/tasks/demo", "TASK-001", "ctx")

    result = run_done_gate(str(root), str(task_dir))

    assert result.decision == "pass", result.message


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


STAGE_RUNTIME_SPEC = """---
id: stage-runtime
description: stage runtime rules
stages: [code, review]
enforcement: required
verifiers:
  - rule: RULE-stage-001
    type: test
    config:
      argv: [python3, -c, "open('code-ran.txt', 'a').write('x')"]
      timeout: 30
  - rule: RULE-stage-002
    type: test
    stage: review
    config:
      argv: [python3, -c, "open('review-ran.txt', 'a').write('x')"]
      timeout: 30
---

# Stage Rules

## Rules
- [RULE-stage-001] code rule.
- [RULE-stage-002] review rule.
"""

LEGACY_RUNTIME_SPEC = """---
id: legacy-runtime
description: legacy runtime rules
stages: [code, review]
enforcement: required
verifiers:
  - rule: RULE-legacy-001
    type: test
    config:
      argv: [python3, -c, "open('legacy-ran.txt', 'a').write('x')"]
      timeout: 30
---

# Legacy Rules

## Rules
- [RULE-legacy-001] legacy rule without stage/files declarations.
"""


def _stage_repo(tmp_path: Path, spec_text: str = STAGE_RUNTIME_SPEC) -> tuple[Path, Path]:
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "test@example.com")
    _git(tmp_path, "config", "user.name", "Test")
    app = tmp_path / "src/app.py"
    app.parent.mkdir()
    app.write_text("VALUE = 1\n", encoding="utf-8")
    specs = tmp_path / ".code-flow/specs/stage"
    specs.mkdir(parents=True)
    (specs / "rules.md").write_text(spec_text, encoding="utf-8")
    config = {"path_mapping": {"stage": {"patterns": ["src/*"], "specs": [{"path": "stage/rules.md"}]}}}
    (tmp_path / ".code-flow/config.yml").write_text(yaml.safe_dump(config), encoding="utf-8")
    task_dir = tmp_path / ".code-flow/tasks/demo"
    task_dir.mkdir(parents=True)
    candidate = resolve_candidates(str(tmp_path), "code", ["src/app.py"])[0]
    context = bind_specs(new_context("demo", (("test", "stage"),)), (BindingInput(candidate, "plan", "stage task"),))
    save_context(str(task_dir / "spec-context.yml"), context)
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-qm", "initial")
    start_active_task(str(tmp_path), ".code-flow/tasks/demo", "TASK-001", "ctx")
    return tmp_path, task_dir


def test_s_01_done_gate_stage_split(tmp_path: Path) -> None:
    """S-01: Done Gate 只执行 code 层；review 规则不执行且保持 pending。"""
    root, task_dir = _stage_repo(tmp_path)

    result = run_done_gate(str(root), str(task_dir))

    assert (root / "code-ran.txt").exists(), "code verifier 必须执行"
    assert not (root / "review-ran.txt").exists(), "review verifier 不得在 Done Gate 执行"
    rules = {rule.ref: rule for rule in load_context(str(task_dir / "spec-context.yml")).bindings[0].rules}
    assert rules["RULE-stage-002"].stage_status["review"].status == "pending"
    assert rules["RULE-stage-001"].stage_status["code"].status == "verified"
    assert result.decision == "pass", result.message
    assert result.deferred_review == 1


def test_s_05_legacy_defaults(tmp_path: Path) -> None:
    """S-05: 未声明 stage/files 的旧格式 verifier 仍在 Done Gate 执行。"""
    root, task_dir = _stage_repo(tmp_path, LEGACY_RUNTIME_SPEC)

    result = run_done_gate(str(root), str(task_dir))

    assert (root / "legacy-ran.txt").exists(), "旧格式 verifier 必须照常执行"
    assert result.decision == "pass", result.message
    assert result.deferred_review == 0


def _scope_repo(tmp_path: Path, other_timeout: int = 30) -> tuple[Path, Path]:
    """app(src/*) 与 other(db/*) 两个 required spec 均已绑定（模拟需求级累积 context）。"""
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "test@example.com")
    _git(tmp_path, "config", "user.name", "Test")
    (tmp_path / "src").mkdir()
    (tmp_path / "db").mkdir()
    (tmp_path / "src/app.py").write_text("VALUE = 1\n", encoding="utf-8")
    (tmp_path / "db/model.py").write_text("MODEL = 1\n", encoding="utf-8")
    specs = tmp_path / ".code-flow/specs"
    (specs / "app").mkdir(parents=True)
    (specs / "other").mkdir()
    (specs / "app/rules.md").write_text(
        "---\nid: app-runtime\ndescription: app rules\nstages: [code, review]\nenforcement: required\n"
        "verifiers:\n  - rule: RULE-app-001\n    type: test\n    config:\n"
        "      argv: [python3, -c, \"open('app-ran.txt', 'a').write('x')\"]\n      timeout: 30\n"
        "---\n# App Rules\n## Rules\n- [RULE-app-001] app rule.\n",
        encoding="utf-8",
    )
    (specs / "other/rules.md").write_text(
        "---\nid: other-runtime\ndescription: other rules\nstages: [code, review]\nenforcement: required\n"
        "verifiers:\n  - rule: RULE-other-001\n    type: test\n    config:\n"
        "      argv: [python3, -c, \"open('other-ran.txt', 'a').write('x')\"]\n"
        f"      timeout: {other_timeout}\n"
        "---\n# Other Rules\n## Rules\n- [RULE-other-001] other rule.\n",
        encoding="utf-8",
    )
    config = {"path_mapping": {
        "app": {"patterns": ["src/*"], "specs": [{"path": "app/rules.md"}]},
        "other": {"patterns": ["db/*"], "specs": [{"path": "other/rules.md"}]},
    }}
    (tmp_path / ".code-flow/config.yml").write_text(yaml.safe_dump(config), encoding="utf-8")
    task_dir = tmp_path / ".code-flow/tasks/demo"
    task_dir.mkdir(parents=True)
    app_candidate = resolve_candidates(str(tmp_path), "code", ["src/app.py"])[0]
    other_candidate = resolve_candidates(str(tmp_path), "code", ["db/model.py"])[0]
    context = new_context("demo", (("test", "scope"),))
    context = bind_specs(context, (
        BindingInput(app_candidate, "plan", "app task"),
        BindingInput(other_candidate, "plan", "需求级累积绑定"),
    ))
    save_context(str(task_dir / "spec-context.yml"), context)
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-qm", "initial")
    return tmp_path, task_dir


def _write_task_refs(task_dir: Path, refs: str) -> Path:
    path = task_dir / "demo.md"
    path.write_text(
        f"# Tasks\n\n## TASK-001: Demo\n- **Status**: in-progress\n- **Spec-Refs**: {refs}\n",
        encoding="utf-8",
    )
    return path


def test_out_of_scope_verifier_deferred_to_requirement(tmp_path: Path) -> None:
    """路径只命中 app：other 的 code verifier 不在本任务执行，登记 deferred_to_review。"""
    root, task_dir = _scope_repo(tmp_path)
    start_active_task(str(root), ".code-flow/tasks/demo", "TASK-001", "ctx")
    (root / "src/app.py").write_text("VALUE = 2\n", encoding="utf-8")

    result = run_done_gate(str(root), str(task_dir))

    assert result.decision == "pass", result.message
    assert (root / "app-ran.txt").exists(), "范围内 verifier 必须执行"
    assert not (root / "other-ran.txt").exists(), "范围外 verifier 不得执行"
    assert result.deferred_requirement == 1
    binding = next(b for b in load_context(str(task_dir / "spec-context.yml")).bindings
                   if b.spec_id == "other-runtime")
    assert binding.rules[0].stage_status["code"].evidence[-1]["error_code"] == "deferred_to_review"


def test_spec_refs_keeps_spec_in_scope(tmp_path: Path) -> None:
    """无路径命中但有 Spec-Refs：声明的 spec 仍在本任务执行，其余延后。"""
    root, task_dir = _scope_repo(tmp_path)
    _write_task_refs(task_dir, "other-runtime#RULE-other-001")
    start_active_task(str(root), ".code-flow/tasks/demo", "TASK-001", "ctx")
    (root / "docs").mkdir()
    (root / "docs/note.md").write_text("note\n", encoding="utf-8")

    result = run_done_gate(str(root), str(task_dir))

    assert result.decision == "pass", result.message
    assert (root / "other-ran.txt").exists(), "Spec-Refs 声明的 verifier 必须执行"
    assert not (root / "app-ran.txt").exists(), "未声明的 spec 延后"
    assert result.deferred_requirement == 1


def test_no_scope_sources_falls_back_to_all_bindings(tmp_path: Path) -> None:
    """无 Spec-Refs 且无路径命中（老任务）：不静默跳过，回退全量绑定。"""
    root, task_dir = _scope_repo(tmp_path)
    start_active_task(str(root), ".code-flow/tasks/demo", "TASK-001", "ctx")

    result = run_done_gate(str(root), str(task_dir))

    assert result.decision == "pass", result.message
    assert (root / "app-ran.txt").exists() and (root / "other-ran.txt").exists()
    assert result.deferred_requirement == 0


def test_over_budget_verifier_deferred(tmp_path: Path) -> None:
    """声明 timeout 超预算（默认 300s）的 verifier 不执行；budget=0 恢复执行。"""
    root, task_dir = _scope_repo(tmp_path, other_timeout=9999)
    _write_task_refs(task_dir, "other-runtime#RULE-other-001")
    start_active_task(str(root), ".code-flow/tasks/demo", "TASK-001", "ctx")
    (root / "db/model.py").write_text("MODEL = 2\n", encoding="utf-8")

    result = run_done_gate(str(root), str(task_dir))

    assert result.decision == "pass", result.message
    assert not (root / "other-ran.txt").exists(), "超预算 verifier 不得执行"
    assert result.deferred_budget == 1

    config_path = root / ".code-flow/config.yml"
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    config["quality_loop"] = {"enabled": True, "finish_verifier_budget": 0}
    config_path.write_text(yaml.safe_dump(config), encoding="utf-8")

    unlimited = run_done_gate(str(root), str(task_dir))

    assert unlimited.decision == "pass", unlimited.message
    assert (root / "other-ran.txt").exists(), "budget=0 时必须执行"
