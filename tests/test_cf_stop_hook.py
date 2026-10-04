#!/usr/bin/env python3
"""Tests for cf_stop_hook.py — Stop 收尾守门 (TASK-010).

Scenarios:
- S-05 失败校验 → decision=block + on_fail 提示；全过 → 静默
- E-05 无 validation.yml → 静默；无 edit 事件 → 静默
- stop_hook_active → 静默（防循环）；开关关闭 → 静默
- trigger brace glob 展开与 **/ 根文件匹配
- stop_check 事件落日志；命令不可用 → degrade 跳过
"""
import io
import json
import os
import sys
import tempfile
import unittest.mock as mock

import yaml

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "core", "code-flow", "scripts"))
import cf_log
import cf_stop_hook
from cf_stop_hook import expand_braces, trigger_matches


def test_expand_braces():
    assert expand_braces("**/*.{ts,tsx}") == ["**/*.ts", "**/*.tsx"]
    assert expand_braces("**/*.py") == ["**/*.py"]


def test_malformed_stdin_degrades_silently():
    """坏 JSON 不能变成 block（否则同一坏输入会反复循环阻断）。"""
    with tempfile.TemporaryDirectory() as root:
        _make_project(root, [PASS_V])
        with mock.patch("sys.stdin", io.StringIO("{not json")), \
                mock.patch("sys.stdout", io.StringIO()) as out, \
                mock.patch("os.getcwd", return_value=root):
            cf_stop_hook.main()
        assert out.getvalue() == ""


def test_early_failure_still_blocks_in_required_mode():
    """config 解析前的异常也必须 fail-closed（旧实现依赖 locals() 探测会静默）。"""
    with tempfile.TemporaryDirectory() as root:
        _make_project(root, [PASS_V])
        with mock.patch("sys.stdin", io.StringIO('{"session_id": "s1"}')), \
                mock.patch("sys.stdout", io.StringIO()) as out, \
                mock.patch("os.getcwd", return_value=root), \
                mock.patch("cf_stop_hook.load_config", side_effect=RuntimeError("boom")):
            cf_stop_hook.main()
        payload = json.loads(out.getvalue())
        assert payload["decision"] == "block"
        assert "SPEC_WORKFLOW_BLOCKED" in payload["reason"]


def test_trigger_matches_root_and_nested():
    assert trigger_matches("**/*.py", "src/a.py")
    assert trigger_matches("**/*.py", "a.py")          # **/ 根文件兜底
    assert trigger_matches("**/*.{ts,tsx}", "src/x.tsx")
    assert not trigger_matches("**/*.py", "a.md")


def _make_project(root: str, validators: list, ql: bool = True) -> None:
    os.makedirs(os.path.join(root, ".code-flow"), exist_ok=True)
    config = {"quality_loop": {"enabled": ql}, "path_mapping": {}}
    with open(os.path.join(root, ".code-flow", "config.yml"), "w") as f:
        yaml.dump(config, f)
    if validators is not None:
        with open(os.path.join(root, ".code-flow", "validation.yml"), "w") as f:
            yaml.dump({"validators": validators}, f)


def _run(root: str, sid: str = "s1", stop_active: bool = False) -> dict:
    payload = {"session_id": sid}
    if stop_active:
        payload["stop_hook_active"] = True
    with mock.patch("sys.stdin", io.StringIO(json.dumps(payload))), \
            mock.patch("sys.stdout", io.StringIO()) as out, \
            mock.patch("os.getcwd", return_value=root):
        cf_stop_hook.main()
    text = out.getvalue()
    return json.loads(text) if text.strip() else {}

PASS_V = {"name": "总是通过", "trigger": "**/*.py",
          "command": "python3 -c 'pass'", "timeout": 5000, "on_fail": "n/a"}
FAIL_V = {"name": "总是失败", "trigger": "**/*.py",
          "command": "python3 -c 'import sys; sys.exit(1)'",
          "timeout": 5000, "on_fail": "去修"}


