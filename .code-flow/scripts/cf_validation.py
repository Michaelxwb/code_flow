"""Programmatic validation entry with complete Git scope and argv execution."""
from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
from typing import IO, Optional, Sequence
import sys

from cf_exec_base import execution_session
from cf_spec_context import _git_changes, current_owned_paths, load_active_task


def validation_scope(root: str, files: Sequence[str] = ()) -> tuple[str, ...]:
    base = Path(root).resolve()
    if files:
        selected = []
        for name in files:
            path = (base / name).resolve()
            if base not in path.parents:
                raise ValueError(f"validation path outside project: {name}")
            selected.append(path.relative_to(base).as_posix())
        return tuple(sorted(set(selected)))
    if (base / ".code-flow/.active-task.json").exists():
        return current_owned_paths(str(base), load_active_task(str(base)))
    return tuple(sorted(_git_changes(str(base))))


def _validators(root: str) -> list[dict[str, object]]:
    from cf_stop_hook import load_validators
    if (Path(root) / ".code-flow/validation.yml").is_file():
        return load_validators(root)
    package = Path(root) / "package.json"
    if not package.is_file():
        return []
    data = json.loads(package.read_text(encoding="utf-8"))
    scripts = data.get("scripts", {}) if isinstance(data, dict) else {}
    if not isinstance(scripts, dict):
        raise ValueError("invalid package scripts")
    return [{"name": name, "trigger": "*", "command": f"npm run {name}", "timeout": 60000}
            for name in ("test", "lint") if isinstance(scripts.get(name), str)]


def validate_files(root: str, files: Sequence[str] = (), budget: Optional[float] = None) -> dict[str, object]:
    from cf_stop_hook import run_validators
    selected = validation_scope(root, files)
    validators = _validators(root)
    if not selected:
        return {"decision": "pass", "files": [], "reason": "no_changes"}
    if not validators:
        return {"decision": "block", "files": selected, "reason": "no_validators_configured"}
    maximum = budget if budget is not None else sum(float(v.get("timeout", 30000)) / 1000 for v in validators)
    if not math.isfinite(maximum) or maximum <= 0:
        raise ValueError("validation budget must be finite and positive")
    with execution_session():
        failures, truncated = run_validators(root, validators, list(selected), "cf-validate", maximum, strict=True)
    return {"decision": "block" if failures or truncated else "pass", "files": selected,
            "failures": failures, "incomplete": truncated}


def main(argv: Optional[Sequence[str]] = None, stdout: IO[str] = sys.stdout) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=os.getcwd())
    parser.add_argument("--files", nargs="*", default=[])
    parser.add_argument("--budget", type=float)
    parser.add_argument("--scope-only", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = {"files": validation_scope(args.root, args.files)} if args.scope_only else validate_files(args.root, args.files, args.budget)
        stdout.write(json.dumps(result, ensure_ascii=False))
        return 3 if result.get("decision") == "block" else 0
    except (OSError, ValueError) as exc:
        stdout.write(json.dumps({"decision": "block", "error": str(exc)}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
