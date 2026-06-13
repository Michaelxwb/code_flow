#!/usr/bin/env python3
"""Requirement-driven tests for inject.mode=catalog (spec catalog self-serve).

Requirements (注入准确性重构 方案 C):
- R1  catalog 模式 + 无路径证据 → 注入 spec 目录（含 Tier1 约束行）
- R2  catalog 模式 + prompt 含命中 domain 的路径 → 仍直注完整约束（高置信）
- R3  目录会话内去重：dedup_window 内第二条无路径 prompt 不重复注入
- R4  mode 缺失/其他值 → full 旧行为（向后兼容）
- R5  description 优先级：frontmatter > blockquote > H1 > ""
- R6  frontmatter 不进入完整注入内容（不占注入预算）
- R7  catalog_max 截断：Tier1 约束行优先保留，导航行先被丢弃
- R8  spec 文件缺失/不可读 → 目录跳过该行不崩溃
- R9  无可注入 spec → 无 stdout 噪音
- R10 回放回归：真实漏注 prompt（"同步顺便把 _TAG_ALIASES…"）目录必须
      包含 scripts/code-standards.md 行
"""
import io
import json
import os
import sys
import tempfile
import unittest.mock as mock
import yaml

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "core", "code-flow", "scripts"))
from cf_core import (
    CATALOG_HEADER,
    build_effective_mapping,
    build_spec_catalog,
    estimate_tokens,
    parse_spec_frontmatter,
    resolve_inject_mode,
    spec_description,
)
from cf_user_prompt_hook import main


SCRIPTS_DESC = "改 Python 脚本/Hook 时适用"

REPLAY_PROMPT = "同步顺便把 _TAG_ALIASES 也加上 hook/inject/spec/task 那几个词"


def _make_project(tmpdir: str, mode: str = "catalog") -> str:
    """Minimal .code-flow project; mode=None omits inject.mode entirely."""
    cf_dir = os.path.join(tmpdir, ".code-flow")
    scripts_dir = os.path.join(cf_dir, "specs", "scripts")
    os.makedirs(scripts_dir, exist_ok=True)

    with open(os.path.join(scripts_dir, "code-standards.md"), "w") as f:
        f.write(
            f"---\ndescription: {SCRIPTS_DESC}\n---\n\n"
            "# Standards\n- 所有函数必须有 type hints\n"
        )
    with open(os.path.join(scripts_dir, "_map.md"), "w") as f:
        f.write("# Map\n\n> scripts 域导航地图\n\n内容。\n")

    inject_cfg = {"auto": True, "code_extensions": [".py", ".js"]}
    if mode is not None:
        inject_cfg["mode"] = mode
    config = {
        "version": 1,
        "budget": {"l1_max": 1700, "map_max": 400, "catalog_max": 200},
        "inject": inject_cfg,
        "path_mapping": {
            "scripts": {
                "patterns": ["**/*.py"],
                "specs": [
                    {"path": "scripts/_map.md", "tags": ["*"], "tier": 0},
                    {"path": "scripts/code-standards.md", "tags": ["core", "hook"], "tier": 1},
                ],
            },
        },
    }
    with open(os.path.join(cf_dir, "config.yml"), "w") as f:
        yaml.dump(config, f)
    return tmpdir


def _run_main(prompt: str, project_root: str, session_id: str = "sess-catalog") -> dict:
    stdin_data = json.dumps({"prompt": prompt, "session_id": session_id})
    with mock.patch("sys.stdin", io.StringIO(stdin_data)), \
            mock.patch("sys.stdout", io.StringIO()) as mock_out, \
            mock.patch("os.getcwd", return_value=project_root):
        main()
    output = mock_out.getvalue()
    return json.loads(output) if output.strip() else {}


# --- R5: description source priority ---
def test_description_prefers_frontmatter():
    content = "---\ndescription: 前言描述\n---\n\n# 标题\n\n> 引用描述\n"
    assert spec_description(content) == "前言描述"


def test_description_falls_back_to_blockquote():
    content = "# 标题\n\n> 引用描述\n\n内容\n"
    assert spec_description(content) == "引用描述"


def test_description_falls_back_to_h1():
    content = "# 标题\n\n内容\n"
    assert spec_description(content) == "标题"


def test_description_empty_when_nothing():
    assert spec_description("plain text only\n") == ""


