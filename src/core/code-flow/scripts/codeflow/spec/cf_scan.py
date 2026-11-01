#!/usr/bin/env python3
import json
import glob
import os
import re
import sys
from pathlib import Path

from codeflow.core import cf_log
from codeflow.acceptance.cf_checks import load_check_state, parse_spec_checks
from codeflow.core.cf_core import (
    build_effective_mapping,
    build_spec_catalog,
    estimate_tokens,
    load_config,
    project_instruction_file,
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


_YAML_STRUCTURE = re.compile(
    r"^(?:stages:.*|enforcement:.*|verifiers:.*|tags:.*|tier:.*|"
    r"- (?:design|plan|code|review)|-?\s*type:\s*(?:command|test))$"
)


def _audit_body(content: str) -> str:
    """Remove only a complete frontmatter block at the start of the file."""
    lines = content.splitlines()
    if lines and lines[0].strip() == "---":
        end = next((i for i in range(1, len(lines)) if lines[i].strip() == "---"), None)
        if end is not None:
            return "\n".join(lines[end + 1:])
    return content


def find_redundant_lines(specs: list) -> dict:
    line_map: dict = {}
    for spec in specs:
        for raw in _audit_body(spec["content"]).splitlines():
            line = normalize_line(raw)
            if not line:
                continue
            if line.startswith("#") or line == "---" or _YAML_STRUCTURE.fullmatch(line):
                continue
            if len(line) < 6:
                continue
            line_map.setdefault(line, set()).add(spec["path"])
    redundant = {line: paths for line, paths in line_map.items() if len(paths) >= 3}
    return redundant


def _audit_options(config: dict) -> tuple[list[str], int]:
    audit = config.get("audit", {})
    if not isinstance(audit, dict):
        raise ValueError("audit must be a mapping")
    roots = audit.get("path_roots", [])
    if not isinstance(roots, list) or any(not isinstance(root, str) or not root for root in roots):
        raise ValueError("audit.path_roots must be a list of paths")
    maximum = audit.get("long_spec_tokens", 500)
    if type(maximum) is not int or maximum <= 0:
        raise ValueError("audit.long_spec_tokens must be a positive integer")
    return roots, maximum


def _audit_roots(project_root: str, configured: list[str]) -> tuple[list[str], list[dict[str, str]]]:
    project = Path(project_root).resolve()
    roots: list[str] = []
    warnings: list[dict[str, str]] = []
    discovered = [path for pattern in ("apps/*/src/*", "packages/*/src/*", "lib/*/src/*")
                  for path in sorted(glob.glob(str(project / pattern)))]
    for value in [*configured, *discovered]:
        candidate = (project / value).resolve()
        if (candidate != project and project not in candidate.parents) or not candidate.is_dir() or not os.access(candidate, os.R_OK | os.X_OK):
            if value in configured:
                warnings.append({"code": "invalid_path_root", "path": value})
            continue
        resolved = str(candidate)
        if resolved not in roots:
            roots.append(resolved)
    return roots, warnings


def _path_resolution(text: str, project_root: str, base_dir: str,
                     roots: list[str]) -> tuple[list[str], dict[str, str]]:
    missing: list[str] = []
    resolved: dict[str, str] = {}
    project = Path(project_root).resolve()
    for token in _path_tokens(text):
        candidates = [str(project), base_dir, *roots]
        if os.path.isabs(token):
            candidates = [""]
        for root in candidates:
            if root and not Path(root).is_dir():
                continue
            target = Path(os.path.join(root, token)).resolve()
            if not os.path.isabs(token) and target != project and project not in target.parents:
                continue
            if target.exists():
                resolved[token] = os.path.relpath(root, project) if root else "/"
                break
        else:
            missing.append(token)
    return missing, resolved


def _path_tokens(text: str) -> list[str]:
    tokens: set[str] = set()
    for word in re.findall(r"[^\s`<>()\"']+", text):
        if "://" in word or any(char in word for char in "*?{}[]"):
            continue
        tokens.update(PATH_PATTERN.findall(word))
    return sorted(tokens)


def find_missing_paths(text: str, project_root: str, base_dir: str = "") -> list:
    """路径引用检查：项目根解析失败时，再按 spec 自身目录二次解析——
    _map.md 常用相对本域目录的引用（如 design/design-lite.md）。"""
    return _path_resolution(text, project_root, base_dir, [])[0]


def build_report(project_root: str, platform: str = "") -> dict:
    """规范质量审计数据（cf-scan 引擎，亦供 cf-stats --audit 复用）。

    files 含 issues / template 标记，review 为待复审清单；展示层负责过滤与渲染。"""
    files = []
    total_tokens = 0

    instruction_file = project_instruction_file(project_root, platform)
    claude_path = os.path.join(project_root, instruction_file)
    if os.path.exists(claude_path):
        content = read_text(claude_path)
        tokens = estimate_tokens(content)
        total_tokens += tokens
        files.append({"path": instruction_file, "tokens": tokens, "issues": []})

    specs_root = os.path.join(project_root, ".code-flow", "specs")
    specs = []
    if os.path.isdir(specs_root):
        for root, _, filenames in os.walk(specs_root):
            for name in filenames:
                if not name.endswith(".md"):
                    continue
                full_path = os.path.join(root, name)
                rel = os.path.relpath(full_path, specs_root)
                if rel.replace(os.sep, "/").startswith("_session/"):
                    continue
                content = read_text(full_path)
                if not content:
                    continue
                tokens = estimate_tokens(content)
                total_tokens += tokens
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
    configured_roots, long_spec_tokens = _audit_options(config)
    roots, audit_warnings = _audit_roots(project_root, configured_roots)
    effective_mapping = build_effective_mapping(
        project_root, config.get("path_mapping") or {}
    )
    excluded_specs = non_injectable_specs(effective_mapping)
    for spec in specs:
        spec["template"] = spec.get("rel", "") in excluded_specs

    redundant_map = find_redundant_lines([s for s in specs if not s["template"]])

    for spec in specs:
        issues = []
        if not spec["template"] and spec["tokens"] > long_spec_tokens:
            issues.append(f"冗长: {spec['tokens']} tokens")

        spec_dir = os.path.join(specs_root, os.path.dirname(spec.get("rel", "")))
        missing_paths, resolved_paths = _path_resolution(spec["content"], project_root, spec_dir, roots)
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
            "resolved_paths": resolved_paths,
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
        "audit_warnings": audit_warnings,
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
