#!/usr/bin/env python3
import json
import os
import sys

from cf_core import estimate_tokens, load_config


def read_text(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8") as file:
            return file.read().strip()
    except Exception:
        return ""


def main() -> None:
    project_root = os.getcwd()
    config = load_config(project_root)
    budget_cfg = config.get("budget") or {}

    human_output = "--human" in sys.argv
    json_output = not human_output
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
    specs_root = os.path.join(project_root, ".code-flow", "specs")
    spec_domain_map = {}
    missing_specs = []
    domains_with_no_loaded_specs = []

    for domain, domain_cfg in (config.get("path_mapping") or {}).items():
        if domain_filter and domain_filter != domain:
            continue

        items = []
        specs_config = domain_cfg.get("specs") or []
        configured_count = 0

        for spec_entry in specs_config:
            rel = spec_entry["path"] if isinstance(spec_entry, dict) else spec_entry
            if not rel:
                continue
            configured_count += 1
            spec_domain_map[rel] = domain
            full_path = os.path.join(specs_root, rel)
            if not os.path.exists(full_path):
                missing_specs.append({"domain": domain, "path": rel})
                continue
            content = read_text(full_path)
            if not content:
                continue
            tokens = estimate_tokens(content)
            items.append({"path": rel, "tokens": tokens})
            total_tokens += tokens

        if items:
            l1[domain] = items
        elif configured_count > 0:
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

    output = {
        "l0": {"file": "CLAUDE.md", "tokens": l0_tokens, "budget": l0_budget},
        "l1": l1,
        "total_tokens": total_tokens,
        "total_budget": total_budget,
        "utilization": utilization,
        "warnings": warnings,
        "spec_domain_map": spec_domain_map,
        "missing_specs": missing_specs,
    }
    if json_output:
        print(json.dumps(output, ensure_ascii=False))
        return

    print("L0 (CLAUDE.md):", f"{l0_tokens} / {l0_budget}")
    for domain, items in l1.items():
        total_domain = sum(item["tokens"] for item in items)
        print(f"L1 {domain}:", total_domain)
        for item in items:
            print(" -", item["path"], item["tokens"])
    if missing_specs:
        print("MISSING SPECS:")
        for item in missing_specs:
            print(" -", item["domain"], item["path"])
    print("TOTAL:", f"{total_tokens} / {total_budget}")
    print("UTILIZATION:", utilization)
    if warnings:
        print("WARNINGS:", "; ".join(warnings))


if __name__ == "__main__":
    main()
