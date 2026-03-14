#!/usr/bin/env python3
import json
import os
import sys
import fnmatch

from cf_core import (
    assemble_context,
    load_config,
    load_inject_state,
    match_domains,
    read_specs,
    save_inject_state,
    select_specs,
)


def match_details(rel_path: str, mapping: dict) -> dict:
    details = {}
    for domain, cfg in (mapping or {}).items():
        patterns = cfg.get("patterns") or []
        for pattern in patterns:
            if fnmatch.fnmatch(rel_path, pattern):
                details[domain] = pattern
                break
    return details


def main() -> None:
    project_root = os.getcwd()
    config = load_config(project_root)
    if not config:
        print(json.dumps({"error": "config_missing"}, ensure_ascii=False))
        return

    mapping = config.get("path_mapping") or {}
    available_domains = sorted(mapping.keys())
    args = sys.argv[1:]
    list_specs = "--list-specs" in args
    list_domain = ""
    if list_specs:
        for arg in args:
            if arg.startswith("--domain="):
                list_domain = arg.split("=", 1)[1]
        if list_domain and list_domain in mapping:
            specs = (mapping.get(list_domain) or {}).get("specs") or []
            print(json.dumps({"domain": list_domain, "specs": specs}, ensure_ascii=False))
            return
        print(json.dumps({"error": "domain_not_found", "available_domains": available_domains}, ensure_ascii=False))
        return
    if not args:
        state_path = os.path.join(project_root, ".code-flow", ".inject-state")
        recent_target = ""
        try:
            with open(state_path, "r", encoding="utf-8") as file:
                data = json.load(file)
            recent_target = data.get("last_file", "")
        except Exception:
            recent_target = ""

        if not recent_target:
            print(
                json.dumps(
                    {
                        "error": "missing_target",
                        "available_domains": available_domains,
                        "usage": "cf-inject <domain|file_path>",
                    },
                    ensure_ascii=False,
                )
            )
            return
        target = recent_target
    else:
        target = args[0]
    match_info = {}
    if target in mapping:
        domains = [target]
    else:
        abs_path = target
        if not os.path.isabs(abs_path):
            abs_path = os.path.join(project_root, target)
        rel_path = os.path.relpath(abs_path, project_root)
        domains = match_domains(rel_path, mapping)
        match_info = match_details(rel_path, mapping)

    if not domains:
        print(
            json.dumps(
                {
                    "error": "domain_not_found",
                    "target": target,
                    "available_domains": available_domains,
                },
                ensure_ascii=False,
            )
        )
        return

    specs = []
    priorities = {}
    for domain in domains:
        domain_cfg = mapping.get(domain) or {}
        priorities.update(domain_cfg.get("spec_priority") or {})
        specs.extend(read_specs(project_root, domain, domain_cfg))

    if not specs:
        print(json.dumps({"error": "specs_empty", "domains": domains}, ensure_ascii=False))
        return

    budget_cfg = config.get("budget") or {}
    budget = budget_cfg.get("l1_max", 1700)
    try:
        budget = int(budget)
    except Exception:
        budget = 1700

    selected = select_specs(specs, budget, priorities)
    if not selected:
        print(json.dumps({"error": "budget_exceeded", "budget": budget}, ensure_ascii=False))
        return

    included_domains = {spec.get("domain") for spec in selected if spec.get("domain")}
    state = load_inject_state(project_root)
    injected_domains = state.get("injected_domains") or []
    if not isinstance(injected_domains, list):
        injected_domains = []
    injected_domains = {d for d in injected_domains if isinstance(d, str)}
    state_payload = {"injected_domains": sorted(injected_domains | included_domains)}
    state_payload["last_file"] = target
    save_inject_state(project_root, state_payload)

    total_tokens = sum(spec.get("tokens", 0) for spec in selected)
    output = {
        "domains": sorted(included_domains),
        "selected_specs": [
            {"path": spec["path"], "tokens": spec["tokens"]} for spec in selected
        ],
        "total_tokens": total_tokens,
        "budget": budget,
        "context": assemble_context(selected, "## Active Specs"),
    }
    if os.environ.get("CF_DEBUG") == "1":
        output["match_info"] = match_info
        output["target"] = target
    print(json.dumps(output, ensure_ascii=False))


if __name__ == "__main__":
    main()
