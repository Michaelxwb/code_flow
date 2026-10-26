"""Programmatic validation entry with complete Git scope and argv execution."""
from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
from typing import IO, Optional, Sequence
import sys
import time

from cf_exec_base import execution_session
from cf_spec_context import _git_changes, current_owned_paths, load_active_task
from cf_validators import PARSE_ERROR, VALID, ValidatorConfig, is_heavy, resolve_validators, run_validators


_MANAGED_PREFIXES = (".code-flow/", ".claude/", ".codex/", ".costrict/", ".opencode/", ".agents/")


def _is_managed(path: str) -> bool:
    return path.startswith(_MANAGED_PREFIXES)


def validation_scope(root: str, files: Sequence[str] = ()) -> tuple[str, ...]:
    base = Path(root).resolve()
    if files:
        selected = []
        for name in files:
            path = (base / name).resolve()
            if base not in path.parents:
                raise ValueError(f"validation path outside project: {name}")
            relative = path.relative_to(base).as_posix()
            if _is_managed(relative):
                continue
            selected.append(relative)
        return tuple(sorted(set(selected)))
    # Tool-managed trees (deployed hooks/commands/plugins) are not project
    # source: validating them makes template validators (eslint/vitest/mypy)
    # fire on every install and blocks verify-e2e for unrelated stacks.
    if (base / ".code-flow/.active-task.json").exists():
        scoped = current_owned_paths(str(base), load_active_task(str(base)))
    else:
        scoped = tuple(sorted(_git_changes(str(base))))
    return tuple(sorted(item for item in scoped if not _is_managed(item)))


def validate_files(root: str, files: Sequence[str] = (), budget: Optional[float] = None,
                   include_heavy: bool = True, use_cache: bool = True) -> dict[str, object]:
    selected = validation_scope(root, files)
    config, effective = resolve_validators(root)
    if config.state == PARSE_ERROR:
        return {"decision": "block", "files": selected, "reason": "invalid_validation_config",
                "error": config.error}
    validators = list(effective)
    if not include_heavy:
        validators = [item for item in validators if not is_heavy(item)]
    if not selected:
        return {"decision": "pass", "files": [], "reason": "no_changes"}
    if not validators:
        return {"decision": "block", "files": selected, "reason": "no_validators_configured"}
    maximum = budget if budget is not None else sum(float(v.get("timeout", 30000)) / 1000 for v in validators)
    if not math.isfinite(maximum) or maximum <= 0:
        raise ValueError("validation budget must be finite and positive")
    with execution_session():
        outcome = run_validators(root, ValidatorConfig(VALID, tuple(validators)), list(selected),
                                 "cf-validate", time.monotonic() + maximum, strict=True, cache=use_cache)
    return {"decision": "block" if outcome.failures or outcome.truncated else "pass", "files": selected,
            "failures": outcome.failures, "incomplete": outcome.truncated, "reused": outcome.reused}


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


if __name__ == "__main__":
    raise SystemExit(main())
