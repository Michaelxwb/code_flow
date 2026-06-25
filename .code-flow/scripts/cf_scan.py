#!/usr/bin/env python3
import json
import os
import re
import sys

import cf_log
from cf_checks import load_check_state, parse_spec_checks
from cf_core import (
    build_effective_mapping,
    build_spec_catalog,
    estimate_tokens,
    load_config,
    non_injectable_specs,
    parse_spec_frontmatter,
)

REVIEW_MIN_COVERAGE_DAYS = 7


def _log_coverage_sufficient(events: list) -> bool:
    """"未命中"信号需要足够的日志覆盖期——刚部署一天的日志没资格断言
    "30 天未命中"（实测误伤：单条事件就把全部 spec 标为待复审）。"""
    from datetime import datetime, timedelta
    earliest = min((str(e.get("ts", "")) for e in events), default="")
    try:
        first = datetime.fromisoformat(earliest)
    except ValueError:
        return False
    return first <= datetime.now() - timedelta(days=REVIEW_MIN_COVERAGE_DAYS)


def build_review_list(project_root: str, specs: list) -> list:
    """待复审清单（FEAT-06）：未命中注入 / 已停用 / 反复误报。

    豁免：check-state `_review_exempt` 列表中的条目不再提示（S-09 处置闭环）。
    日志覆盖不足 REVIEW_MIN_COVERAGE_DAYS 天时跳过"未命中"信号，
    避免误伤全新安装与刚部署项目。
    """
    state = load_check_state(project_root)
    exempt = set(state.get("_review_exempt") or [])
    review: list = []

    events = cf_log.read_events(project_root, days=30)
    if events and _log_coverage_sufficient(events):
        engaged: set = set()
        for event in events:
            data = event.get("data") or {}
            if event.get("event") == "inject":
                engaged.update(data.get("specs") or [])
            elif event.get("event") == "violation" and data.get("spec"):
                engaged.add(data["spec"])
        for spec in specs:
            rel = spec.get("rel", "")
            if rel.endswith("_map.md") or rel.startswith("shared/"):
                continue
            if rel not in engaged and rel not in exempt:
                review.append({"item": rel, "reason": "30 天未命中注入/未触发检查"})

    for cid, entry in state.items():
        if cid.startswith("_") or not isinstance(entry, dict) or cid in exempt:
            continue
        if entry.get("disabled"):
            review.append({
                "item": cid,
                "reason": f"已自动停用（{entry.get('disabled_reason', '')}），待改写或删除",
            })
        elif int(entry.get("fp_count", 0)) >= 2:
            review.append({"item": cid, "reason": f"误报 {entry['fp_count']} 次"})
    return review


PATH_PATTERN = re.compile(r"(?:[\w./-]+/)+[\w.-]+\.[A-Za-z0-9]+")


