#!/usr/bin/env python3
import json
import os
import sys

from cf_core import (
    assemble_context,
    is_code_file,
    load_config,
    load_inject_state,
    match_domains,
    read_specs,
    save_inject_state,
    select_specs,
)


def main() -> None:
    try:
        raw = sys.stdin.read()
        if not raw.strip():
            return
        data = json.loads(raw)
        tool_name = data.get("tool_name", "")
        tool_input = data.get("tool_input") or {}
        file_path = tool_input.get("file_path", "")
        if tool_name not in {"Edit", "Write", "MultiEdit"}:
            return
        if not isinstance(file_path, str) or not file_path:
            return

        project_root = os.getcwd()
        abs_path = file_path
        if not os.path.isabs(abs_path):
            abs_path = os.path.join(project_root, file_path)
        rel_path = os.path.relpath(abs_path, project_root)

        config = load_config(project_root)
        if not config:
            return
        inject_config = config.get("inject") or {}
        if inject_config.get("auto") is False:
            return
        if not is_code_file(rel_path, inject_config):
            return

        mapping = config.get("path_mapping") or {}
        domains = match_domains(rel_path, mapping)
        if not domains:
            return

        state = load_inject_state(project_root)
        injected_domains = state.get("injected_domains") or []
        if not isinstance(injected_domains, list):
            injected_domains = []
        injected_domains = {d for d in injected_domains if isinstance(d, str)}
        new_domains = [domain for domain in domains if domain not in injected_domains]
        if not new_domains:
            state_payload = {"injected_domains": sorted(injected_domains)}
            state_payload["last_file"] = abs_path
            save_inject_state(project_root, state_payload)
            return

        specs = []
        priorities = {}
        for domain in new_domains:
            domain_cfg = mapping.get(domain) or {}
            priorities.update(domain_cfg.get("spec_priority") or {})
            specs.extend(read_specs(project_root, domain, domain_cfg))

        if not specs:
            return

        budget_cfg = config.get("budget") or {}
        budget = budget_cfg.get("l1_max", 1700)
        try:
            budget = int(budget)
        except Exception:
            budget = 1700

        selected = select_specs(specs, budget, priorities)
        if not selected:
            return

        included_domains = {spec.get("domain") for spec in selected if spec.get("domain")}
        state_payload = {"injected_domains": sorted(injected_domains | included_domains)}
        state_payload["last_file"] = abs_path
        save_inject_state(project_root, state_payload)

        payload = {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "additionalContext": assemble_context(selected, "## Active Specs (auto-injected)"),
            }
        }
        if os.environ.get("CF_DEBUG") == "1":
            payload["debug"] = {
                "target": abs_path,
                "domains": sorted(new_domains),
            }
        sys.stdout.write(json.dumps(payload))
    except Exception:
        return


if __name__ == "__main__":
    main()
