#!/usr/bin/env python3
"""[workflow-smoothness] 修复回归：工作流断点与状态一致性。

覆盖：
- start 错误跨模块实例传播（direct script run 不再 internal_error）
- Coverage 缺命令列时从 Acceptance Contract 回退提取
- 重锁 manifest 保留运行态（status/evidence/runs）
- 无自有场景 TASK finish 不再 no_executable_scenarios
- 已验证 E2E 不被 e2e_deferred 降级
- 跨需求 bind 不污染 active marker hash
- decision 返回目标 rule 状态
- cheap-gate 跳过证据幂等
- 带注解层级 Stop hook 不误报
- legacy 会话状态缺 next_remind_at 不崩溃
"""
import json
import os
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "src/core/code-flow/scripts"
sys_path_added = str(SCRIPTS)
import sys  # noqa: E402

if sys_path_added not in sys.path:
    sys.path.insert(0, sys_path_added)

from cf_acceptance_evidence import persist_results  # noqa: E402
from cf_acceptance_manifest import extract_manifest, validate_manifest, write_manifest  # noqa: E402
from cf_acceptance_runner import run_manifest  # noqa: E402
from cf_spec_context import (  # noqa: E402
    RuleBinding,
    RuleStageStatus,
    bind_specs,
    load_context,
    load_active_task,
    new_context,
    resync_active_hash,
    save_context,
)
from cf_spec_resolver import resolve_candidates  # noqa: E402
from cf_spec_session import context_sha256  # noqa: E402
from cf_task_runtime import _update_rule  # noqa: E402
from cf_workflow_service import start_task  # noqa: E402


# --- helpers ---

def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _task_file(tmp_path: Path, coverage_rows: str, contract_rows: str = "") -> Path:
    if not contract_rows:
        contract_rows = (
            "| 场景ID | 测试层级 | 不得 Mock | 关键断言 | 测试文件 | 命令 | 状态 |\n"
            "|--------|---------|----------|---------|---------|------|------|\n"
        )
    task = tmp_path / "work.md"
    _write(
        task,
        "## Acceptance Coverage\n"
        "| 场景ID | 来源设计 | 测试层级 | 关键真实边界 | 负责任务 | 状态 |\n"
        "|--------|---------|---------|-------------|---------|------|\n"
        f"{coverage_rows}\n"
        "## TASK-001: Demo\n"
        "- **Status**: draft\n"
        "- **Acceptance-Refs**: S-01\n"
        "### Acceptance Contract\n"
        f"{contract_rows}"
        "### Acceptance Evidence\nnone\n",
    )
    return task


# --- 1. Coverage 命令列回退 ---

def test_manifest_falls_back_to_contract_command(tmp_path: Path) -> None:
    """Coverage 模板无命令列时，从 Contract 的执行命令列注册。"""
    task = _task_file(
        tmp_path,
        "| S-01 | d.md#x | integration | real | TASK-001 | planned |",
        "| 场景ID | 测试层级 | 不得 Mock | 关键断言 | 测试文件 | 命令 | 状态 |\n"
        "|--------|---------|----------|---------|---------|------|------|\n"
        "| S-01 | integration | real | works | tests/t.py | python3 -m pytest -q tests/t.py | planned |\n",
    )
    manifest = extract_manifest(str(task))
    assert manifest["scenarios"][0]["command"] == ["python3", "-m", "pytest", "-q", "tests/t.py"]


def test_coverage_command_column_wins_over_contract(tmp_path: Path) -> None:
    """Coverage 自带第 7 列时优先于 Contract 回退。"""
    task = _task_file(
        tmp_path,
        '| S-01 | d.md#x | integration | real | TASK-001 | planned | ["python3","-c","pass"] |',
        "| 场景ID | 测试层级 | 不得 Mock | 关键断言 | 测试文件 | 命令 | 状态 |\n"
        "|--------|---------|----------|---------|---------|------|------|\n"
        "| S-01 | integration | real | works | tests/t.py | python3 -m pytest -q tests/t.py | planned |\n",
    )
    manifest = extract_manifest(str(task))
    assert manifest["scenarios"][0]["command"] == ["python3", "-c", "pass"]