def read_text(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8") as file:
            return file.read().strip()
    except Exception:
        return ""


def normalize_line(line: str) -> str:
    return " ".join(line.strip().split())


def find_redundant_lines(specs: list) -> dict:
    line_map: dict = {}
    for spec in specs:
        for raw in spec["content"].splitlines():
            line = normalize_line(raw)
            if not line:
                continue
            if line.startswith("#") or line == "---":
                continue
            if len(line) < 6:
                continue
            line_map.setdefault(line, set()).add(spec["path"])
    redundant = {line: paths for line, paths in line_map.items() if len(paths) >= 3}
    return redundant


def find_missing_paths(text: str, project_root: str, base_dir: str = "") -> list:
    """路径引用检查：项目根解析失败时，再按 spec 自身目录二次解析——
    _map.md 常用相对本域目录的引用（如 design/design-lite.md）。"""
    missing: list = []
    for token in set(PATH_PATTERN.findall(text)):
        if token.startswith("http://") or token.startswith("https://"):
            continue
        if os.path.isabs(token):
            if not os.path.exists(token):
                missing.append(token)
            continue
        if os.path.exists(os.path.join(project_root, token)):
            continue
        if base_dir and os.path.exists(os.path.join(base_dir, token)):
            continue
        missing.append(token)
    return sorted(missing)


def build_report(project_root: str) -> dict:
    """规范质量审计数据（cf-scan 引擎，亦供 cf-stats --audit 复用）。

    files 含 issues / template 标记，review 为待复审清单；展示层负责过滤与渲染。"""
    files = []
    total_tokens = 0

    claude_path = os.path.join(project_root, "CLAUDE.md")
    if os.path.exists(claude_path):
        content = read_text(claude_path)
        tokens = estimate_tokens(content)
        total_tokens += tokens
        files.append({"path": "CLAUDE.md", "tokens": tokens, "issues": []})

    specs_root = os.path.join(project_root, ".code-flow", "specs")
    specs = []
    if os.path.isdir(specs_root):
        for root, _, filenames in os.walk(specs_root):
            for name in filenames:
                if not name.endswith(".md"):
                    continue
                full_path = os.path.join(root, name)
                content = read_text(full_path)
                if not content:
                    continue
                tokens = estimate_tokens(content)
                total_tokens += tokens
                rel = os.path.relpath(full_path, specs_root)
                if rel.replace(os.sep, "/").startswith("_session/"):
                    continue  # 会话级临时约束（FEAT-08）不参与审计与预算
                rel_path = os.path.join("specs", rel).replace(os.sep, "/")
                spec_entry = {
                    "path": rel_path,
                    "rel": rel.replace(os.sep, "/"),
                    "tokens": tokens,
                    "issues": [],
                    "content": content,
                }
                specs.append(spec_entry)

    # 模板标记前置：模板（tags:[]）不参与冗长/冗余审计，也不把
    # 模板间共享的文档头计入其他文件的冗余计数
    config = load_config(project_root)
    effective_mapping = build_effective_mapping(
        project_root, config.get("path_mapping") or {}
    )
    excluded_specs = non_injectable_specs(effective_mapping)
    for spec in specs:
        spec["template"] = spec.get("rel", "") in excluded_specs

    redundant_map = find_redundant_lines([s for s in specs if not s["template"]])

    for spec in specs:
        issues = []
        if not spec["template"] and spec["tokens"] > 500:
            issues.append(f"冗长: {spec['tokens']} tokens")

        spec_dir = os.path.join(specs_root, os.path.dirname(spec.get("rel", "")))
        missing_paths = find_missing_paths(spec["content"], project_root, spec_dir)
        for path in missing_paths[:3]:
            issues.append(f"过时: 路径不存在 {path}")

        redundant_lines = [line for line, paths in redundant_map.items() if spec["path"] in paths]
        for line in redundant_lines[:3]:
            issues.append(f"冗余: '{line}' 出现于 {len(redundant_map[line])} 个文件")

        # Constraint specs feed the catalog one line each — flag missing
        # frontmatter description (catalog falls back to blockquote/H1).
        rel = spec.get("rel", "")
        is_constraint = not rel.endswith("_map.md") and not rel.startswith("shared/")
        if is_constraint:
            meta, _ = parse_spec_frontmatter(spec["content"])
            if not (meta.get("description") or "").strip():
                issues.append("缺描述: 建议加 frontmatter description（catalog 适用场景一句话）")
            # checks 标注校验（E-01 / B-04 的离线出口）
            _, check_errors = parse_spec_checks(spec["content"])
            for error in check_errors[:3]:
                issues.append(f"checks: {error}")

        files.append({
            "path": spec["path"],
            "tokens": spec["tokens"],
            "issues": issues,
            "template": spec["template"],
        })

    for entry in files:
        if total_tokens <= 0:
            entry["percent"] = "0%"
        else:
            entry["percent"] = f"{round(entry['tokens'] * 100 / total_tokens)}%"

    budget = (config.get("budget") or {}).get("total", 2500)
    try:
        budget = int(budget)
    except Exception:
        budget = 2500

    try:
        catalog_max = int((config.get("budget") or {}).get("catalog_max", 200))
    except Exception:
        catalog_max = 200
    catalog = build_spec_catalog(project_root, effective_mapping, catalog_max)
    catalog_info = {
        "tokens": estimate_tokens(catalog),
        "max": catalog_max,
        "entries": catalog.count("\n- `"),
    }

    review = build_review_list(project_root, specs)

    # 预算口径与 cf-stats 一致：tags:[] 命令模板不计入注入预算
    templates_tokens = sum(e["tokens"] for e in files if e.get("template"))
    injectable_tokens = total_tokens - templates_tokens

    return {
        "files": files,
        "total_tokens": injectable_tokens,
        "templates_tokens": templates_tokens,
        "budget": budget,
        "catalog": catalog_info,
        "review": review,
        "warnings": [],
    }


def main() -> None:
    json_output = "--json" in sys.argv
    only_issues = "--only-issues" in sys.argv
    limit = None
    for arg in sys.argv[1:]:
        if arg.startswith("--limit="):
            try:
                limit = int(arg.split("=", 1)[1])
            except Exception:
                limit = None

    report = build_report(os.getcwd())
    files = report["files"]
    if limit is not None:
        files = files[:limit]
    if only_issues:
        files = [entry for entry in files if entry.get("issues")]

    if json_output:
        print(json.dumps(dict(report, files=files), ensure_ascii=False))
        return

    catalog_info = report["catalog"]
    print("FILE | TOKENS | PERCENT | ISSUES")
    for entry in files:
        issues = entry.get("issues") or []
        issue_text = " / ".join(issues) if issues else "-"
        marker = " [模板]" if entry.get("template") else ""
        print(f"{entry['path']}{marker} | {entry['tokens']} | {entry['percent']} | {issue_text}")
    print("TOTAL:", f"{report['total_tokens']} / {report['budget']}")
    if report["templates_tokens"]:
        print("TEMPLATES (非注入):", f"{report['templates_tokens']} tokens，不计预算")
    print(
        "CATALOG:",
        f"{catalog_info['tokens']} / {catalog_info['max']} tokens,",
        f"{catalog_info['entries']} entries",
    )
    if report["review"]:
        print("REVIEW (待复审):")
        for item in report["review"]:
            print(f" - {item['item']}: {item['reason']}")


if __name__ == "__main__":
    main()
