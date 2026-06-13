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


def test_unmatched_trigger_skipped():
    with tempfile.TemporaryDirectory() as root:
        _make_project(root, [dict(FAIL_V, trigger="**/*.go")])
        cf_log.append_event(root, "edit", {"file": "src/a.py", "tool": "Edit"}, "s1")
        assert _run(root) == {}