def test_manifest_without_any_command_still_blocks_execution(tmp_path: Path) -> None:
    """两处都没有命令时保持 fail-closed（执行验收仍阻断）。"""
    task = _task_file(
        tmp_path,
        "| S-01 | d.md#x | integration | real | TASK-001 | planned |",
    )
    manifest = extract_manifest(str(task))
    assert manifest["scenarios"][0]["command"] is None
    target = tmp_path / ".acceptance-manifest.json"
    write_manifest(str(task), str(target))
    result = run_manifest(str(target), str(tmp_path))
    assert result["decision"] == "block"
    assert result.get("error") == "no_executable_scenarios"


# --- 2. 重锁保留运行态 ---

def test_relock_preserves_runtime_state(tmp_path: Path) -> None:
    task = _task_file(
        tmp_path,
        "| S-01 | d.md#x | integration | real | TASK-001 | planned |",
        "| 场景ID | 测试层级 | 不得 Mock | 关键断言 | 测试文件 | 命令 | 状态 |\n"
        "|--------|---------|----------|---------|---------|------|------|\n"
        "| S-01 | integration | real | works | tests/t.py | python3 -c pass | planned |\n",
    )
    target = tmp_path / ".acceptance-manifest.json"
    write_manifest(str(task), str(target))
    data = json.loads(target.read_text(encoding="utf-8"))
    row = data["scenarios"][0]
    row["status"] = "verified"
    row["revision"] = 3
    row["evidence"] = {"id": "S-01", "status": "passed", "exit_code": 0}
    row["runs"] = [{"id": "S-01", "status": "passed"}]
    target.write_text(json.dumps(data), encoding="utf-8")

    write_manifest(str(task), str(target))

    again = json.loads(target.read_text(encoding="utf-8"))["scenarios"][0]
    assert again["status"] == "verified"
    assert again["revision"] == 3
    assert again["evidence"]["exit_code"] == 0
    assert again["runs"] == [{"id": "S-01", "status": "passed"}]
    assert validate_manifest(str(task), str(target)) == (True, "")


def test_relock_after_task_edit_drops_stale_evidence(tmp_path: Path) -> None:
    """任务事实变化（作用域漂移）时重锁必须丢弃旧证据。"""
    task = _task_file(
        tmp_path,
        "| S-01 | d.md#x | integration | real | TASK-001 | planned |",
        "| 场景ID | 测试层级 | 不得 Mock | 关键断言 | 测试文件 | 命令 | 状态 |\n"
        "|--------|---------|----------|---------|---------|------|------|\n"
        "| S-01 | integration | real | works | tests/t.py | python3 -c pass | planned |\n",
    )
    target = tmp_path / ".acceptance-manifest.json"
    write_manifest(str(task), str(target))
    data = json.loads(target.read_text(encoding="utf-8"))
    data["scenarios"][0]["evidence"] = {"id": "S-01", "status": "passed", "exit_code": 0}
    data["scenarios"][0]["status"] = "verified"
    target.write_text(json.dumps(data), encoding="utf-8")

    text = task.read_text(encoding="utf-8").replace("| real | TASK-001 |", "| changed | TASK-001 |")
    task.write_text(text, encoding="utf-8")

    write_manifest(str(task), str(target))
    again = json.loads(target.read_text(encoding="utf-8"))["scenarios"][0]
    assert again.get("evidence") is None
    assert again["status"] == "planned"


# --- 3. 无自有场景 TASK ---

def test_owner_without_own_scenarios_passes(tmp_path: Path) -> None:
    manifest = tmp_path / "m.json"
    manifest.write_text(json.dumps({
        "scenarios": [
            {"id": "S-01", "kind": "functional", "owner": "TASK-001",
             "command": ["python3", "-c", "pass"], "cwd": ".", "timeout": 10, "depends_on": []},
        ]
    }), encoding="utf-8")
    result = run_manifest(str(manifest), str(tmp_path), owner="TASK-002")
    assert result["decision"] == "pass"
    assert result["reason"] == "no_owned_scenarios"


