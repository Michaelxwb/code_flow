#!/usr/bin/env python3
"""Command adapter for canonical acceptance scenario sources."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import IO, Optional, Sequence

import yaml

from codeflow.acceptance.cf_scenario_source import (
    E2E_CRITICAL_PRIORITIES, E2E_RATIO_WARNING, EXEC_MODES, LEVELS, PRIORITIES,
    SCENARIO_ID, SCHEMA_VERSION, ScenarioError, audit_scenario_source,
    load_requirement_scenarios, merge_scenarios, migrate_from_coverage,
    parse_scenarios, reconcile_coverage, require_source, scenario_status,
    validate_e2e_quality,
)


def main(argv: Optional[Sequence[str]] = None, stdout: IO[str] = sys.stdout) -> int:
    parser = argparse.ArgumentParser(prog=os.environ.get("CF_RUNTIME_COMMAND") or None)
    sub = parser.add_subparsers(dest="action", required=True)
    for name in ("parse", "merge"):
        command = sub.add_parser(name)
        command.add_argument("--file", action="append", required=True)
        command.add_argument("--quality", action="store_true",
                             help="run the E2E precision gate against the scenario source")
        command.add_argument("--json", action="store_true")
    migrate = sub.add_parser("migrate")
    migrate.add_argument("--task-file", required=True)
    migrate.add_argument("--output", default="")
    migrate.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.action == "migrate":
            from codeflow.acceptance.cf_acceptance_manifest_core import extract_manifest
            coverage = extract_manifest(args.task_file)["scenarios"]
            result = migrate_from_coverage(coverage)
            if args.output:
                text = "---\n" + yaml.safe_dump(result, sort_keys=False, allow_unicode=True) + "---\n"
                Path(args.output).write_text(text, encoding="utf-8")
            stdout.write(json.dumps(result, ensure_ascii=False))
            return 0
        sets = [parse_scenarios(path) for path in args.file]
        if args.action == "parse" and len(sets) > 1:
            raise ScenarioError("invalid_action", "parse 只接受一个文件；多文件用 merge")
        result = sets[0] if args.action == "parse" else {"schema": SCHEMA_VERSION, "scenarios": merge_scenarios(sets)}
        if args.quality:
            quality = validate_e2e_quality(result["scenarios"])
            result = {**result, "ok": quality["ok"], "quality": quality}
        stdout.write(json.dumps(result, ensure_ascii=False))
        return 0 if not args.quality or bool(result.get("ok")) else 3
    except ScenarioError as exc:
        stdout.write(json.dumps({"ok": False, "code": exc.code, "message": exc.message, "details": exc.details}, ensure_ascii=False))
        return 3
