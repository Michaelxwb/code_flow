#!/usr/bin/env python3
"""Golden set 注入准确性回归测试（catalog 模式）。

用例来源：tests/fixtures/injection_golden.yml（2026-06-12 真实场景 A/B 评测固化，
旧词表模式基线：可达率 76%、误注 2/20、平均 1277 tokens/prompt）。

测试环境镜像本仓库真实的 .code-flow/config.yml + specs/，所以它同时回归：
- catalog 注入逻辑（cf_user_prompt_hook / cf_core.build_spec_catalog）
- 本仓库 config 的 path_mapping patterns（fnmatch 直系文件命中，2026-06-12 修复）
- spec 文件的 description frontmatter 完整性
specs/config 结构调整后若用例失败，属预期信号——更新 golden 而不是放宽断言。

不变量：
- I1 可达率 100%：每个期望 spec 以完整注入或目录行形式进入模型视野
- I2 path 类必须直注完整约束（PreToolUse 同款确定性保障）
- I3 误注为 0：未期望的约束 spec 不得以完整内容注入
- I4 irrelevant 类不得注入任何完整约束
- I5 catalog 注入开销 ≤ budget.catalog_max
"""
import io
import json
import os
import shutil
import sys
import tempfile
import unittest.mock as mock

import pytest
import yaml

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "core", "code-flow", "scripts"))
from cf_user_prompt_hook import main

REPO = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
GOLDEN_PATH = os.path.join(os.path.dirname(__file__), "fixtures", "injection_golden.yml")
CONSTRAINT_SPECS = ("scripts/code-standards.md", "cli/code-standards.md")


def _load_cases() -> list:
    with open(GOLDEN_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)["cases"]


CASES = _load_cases()
CASE_IDS = [f"{c['category']}-{i}" for i, c in enumerate(CASES)]


@pytest.fixture(scope="module")
def golden_project() -> str:
    """Temp project mirroring this repo's real .code-flow (specs + config)."""
    root = tempfile.mkdtemp(prefix="cf-golden-")
    cf_dir = os.path.join(root, ".code-flow")
    shutil.copytree(
        os.path.join(REPO, ".code-flow", "specs"), os.path.join(cf_dir, "specs")
    )
    shutil.copyfile(
        os.path.join(REPO, ".code-flow", "config.yml"),
        os.path.join(cf_dir, "config.yml"),
    )
    yield root
    shutil.rmtree(root, ignore_errors=True)


def _run_hook(prompt: str, project_root: str, session_id: str) -> str:
    stdin_data = json.dumps({"prompt": prompt, "session_id": session_id})
    with mock.patch("sys.stdin", io.StringIO(stdin_data)), \
            mock.patch("sys.stdout", io.StringIO()) as mock_out, \
            mock.patch("os.getcwd", return_value=project_root):
        main()
    output = mock_out.getvalue()
    if not output.strip():
        return ""
    return json.loads(output)["hookSpecificOutput"]["additionalContext"]


def _full_injected(ctx: str) -> set:
    return {p for p in CONSTRAINT_SPECS if f"#### {p}" in ctx}


def _reachable(ctx: str, spec: str) -> bool:
    return f"#### {spec}" in ctx or f"`{spec}`" in ctx


def _expected_list(case: dict) -> list:
    exp = case.get("expected")
    if not exp:
        return []
    return [exp] if isinstance(exp, str) else list(exp)


def _direct_list(case: dict) -> list:
    """必须直注完整约束的 spec：显式 direct 字段优先，path 类默认 expected 全量。"""
    direct = case.get("direct")
    if direct is not None:
        return list(direct)
    if case["category"] == "path":
        return _expected_list(case)
    return []


def test_repo_config_is_catalog_mode(golden_project: str) -> None:
    """golden 的前提：本仓库 config 启用 catalog 模式。"""
    with open(os.path.join(golden_project, ".code-flow", "config.yml"), encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    assert (cfg.get("inject") or {}).get("mode") == "catalog"


@pytest.mark.parametrize("case", CASES, ids=CASE_IDS)
def test_golden_case(case: dict, golden_project: str) -> None:
    ctx = _run_hook(
        case["prompt"], golden_project, session_id=f"golden-{CASES.index(case)}"
    )
    expected = _expected_list(case)
    full = _full_injected(ctx)

    if not expected:
        # I4: 无关场景不得注入任何完整约束（目录/导航可接受）
        assert not full, (
            f"无关 prompt 误注完整约束 {sorted(full)}: {case['prompt']!r}"
        )
        return

    # I1: 每个期望 spec 都必须可达（完整注入或目录行）
    missed = [s for s in expected if not _reachable(ctx, s)]
    assert not missed, (
        f"期望 {missed} 未进入模型视野: {case['prompt']!r}\n注入内容:\n{ctx[:500]}"
    )
    # I2: direct 列表中的 spec 必须直注完整约束
    not_direct = [s for s in _direct_list(case) if s not in full]
    assert not not_direct, (
        f"未直注完整约束 {not_direct}（实际直注 {sorted(full)}）: {case['prompt']!r}"
    )
    # I3: 不得误注期望之外约束的完整内容
    unexpected = full - set(expected)
    assert not unexpected, (
        f"误注完整约束 {sorted(unexpected)}: {case['prompt']!r}"
    )


def test_catalog_cost_within_budget(golden_project: str) -> None:
    """I5: 无路径 prompt 的注入开销 ≤ catalog_max（对比旧模式 1117+ tokens）。"""
    with open(os.path.join(golden_project, ".code-flow", "config.yml"), encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    catalog_max = int((cfg.get("budget") or {}).get("catalog_max", 200))
    ctx = _run_hook("随便聊一个新话题", golden_project, session_id="golden-cost")
    assert ctx, "应注入 spec 目录"
    assert len(ctx) // 4 <= catalog_max, (
        f"catalog 超出预算: {len(ctx) // 4} > {catalog_max} tokens"
    )


def test_golden_aggregate_reachability(golden_project: str) -> None:
    """汇总不变量：可达率必须保持 100%（旧模式基线 76%）。"""
    missed = []
    total = 0
    for i, case in enumerate(CASES):
        expected = _expected_list(case)
        if not expected:
            continue
        total += len(expected)
        ctx = _run_hook(case["prompt"], golden_project, session_id=f"golden-agg-{i}")
        missed.extend(
            f"{case['prompt']!r} → {s}" for s in expected if not _reachable(ctx, s)
        )
    assert not missed, (
        f"可达率跌破 100%（{total - len(missed)}/{total}），漏注: {missed}"
    )
