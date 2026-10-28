"""Programmatic validation entry with complete Git scope and argv execution."""
from __future__ import annotations

import argparse
import json
import os
from typing import IO, Optional, Sequence
import sys

from codeflow.task.cf_validation_service import validate_files, validation_scope


def main(argv: Optional[Sequence[str]] = None, stdout: IO[str] = sys.stdout) -> int:
    parser = argparse.ArgumentParser(prog=os.environ.get("CF_RUNTIME_COMMAND") or None)
    parser.add_argument("--root", default=os.getcwd())
    parser.add_argument("--files", nargs="*", default=[])
    parser.add_argument("--budget", type=float)
    parser.add_argument("--no-heavy", action="store_true", help="Skip heavy validators (task-level finish scope)")
    parser.add_argument("--no-cache", action="store_true", help="Force validators to run; skip content-fingerprint reuse")
    parser.add_argument("--scope-only", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = ({"files": validation_scope(args.root, args.files)} if args.scope_only
                  else validate_files(args.root, args.files, args.budget, include_heavy=not args.no_heavy,
                                      use_cache=not args.no_cache))
        stdout.write(json.dumps(result, ensure_ascii=False))
        return 3 if result.get("decision") == "block" else 0
    except (OSError, ValueError) as exc:
        stdout.write(json.dumps({"decision": "block", "error": str(exc)}, ensure_ascii=False))
        return 2
