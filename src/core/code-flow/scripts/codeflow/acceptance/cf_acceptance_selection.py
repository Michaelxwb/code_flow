"""Shared owner, profile and dependency selection for acceptance scenarios."""
from __future__ import annotations

from dataclasses import dataclass
import subprocess
from typing import Callable, Mapping, Optional, Sequence

from codeflow.acceptance.cf_acceptance_schema import scenario_check_ids
from codeflow.acceptance.cf_check_inputs import match_path


def select_owned(items: list[Mapping[str, object]], owner: str) -> list[Mapping[str, object]]:
    """Keep scenarios owned by the active TASK; ownerless legacy scenarios stay
    included so old manifests keep working. Cross-TASK depends_on edges are
    pruned: single-TASK ordering is enforced here, whole-demand ordering at
    the final (archive/E2E) gate."""
    if not owner:
        return items
    # 逗号分隔时按多个 owner 过滤：批次 smoke 只跑本批已并入 TASK 的场景。
    owners = {value.strip() for value in owner.split(",") if value.strip()}
    kept = [
        item for item in items
        if not isinstance(item.get("owner"), str) or not item.get("owner") or item.get("owner") in owners
    ]
    kept_ids = {str(item.get("id")) for item in kept}
    pruned: list[Mapping[str, object]] = []
    for item in kept:
        if not isinstance(item, dict):
            pruned.append(item)
            continue
        deps = item.get("depends_on")
        if isinstance(deps, list):
            item = {**item, "depends_on": [dep for dep in deps if str(dep) in kept_ids]}
        pruned.append(item)
    return pruned


def changed_paths(root: str) -> set[str]:
    changed: set[str] = set()
    for arguments in (("diff", "--name-only", "HEAD"), ("ls-files", "--others", "--exclude-standard")):
        completed = subprocess.run(("git", "-C", root, *arguments), text=True, capture_output=True, check=False)
        if completed.returncode == 0:
            changed.update(line.strip() for line in completed.stdout.splitlines() if line.strip())
    return changed


@dataclass(frozen=True)
class _ProfileContext:
    """Manifest-wide facts shared by every per-scenario selection rule."""

    checks: Mapping[str, Mapping[str, object]]
    changed: frozenset[str]
    scenarios: tuple[Mapping[str, object], ...]
    explicit_priority: bool
    forced: frozenset[str]
    has_smoke_profile: bool
    has_e2e: bool
    e2e_smoke_exists: bool


@dataclass(frozen=True)
class _ScenarioFacts:
    """Per-scenario facts computed once, then consumed by the rule tables."""

    scenario_id: str
    priority: str
    is_e2e: bool
    smoke: bool
    check_ids: tuple[str, ...]
    scenario_checks: tuple[Optional[Mapping[str, object]], ...]
    path_patterns: tuple[str, ...]
    path_matches: bool
    repo_scoped: bool
    inputs_match: bool


_RuleTable = tuple[tuple[Callable[["_ProfileContext", "_ScenarioFacts"], bool],
                          Callable[["_ProfileContext", "_ScenarioFacts"], bool]], ...]


# Ordered (condition, decision) rules. The first matching condition decides
# whether the scenario runs; later rules are not consulted. Explicit smoke
# markers on E2E journeys keep smoke from silently expanding to every E2E.
_SMOKE_RULES: _RuleTable = (
    (lambda ctx, facts: facts.is_e2e,
     lambda ctx, facts: facts.smoke or not ctx.e2e_smoke_exists),
    (lambda ctx, facts: ctx.explicit_priority,
     lambda ctx, facts: facts.priority.upper() == "P0" or facts.smoke),
    (lambda ctx, facts: ctx.has_smoke_profile,
     lambda ctx, facts: facts.smoke),
    (lambda ctx, facts: ctx.has_e2e,
     lambda ctx, facts: False),
    (lambda ctx, facts: True,
     lambda ctx, facts: True),
)

# Changed runs only path-scoped E2E journeys. An empty changed set means the
# diff is unavailable, so E2E journeys fail closed and still run. Smoke E2E
# without trigger paths belongs to the explicit smoke profile.
_CHANGED_RULES: _RuleTable = (
    (lambda ctx, facts: facts.is_e2e and bool(facts.path_patterns),
     lambda ctx, facts: not ctx.changed or facts.path_matches),
    (lambda ctx, facts: facts.is_e2e and facts.smoke,
     lambda ctx, facts: False),
    (lambda ctx, facts: True,
     lambda ctx, facts: (not ctx.explicit_priority
                         or facts.priority.upper() == "P0"
                         or facts.smoke
                         or facts.repo_scoped
                         or not ctx.changed
                         or facts.inputs_match)),
)

_PROFILE_RULES: Mapping[str, _RuleTable] = {
    "smoke": _SMOKE_RULES,
    "changed": _CHANGED_RULES,
}


def _apply_rule_table(rules: _RuleTable, ctx: _ProfileContext,
                      facts: _ScenarioFacts) -> bool:
    for condition, decision in rules:
        if condition(ctx, facts):
            return decision(ctx, facts)
    return False


