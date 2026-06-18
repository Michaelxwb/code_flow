#!/usr/bin/env python3
"""Regression tests for cf-learn command/skill documentation contracts."""

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

TEMPLATE_TO_INSTALLED = {
    "src/adapters/codex/skills/cf-learn/SKILL.md": ".agents/skills/cf-learn/SKILL.md",
    "src/adapters/claude/commands/cf-learn.md": ".claude/commands/cf-learn.md",
    "src/adapters/costrict/commands/cf-learn.md": ".costrict/commands/cf-learn.md",
    "src/adapters/opencode/commands/cf-learn.md": ".opencode/commands/cf-learn.md",
}


def _read_text(rel_path: str) -> str:
    return (ROOT / rel_path).read_text(encoding="utf-8")


def _assert_core_learning_contract(text: str) -> None:
    required = [
        "证据优先",
        "禁止编造",
        "用户确认",
        "置信度",
        "低置信度不自动写入",
        "来源文件",
        "证据片段",
        ".code-flow/config.yml",
        "path_mapping",
        "directory-structure.md",
        "component-specs.md",
        "quality-standards.md",
        "database.md",
        "logging.md",
        "platform-rules.md",
        "code-quality-performance.md",
        "不要创建猜测文件",
        "已有人工内容要保留",
    ]
    for phrase in required:
        assert phrase in text


def _assert_project_type_pruning_contract(text: str) -> None:
    required = [
        "项目类型识别",  # 必须能识别 frontend/backend/fullstack/generic
        "fullstack",
        "generic",
        "域漂移",  # 检测 specs 与真实技术栈漂移
        "裁剪候选",
        "补全建议",
        "cf-init <type>",  # 缺域时引导而非自行 scaffold
        "永不",  # 用户自定义域永不裁剪
        "破坏性操作",  # 删除前必须展示清单 + 确认门
        "宁可漏报不可误删",
    ]
    for phrase in required:
        assert phrase in text


def test_cf_learn_templates_require_evidence_backed_candidates() -> None:
    for template_path in TEMPLATE_TO_INSTALLED:
        _assert_core_learning_contract(_read_text(template_path))


def test_cf_learn_templates_detect_project_type_and_prune() -> None:
    for template_path in TEMPLATE_TO_INSTALLED:
        _assert_project_type_pruning_contract(_read_text(template_path))


def _assert_reconcile_contract(text: str) -> None:
    required = [
        "多维度深读",  # 多角度精读代码而非只 rg 关键字
        "贴合",  # 总结要贴近项目真实做法
        "模板条目对账",  # reconcile
        "改写",  # 矛盾项改写
        "删减",  # 无证据项删减
        "多个文件一致证据",  # 防误删 house-style 的护栏
        "改写优先于删除",
        "破坏性",  # 替换/删除走确认门 + diff
    ]
    for phrase in required:
        assert phrase in text


def test_cf_learn_templates_reconcile_and_replace() -> None:
    for template_path in TEMPLATE_TO_INSTALLED:
        _assert_reconcile_contract(_read_text(template_path))


def _assert_pipeline_coherence_contract(text: str) -> None:
    required = [
        "## 执行流程",  # D: 顶部有序流程总览
        "全量扫描还必须消费",  # A: 纠正信号接入主流程
        "机检草稿（checks）：可机检的新规则",  # B: checks 草稿通用化（非仅 correction 路径）
        "或全量扫描发现 `_map` 与真实结构漂移",  # C: _map 漂移也走对账
        "[动作: 新增|改写|删减|保留]",  # F: 候选携带 reconcile 动作标签
    ]
    for phrase in required:
        assert phrase in text


def test_cf_learn_templates_pipeline_coherence() -> None:
    for template_path in TEMPLATE_TO_INSTALLED:
        _assert_pipeline_coherence_contract(_read_text(template_path))


def _normalize_binding_tokens(text: str) -> str:
    """跨平台能力基线：剥掉平台绑定 token 后，4 份正文应逐字相同。

    允许的平台差异仅限：frontmatter、命令前缀、CLAUDE.md↔AGENTS.md、apply_patch 措辞。
    任何能力分叉（某平台拿到不同/降级的行为）都会让归一化后的正文不等而被此测试拦截。
    """
    text = re.sub(r"^---\n.*?\n---\n", "", text, count=1, flags=re.DOTALL)
    text = text.replace("AGENTS.md", "CLAUDE.md")
    text = text.replace("/project:cf-learn", "cf-learn")
    text = text.replace("用 `apply_patch` 追加", "追加")
    return text.strip()


def test_cf_learn_bodies_identical_modulo_binding_tokens() -> None:
    normed = {
        path: _normalize_binding_tokens(_read_text(path))
        for path in TEMPLATE_TO_INSTALLED
    }
    baseline_path = "src/adapters/claude/commands/cf-learn.md"
    baseline = normed[baseline_path]
    for path, body in normed.items():
        assert body == baseline, f"{path} 与基线存在绑定 token 之外的能力分叉"


def test_installed_cf_learn_docs_match_adapter_templates() -> None:
    for template_path, installed_path in TEMPLATE_TO_INSTALLED.items():
        assert _read_text(installed_path) == _read_text(template_path)


def test_cf_learn_platform_global_targets_are_correct() -> None:
    codex = _read_text("src/adapters/codex/skills/cf-learn/SKILL.md")
    claude = _read_text("src/adapters/claude/commands/cf-learn.md")
    costrict = _read_text("src/adapters/costrict/commands/cf-learn.md")
    opencode = _read_text("src/adapters/opencode/commands/cf-learn.md")

    assert "写入 `AGENTS.md`" in codex
    assert "写入 `AGENTS.md`" in opencode
    assert "写入 `CLAUDE.md`" in claude
    assert "写入 `CLAUDE.md`" in costrict

    assert "`/project:cf-learn`" in claude
    assert "`/project:cf-learn`" in costrict
    assert "`/project:cf-learn`" in opencode
    assert "`cf-learn`" in codex

    # apply_patch 是 codex 的编辑机制；opencode 用自身编辑工具，不应残留 apply_patch
    assert "apply_patch" not in opencode