def test_failed_validator_blocks_with_reason():
    with tempfile.TemporaryDirectory() as root:
        _make_project(root, [PASS_V, FAIL_V])
        cf_log.append_event(root, "edit", {"file": "src/a.py", "tool": "Edit"}, "s1")
        result = _run(root)
        assert result["decision"] == "block"
        assert "总是失败" in result["reason"]
        assert "去修" in result["reason"]
        checks = cf_log.read_events(root, events=("stop_check",))
        assert {c["data"]["passed"] for c in checks} == {True, False}


def test_all_pass_silent():
    with tempfile.TemporaryDirectory() as root:
        _make_project(root, [PASS_V])
        cf_log.append_event(root, "edit", {"file": "src/a.py", "tool": "Edit"}, "s1")
        assert _run(root) == {}


def test_no_validation_yml_silent_e05():
    with tempfile.TemporaryDirectory() as root:
        _make_project(root, None)
        cf_log.append_event(root, "edit", {"file": "src/a.py", "tool": "Edit"}, "s1")
        assert _run(root) == {}


def test_no_session_edits_silent():
    with tempfile.TemporaryDirectory() as root:
        _make_project(root, [FAIL_V])
        cf_log.append_event(root, "edit", {"file": "src/a.py", "tool": "Edit"}, "other-session")
        assert _run(root, sid="s1") == {}


def test_stop_hook_active_silent():
    with tempfile.TemporaryDirectory() as root:
        _make_project(root, [FAIL_V])
        cf_log.append_event(root, "edit", {"file": "src/a.py", "tool": "Edit"}, "s1")
        assert _run(root, stop_active=True) == {}


def test_quality_loop_off_silent():
    with tempfile.TemporaryDirectory() as root:
        _make_project(root, [FAIL_V], ql=False)
        cf_log.append_event(root, "edit", {"file": "src/a.py", "tool": "Edit"}, "s1")
        assert _run(root) == {}


def test_worktree_internal_edits_do_not_trigger_validators():
    """并行子 agent 的 worktree 内编辑不得触发主工作区 validators。"""
    with tempfile.TemporaryDirectory() as root:
        _make_project(root, [FAIL_V])
        cf_log.append_event(
            root, "edit",
            {"file": ".code-flow/worktrees/run-1/TASK-001/src/a.py", "tool": "Edit"},
            "s1",
        )
        assert _run(root) == {}


def test_stop_hook_uses_cheap_done_gate():
    """Stop 阶段必须走 cheap 门禁：不执行命令类 verifier / acceptance 场景。"""
    with tempfile.TemporaryDirectory() as root:
        _make_project(root, None)
        marker = os.path.join(root, ".code-flow", ".active-task.json")
        with open(marker, "w", encoding="utf-8") as f:
            f.write("{}")
        fake = mock.Mock(decision="pass", message="", evidence=(), files=[])
        with mock.patch("cf_stop_hook.load_active_task", return_value=mock.Mock(task_dir=".code-flow/tasks/demo")), \
                mock.patch("cf_stop_hook.run_done_gate", return_value=fake) as gate:
            payload = {"session_id": "s1"}
            with mock.patch("sys.stdin", io.StringIO(json.dumps(payload))), \
                    mock.patch("sys.stdout", io.StringIO()) as out, \
                    mock.patch("os.getcwd", return_value=root):
                cf_stop_hook.main()
        gate.assert_called_once()
        assert gate.call_args.kwargs.get("cheap") is True
        assert out.getvalue() == ""


def test_heavy_validator_skipped_on_stop_but_run_by_validate():
    """heavy 全量测试只在 /cf-validate 执行，Stop 每轮跳过。"""
    with tempfile.TemporaryDirectory() as root:
        _make_project(root, [dict(FAIL_V, heavy=True)])
        cf_log.append_event(root, "edit", {"file": "src/a.py", "tool": "Edit"}, "s1")
        assert _run(root) == {}
        from cf_validation import validate_files
        result = validate_files(root, ["src/a.py"])
        assert result["decision"] == "block", "cf-validate 必须仍然执行 heavy validator"


