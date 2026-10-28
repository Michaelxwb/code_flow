"""Validation scope and execution shared by task verification and CLI."""
from __future__ import annotations

import math
from pathlib import Path
import time
from typing import Optional, Sequence

from codeflow.core import cf_git
from codeflow.core.cf_exec_base import execution_session
from codeflow.core.cf_validators import PARSE_ERROR, VALID, ValidatorConfig, is_heavy, resolve_validators, run_validators
from codeflow.spec.cf_active_task import current_owned_paths, load_active_task


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
        scoped = tuple(sorted(cf_git.changed_files(str(base))))
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