def test_owner_filtered_zero_executable_legacy_ownerless_still_blocks(tmp_path: Path) -> None:
    """无 owner 的旧场景不享受 no_owned_scenarios 放行。"""
    manifest = tmp_path / "m.json"
    manifest.write_text(json.dumps({
        "scenarios": [
            {"id": "S-01", "kind": "functional", "command": None, "cwd": ".", "timeout": 10},
        ]
    }), encoding="utf-8")
    result = run_manifest(str(manifest), str(tmp_path), owner="TASK-002")
    assert result["decision"] == "block"


# --- 4. E2E deferral 不降级 verified ---

def test_e2e_deferred_does_not_downgrade_verified(tmp_path: Path) -> None:
    manifest = tmp_path / "m.json"
    data = {
        "scenarios": [
            {"id": "E-01", "kind": "e2e", "owner": "TASK-001", "command": ["python3", "-c", "pass"],
             "cwd": ".", "timeout": 10, "depends_on": [], "status": "verified",
             "evidence": {"id": "E-01", "status": "passed", "exit_code": 0}, "revision": 2},
        ]
    }
    manifest.write_text(json.dumps(data), encoding="utf-8")
    persist_results(manifest, data, [{"id": "E-01", "kind": "e2e", "status": "e2e_deferred"}])
    row = json.loads(manifest.read_text(encoding="utf-8"))["scenarios"][0]
    assert row["status"] == "verified"
    assert row["evidence"]["exit_code"] == 0
    assert row["revision"] == 2


def test_e2e_deferred_still_recorded_before_verification(tmp_path: Path) -> None:
    manifest = tmp_path / "m2.json"
    data = {
        "scenarios": [
            {"id": "E-01", "kind": "e2e", "owner": "TASK-001", "command": ["python3", "-c", "pass"],
             "cwd": ".", "timeout": 10, "depends_on": [], "status": "planned"},
        ]
    }
    manifest.write_text(json.dumps(data), encoding="utf-8")
    persist_results(manifest, data, [{"id": "E-01", "kind": "e2e", "status": "e2e_deferred"}])
    row = json.loads(manifest.read_text(encoding="utf-8"))["scenarios"][0]
    assert row["status"] == "e2e_deferred"


def test_ownerless_scenario_without_coverage_not_written_to_first_task(tmp_path: Path) -> None:
    """无 owner 且无 Coverage 表的旧场景不得写入第一个 TASK 段。"""
    from cf_acceptance_evidence import sync_task_evidence

    task = tmp_path / "task.md"
    task.write_text(
        "# Tasks\n\n## TASK-001: A\n- **Status**: done\n"
        "### Acceptance Contract\n| S-01 | verified |\n"
        "### Acceptance Evidence\n| S-01 | x |\n\n"
        "## TASK-002: B\n- **Status**: done\n"
        "### Acceptance Contract\n| S-02 | verified |\n"
        "### Acceptance Evidence\n| S-02 | x |\n",
        encoding="utf-8",
    )
    outcome = sync_task_evidence(task, "S-99", "runner", "x", "", "verified")
    assert outcome == "skipped_no_owner"
    assert "S-99" not in task.read_text(encoding="utf-8")


def test_ownerless_scenario_with_coverage_updates_only_coverage(tmp_path: Path) -> None:
    from cf_acceptance_evidence import sync_task_evidence

    task = tmp_path / "task.md"
    task.write_text(
        "# Tasks\n\n## Acceptance Coverage\n"
        "| 场景ID | 来源设计 | 测试层级 | 关键真实边界 | 负责任务 | 状态 |\n"
        "|--------|---------|---------|-------------|---------|------|\n"
        "| S-09 | d.md#x | integration | real | | planned |\n\n"
        "## TASK-001: A\n- **Status**: done\n### Acceptance Contract\nx\n### Acceptance Evidence\nx\n",
        encoding="utf-8",
    )
    outcome = sync_task_evidence(task, "S-09", "runner", "passed", "", "verified")
    assert outcome == "synced"
    text = task.read_text(encoding="utf-8")
    assert "| S-09 | d.md#x | integration | real | | verified |" in text
    # 不写入 TASK-001 段
    assert "S-09: verified" not in text


