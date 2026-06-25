#!/usr/bin/env python3
import json
import os
import sys
from typing import Optional

import cf_log
from cf_checks import load_check_state
from cf_core import (
    build_effective_mapping,
    build_spec_catalog,
    compress_content,
    estimate_tokens,
    load_config,
    non_injectable_specs,
    resolve_inject_mode,
    resolve_quality_loop,
)


def _violation_fixed(index: int, events: list) -> bool:
    """修正口径：违规后同会话同文件有后续编辑，且其后无同 check 再违规。

    用日志追加顺序判先后（ts 仅秒级精度，同秒事件无法靠时间戳排序）。
    """
    violation = events[index]
    v_data = violation.get("data") or {}
    later_edit = False
    for event in events[index + 1:]:
        if event.get("sid") != violation.get("sid"):
            continue
        data = event.get("data") or {}
        if event.get("event") == "edit" and data.get("file") == v_data.get("file"):
            later_edit = True
        if (
            later_edit
            and event.get("event") == "violation"
            and data.get("check_id") == v_data.get("check_id")
            and data.get("file") == v_data.get("file")
        ):
            return False
    return later_edit


def quality_loop_summary(project_root: str, config: dict) -> dict:
    """FEAT-05/02 度量聚合：Top 违规榜 / 修正率 / 误报与停用 / 降级组件。"""
    switches = resolve_quality_loop(config)
    events = cf_log.read_events(project_root, days=30)
    summary = {"switches": switches, "window_days": 30}
    if not events:
        summary["note"] = "暂无数据"
        return summary

    violations = [e for e in events if e.get("event") == "violation"]
    counts: dict = {}
    for v in violations:
        data = v.get("data") or {}
        key = f"{data.get('spec', '?')}#{data.get('check_id', '?')}"
        counts[key] = counts.get(key, 0) + 1
    summary["top_violations"] = sorted(
        ({"rule": k, "count": n} for k, n in counts.items()),
        key=lambda item: -item["count"],
    )[:10]

    fixed = sum(
        1 for i, event in enumerate(events)
        if event.get("event") == "violation" and _violation_fixed(i, events)
    )
    summary["violation_total"] = len(violations)
    summary["fix_rate"] = (
        f"{round(fixed * 100 / len(violations))}%" if violations else "n/a"
    )

    state = load_check_state(project_root)
    summary["checks"] = {
        cid: {
            "hit_count": entry.get("hit_count", 0),
            "fp_count": entry.get("fp_count", 0),
            "disabled": bool(entry.get("disabled")),
            "disabled_reason": entry.get("disabled_reason", ""),
        }
        for cid, entry in state.items()
        if isinstance(entry, dict) and not cid.startswith("_")
    }

    degraded: dict = {}
    for event in events:
        if event.get("event") != "degrade":
            continue
        data = event.get("data") or {}
        component = data.get("component", "?")
        item = degraded.setdefault(component, {"count": 0, "last_error": ""})
        item["count"] += 1
        item["last_error"] = data.get("error", "")
    summary["degraded"] = degraded
    return summary


