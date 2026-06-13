#!/usr/bin/env python3
"""Tests for quality_loop switches (TASK-002) and check-state / cf_feedback (TASK-006).

Scenarios:
- resolve_quality_loop：缺失→全关（升级用户行为不变）/ enabled=true 全开 /
  子开关仅 literal false 关闭 / 非法值安全处理（RULE-06）
- degrade helper 不抛出（RULE-01）
- check-state：B-03 第 3 次 ignore 恰好停用 / 误报率 >10% 停用 / 损坏重建
- cf_feedback CLI：成功 0 / 用法 1 / 未知 id 2
"""
import io
import json
import os
import sys
import tempfile
import unittest.mock as mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "core", "code-flow", "scripts"))
import cf_checks
import cf_feedback
import cf_log
from cf_core import resolve_quality_loop


# --- resolve_quality_loop (TASK-002) ---
def test_missing_section_all_off():
    assert resolve_quality_loop({}) == {
        "enabled": False, "post_check": False,
        "stop_check": False, "correction_capture": False,
    }
    assert resolve_quality_loop(None)["enabled"] is False


def test_enabled_true_turns_subswitches_on():
    out = resolve_quality_loop({"quality_loop": {"enabled": True}})
    assert out == {
        "enabled": True, "post_check": True,
        "stop_check": True, "correction_capture": True,
    }


def test_sub_switch_literal_false_only():
    cfg = {"quality_loop": {"enabled": True, "post_check": False, "stop_check": "no"}}
    out = resolve_quality_loop(cfg)
    assert out["post_check"] is False        # literal false 关闭
    assert out["stop_check"] is True         # 非 literal false → 跟随 enabled


def test_enabled_non_literal_true_stays_off():
    for value in ("true", 1, "yes", None):
        out = resolve_quality_loop({"quality_loop": {"enabled": value}})
        assert out["enabled"] is False, value


def test_degrade_never_raises():
    with tempfile.TemporaryDirectory() as root:
        cf_log.degrade(root, "post_check", ValueError("boom"), "s1")
        events = cf_log.read_events(root, events=("degrade",))
        assert events[0]["data"]["component"] == "post_check"
    # 不可写也不抛
    cf_log.degrade("/nonexistent/deep/path", "x", "y")


# --- check-state (TASK-006) ---
def test_third_ignore_disables_exactly():
    with tempfile.TemporaryDirectory() as root:
        # 大量 hit 避免误报率路径提前触发，单测 fp_count 阈值
        cf_checks.record_hits(root, ["no-print"] * 0 or [])
        state = cf_checks.load_check_state(root)
        state["no-print"] = {"hit_count": 100}
        cf_checks.save_check_state(root, state)
        r1 = cf_checks.record_false_positive(root, "no-print")
        r2 = cf_checks.record_false_positive(root, "no-print")
        assert r1["disabled"] is False and r2["disabled"] is False
        r3 = cf_checks.record_false_positive(root, "no-print")
        assert r3["disabled"] is True and r3["fp_count"] == 3


def test_fp_rate_disables_before_count():
    with tempfile.TemporaryDirectory() as root:
        state = {"rare-check": {"hit_count": 5}}
        cf_checks.save_check_state(root, state)
        # 1/5 = 20% > 10% → 第一次标记即停用
        result = cf_checks.record_false_positive(root, "rare-check")
        assert result["disabled"] is True


def test_corrupt_state_rebuilt():
    with tempfile.TemporaryDirectory() as root:
        os.makedirs(os.path.join(root, ".code-flow"))
        with open(cf_checks.state_path(root), "w") as f:
            f.write("{broken")
        assert cf_checks.load_check_state(root) == {}
        result = cf_checks.record_false_positive(root, "x-check")
        assert result["fp_count"] == 1


# --- cf_feedback CLI (TASK-006) ---
def _make_project_with_check(root: str) -> None:
    specs = os.path.join(root, ".code-flow", "specs", "scripts")
    os.makedirs(specs)
    with open(os.path.join(specs, "code-standards.md"), "w", encoding="utf-8") as f:
        f.write(
            "---\ndescription: d\nchecks:\n"
            "  - id: no-print-debug\n    type: regex\n"
            "    pattern: 'print\\('\n    message: m\n---\n# S\n"
        )
    import yaml
    config = {"path_mapping": {"scripts": {"patterns": ["**/*.py"], "specs": [
        {"path": "scripts/code-standards.md", "tags": ["core"], "tier": 1}]}}}
    with open(os.path.join(root, ".code-flow", "config.yml"), "w") as f:
        yaml.dump(config, f)


def test_feedback_ignore_known_check():
    with tempfile.TemporaryDirectory() as root:
        _make_project_with_check(root)
        with mock.patch("os.getcwd", return_value=root), \
                mock.patch("sys.stdout", io.StringIO()) as out:
            code = cf_feedback.main(["ignore", "no-print-debug"])
        assert code == 0
        result = json.loads(out.getvalue())
        assert result["check_id"] == "no-print-debug"
        assert result["fp_count"] == 1
        events = cf_log.read_events(root, events=("false_positive",))
        assert events[0]["data"]["check_id"] == "no-print-debug"


def test_feedback_unknown_check_exit_2():
    with tempfile.TemporaryDirectory() as root:
        _make_project_with_check(root)
        with mock.patch("os.getcwd", return_value=root):
            assert cf_feedback.main(["ignore", "nonexistent-check"]) == 2