def test_frontmatter_stripped_and_parsed():
    meta, body = parse_spec_frontmatter("---\ndescription: x\n---\n\n# T\n")
    assert meta == {"description": "x"}
    assert body.strip() == "# T"


def test_no_frontmatter_passthrough():
    meta, body = parse_spec_frontmatter("# T\n---\nnot frontmatter")
    assert meta == {}
    assert body.startswith("# T")


# --- mode resolution (R4 backbone) ---
def test_mode_literal_catalog_enables():
    assert resolve_inject_mode({"mode": "catalog"}) == "catalog"
    assert resolve_inject_mode({"mode": " Catalog "}) == "catalog"


def test_mode_missing_or_other_is_full():
    assert resolve_inject_mode({}) == "full"
    assert resolve_inject_mode({"mode": None}) == "full"
    assert resolve_inject_mode({"mode": "full"}) == "full"
    assert resolve_inject_mode({"mode": True}) == "full"
    assert resolve_inject_mode(None) == "full"


# --- R1: catalog injected for promptless-path turns ---
def test_catalog_injected_without_path_evidence():
    with tempfile.TemporaryDirectory() as tmpdir:
        _make_project(tmpdir)
        result = _run_main("帮我优化一下缓存策略", tmpdir)
        ctx = result["hookSpecificOutput"]["additionalContext"]
        assert "Spec Catalog" in ctx
        assert "scripts/code-standards.md" in ctx
        assert SCRIPTS_DESC in ctx
        # 目录不是完整约束注入
        assert "type hints" not in ctx


# --- R2: explicit path keeps deterministic full injection (+ catalog appended) ---
def test_catalog_mode_path_prompt_injects_full_specs():
    """路径直注完整约束，同时附带目录保证跨域可达（同一去重窗口控制）。"""
    with tempfile.TemporaryDirectory() as tmpdir:
        _make_project(tmpdir)
        result = _run_main("edit src/core/cf_core.py", tmpdir)
        ctx = result["hookSpecificOutput"]["additionalContext"]
        assert "Active Specs" in ctx
        assert "Spec Catalog" in ctx


def test_catalog_not_reappended_within_window_on_path_turn():
    """第一回合目录已注入，窗口内的路径回合只直注完整约束、不重复带目录。"""
    with tempfile.TemporaryDirectory() as tmpdir:
        _make_project(tmpdir)
        first = _run_main("先聊聊方案", tmpdir, session_id="s-mix")
        assert "Spec Catalog" in first["hookSpecificOutput"]["additionalContext"]
        second = _run_main("edit src/core/cf_core.py", tmpdir, session_id="s-mix")
        ctx = second["hookSpecificOutput"]["additionalContext"]
        assert "Active Specs" in ctx
        assert "Spec Catalog" not in ctx


# --- R3: catalog dedup within session window ---
def test_catalog_deduped_within_window():
    with tempfile.TemporaryDirectory() as tmpdir:
        _make_project(tmpdir)
        first = _run_main("先聊聊架构", tmpdir, session_id="s1")
        assert "Spec Catalog" in first["hookSpecificOutput"]["additionalContext"]
        second = _run_main("继续聊", tmpdir, session_id="s1")
        assert second == {}


def test_catalog_reinjected_for_new_session():
    with tempfile.TemporaryDirectory() as tmpdir:
        _make_project(tmpdir)
        _run_main("先聊聊", tmpdir, session_id="s1")
        other = _run_main("新会话", tmpdir, session_id="s2")
        assert "Spec Catalog" in other["hookSpecificOutput"]["additionalContext"]


# --- R4: missing/full mode keeps old behavior ---
def test_mode_missing_keeps_old_tier0_fallback():
    with tempfile.TemporaryDirectory() as tmpdir:
        _make_project(tmpdir, mode=None)
        result = _run_main("帮我优化一下缓存策略", tmpdir)
        ctx = result["hookSpecificOutput"]["additionalContext"]
        assert "Spec Catalog" not in ctx
        assert "_map.md" in ctx


def test_mode_full_explicit_keeps_old_behavior():
    with tempfile.TemporaryDirectory() as tmpdir:
        _make_project(tmpdir, mode="full")
        result = _run_main("帮我优化一下缓存策略", tmpdir)
        ctx = result["hookSpecificOutput"]["additionalContext"]
        assert "Spec Catalog" not in ctx


