"""Platform-neutral edit routing and compliance services."""
import os
from pathlib import Path

import cf_log
from cf_checks import load_check_state, load_spec_checks, record_hits, run_checks, save_check_state
from cf_core import (build_effective_mapping, effective_project_root, is_code_file, load_config,
                     match_domains, normalize_path, normalize_spec_entry, resolve_enforcement, resolve_quality_loop)
from cf_session_state import load_session_state, save_session_state
from cf_spec_context import ContextError, injection_version, load_active_task, load_context
from cf_spec_resolver import resolve_candidate_headers
from cf_spec_router import RouterError, route_prompt

_WARN_TEXT = "⚠ Spec Workflow 校验未通过（warn 模式）：{message} — 建议运行 cf-spec doctor 检查。"


def _active_expansion(root: str, relative: str) -> tuple[str, ...]:
    marker = Path(root) / ".code-flow/.active-task.json"
    if not marker.exists():
        return ()
    active = load_active_task(root)
    context = load_context(str(Path(root) / active.task_dir / "spec-context.yml"))
    bound = {item.spec_id for item in context.bindings}
    return tuple(
        item.spec_id for item in resolve_candidate_headers(root, "code", (relative,))
        if item.spec_id not in bound and item.enforcement == "required"
        and getattr(item, "scope", "path") != "unmatched"
    )


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
    config = load_config(root)
    enforcement = resolve_enforcement(config) if config else "required"
    try:
        expanded = _active_expansion(root, relative)
        result = route_prompt(root, (relative,), sid)
    except (RouterError, ContextError) as exc:
        if enforcement == "required":
            return f"SPEC_WORKFLOW_BLOCKED [{exc.code}]: {exc}. Run cf-spec doctor before continuing.", (), True
        return (_WARN_TEXT.format(message=str(exc)) if enforcement == "warn" else ""), (), False
    if expanded:
        return f"⚠ 该路径引入未绑定 required Spec：{', '.join(expanded)} — 建议先 refresh Context / Plan 再继续编辑。", (), False
    text = result.text
    if result.mode == "task" and result.context_sha256:
        state = load_session_state(root)
        version = injection_version(root, sid, result.context_sha256)
        if state.get("injected_version") == version:
            text = ""
        else:
            state["injected_version"] = version
            save_session_state(root, state)
    return text, tuple(result.specs), False


def prepare_edit(session_root: str, path: str, sid: str, tool: str) -> tuple[str, bool]:
    absolute = path if os.path.isabs(path) else os.path.join(session_root, path)
    root = effective_project_root(session_root, absolute)
    relative = normalize_path(os.path.relpath(absolute, root))
    text, specs, blocked = _routing_result(root, relative, sid)
    cf_log.append_event(root, "edit_intent", {"file": relative, "tool": tool, "specs": list(specs)}, sid)
    return text, blocked


def before_edit(session_root: str, path: str, sid: str, tool: str) -> str:
    return prepare_edit(session_root, path, sid, tool)[0]


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
