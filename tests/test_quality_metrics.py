#!/usr/bin/env python3
"""Tests for cf-stats quality_loop 聚合 (TASK-013) 与 cf-scan 复审清单 (TASK-014).

Scenarios:
- S-08 Top 违规榜聚合与排序；修正率口径（违规→后续编辑→未再违规）
- 空日志 → "暂无数据"；degraded 组件聚合
- S-09 复审：未命中 spec 标记 / disabled check 标记 / fp≥2 标记 / 豁免跳过
- checks 语法错误进 cf-scan issues（E-01 离线出口）
"""
import os
import sys
import tempfile

import yaml

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "core", "code-flow", "scripts"))
import cf_checks
import cf_log
from cf_scan import build_review_list
from cf_stats import quality_loop_summary

QL_CONFIG = {"quality_loop": {"enabled": True}}


def _seed_violation_fixed(root: str) -> None:
    """violation → edit（修正）序列，且未再违规。"""
    cf_log.append_event(root, "violation",
                        {"check_id": "no-print", "spec": "s/c.md", "file": "a.py",
                         "severity": "warn"}, "s1")
    cf_log.append_event(root, "edit", {"file": "a.py", "tool": "Edit"}, "s1")


def _seed_violation_unfixed(root: str) -> None:
    """violation → edit → 同 check 再违规（未修正）。"""
    cf_log.append_event(root, "violation",
                        {"check_id": "bare-except", "spec": "s/c.md", "file": "b.py",
                         "severity": "warn"}, "s1")
    cf_log.append_event(root, "edit", {"file": "b.py", "tool": "Edit"}, "s1")
    cf_log.append_event(root, "violation",
                        {"check_id": "bare-except", "spec": "s/c.md", "file": "b.py",
                         "severity": "warn"}, "s1")


def test_stats_empty_log_note():
    with tempfile.TemporaryDirectory() as root:
        summary = quality_loop_summary(root, QL_CONFIG)
        assert summary["note"] == "暂无数据"
        assert summary["switches"]["enabled"] is True


def test_stats_top_violations_and_fix_rate():
    with tempfile.TemporaryDirectory() as root:
        _seed_violation_fixed(root)
        _seed_violation_unfixed(root)
        summary = quality_loop_summary(root, QL_CONFIG)
        rules = {item["rule"]: item["count"] for item in summary["top_violations"]}
        assert rules["s/c.md#bare-except"] == 2
        assert rules["s/c.md#no-print"] == 1
        # 3 个违规事件：no-print 已修正（1），bare-except 两条均未修正
        assert summary["violation_total"] == 3
        assert summary["fix_rate"] == f"{round(1 * 100 / 3)}%"


def test_stats_degraded_aggregation():
    with tempfile.TemporaryDirectory() as root:
        cf_log.degrade(root, "post_check", "timeout-x", "s1")
        cf_log.degrade(root, "post_check", "timeout-y", "s1")
        summary = quality_loop_summary(root, QL_CONFIG)
        assert summary["degraded"]["post_check"]["count"] == 2
        assert summary["degraded"]["post_check"]["last_error"] == "timeout-y"


def _seed_old_inject(root: str, specs: list, days_ago: int = 10) -> None:
    """伪造 days_ago 天前的 inject 事件，满足复审信号的覆盖期门槛。"""
    import json as jsonlib
    from datetime import datetime, timedelta
    cf_log.append_event(root, "inject", {"specs": specs, "mode": "full",
                                         "source": "pretooluse"}, "s1")
    old = {
        "v": 1,
        "ts": (datetime.now() - timedelta(days=days_ago)).isoformat(timespec="seconds"),
        "sid": "s0", "event": "inject",
        "data": {"specs": specs, "mode": "full", "source": "pretooluse"},
    }
    with open(cf_log.log_path(root), "a", encoding="utf-8") as f:
        f.write(jsonlib.dumps(old) + "\n")


def test_review_unengaged_spec_flagged():
    with tempfile.TemporaryDirectory() as root:
        _seed_old_inject(root, ["cli/code-standards.md"])
        specs = [
            {"rel": "cli/code-standards.md"},
            {"rel": "scripts/code-standards.md"},   # 未命中
            {"rel": "cli/_map.md"},                  # 导航不参与
            {"rel": "shared/prd-template.md"},       # shared 不参与
        ]
        review = build_review_list(root, specs)
        items = {r["item"] for r in review}
        assert "scripts/code-standards.md" in items
        assert "cli/code-standards.md" not in items
        assert "cli/_map.md" not in items