# --- R6: frontmatter never reaches injected spec content ---
def test_frontmatter_not_in_full_injection():
    with tempfile.TemporaryDirectory() as tmpdir:
        _make_project(tmpdir)
        result = _run_main("edit src/core/cf_core.py", tmpdir)
        ctx = result["hookSpecificOutput"]["additionalContext"]
        assert "description:" not in ctx
        assert "type hints" in ctx


# --- R7: truncation keeps tier-1 rows first ---
def test_catalog_truncation_drops_maps_first():
    with tempfile.TemporaryDirectory() as tmpdir:
        _make_project(tmpdir)
        mapping = build_effective_mapping(tmpdir, _load_mapping(tmpdir))
        full = build_spec_catalog(tmpdir, mapping, catalog_max=10000)
        assert "scripts/code-standards.md" in full
        assert "scripts/_map.md" in full
        # 预算只够 header + 第一行（Tier1 约束行）
        lines = full.split("\n")
        first_row_idx = next(i for i, l in enumerate(lines) if l.startswith("- `"))
        partial = "\n".join(lines[: first_row_idx + 1])
        truncated = build_spec_catalog(
            tmpdir, mapping, catalog_max=estimate_tokens(partial)
        )
        assert "scripts/code-standards.md" in truncated
        assert "scripts/_map.md" not in truncated


def _load_mapping(tmpdir: str) -> dict:
    with open(os.path.join(tmpdir, ".code-flow", "config.yml")) as f:
        return yaml.safe_load(f).get("path_mapping") or {}


# --- R8: missing spec file row skipped, no crash ---
def test_catalog_skips_missing_spec_file():
    with tempfile.TemporaryDirectory() as tmpdir:
        _make_project(tmpdir)
        config_path = os.path.join(tmpdir, ".code-flow", "config.yml")
        with open(config_path) as f:
            cfg = yaml.safe_load(f)
        cfg["path_mapping"]["scripts"]["specs"].append(
            {"path": "scripts/ghost.md", "tags": ["ghost"], "tier": 1}
        )
        with open(config_path, "w") as f:
            yaml.dump(cfg, f)
        result = _run_main("随便聊聊", tmpdir)
        ctx = result["hookSpecificOutput"]["additionalContext"]
        assert "ghost.md" not in ctx
        assert "scripts/code-standards.md" in ctx


# --- R9: nothing injectable → silent no-op ---
def test_catalog_empty_project_no_output():
    with tempfile.TemporaryDirectory() as tmpdir:
        cf_dir = os.path.join(tmpdir, ".code-flow")
        os.makedirs(os.path.join(cf_dir, "specs"), exist_ok=True)
        with open(os.path.join(cf_dir, "config.yml"), "w") as f:
            yaml.dump({"version": 1, "inject": {"auto": True, "mode": "catalog"}}, f)
        result = _run_main("随便聊聊", tmpdir)
        assert result == {}


# --- R10: replay the real-session miss ---
def test_replay_tag_aliases_prompt_surfaces_constraint_spec():
    """实测回归：该 prompt 在词表模式下 prompt_tags=[]，约束 spec 完全缺席；
    catalog 模式下目录行必须让模型看得到 scripts/code-standards.md。"""
    with tempfile.TemporaryDirectory() as tmpdir:
        _make_project(tmpdir)
        result = _run_main(REPLAY_PROMPT, tmpdir)
        ctx = result["hookSpecificOutput"]["additionalContext"]
        assert "Spec Catalog" in ctx
        assert "scripts/code-standards.md" in ctx
        assert SCRIPTS_DESC in ctx


# --- FEAT-08: _session 临时约束自动进目录 (S-11) ---
def test_session_task_spec_appears_in_catalog():
    with tempfile.TemporaryDirectory() as tmpdir:
        _make_project(tmpdir)
        session_dir = os.path.join(tmpdir, ".code-flow", "specs", "_session")
        os.makedirs(session_dir)
        with open(os.path.join(session_dir, "task-demo.md"), "w", encoding="utf-8") as f:
            f.write("---\ndescription: 当前任务 demo 的验收约束\n---\n\n# 验收\n- S-01 …\n")
        result = _run_main("聊聊下一步", tmpdir, session_id="s-feat08")
        ctx = result["hookSpecificOutput"]["additionalContext"]
        assert "_session/task-demo.md" in ctx
        assert "当前任务 demo 的验收约束" in ctx


# --- catalog header sanity ---
def test_catalog_header_instructs_reading():
    assert "Read" in CATALOG_HEADER
