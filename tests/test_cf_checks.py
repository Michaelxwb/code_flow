#!/usr/bin/env python3
"""Tests for cf_checks.py — parse (TASK-004) and execute (TASK-005).

Parse scenarios: 合法 / 非法正则 / 未知与预留 type / 缺字段 / 重复 id /
message 超长截断 / 无 frontmatter / YAML 损坏。
Run scenarios: 命中 / files glob 不匹配 / 超大内容跳过(B-01) / disabled 过滤 /
单 check 超时(E-02) / 行数上限(RISK-05) / mtime 缓存。
"""
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "core", "code-flow", "scripts"))
import cf_checks
from cf_checks import load_spec_checks, parse_spec_checks, run_checks

VALID_SPEC = """---
description: 测试用规范
checks:
  - id: no-print-debug
    type: regex
    pattern: '^\\s*print\\('
    files: "**/*.py"
    message: 禁止 print() 调试，用 _log() 到 stderr
  - id: bare-except
    type: regex
    pattern: 'except\\s*:'
    message: 禁止裸 except
    severity: info
---

# Standards
"""


# --- parse (TASK-004) ---
def test_parse_valid_checks():
    checks, errors = parse_spec_checks(VALID_SPEC)
    assert errors == []
    assert [c["id"] for c in checks] == ["no-print-debug", "bare-except"]
    assert checks[0]["files"] == "**/*.py"
    assert checks[1]["files"] == "*"             # 缺省（"*" 跨 "/"，"**/*" 会漏根文件）
    assert checks[0]["severity"] == "warn"       # 缺省
    assert checks[1]["severity"] == "info"


def test_parse_no_frontmatter_or_no_checks():
    assert parse_spec_checks("# Title\ncontent") == ([], [])
    assert parse_spec_checks("---\ndescription: x\n---\n# T") == ([], [])
    assert parse_spec_checks(None) == ([], [])


def test_parse_invalid_regex_skipped_with_error():
    spec = "---\nchecks:\n  - id: bad-re\n    type: regex\n    pattern: '['\n    message: m\n---\n"
    checks, errors = parse_spec_checks(spec)
    assert checks == []
    assert any("非法正则" in e for e in errors)


def test_parse_unknown_and_reserved_types():
    spec = (
        "---\nchecks:\n"
        "  - id: a-cmd\n    type: cmd\n    pattern: x\n    message: m\n"
        "  - id: b-odd\n    type: magic\n    pattern: x\n    message: m\n---\n"
    )
    checks, errors = parse_spec_checks(spec)
    assert checks == []
    assert any("暂未实现" in e for e in errors)
    assert any("未知 type" in e for e in errors)


def test_parse_missing_fields_and_duplicate_id():
    spec = (
        "---\nchecks:\n"
        "  - id: ok-one\n    type: regex\n    pattern: 'x'\n    message: m\n"
        "  - id: ok-one\n    type: regex\n    pattern: 'y'\n    message: m\n"
        "  - id: NoKebab\n    type: regex\n    pattern: 'z'\n    message: m\n"
        "  - id: no-msg\n    type: regex\n    pattern: 'w'\n---\n"
    )
    checks, errors = parse_spec_checks(spec)
    assert [c["id"] for c in checks] == ["ok-one"]
    assert any("重复" in e for e in errors)
    assert any("kebab-case" in e for e in errors)
    assert any("message 缺失" in e for e in errors)


def test_parse_message_truncated(monkeypatch):
    long_msg = "长" * 300
    spec = f"---\nchecks:\n  - id: long-msg\n    type: regex\n    pattern: 'x'\n    message: {long_msg}\n---\n"
    checks, errors = parse_spec_checks(spec)
    assert len(checks[0]["message"]) == cf_checks.MESSAGE_MAX_LEN
    assert any("截断" in e for e in errors)


def test_parse_broken_yaml():
    spec = "---\nchecks: [unclosed\n---\n"
    checks, errors = parse_spec_checks(spec)
    assert checks == []
    assert errors and "YAML" in errors[0]


# --- run (TASK-005) ---
def _checks():
    checks, errors = parse_spec_checks(VALID_SPEC)
    assert not errors
    return checks


def test_run_hit_reports_violation():
    violations, skipped = run_checks(_checks(), "src/a.py", "x = 1\nprint('debug')\n")
    assert skipped == []
    assert len(violations) == 1
    v = violations[0]
    assert v["check_id"] == "no-print-debug"
    assert v["line_no"] == 2
    assert "禁止 print()" in v["message"]


def test_run_glob_mismatch_skips():
    violations, _ = run_checks(_checks(), "src/a.js", "print('x')\n")
    assert all(v["check_id"] != "no-print-debug" for v in violations)


def test_run_oversize_skipped():
    big = "a" * (cf_checks.MAX_CONTENT_BYTES + 1)
    violations, skipped = run_checks(_checks(), "src/a.py", big)
    assert violations == []
    assert skipped == [{"check_id": "*", "reason": "content_too_large"}]


def test_run_disabled_filtered():
    state = {"no-print-debug": {"disabled": True}}
    violations, _ = run_checks(_checks(), "src/a.py", "print('x')\n", state=state)
    assert violations == []


def test_run_line_cap():
    content = "\n".join("print('x')" for _ in range(10))
    violations, _ = run_checks(_checks(), "src/a.py", content)
    assert len(violations) == cf_checks.MAX_LINES_PER_CHECK


def test_run_timeout_skips_check():
    class SlowRegex:
        def search(self, line):
            time.sleep(0.2)
            return None
    slow = {
        "id": "slow-check", "type": "regex", "pattern": "x", "regex": SlowRegex(),
        "files": "*", "message": "m", "severity": "warn",
    }
    violations, skipped = run_checks([slow], "a.py", "line\n", timeout=0.05)
    assert violations == []
    assert skipped == [{"check_id": "slow-check", "reason": "timeout"}]


def test_load_spec_checks_mtime_cache():
    with tempfile.TemporaryDirectory() as root:
        path = os.path.join(root, "spec.md")
        with open(path, "w", encoding="utf-8") as f:
            f.write(VALID_SPEC)
        first, _ = load_spec_checks(path)
        assert len(first) == 2
        # 命中缓存：同 mtime 返回同对象
        second, _ = load_spec_checks(path)
        assert second is first
        # 改写文件 → mtime 变化 → 重新解析
        time.sleep(0.01)
        with open(path, "w", encoding="utf-8") as f:
            f.write("---\nchecks:\n  - id: only-one\n    type: regex\n    pattern: 'x'\n    message: m\n---\n")
        os.utime(path, (time.time() + 5, time.time() + 5))
        third, _ = load_spec_checks(path)
        assert [c["id"] for c in third] == ["only-one"]


def test_load_spec_checks_missing_file():
    assert load_spec_checks("/nonexistent/spec.md") == ([], [])