def test_manual_run_without_pipe_exits_immediately():
    """交互式手动运行（无 stdin 管道）必须立即退出，不得阻塞读取 stdin。"""

    class _Tty:
        def isatty(self):
            return True

        def read(self):
            raise AssertionError("tty 下不得读取 stdin")

    with mock.patch("sys.stdin", _Tty()), \
            mock.patch("sys.stdout", io.StringIO()), \
            mock.patch("sys.stderr", io.StringIO()):
        cf_stop_hook.main()


def _git_init(root: str) -> None:
    import subprocess
    subprocess.run(("git", "init", "-q"), cwd=root, check=True)
    subprocess.run(("git", "config", "user.email", "t@t"), cwd=root, check=True)
    subprocess.run(("git", "config", "user.name", "t"), cwd=root, check=True)
    subprocess.run(("git", "add", "-A"), cwd=root, check=True)
    subprocess.run(("git", "commit", "-qm", "init"), cwd=root, check=True)


def _counter_validator(counter: str, fail: bool = False) -> dict:
    if fail:
        command = f"python3 -c \"open('{counter}', 'a').write('x'); import sys; sys.exit(1)\""
    else:
        command = f"python3 -c \"open('{counter}', 'a').write('x')\""
    return {"name": "计数", "trigger": "**/*.py", "command": command,
            "timeout": 5000, "on_fail": "n/a"}


def test_validator_cache_reuses_unchanged_content():
    """内容未变 → 复用（不执行）；.code-flow 写入与提交同一内容都不失效；内容变化 → 重跑。"""
    with tempfile.TemporaryDirectory() as root:
        counter = os.path.join(root, "runs.txt")
        _make_project(root, [_counter_validator(counter)])
        os.makedirs(os.path.join(root, "src"), exist_ok=True)
        with open(os.path.join(root, "src", "a.py"), "w") as f:
            f.write("a = 1\n")
        _git_init(root)
        from cf_validation import validate_files

        first = validate_files(root, ["src/a.py"])
        assert first["decision"] == "pass" and first["reused"] == 0
        with open(counter) as f:
            assert f.read() == "x"

        second = validate_files(root, ["src/a.py"])
        assert second["decision"] == "pass" and second["reused"] == 1
        with open(counter) as f:
            assert f.read() == "x", "命中缓存不得执行命令"

        with open(os.path.join(root, ".code-flow", "state.json"), "w") as f:
            f.write("{}\n")
        third = validate_files(root, ["src/a.py"])
        assert third["reused"] == 1, ".code-flow 运行时写入不得使缓存失效"

        with open(os.path.join(root, "src", "a.py"), "a") as f:
            f.write("b = 2\n")
        changed = validate_files(root, ["src/a.py"])
        assert changed["reused"] == 0
        with open(counter) as f:
            assert f.read() == "xx", "内容变化必须重跑"

        import subprocess
        subprocess.run(("git", "add", "src/a.py"), cwd=root, check=True)
        subprocess.run(("git", "commit", "-qm", "change"), cwd=root, check=True)
        committed = validate_files(root, ["src/a.py"])
        assert committed["reused"] == 1, "提交同一内容不得使缓存失效"


def test_validator_failure_never_cached():
    """失败结果不入缓存：下一次仍必须真实执行。"""
    with tempfile.TemporaryDirectory() as root:
        counter = os.path.join(root, "runs.txt")
        _make_project(root, [_counter_validator(counter, fail=True)])
        os.makedirs(os.path.join(root, "src"), exist_ok=True)
        with open(os.path.join(root, "src", "a.py"), "w") as f:
            f.write("a = 1\n")
        _git_init(root)
        from cf_validation import validate_files

        first = validate_files(root, ["src/a.py"])
        second = validate_files(root, ["src/a.py"])

        assert first["decision"] == "block" and second["decision"] == "block"
        with open(counter) as f:
            assert f.read() == "xx", "失败结果必须每次真实执行"


def test_unmatched_trigger_skipped():
    with tempfile.TemporaryDirectory() as root:
        _make_project(root, [dict(FAIL_V, trigger="**/*.go")])
        cf_log.append_event(root, "edit", {"file": "src/a.py", "tool": "Edit"}, "s1")
        assert _run(root) == {}