# --- 5. 跨需求 bind 不污染 marker ---

def test_resync_active_hash_ignores_other_task_dir(tmp_path: Path) -> None:
    root = tmp_path
    marker_dir = root / ".code-flow/.active-task.json"
    active = {
        "version": 1, "task_dir": str(root / ".code-flow/tasks/a"), "task_id": "TASK-001",
        "status": "active", "context_sha256": "a" * 64,
        "baseline": {"head": None, "last_seen_head": None, "captured_at": "t", "preexisting_changes": {}},
        "owned_paths": [], "excluded_paths": [],
    }
    _write(marker_dir, json.dumps(active))
    # 其他需求：不得改写
    assert resync_active_hash(str(root), str(root / ".code-flow/tasks/b"), "b" * 64) is False
    assert load_active_task(str(root)).context_sha256 == "a" * 64
    # 本需求：允许
    assert resync_active_hash(str(root), str(root / ".code-flow/tasks/a"), "c" * 64) is True
    assert load_active_task(str(root)).context_sha256 == "c" * 64


# --- 6. decision 返回目标 rule 状态 ---

def _manual_rule(ref: str) -> RuleBinding:
    return RuleBinding(
        ref=ref, summary="s", text_sha256="t" * 8, enforcement="required",
        verifier_ref=f"spec#{ref}", verifier_stage="plan",
        stage_status={"plan": RuleStageStatus(status="pending", refs=(), decision=None, evidence=())},
    )


def test_update_rule_cheap_skip_is_idempotent() -> None:
    rule = _manual_rule("RULE-a-001")
    evidence = {
        "verifier_ref": "spec#RULE-a-001", "executed_at": "t", "status": "unverified",
        "rule_text_sha256": rule.text_sha256, "artifact_sha256": None,
        "diff_sha256": "deadbeef", "result_sha256": "r1",
        "error_code": "skipped_in_cheap_gate", "details": {"skipped": True},
    }
    updated = rule
    for _ in range(4):
        updated = _update_rule(updated, evidence)
    assert len(updated.stage_status["plan"].evidence) == 1
    # 普通证据仍按 diff 去重（相同则幂等，不同则追加）
    normal = dict(evidence, error_code=None, result_sha256="r2")
    updated = _update_rule(updated, normal)
    updated = _update_rule(updated, normal)
    assert len(updated.stage_status["plan"].evidence) == 2


# --- 7. Stop hook 注解层级复用 _kind 已在 test_cf_stop_hook 中直测 ---


def test_stop_hook_annotated_e2e_level_not_false_blocked() -> None:
    """带注解的 E2E 层级（E2E（Playwright））与 manifest _kind 判定一致。"""
    from cf_stop_hook import _acceptance_gap

    section = (
        "## TASK-001: demo\n- **Status**: done\n- **Acceptance-Refs**: S-01\n"
        "### Acceptance Contract\n"
        "| S-01 | integration | real | works | tests/x.py | c | e2e_deferred |\n"
        "### Acceptance Evidence\n| S-01 | x | e2e_deferred |\n"
    )
    coverage = (
        "## Acceptance Coverage\n"
        "| S-01 | d.md#x | E2E（Playwright） | real | TASK-001 | e2e_deferred |\n"
    )
    assert _acceptance_gap("TASK-001", section, coverage) == ""


def test_stop_hook_annotated_manual_level_not_false_blocked() -> None:
    from cf_stop_hook import _acceptance_gap

    section = (
        "## TASK-001: demo\n- **Status**: done\n- **Acceptance-Refs**: S-01\n"
        "### Acceptance Contract\n"
        "| S-01 | integration | real | works | x | c | manual_pending |\n"
        "### Acceptance Evidence\n| S-01 | x | manual_pending |\n"
    )
    coverage = (
        "## Acceptance Coverage\n"
        "| S-01 | d.md#x | manual(chrome) | real | TASK-001 | manual_pending |\n"
    )
    assert _acceptance_gap("TASK-001", section, coverage) == ""


# --- 8. start direct-run 错误传播 ---

