#!/usr/bin/env python3
"""Tests for cf_post_hook.py — PostToolUse 合规反馈 (TASK-007).

Scenarios:
- S-01 违规反馈：写入含 print() 的文件 → additionalContext 含 message/规则/误报提示
- 违规事件落日志 + hit_count 递增（S-02 数据链路）
- 同 check 同文件会话内只报一次（RISK-05）；新会话重置
- disabled check 不报（与 cf_feedback 闭环）
- E-07 spec checks 损坏 → 静默；开关关闭 → 静默；非代码文件 → 静默
- 协议：无违规时无 stdout；输出恒为合法 JSON
"""
import io
import json
import os
import sys
import tempfile
import unittest.mock as mock

import yaml

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "core", "code-flow", "scripts"))
import cf_checks
import cf_log
import cf_post_hook

SPEC_WITH_CHECKS = """---
description: 测试规范
checks:
  - id: no-print-debug
    type: regex
    pattern: 'print\\('
    files: "**/*.py"
    message: 禁止 print() 调试，用 _log() 到 stderr
---

# Standards
- 禁止 print() 调试
"""


def _make_project(root: str, spec_content: str = SPEC_WITH_CHECKS, ql: bool = True) -> None:
    specs = os.path.join(root, ".code-flow", "specs", "scripts")
    os.makedirs(specs)
    with open(os.path.join(specs, "code-standards.md"), "w", encoding="utf-8") as f:
        f.write(spec_content)
    config = {
        "inject": {"auto": True, "code_extensions": [".py"]},
        "quality_loop": {"enabled": ql},
        "path_mapping": {"scripts": {"patterns": ["src/*.py"], "specs": [
            {"path": "scripts/code-standards.md", "tags": ["core"], "tier": 1},
        ]}},
    }
    with open(os.path.join(root, ".code-flow", "config.yml"), "w") as f:
        yaml.dump(config, f)


def _write_target(root: str, rel: str, content: str) -> None:
    path = os.path.join(root, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


def _run(root: str, rel: str = "src/app.py", sid: str = "s1") -> dict:
    stdin_data = json.dumps({
        "tool_name": "Edit",
        "tool_input": {"file_path": rel},
        "session_id": sid,
    })
    with mock.patch("sys.stdin", io.StringIO(stdin_data)), \
            mock.patch("sys.stdout", io.StringIO()) as out, \
            mock.patch("os.getcwd", return_value=root):
        cf_post_hook.main()
    text = out.getvalue()
    return json.loads(text) if text.strip() else {}


def test_violation_feedback_s01():
    with tempfile.TemporaryDirectory() as root:
        _make_project(root)
        _write_target(root, "src/app.py", "x = 1\nprint('debug')\n")
        result = _run(root)
        ctx = result["hookSpecificOutput"]["additionalContext"]
        assert result["hookSpecificOutput"]["hookEventName"] == "PostToolUse"
        assert "禁止 print() 调试" in ctx
        assert "scripts/code-standards.md#no-print-debug" in ctx
        assert "误报" in ctx
        assert "违规行 2" in ctx


def test_violation_event_and_hit_count():
    with tempfile.TemporaryDirectory() as root:
        _make_project(root)
        _write_target(root, "src/app.py", "print('x')\n")
        _run(root)
        events = cf_log.read_events(root, events=("violation",))
        assert events and events[0]["data"]["check_id"] == "no-print-debug"
        state = cf_checks.load_check_state(root)
        assert state["no-print-debug"]["hit_count"] == 1


def test_same_check_same_file_reported_once_per_session():
    with tempfile.TemporaryDirectory() as root:
        _make_project(root)
        _write_target(root, "src/app.py", "print('x')\n")
        first = _run(root, sid="s1")
        assert first != {}
        second = _run(root, sid="s1")
        assert second == {}            # 会话内去重
        third = _run(root, sid="s2")
        assert third != {}             # 新会话重置


def test_disabled_check_not_reported():
    with tempfile.TemporaryDirectory() as root:
        _make_project(root)
        _write_target(root, "src/app.py", "print('x')\n")
        cf_checks.save_check_state(root, {"no-print-debug": {"disabled": True}})
        assert _run(root) == {}


def test_clean_file_silent():
    with tempfile.TemporaryDirectory() as root:
        _make_project(root)
        _write_target(root, "src/app.py", "x = 1\n")
        assert _run(root) == {}


def test_quality_loop_disabled_silent():
    with tempfile.TemporaryDirectory() as root:
        _make_project(root, ql=False)
        _write_target(root, "src/app.py", "print('x')\n")
        assert _run(root) == {}


def test_broken_checks_frontmatter_silent_e07():
    broken = "---\nchecks: [unclosed\n---\n# S\n"
    with tempfile.TemporaryDirectory() as root:
        _make_project(root, spec_content=broken)
        _write_target(root, "src/app.py", "print('x')\n")
        assert _run(root) == {}


def test_non_code_file_silent():
    with tempfile.TemporaryDirectory() as root:
        _make_project(root)
        _write_target(root, "src/notes.md", "print('x')\n")
        assert _run(root, rel="src/notes.md") == {}


def test_empty_stdin_silent():
    with tempfile.TemporaryDirectory() as root:
        _make_project(root)
        with mock.patch("sys.stdin", io.StringIO("")), \
                mock.patch("sys.stdout", io.StringIO()) as out, \
                mock.patch("os.getcwd", return_value=root):
            cf_post_hook.main()
        assert out.getvalue() == ""