def read_text(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8") as file:
            return file.read().strip()
    except Exception:
        return ""


def normalize_rel_path(path: str) -> str:
    return path.replace(os.sep, "/")


def extract_spec_path(spec_entry) -> str:
    if isinstance(spec_entry, dict):
        return normalize_rel_path(spec_entry.get("path", ""))
    if isinstance(spec_entry, str):
        return normalize_rel_path(spec_entry)
    return ""


def discover_specs(specs_root: str) -> dict:
    discovered = {}
    if not os.path.isdir(specs_root):
        return discovered

    for root, _, files in os.walk(specs_root):
        for filename in files:
            if not filename.endswith(".md"):
                continue
            full_path = os.path.join(root, filename)
            rel = normalize_rel_path(os.path.relpath(full_path, specs_root))
            parts = rel.split("/", 1)
            if len(parts) < 2:
                continue
            domain = parts[0]
            discovered.setdefault(domain, []).append(rel)

    for domain in discovered:
        discovered[domain] = sorted(set(discovered[domain]))
    return discovered


def configured_specs(config: dict, domain: str) -> list:
    mapping = (config.get("path_mapping") or {}).get(domain) or {}
    specs_config = mapping.get("specs") or []
    result = []
    for spec_entry in specs_config:
        rel = extract_spec_path(spec_entry)
        if rel:
            result.append(rel)
    return result


def resolve_domains(config: dict, discovered: dict, domain_filter: Optional[str]) -> list:
    if domain_filter:
        if domain_filter in discovered:
            return [domain_filter]
        if domain_filter in (config.get("path_mapping") or {}):
            return [domain_filter]
        return []

    if discovered:
        return sorted(discovered.keys())
    return sorted((config.get("path_mapping") or {}).keys())


def _build_item(rel: str, raw_content: str) -> dict:
    raw_tokens = estimate_tokens(raw_content)
    compressed_tokens = estimate_tokens(compress_content(raw_content))
    saved_pct = (
        round((raw_tokens - compressed_tokens) * 100 / raw_tokens, 1)
        if raw_tokens
        else 0.0
    )
    return {
        "path": rel,
        "tokens": compressed_tokens,
        "tokens_raw": raw_tokens,
        "tokens_compressed": compressed_tokens,
        "saved_pct": saved_pct,
    }


def collect_domain_items(
    specs_root: str,
    domain: str,
    configured: list,
    discovered: list,
) -> tuple:
    items = []
    missing = []
    seen = set()

    for rel in configured:
        if rel in seen:
            continue
        seen.add(rel)
        full_path = os.path.join(specs_root, rel)
        if not os.path.exists(full_path):
            missing.append({"domain": domain, "path": rel})
            continue
        content = read_text(full_path)
        if content:
            items.append(_build_item(rel, content))

    for rel in discovered:
        if rel in seen:
            continue
        seen.add(rel)
        full_path = os.path.join(specs_root, rel)
        content = read_text(full_path)
        if content:
            items.append(_build_item(rel, content))

    return items, missing


def main() -> None:
    project_root = os.getcwd()
    config = load_config(project_root)
    budget_cfg = config.get("budget") or {}

    human_output = "--human" in sys.argv
    json_output = not human_output
    audit_mode = "--audit" in sys.argv
    domain_filter = None
    for arg in sys.argv[1:]:
        if arg.startswith("--domain="):
            domain_filter = arg.split("=", 1)[1]

    l0_budget = budget_cfg.get("l0_max", 800)
    l1_budget = budget_cfg.get("l1_max", 1700)
    total_budget = budget_cfg.get("total", l0_budget + l1_budget)

    try:
        l0_budget = int(l0_budget)
    except Exception:
        l0_budget = 800
    try:
        total_budget = int(total_budget)
    except Exception:
        total_budget = l0_budget + l1_budget

    claude_path = os.path.join(project_root, "CLAUDE.md")
    l0_tokens = 0
    if os.path.exists(claude_path):
        l0_tokens = estimate_tokens(read_text(claude_path))

    l1 = {}
    total_tokens = l0_tokens
    templates_tokens = 0
    specs_root = os.path.join(project_root, ".code-flow", "specs")
    spec_domain_map = {}
    missing_specs = []
    domains_with_no_loaded_specs = []
    discovered = discover_specs(specs_root)
    domains = resolve_domains(config, discovered, domain_filter)
    config_fallback_mode = not discovered

    effective_mapping = build_effective_mapping(
        project_root, config.get("path_mapping") or {}
    )
    excluded_specs = non_injectable_specs(effective_mapping)

    for domain in domains:
        configured = configured_specs(config, domain)
        discovered_paths = discovered.get(domain, [])
        items, missing = collect_domain_items(specs_root, domain, configured, discovered_paths)

        for rel in configured:
            if not rel:
                continue
            spec_domain_map[rel] = domain
        for rel in discovered_paths:
            spec_domain_map[rel] = domain

        missing_specs.extend(missing)

        for item in items:
            item["injectable"] = item["path"] not in excluded_specs
        if items:
            l1[domain] = items
            total_tokens += sum(i["tokens"] for i in items if i["injectable"])
            templates_tokens += sum(i["tokens"] for i in items if not i["injectable"])
        elif configured and (config_fallback_mode or discovered_paths):
            domains_with_no_loaded_specs.append(domain)

    utilization = "0%"
    if total_budget:
        utilization = f"{round(total_tokens * 100 / total_budget)}%"

    warnings = []
    if l0_tokens > l0_budget:
        warnings.append("L0 超出预算")
    l1_tokens = total_tokens - l0_tokens
    if l1_tokens > l1_budget:
        warnings.append("L1 超出预算")
    if total_tokens > total_budget:
        warnings.append("总预算超出")
    if missing_specs:
        warnings.append(f"配置的 spec 文件缺失: {len(missing_specs)} 个")
    if domains_with_no_loaded_specs:
        domains_text = ", ".join(sorted(set(domains_with_no_loaded_specs)))
        warnings.append(f"以下域未加载到任何 L1 spec: {domains_text}")

    total_raw = sum(
        item.get("tokens_raw", item["tokens"])
        for items in l1.values()
        for item in items
        if item.get("injectable", True)
    )
    total_compressed = sum(
        item.get("tokens_compressed", item["tokens"])
        for items in l1.values()
        for item in items
        if item.get("injectable", True)
    )
    total_saved_pct = (
        round((total_raw - total_compressed) * 100 / total_raw, 1)
        if total_raw
        else 0.0
    )
    compression_summary = {
        "total_raw": total_raw,
        "total_compressed": total_compressed,
        "total_saved_pct": total_saved_pct,
    }

    inject_mode = resolve_inject_mode(config.get("inject") or {})
    try:
        catalog_max = int(budget_cfg.get("catalog_max", 200))
    except Exception:
        catalog_max = 200
    catalog_text = build_spec_catalog(project_root, effective_mapping, catalog_max)
    catalog_summary = {
        "mode": inject_mode,
        "tokens": estimate_tokens(catalog_text),
        "budget": catalog_max,
        "entries": catalog_text.count("\n- `"),
    }

    ql_summary = quality_loop_summary(project_root, config)

    output = {
        "l0": {"file": "CLAUDE.md", "tokens": l0_tokens, "budget": l0_budget},
        "l1": l1,
        "total_tokens": total_tokens,
        "total_budget": total_budget,
        "utilization": utilization,
        "warnings": warnings,
        "spec_domain_map": spec_domain_map,
        "missing_specs": missing_specs,
        "compression_summary": compression_summary,
        "catalog": catalog_summary,
        "quality_loop": ql_summary,
        "templates": {
            "tokens": templates_tokens,
            "files": sorted(excluded_specs),
            "note": "tags:[] 命令专用模板，永不自动注入，不计预算",
        },
    }
    if audit_mode:
        from cf_scan import build_report
        scan = build_report(project_root)
        output["audit"] = {
            "files": [e for e in scan["files"] if e.get("issues")],
            "review": scan["review"],
        }

    if json_output:
        print(json.dumps(output, ensure_ascii=False))
        return

    print("L0 (CLAUDE.md):", f"{l0_tokens} / {l0_budget}")
    for domain, items in l1.items():
        total_domain = sum(i["tokens"] for i in items if i.get("injectable", True))
        print(f"L1 {domain}:", total_domain)
        for item in items:
            raw = item.get("tokens_raw", item["tokens"])
            compressed = item.get("tokens_compressed", item["tokens"])
            saved = item.get("saved_pct", 0.0)
            suffix = "" if item.get("injectable", True) else "（模板，不计预算）"
            print(" -", item["path"], item["tokens"],
                  f"(raw={raw}→compressed={compressed}, -{saved}%)" + suffix)
    if templates_tokens:
        print("TEMPLATES (非注入):", f"{templates_tokens} tokens，不计预算")
    if missing_specs:
        print("MISSING SPECS:")
        for item in missing_specs:
            print(" -", item["domain"], item["path"])
    print("TOTAL:", f"{total_tokens} / {total_budget}")
    print("UTILIZATION:", utilization)
    print(
        "COMPRESSION:",
        f"{total_raw} → {total_compressed} (-{total_saved_pct}%)",
    )
    print(
        "CATALOG:",
        f"mode={inject_mode},",
        f"{catalog_summary['tokens']} / {catalog_max} tokens,",
        f"{catalog_summary['entries']} entries",
    )
    switches = ql_summary["switches"]
    print("QUALITY-LOOP:", "enabled" if switches["enabled"] else "disabled")
    if ql_summary.get("note"):
        print(" -", ql_summary["note"])
    else:
        print(
            " - violations:", ql_summary.get("violation_total", 0),
            "| fix_rate:", ql_summary.get("fix_rate", "n/a"),
        )
        for item in ql_summary.get("top_violations", [])[:5]:
            print("   ·", item["rule"], item["count"])
        for cid, info in ql_summary.get("checks", {}).items():
            if info["disabled"] or info["fp_count"]:
                print(
                    f"   · {cid}: hits={info['hit_count']} fp={info['fp_count']}"
                    + (f" DISABLED({info['disabled_reason']})" if info["disabled"] else "")
                )
        for component, info in ql_summary.get("degraded", {}).items():
            print(f"   · degraded {component}: {info['count']} ({info['last_error']})")
    if warnings:
        print("WARNINGS:", "; ".join(warnings))

    if audit_mode:
        audit = output["audit"]
        print("AUDIT (规范质量):")
        if not audit["files"] and not audit["review"]:
            print(" - 无问题")
        for entry in audit["files"]:
            print(" -", entry["path"], "|", " / ".join(entry["issues"]))
        if audit["review"]:
            print(" REVIEW (待复审):")
            for item in audit["review"]:
                print(f"   · {item['item']}: {item['reason']}")
    else:
        print("AUDIT: 运行 cf-stats --audit 查看规范质量问题与待复审清单")


if __name__ == "__main__":
    main()
