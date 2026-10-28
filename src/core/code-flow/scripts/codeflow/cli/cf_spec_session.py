#!/usr/bin/env python3
"""CLI wrapper for TASK-bound Spec Context projection."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from typing import IO, Optional, Sequence

from codeflow.spec.cf_spec_context_model import context_sha256, load_context
from codeflow.spec.cf_task_projection import SessionProjection, project_task_session
from codeflow.task.cf_task_doc import task_section, task_spec_refs


def _task_section(text: str, task_id: str) -> str:
    return task_section(text, task_id).body


def _refs(section: str) -> tuple[str, ...]:
    return task_spec_refs(section)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog=os.environ.get("CF_RUNTIME_COMMAND", "cf_spec_session.py"))
    parser.add_argument("--task-dir", required=True)
    parser.add_argument("--task-file", required=True)
    parser.add_argument("--task", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--budget", type=int, default=12000)
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: Optional[Sequence[str]] = None, stdout: IO[str] = sys.stdout) -> int:
    try:
        args = _parser().parse_args(argv)
        context = load_context(str(Path(args.task_dir) / "spec-context.yml"))
        result = project_task_session(context, args.task_file, args.task, args.budget)
        Path(args.output).write_text(result.text, encoding="utf-8")
        stdout.write(json.dumps(result.__dict__, ensure_ascii=False))
        return 0
    except Exception as exc:
        stdout.write(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 3
