"""Platform-neutral edit routing and compliance services."""
import os
from pathlib import Path
from typing import Sequence

from codeflow.core import cf_log
from codeflow.acceptance.cf_checks import load_check_state, load_spec_checks, record_hits, run_checks, save_check_state
from codeflow.core.cf_core import (build_effective_mapping, effective_project_root, is_code_file, load_config,
                     match_domains, normalize_path, normalize_spec_entry, resolve_enforcement, resolve_quality_loop)
from codeflow.spec.cf_injection import injection_text
from codeflow.spec.cf_spec_router import RouterError, route_prompt

FEEDBACK_HINT = '如认为误报，直接告诉我"这是误报"，我会标记忽略。'
_REPORTED_KEY = "_reported"


def _collect_checks(project_root: str, domains: list[str], mapping: dict[str, object]) -> list[dict[str, object]]:
    """Aggregate checks of all constraint specs in matched domains.

    Each check is annotated with its source spec path. Checks apply whenever
    their own `files` glob matches — independent of injection tag gating.
    """
    specs_root = os.path.join(project_root, ".code-flow", "specs")
    collected = []
    seen_specs = set()
    for domain in domains:
        for entry in (mapping.get(domain) or {}).get("specs") or []:
            cfg = normalize_spec_entry(entry)
            rel = cfg.get("path")
            if not rel or rel in seen_specs or not cfg.get("tags"):
                continue
            seen_specs.add(rel)
            checks, _ = load_spec_checks(os.path.join(specs_root, rel))
            for check in checks:
                item = dict(check)
                item["spec"] = rel
                collected.append(item)
    return collected


def _session_reported(state: dict[str, object], sid: str) -> set[str]:
    session = state.get(_REPORTED_KEY) or {}
    if session.get("sid") != sid:
        return set()
    return set(session.get("keys") or [])


def _save_reported(project_root: str, state: dict[str, object], sid: str, keys: set[str]) -> None:
    state[_REPORTED_KEY] = {"sid": sid, "keys": sorted(keys)}
    save_check_state(project_root, state)


def _feedback_text(violations: list[dict[str, object]]) -> str:
    lines = ["## Spec 合规反馈 (auto-check)", ""]
    for v in violations:
        lines.append(f"⚠ {v['message']}（规则: {v['spec']}#{v['check_id']}）")
        lines.append(f"  违规行 {v['line_no']}: {v['line']}")
    lines.append("")
    lines.append("请修正以上违规后再继续。" + FEEDBACK_HINT)
    return "\n".join(lines)



def _routing_result(root: str, relative: str, sid: str) -> tuple[str, tuple[str, ...], bool]:
    return _route_edits(root, (relative,), sid)


def _route_edits(root: str, paths: Sequence[str], sid: str) -> tuple[str, tuple[str, ...], bool]:
    try:
        result = route_prompt(root, paths, sid, check_scope=True)
    except RouterError as exc:
        return f"SPEC_WORKFLOW_BLOCKED [{exc.code}]: {exc}. Run cf-spec doctor before continuing.", (), True
    text = injection_text(root, sid, result)
    emitted = tuple(result.specs) if text else ()
    if result.expanded_specs:
        warning = f"⚠ 该路径引入未绑定 required Spec：{', '.join(result.expanded_specs)} — 建议先 refresh Context / Plan 再继续编辑。"
        text = "\n\n".join(part for part in (warning, text) if part)
    return text, emitted, False


def prepare_edit(session_root: str, path: str, sid: str, tool: str) -> tuple[str, bool]:
    return prepare_edits(session_root, (path,), sid, tool)


def prepare_edits(session_root: str, paths: Sequence[str], sid: str, tool: str) -> tuple[str, bool]:
    groups: dict[str, list[str]] = {}
    for path in paths:
        absolute = path if os.path.isabs(path) else os.path.join(session_root, path)
        root = effective_project_root(session_root, absolute)
        relative = normalize_path(os.path.relpath(absolute, root))
        if relative not in groups.setdefault(root, []):
            groups[root].append(relative)
    feedback = []
    rejected = False
    for root, relative_paths in groups.items():
        text, specs, blocked = _route_edits(root, relative_paths, sid)
        rejected = rejected or blocked
        if text:
            feedback.append(text)
        for relative in relative_paths:
            cf_log.append_event(root, "edit_intent", {"file": relative, "tool": tool,
                                "specs": list(specs), "blocked": blocked}, sid)
    return "\n\n".join(dict.fromkeys(feedback)), rejected


def _fresh_violations(root: str, path: str, content: str, checks: list[dict[str, object]], sid: str) -> list[dict[str, object]]:
    state = load_check_state(root)
    violations, skipped = run_checks(checks, path, content, state)
    for item in skipped:
        cf_log.degrade(root, "post_check", f"{item['check_id']}:{item['reason']}", sid)
    spec_by_check = {check["id"]: check["spec"] for check in checks}
    reported = _session_reported(state, sid)
    fresh = []
    for violation in violations:
        key = f"{violation['check_id']}|{violation['file']}"
        if key not in reported:
            violation["spec"] = spec_by_check.get(violation["check_id"], "")
            fresh.append(violation)
            reported.add(key)
    if fresh:
        record_hits(root, sorted({v["check_id"] for v in fresh}))
        _save_reported(root, load_check_state(root), sid, reported)
    return fresh


def after_edit(session_root: str, path: str, sid: str, tool: str, deleted: bool = False) -> str:
    absolute = path if os.path.isabs(path) else os.path.join(session_root, path)
    root = effective_project_root(session_root, absolute)
    config = load_config(root)
    if not config or resolve_enforcement(config) == "inject" or not resolve_quality_loop(config)["post_check"]:
        return ""
    relative = normalize_path(os.path.relpath(absolute, root))
    cf_log.append_event(root, "edit", {"file": relative, "tool": tool}, sid)
    if deleted or not is_code_file(relative, config.get("quality_loop") or {}):
        return ""
    mapping = build_effective_mapping(root, config.get("path_mapping") or {})
    checks = _collect_checks(root, match_domains(relative, mapping), mapping)
    if not checks:
        return ""
    try:
        content = Path(absolute).read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        cf_log.degrade(root, "post_check", f"read_failed:{relative}:{exc}", sid)
        return ""
    fresh = _fresh_violations(root, relative, content, checks, sid)
    for violation in fresh:
        cf_log.append_event(root, "violation", {"check_id": violation["check_id"], "spec": violation["spec"],
                            "file": violation["file"], "severity": violation["severity"]}, sid)
    return _feedback_text(fresh) if fresh else ""
