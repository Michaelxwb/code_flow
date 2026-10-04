#!/usr/bin/env python3
"""cf_feedback: mark a check as false positive (FEAT-02 对话即反馈).

The violation feedback text tells the user "误报可直接告诉我"; the agent then
runs this CLI on the user's behalf — no new slash command, no config editing.

Usage: python3 cf_feedback.py ignore <check-id>
Exit codes: 0 = recorded / 1 = usage error / 2 = unknown check id.
stdout: one JSON line {"check_id", "fp_count", "hit_count", "disabled"}.
"""
import json
import argparse
import os
import sys

from cf_checks import load_check_state, load_spec_checks, record_false_positive
from cf_core import build_effective_mapping, load_config, normalize_spec_entry
from cf_log import append_event


def known_check_ids(project_root: str) -> set[str]:
    """All check ids: declared in any configured spec, or already in state."""
    ids = set(load_check_state(project_root).keys())
    config = load_config(project_root)
    mapping = build_effective_mapping(
        project_root, (config or {}).get("path_mapping") or {}
    )
    specs_root = os.path.join(project_root, ".code-flow", "specs")
    for domain_cfg in mapping.values():
        for entry in (domain_cfg or {}).get("specs") or []:
            rel = normalize_spec_entry(entry).get("path")
            if not rel:
                continue
            checks, _ = load_spec_checks(os.path.join(specs_root, rel))
            ids.update(check["id"] for check in checks)
    return ids


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog=os.environ.get("CF_RUNTIME_COMMAND", "cf_feedback.py"))
    parser.add_argument("action", choices=("ignore",), metavar=os.environ.get("CF_RUNTIME_ACTION") or None)
    parser.add_argument("check_id")
    check_id = parser.parse_args(argv).check_id
    project_root = os.getcwd()
    if check_id not in known_check_ids(project_root):
        sys.stderr.write(f"unknown check id: {check_id}\n")
        return 2
    append_event(
        project_root, "false_positive", {"check_id": check_id}, "cf-feedback"
    )
    result = record_false_positive(project_root, check_id)
    sys.stdout.write(json.dumps(result, ensure_ascii=False) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