def test_feedback_usage_exit_1():
    assert cf_feedback.main([]) == 1
    assert cf_feedback.main(["delete", "x"]) == 1


# --- hook 埋点 (TASK-003) ---
def _make_hook_project(root: str, ql_enabled: bool) -> None:
    import yaml
    specs = os.path.join(root, ".code-flow", "specs", "scripts")
    os.makedirs(specs)
    with open(os.path.join(specs, "_map.md"), "w", encoding="utf-8") as f:
        f.write("# Map\n\n> scripts 导航\n")
    with open(os.path.join(specs, "code-standards.md"), "w", encoding="utf-8") as f:
        f.write("---\ndescription: d\n---\n# S\n- 规则\n")
    config = {
        "inject": {"auto": True, "code_extensions": [".py"], "mode": "catalog"},
        "quality_loop": {"enabled": ql_enabled},
        "path_mapping": {"scripts": {"patterns": ["**/*.py"], "specs": [
            {"path": "scripts/_map.md", "tags": ["*"], "tier": 0},
            {"path": "scripts/code-standards.md", "tags": ["core"], "tier": 1},
        ]}},
    }
    with open(os.path.join(root, ".code-flow", "config.yml"), "w") as f:
        yaml.dump(config, f)


def _run_inject_hook(root: str, payload: dict) -> None:
    import cf_inject_hook
    stdin_data = json.dumps(payload)
    with mock.patch("sys.stdin", io.StringIO(stdin_data)), \
            mock.patch("sys.stdout", io.StringIO()), \
            mock.patch("os.getcwd", return_value=root):
        cf_inject_hook.main()


def test_inject_hook_records_edit_and_inject_events():
    with tempfile.TemporaryDirectory() as root:
        _make_hook_project(root, ql_enabled=True)
        _run_inject_hook(root, {
            "tool_name": "Edit",
            "tool_input": {"file_path": "src/core/cf_core.py"},
            "session_id": "s-evt",
        })
        edits = cf_log.read_events(root, events=("edit",))
        injects = cf_log.read_events(root, events=("inject",))
        assert edits and edits[0]["data"]["tool"] == "Edit"
        assert edits[0]["sid"] == "s-evt"
        assert injects and injects[0]["data"]["source"] == "pretooluse"


def test_inject_hook_disabled_writes_no_log():
    with tempfile.TemporaryDirectory() as root:
        _make_hook_project(root, ql_enabled=False)
        _run_inject_hook(root, {
            "tool_name": "Edit",
            "tool_input": {"file_path": "src/core/cf_core.py"},
            "session_id": "s-off",
        })
        assert not os.path.exists(cf_log.log_path(root))


# --- 纠正句式检测 (TASK-011) ---
def test_detect_correction_positive_cases():
    from cf_checks import detect_correction
    for prompt in (
        "不要用 print 调试，改回去",
        "这里写错了，不是这样实现的",
        "我说过 hook 输出必须是 JSON",
        "don't use print here",
        "that's wrong, revert it",
    ):
        assert detect_correction(prompt), prompt


def test_detect_correction_negative_cases_e06():
    from cf_checks import detect_correction
    for prompt in (
        "不要紧，继续",
        "这样做对不对？",
        "这个接口不对外暴露",
        "帮我写个测试",
        "",
    ):
        assert detect_correction(prompt) is None, prompt


def test_correction_event_recorded_s06():
    import cf_user_prompt_hook
    with tempfile.TemporaryDirectory() as root:
        _make_hook_project(root, ql_enabled=True)
        long_tail = "x" * 300
        stdin_data = json.dumps({
            "prompt": f"不要用 print 调试 src/a.py {long_tail}",
            "session_id": "s-corr",
        })
        with mock.patch("sys.stdin", io.StringIO(stdin_data)), \
                mock.patch("sys.stdout", io.StringIO()), \
                mock.patch("os.getcwd", return_value=root):
            cf_user_prompt_hook.main()
        events = cf_log.read_events(root, events=("correction",))
        assert len(events) == 1
        data = events[0]["data"]
        assert data["phrase"] == "不要"
        assert len(data["prompt_head"]) == 200          # 截断（NFR-SEC-01 最小化）
        assert "src/a.py" in data["files"]


def test_correction_capture_off_no_event():
    import cf_user_prompt_hook
    with tempfile.TemporaryDirectory() as root:
        _make_hook_project(root, ql_enabled=False)
        stdin_data = json.dumps({"prompt": "不要用 print", "session_id": "s-off2"})
        with mock.patch("sys.stdin", io.StringIO(stdin_data)), \
                mock.patch("sys.stdout", io.StringIO()), \
                mock.patch("os.getcwd", return_value=root):
            cf_user_prompt_hook.main()
        assert cf_log.read_events(root, events=("correction",)) == []


def test_user_prompt_hook_records_catalog_inject_event():
    import cf_user_prompt_hook
    with tempfile.TemporaryDirectory() as root:
        _make_hook_project(root, ql_enabled=True)
        stdin_data = json.dumps({"prompt": "聊聊架构", "session_id": "s-cat"})
        with mock.patch("sys.stdin", io.StringIO(stdin_data)), \
                mock.patch("sys.stdout", io.StringIO()), \
                mock.patch("os.getcwd", return_value=root):
            cf_user_prompt_hook.main()
        injects = cf_log.read_events(root, events=("inject",))
        assert injects and injects[0]["data"]["source"] == "catalog"
        assert injects[0]["data"]["specs"] == ["__catalog__"]
