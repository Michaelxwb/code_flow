#!/usr/bin/env python3
"""CLI wrapper for the fail-closed Spec Context Stage Gate."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import time
from typing import IO, Optional, Sequence

from codeflow.core.cf_core import phase_timing
from codeflow.spec.cf_spec_context_model import load_context
from codeflow.spec.cf_stage_gate import (
    GateIssue, GateResult, evidence_deferral_kind, result_to_data, validate_plan_coverage, validate_stage,
)


def _merge_results(first: GateResult, second: GateResult) -> GateResult:
    errors = (*first.errors, *second.errors)
    warnings = (*first.warnings, *second.warnings)
    refs = tuple(sorted(set((*first.affected_refs, *second.affected_refs))))
    return GateResult("block" if errors else "pass", errors, warnings, refs)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog=os.environ.get("CF_RUNTIME_COMMAND", "cf_spec_gate.py"))
    parser.add_argument("--task-dir", required=True)
    parser.add_argument("--stage", required=True)
    parser.add_argument("--task", default="")
    parser.add_argument("--artifact", default="")
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: Optional[Sequence[str]] = None, stdout: IO[str] = sys.stdout) -> int:
    started = time.monotonic()
    try:
        args = _parser().parse_args(argv)
        phase_started = time.monotonic()
        context = load_context(str(Path(args.task_dir) / "spec-context.yml"))
        phase_timing("gate.load_context", phase_started)
        phase_started = time.monotonic()
        directory = Path(args.task_dir).resolve()
        root = next((parent.parent for parent in (directory, *directory.parents)
                     if parent.name == ".code-flow"), directory)
        result = validate_stage(context, args.stage, task_id=args.task, root=str(root), task_dir=args.task_dir)
        phase_timing("gate.validate_stage", phase_started)
        if args.stage == "plan" and args.artifact:
            phase_started = time.monotonic()
            result = _merge_results(result, validate_plan_coverage(context, args.artifact))
            phase_timing("gate.validate_plan", phase_started)
        stdout.write(json.dumps(result_to_data(result), ensure_ascii=False))
        phase_timing("gate.total", started)
        return 0 if result.decision == "pass" else 3
    except Exception as exc:
        sys.stderr.write(f"cf_spec_gate error: {exc}\n")
        stdout.write(json.dumps({"decision": "block", "errors": [{"code": "gate_error"}]}, ensure_ascii=False))
        return 2