def _write_task(root: str, body: str) -> str:
    rel_path = ".code-flow/tasks/2026-07-14/demo/demo.md"
    path = os.path.join(root, rel_path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(body)
    return rel_path


def _acceptance_task(status: str, acceptance_status: str) -> str:
    return f"""# Tasks: demo

## Acceptance Coverage

| 场景ID | 状态 |
| S-01 | {acceptance_status} |

## TASK-001: demo

- **Status**: {status}
- **Acceptance-Refs**: S-01, RULE-01

### Acceptance Contract

| 场景ID | 测试 | 状态 |
| S-01 | tests/test_demo.py::test_s01 | {acceptance_status} |

### Acceptance Evidence

| 场景ID | GREEN | 状态 |
| S-01 | pass | {acceptance_status} |
"""


def test_done_task_with_pending_acceptance_blocks_without_validators() -> None:
    with tempfile.TemporaryDirectory() as root:
        _make_project(root, None)
        rel_path = _write_task(root, _acceptance_task("done", "pending"))
        cf_log.append_event(root, "edit", {"file": rel_path, "tool": "Edit"}, "s1")

        result = _run(root)

        assert result["decision"] == "block"
        assert "任务验收契约" in result["reason"]
        assert "planned/pending/TBD" in result["reason"]


def test_done_task_with_verified_acceptance_is_silent() -> None:
    with tempfile.TemporaryDirectory() as root:
        _make_project(root, None)
        rel_path = _write_task(root, _acceptance_task("done", "verified"))
        cf_log.append_event(root, "edit", {"file": rel_path, "tool": "Edit"}, "s1")

        assert _run(root) == {}


def test_in_progress_task_may_pause_with_pending_acceptance() -> None:
    with tempfile.TemporaryDirectory() as root:
        _make_project(root, None)
        rel_path = _write_task(root, _acceptance_task("in-progress", "pending"))
        cf_log.append_event(root, "edit", {"file": rel_path, "tool": "Edit"}, "s1")

        assert _run(root) == {}


def test_legacy_task_without_acceptance_coverage_is_silent() -> None:
    with tempfile.TemporaryDirectory() as root:
        _make_project(root, None)
        rel_path = _write_task(
            root,
            "# Tasks: legacy\n\n## TASK-001: demo\n\n- **Status**: done\n",
        )
        cf_log.append_event(root, "edit", {"file": rel_path, "tool": "Edit"}, "s1")

        assert _run(root) == {}


def _make_project_enforcement(root: str, validators: list, enforcement: str) -> None:
    os.makedirs(os.path.join(root, ".code-flow"), exist_ok=True)
    config = {
        "spec_workflow": {"schema_version": 1, "enforcement": enforcement},
        "quality_loop": {"enabled": True},
        "path_mapping": {},
    }
    with open(os.path.join(root, ".code-flow", "config.yml"), "w") as f:
        yaml.dump(config, f)
    with open(os.path.join(root, ".code-flow", "validation.yml"), "w") as f:
        yaml.dump({"validators": validators}, f)


def test_inject_mode_never_blocks_stop():
    with tempfile.TemporaryDirectory() as root:
        _make_project_enforcement(root, [FAIL_V], "inject")
        cf_log.append_event(root, "edit", {"file": "src/a.py", "tool": "Edit"}, "s1")
        assert _run(root) == {}


def test_warn_mode_logs_failures_without_blocking():
    with tempfile.TemporaryDirectory() as root:
        _make_project_enforcement(root, [FAIL_V], "warn")
        cf_log.append_event(root, "edit", {"file": "src/a.py", "tool": "Edit"}, "s1")
        result = _run(root)
        assert result == {}
        checks = cf_log.read_events(root, events=("stop_check",))
        assert checks and checks[-1]["data"].get("nonfatal") is True
        assert "总是失败" in checks[-1]["data"]["failures"]


def test_required_mode_still_blocks_stop():
    with tempfile.TemporaryDirectory() as root:
        _make_project_enforcement(root, [FAIL_V], "required")
        cf_log.append_event(root, "edit", {"file": "src/a.py", "tool": "Edit"}, "s1")
        result = _run(root)
        assert result["decision"] == "block"