def test_review_no_log_skips_unengaged_signal():
    with tempfile.TemporaryDirectory() as root:
        review = build_review_list(root, [{"rel": "scripts/code-standards.md"}])
        assert review == []      # 全新安装不误伤


def test_review_insufficient_coverage_skips_unengaged_signal():
    """日志覆盖期 < 7 天（刚部署）不启用"未命中"信号——实测误伤回归。"""
    with tempfile.TemporaryDirectory() as root:
        cf_log.append_event(root, "inject", {"specs": ["cli/code-standards.md"],
                                             "mode": "catalog", "source": "catalog"}, "s1")
        review = build_review_list(root, [{"rel": "scripts/code-standards.md"}])
        assert review == []


def test_review_disabled_and_fp_checks():
    with tempfile.TemporaryDirectory() as root:
        cf_checks.save_check_state(root, {
            "dead-check": {"disabled": True, "disabled_reason": "auto: fp_count=3"},
            "noisy-check": {"fp_count": 2, "hit_count": 9},
            "fine-check": {"fp_count": 1, "hit_count": 50},
        })
        review = build_review_list(root, [])
        reasons = {r["item"]: r["reason"] for r in review}
        assert "已自动停用" in reasons["dead-check"]
        assert "误报 2 次" in reasons["noisy-check"]
        assert "fine-check" not in reasons


def test_stats_excludes_command_templates_from_budget():
    """tags:[] 模板不计注入预算（修复 277% 误导性利用率）。"""
    import io
    import json as jsonlib
    import unittest.mock as mock
    import cf_stats

    with tempfile.TemporaryDirectory() as root:
        specs = os.path.join(root, ".code-flow", "specs")
        os.makedirs(os.path.join(specs, "shared"))
        os.makedirs(os.path.join(specs, "scripts"))
        with open(os.path.join(specs, "shared", "prd-template.md"), "w") as f:
            f.write("# PRD 模板\n" + "模板内容\n" * 50)
        with open(os.path.join(specs, "scripts", "code-standards.md"), "w") as f:
            f.write("# 约束\n- 规则\n")
        config = {
            "budget": {"total": 2500, "l0_max": 800, "l1_max": 1700},
            "path_mapping": {
                "shared": {"specs": [
                    {"path": "shared/prd-template.md", "tags": [], "tier": 1}]},
                "scripts": {"specs": [
                    {"path": "scripts/code-standards.md", "tags": ["core"], "tier": 1}]},
            },
        }
        with open(os.path.join(root, ".code-flow", "config.yml"), "w") as f:
            yaml.dump(config, f)
        with mock.patch("os.getcwd", return_value=root), \
                mock.patch("sys.argv", ["cf_stats.py"]), \
                mock.patch("sys.stdout", io.StringIO()) as out:
            cf_stats.main()
        result = jsonlib.loads(out.getvalue())
        template_tokens = result["templates"]["tokens"]
        assert template_tokens > 0
        assert "shared/prd-template.md" in result["templates"]["files"]
        # 模板 token 不在 total 内
        assert result["total_tokens"] < template_tokens + result["total_tokens"]
        flat = [i for items in result["l1"].values() for i in items]
        by_path = {i["path"]: i for i in flat}
        assert by_path["shared/prd-template.md"]["injectable"] is False
        assert by_path["scripts/code-standards.md"]["injectable"] is True
        assert result["total_tokens"] == (
            result["l0"]["tokens"] + by_path["scripts/code-standards.md"]["tokens"]
        )


def test_review_exemption_respected():
    with tempfile.TemporaryDirectory() as root:
        cf_checks.save_check_state(root, {
            "_review_exempt": ["dead-check", "scripts/code-standards.md"],
            "dead-check": {"disabled": True, "disabled_reason": "auto"},
        })
        cf_log.append_event(root, "inject", {"specs": [], "mode": "full",
                                             "source": "pretooluse"}, "s1")
        review = build_review_list(root, [{"rel": "scripts/code-standards.md"}])
        assert review == []