def _profile_context(scenarios: Sequence[Mapping[str, object]],
                     checks: Mapping[str, Mapping[str, object]],
                     changed: Sequence[str],
                     force_ids: Sequence[str]) -> _ProfileContext:
    def _is_smoke(scenario: Mapping[str, object]) -> bool:
        return bool(scenario.get("smoke")) or any(
            str((checks.get(check_id) or {}).get("profile", "")) == "smoke"
            for check_id in scenario_check_ids(scenario)
        )

    return _ProfileContext(
        checks=checks,
        changed=frozenset(changed),
        scenarios=tuple(scenarios),
        explicit_priority=any(isinstance(item.get("priority"), str) for item in scenarios),
        forced=frozenset(str(item) for item in force_ids),
        has_smoke_profile=any(
            str((check or {}).get("profile", "")) == "smoke" for check in checks.values()),
        has_e2e=any(str(item.get("kind", "")) == "e2e" for item in scenarios),
        e2e_smoke_exists=any(
            str(item.get("kind", "")) == "e2e" and _is_smoke(item) for item in scenarios),
    )


def _scenario_facts(ctx: _ProfileContext, scenario: Mapping[str, object]) -> _ScenarioFacts:
    check_ids = tuple(scenario_check_ids(scenario))
    scenario_checks = tuple(ctx.checks.get(check_id) for check_id in check_ids)
    path_patterns = [
        str(pattern) for pattern in (scenario.get("trigger_paths") or [])
        if str(pattern).strip()
    ]
    path_patterns.extend(
        str(pattern)
        for check in scenario_checks if isinstance(check, Mapping)
        for pattern in (check.get("paths") or [])
        if str(pattern).strip()
    )
    path_patterns = tuple(dict.fromkeys(path_patterns))
    inputs_by_check = [(check or {}).get("inputs") for check in scenario_checks]
    return _ScenarioFacts(
        scenario_id=str(scenario.get("id")),
        priority=str(scenario.get("priority", "")),
        is_e2e=str(scenario.get("kind", "")) == "e2e",
        smoke=(bool(scenario.get("smoke")) or any(
            str((check or {}).get("profile", "")) == "smoke" for check in scenario_checks)),
        check_ids=check_ids,
        scenario_checks=scenario_checks,
        path_patterns=path_patterns,
        path_matches=any(
            match_path(path, pattern) for pattern in path_patterns for path in ctx.changed),
        repo_scoped=not check_ids or any(not value for value in inputs_by_check),
        inputs_match=any(
            match_path(path, str(pattern))
            for value in inputs_by_check if isinstance(value, list)
            for pattern in value for path in ctx.changed),
    )


def _scenario_selected(ctx: _ProfileContext, scenario: Mapping[str, object],
                       profile: str) -> bool:
    facts = _scenario_facts(ctx, scenario)
    if facts.scenario_id in ctx.forced:
        return True
    return _apply_rule_table(_PROFILE_RULES[profile], ctx, facts)


def _with_dependencies(scenarios: Sequence[Mapping[str, object]],
                       selected: list[Mapping[str, object]]) -> list[Mapping[str, object]]:
    selected_ids = {str(item.get("id")) for item in selected}
    by_scenario = {str(item.get("id")): item for item in scenarios}
    pending = list(selected)
    while pending:
        current = pending.pop()
        deps = current.get("depends_on", [])
        if not isinstance(deps, list):
            continue
        for dep in deps:
            dep_id = str(dep)
            if dep_id in selected_ids or dep_id not in by_scenario:
                continue
            selected.append(by_scenario[dep_id])
            selected_ids.add(dep_id)
            pending.append(by_scenario[dep_id])
    return selected


def select_scenarios(scenarios: Sequence[Mapping[str, object]],
                      checks: Mapping[str, Mapping[str, object]],
                      profile: str, changed: Sequence[str],
                      force_ids: Sequence[str] = ()) -> list[Mapping[str, object]]:
    ctx = _profile_context(scenarios, checks, changed, force_ids)
    selected = [scenario for scenario in ctx.scenarios
                if _scenario_selected(ctx, scenario, profile)]
    return _with_dependencies(ctx.scenarios, selected)


def _profile_result(data: Mapping[str, object], profile: str,
                    selected: Sequence[Mapping[str, object]]) -> dict[str, object]:
    selected_check_ids = {
        check_id for item in selected for check_id in scenario_check_ids(item)
    }
    result = dict(data)
    result["scenarios"] = list(selected)
    if "checks" in data:
        result["checks"] = [
            item for item in data.get("checks", []) or []
            if isinstance(item, Mapping) and str(item.get("id")) in selected_check_ids
        ]
    result["profile"] = profile
    return result


def select_profile(data: Mapping[str, object], root: str, profile: str,
                    force_ids: Sequence[str] = ()) -> dict[str, object]:
    """Return a shallow manifest view filtered by smoke/changed/full."""
    if profile == "full":
        return dict(data)
    checks = {
        str(item.get("id")): item
        for item in data.get("checks", []) or []
        if isinstance(item, Mapping) and isinstance(item.get("id"), str)
    }
    scenarios = [item for item in data.get("scenarios", []) or [] if isinstance(item, Mapping)]
    selected = select_scenarios(scenarios, checks, profile, changed_paths(root), force_ids)
    return _profile_result(data, profile, selected)


