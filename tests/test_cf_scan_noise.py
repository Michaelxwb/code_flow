#!/usr/bin/env python3
"""cf-scan 降噪回归（2026-06-13 修复）.

- 路径检查支持相对 spec 目录的二次解析（_map 引用 design/x.md 不再误报"过时"）
- 模板（tags:[]）不报"冗长/冗余"，且不把模板间共享行计入其他文件的冗余计数
"""
import io
import json
import os
import sys
import tempfile
import unittest.mock as mock

import yaml

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "core", "code-flow", "scripts"))
import cf_scan
from cf_scan import find_missing_paths

SHARED_HEADER = "> **文档版本**: v1.0\n> **创建日期**: YYYY-MM-DD\n"


def _make_project(root: str) -> None:
    specs = os.path.join(root, ".code-flow", "specs")
    os.makedirs(os.path.join(specs, "shared", "design"))
    os.makedirs(os.path.join(specs, "scripts"))
    # _map 用相对本目录的引用
    with open(os.path.join(specs, "shared", "_map.md"), "w", encoding="utf-8") as f:
        f.write("# Shared Map\n\n> 导航\n\n模板见 design/design-lite.md 与 prd-template.md\n")
    # 三个模板共享文档头（曾被误报冗余），其中一个超长（曾被误报冗长）
    for name, pad in (("prd-template.md", 10), ("design/design-lite.md", 10),
                      ("design/design-full.md", 700)):
        with open(os.path.join(specs, "shared", name), "w", encoding="utf-8") as f:
            f.write(f"# 模板\n{SHARED_HEADER}\n" + "模板正文内容填充\n" * pad)
    with open(os.path.join(specs, "scripts", "code-standards.md"), "w", encoding="utf-8") as f:
        f.write(f"---\ndescription: d\n---\n# 约束\n{SHARED_HEADER}- 规则\n")

    config = {"path_mapping": {
        "shared": {"specs": [
            {"path": "shared/_map.md", "tags": ["*"], "tier": 0},
            {"path": "shared/prd-template.md", "tags": [], "tier": 1},
            {"path": "shared/design/design-lite.md", "tags": [], "tier": 1},
            {"path": "shared/design/design-full.md", "tags": [], "tier": 1},
        ]},
        "scripts": {"specs": [
            {"path": "scripts/code-standards.md", "tags": ["core"], "tier": 1},
        ]},
    }}
    with open(os.path.join(root, ".code-flow", "config.yml"), "w") as f:
        yaml.dump(config, f)


def _run_scan(root: str) -> dict:
    with mock.patch("os.getcwd", return_value=root), \
            mock.patch("sys.argv", ["cf_scan.py", "--json"]), \
            mock.patch("sys.stdout", io.StringIO()) as out:
        cf_scan.main()
    return json.loads(out.getvalue())


def test_find_missing_paths_resolves_from_base_dir():
    with tempfile.TemporaryDirectory() as root:
        os.makedirs(os.path.join(root, "sub", "design"))
        with open(os.path.join(root, "sub", "design", "x.md"), "w") as f:
            f.write("x")
        text = "见 design/x.md 与 ghost/y.md"
        missing = find_missing_paths(text, root, os.path.join(root, "sub"))
        assert "design/x.md" not in missing
        assert "ghost/y.md" in missing


def test_relative_spec_reference_not_flagged_stale():
    with tempfile.TemporaryDirectory() as root:
        _make_project(root)
        result = _run_scan(root)
        map_entry = next(e for e in result["files"] if e["path"] == "specs/shared/_map.md")
        assert not any("过时" in i for i in map_entry["issues"]), map_entry["issues"]


def test_templates_not_flagged_long_or_redundant():
    with tempfile.TemporaryDirectory() as root:
        _make_project(root)
        result = _run_scan(root)
        for entry in result["files"]:
            if entry.get("template"):
                assert not any("冗长" in i or "冗余" in i for i in entry["issues"]), entry


def test_template_lines_not_inflating_others_redundancy():
    """共享文档头出现在 3 个模板 + 1 个约束 spec：模板不参与计数后，
    约束 spec 的出现次数 <3，不应被标冗余。"""
    with tempfile.TemporaryDirectory() as root:
        _make_project(root)
        result = _run_scan(root)
        std = next(e for e in result["files"]
                   if e["path"] == "specs/scripts/code-standards.md")
        assert not any("冗余" in i for i in std["issues"]), std["issues"]