def test_start_missing_context_reports_stable_code(tmp_path: Path) -> None:
    """start 直接脚本运行时，缺失 context 应返回 context_missing 而非 internal_error。"""
    import subprocess

    root = tmp_path
    (root / "src").mkdir()
    _write(root / "src/app.py", "VALUE = 1\n")
    _write(
        root / ".code-flow/config.yml",
        "version: 1\npath_mapping: {}\n",
    )
    task = root / ".code-flow/tasks/demo/work.md"
    _write(
        task,
        "## TASK-001: Demo\n- **Status**: draft\n- **Acceptance-Refs**: N/A\n"
        "### Checklist\n- [ ] x\n### Log\n- [2026-01-01] created (draft)\n",
    )
    for args in (("init", "-q"),):
        subprocess.run(("git", *args), cwd=root, capture_output=True)
    subprocess.run(("git", "add", "-A"), cwd=root, capture_output=True)
    subprocess.run(("git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "x"),
                   cwd=root, capture_output=True)

    cli = Path(__file__).resolve().parents[1] / ".code-flow/scripts/cf_spec_context.py"
    result = subprocess.run(
        [sys.executable, str(cli), "start", "--task-dir", ".code-flow/tasks/demo",
         "--root", str(root), "--task", "TASK-001",
         "--task-file", ".code-flow/tasks/demo/work.md", "--json"],
        input='{"owned_paths": []}', text=True, cwd=root, capture_output=True,
    )
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert payload["error"]["code"] == "context_missing", payload
    assert result.returncode == 3


def test_start_missing_context_direct_script_never_internal_error(tmp_path: Path) -> None:
    """直接脚本运行（__main__ 双模块）也不得把 Contract 错误吞成 internal_error。"""
    import subprocess

    # 损坏的 context：load_context 抛 ContextError（副本类），必须结构化返回。
    root = tmp_path
    (root / "src").mkdir()
    _write(root / "src/app.py", "VALUE = 1\n")
    _write(root / ".code-flow/config.yml", "version: 1\npath_mapping: {}\n")
    _write(root / ".code-flow/tasks/demo/spec-context.yml", "not: [valid yaml\n")
    _write(
        root / ".code-flow/tasks/demo/work.md",
        "## TASK-001: Demo\n- **Status**: draft\n- **Acceptance-Refs**: N/A\n"
        "### Checklist\n- [ ] x\n### Log\n- [2026-01-01] created (draft)\n",
    )
    subprocess.run(("git", "init", "-q"), cwd=root, capture_output=True)
    subprocess.run(("git", "add", "-A"), cwd=root, capture_output=True)
    subprocess.run(("git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "x"),
                   cwd=root, capture_output=True)

    cli = Path(__file__).resolve().parents[1] / ".code-flow/scripts/cf_spec_context.py"
    result = subprocess.run(
        [sys.executable, str(cli), "start", "--task-dir", ".code-flow/tasks/demo",
         "--root", str(root), "--task", "TASK-001",
         "--task-file", ".code-flow/tasks/demo/work.md", "--json"],
        input='{"owned_paths": []}', text=True, cwd=root, capture_output=True,
    )
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert payload["error"]["code"] != "internal_error", payload
    assert result.returncode == 3


# --- 9. validation 范围排除工具托管目录 ---

def test_validation_scope_excludes_managed_trees(tmp_path: Path) -> None:
    from cf_validation import validation_scope

    _write(tmp_path / "src/app.py", "x = 1\n")
    _write(tmp_path / ".opencode/plugins/code-flow/index.js", "export default {}\n")
    _write(tmp_path / ".claude/commands/cf-init.md", "doc\n")
    scope = validation_scope(str(tmp_path), (
        "src/app.py", ".opencode/plugins/code-flow/index.js", ".claude/commands/cf-init.md",
    ))
    assert scope == ("src/app.py",)


def test_validation_scope_git_changes_excludes_managed(tmp_path: Path) -> None:
    import subprocess

    from cf_validation import validation_scope

    root = tmp_path
    _write(root / ".opencode/plugins/code-flow/index.js", "export default {}\n")
    _write(root / "app.js", "console.log(1)\n")
    subprocess.run(("git", "init", "-q"), cwd=root, capture_output=True)
    subprocess.run(("git", "add", "-A"), cwd=root, capture_output=True)
    subprocess.run(("git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "x"),
                   cwd=root, capture_output=True)
    _write(root / ".opencode/plugins/code-flow/index.js", "export default { v: 2 }\n")
    _write(root / "app.js", "console.log(2)\n")
    scope = validation_scope(str(root))
    assert "app.js" in scope
    assert all(not item.startswith(".opencode/") for item in scope)


# --- 10. validator skip_if_missing ---

def test_validator_skip_if_missing_does_not_block(tmp_path: Path) -> None:
    from cf_stop_hook import run_validators

    _write(tmp_path / "src/app.py", "x = 1\n")
    validator = {
        "name": "mypy", "trigger": "**/*.py",
        "command": "python3 -m module_that_does_not_exist_xyz {files}",
        "timeout": 30000, "skip_if_missing": True,
    }
    failures, truncated, _ = run_validators(
        str(tmp_path), [validator], ["src/app.py"], "s1", total_budget=10.0,
    )
    assert failures == [] and truncated is False


def test_validator_without_skip_if_missing_still_fails(tmp_path: Path) -> None:
    from cf_stop_hook import run_validators

    _write(tmp_path / "src/app.py", "x = 1\n")
    validator = {
        "name": "mypy", "trigger": "**/*.py",
        "command": "python3 -m module_that_does_not_exist_xyz {files}",
        "timeout": 30000,
    }
    failures, _truncated, _ = run_validators(
        str(tmp_path), [validator], ["src/app.py"], "s1", total_budget=10.0,
    )
    assert len(failures) == 1


# --- 11. session 状态缺字段不崩溃 ---

def test_session_reminder_legacy_state_without_next_remind_at(tmp_path: Path) -> None:
    from cf_user_prompt_hook import _session_reminder

    root = tmp_path
    _write(root / ".code-flow/config.yml",
           "version: 1\nquality_loop:\n  enabled: true\n  compress_reminder: true\n")
    _write(root / ".code-flow/.session-state.json",
           json.dumps({"session_id": "s1", "prompt_count": 24}))
    # 不得抛 KeyError；旧状态正常推进
    reminder = _session_reminder(str(root), "s1")
    assert isinstance(reminder, str)
    state = json.loads((root / ".code-flow/.session-state.json").read_text(encoding="utf-8"))
    assert state["prompt_count"] == 25


# --- 12. 模板命令列 schema ---

def test_plan_templates_document_coverage_command_column() -> None:
    """四平台 plan 模板必须给出 Coverage 命令列，避免新需求 finish 必卡。"""
    root = Path(__file__).resolve().parents[1]
    templates = (
        "src/adapters/claude/commands/cf-task/plan.md",
        "src/adapters/costrict/commands/cf-task/plan.md",
        "src/adapters/opencode/commands/cf-task/plan.md",
        "src/adapters/codex/skills/cf-task-plan/SKILL.md",
    )
    for rel in templates:
        text = (root / rel).read_text(encoding="utf-8")
        assert "| 场景ID | 来源设计 | 测试层级 | 关键真实边界 | 负责任务 | 状态 | 执行命令 |" in text, rel
        assert "argv JSON" in text, rel


def test_archive_templates_document_working_verify_plan_command() -> None:
    """archive 模板的 verify-plan 调用必须带 --task-dir（照抄可执行）。"""
    root = Path(__file__).resolve().parents[1]
    templates = (
        "src/adapters/claude/commands/cf-task/archive.md",
        "src/adapters/costrict/commands/cf-task/archive.md",
        "src/adapters/opencode/commands/cf-task/archive.md",
        "src/adapters/codex/skills/cf-task-archive/SKILL.md",
    )
    for rel in templates:
        text = (root / rel).read_text(encoding="utf-8")
        assert "--verify-plan --task-dir" in text, rel
        assert "--output \"<需求目录>/.acceptance-manifest.json\" --verify-plan" not in text, rel
