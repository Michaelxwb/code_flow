#!/usr/bin/env python3
"""UserPromptSubmit hook for the Context-first three-branch router."""

import json
import os
import re
import sys

import cf_log
from cf_checks import detect_correction
from cf_core import (
    _log,
    ensure_utf8_io,
    load_config,
    normalize_path,
    resolve_enforcement,
    resolve_quality_loop,
    resolve_session_id,
)
from cf_session_state import load_session_state, save_session_state
from cf_spec_router import RouterError, route_prompt


_PATH_RE = re.compile(r'[@`]?([a-zA-Z0-9_.][a-zA-Z0-9_./\\\-]*\.[a-zA-Z]{1,6})(?![a-zA-Z0-9_])')
_EXT_RE = re.compile(r'\.(py|js|ts|go|rs|java|rb|cs|cpp|c|h)$')

_COMPRESS_INTERVAL = 25
_REINJECT_INTERVAL = 25
_REMINDER_TEXT = (
    "⚠ 本会话已处理较多轮次，上下文较长；批量任务建议在任务间压缩上下文，或拆到新会话继续。"
)
_WARN_TEXT = "⚠ Spec Workflow 校验未通过（warn 模式）：{message} — 建议运行 cf-spec doctor 检查。"


def extract_paths_from_prompt(prompt: str) -> list[str]:
    """Extract explicit file paths without semantic keyword inference."""
    paths = []
    seen = set()
    for match in _PATH_RE.finditer(prompt):
        candidate = normalize_path(match.group(1).lstrip('@`'))
        if candidate not in seen and ('/' in candidate or _EXT_RE.search(candidate)):
            paths.append(candidate)
            seen.add(candidate)
    return paths


def _payload(text: str, mode: str) -> dict[str, object]:
    payload: dict[str, object] = {
        "hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": text}
    }
    if os.environ.get("CF_DEBUG") == "1":
        payload["debug"] = {"mode": mode}
    return payload


def _record_correction(root: str, prompt: str, paths: list[str], sid: str) -> None:
    config = load_config(root)
    if not config or not resolve_quality_loop(config)["correction_capture"]:
        return
    correction = detect_correction(prompt)
    if correction:
        cf_log.append_event(root, "correction", {"phrase": correction["phrase"], "prompt_head": prompt[:200], "files": paths}, sid)


def _session_reminder(root: str, sid: str) -> str:
    """One-line context-compress nudge once per COMPRESS_INTERVAL prompts per session.

    Gated by quality_loop.compress_reminder; disabled → zero IO. Never raises: a
    corrupt state file degrades to no reminder rather than breaking the hook.
    """
    config = load_config(root)
    if not config or not resolve_quality_loop(config)["compress_reminder"]:
        return ""
    state = load_session_state(root)
    try:
        if state.get("session_id") != sid:
            state = {"session_id": sid, "prompt_count": 0, "next_remind_at": _COMPRESS_INTERVAL}
        state["prompt_count"] = int(state.get("prompt_count", 0)) + 1
        reminder = ""
        if state["prompt_count"] >= int(state.get("next_remind_at", _COMPRESS_INTERVAL)):
            reminder = _REMINDER_TEXT
            state["next_remind_at"] = int(state["next_remind_at"]) + _COMPRESS_INTERVAL
    except (ValueError, TypeError):
        return ""
    save_session_state(root, state)
    return reminder


def _route_with_enforcement(root: str, paths: list[str], sid: str, enforcement: str) -> tuple[object, object]:
    """Route with enforcement-aware failure handling.

    required — fail closed with the SPEC_WORKFLOW_BLOCKED message;
    warn    — degrade to a short advisory message;
    inject  — degrade silently.
    Returns (result, error_payload); exactly one is not None.
    """
    try:
        return route_prompt(root, paths, sid), None
    except RouterError as exc:
        if enforcement == "required":
            message = f"SPEC_WORKFLOW_BLOCKED [{exc.code}]: {exc}. Run cf-spec doctor before continuing."
            return None, _payload(message, "blocked")
        if enforcement == "warn":
            return None, _payload(_WARN_TEXT.format(message=str(exc)), "warn")
        return None, None


def main() -> None:
    try:
        ensure_utf8_io()
        raw = sys.stdin.read()
        if not raw.strip():
            return
        data = json.loads(raw)
        prompt = data.get("prompt", "")
        if not isinstance(prompt, str) or not prompt.strip():
            return
        root = os.getcwd()
        sid = resolve_session_id(data)
        config = load_config(root)
        enforcement = resolve_enforcement(config) if config else "required"
        paths = extract_paths_from_prompt(prompt)
        _record_correction(root, prompt, paths, sid)
        result, error_payload = _route_with_enforcement(root, paths, sid, enforcement)
        if error_payload is not None:
            sys.stdout.write(json.dumps(error_payload, ensure_ascii=False))
            return
        if result is None:
            return
        reminder = ""
        if config and resolve_quality_loop(config)["compress_reminder"]:
            reminder = _session_reminder(root, sid)
        text = result.text
        if result.mode == "task" and result.context_sha256:
            # Dedup: inject the projection once per session/context, refreshing
            # at the compress cadence so long sessions do not re-pay 12k chars
            # on every prompt.
            state = load_session_state(root)
            count = int(state.get("prompt_count", 0))
            dirty = False
            if not (config and resolve_quality_loop(config)["compress_reminder"]):
                # compress_reminder off → _session_reminder never bumps the
                # counter; maintain the cadence here so the periodic refresh
                # still fires after compaction.
                count += 1
                state["prompt_count"] = count
                dirty = True
            injected = state.get("injected_sha256")
            last_inject = int(state.get("last_inject_prompt", 0))
            if injected == result.context_sha256 and count - last_inject < _REINJECT_INTERVAL:
                text = ""
            else:
                state["injected_sha256"] = result.context_sha256
                state["last_inject_prompt"] = count
                dirty = True
            if dirty:
                save_session_state(root, state)
        if not text and not reminder:
            return
        if text:
            cf_log.append_event(root, "inject", {"specs": list(result.specs), "mode": result.mode, "source": result.mode}, sid)
        if text and reminder:
            text = text.rstrip() + "\n\n" + reminder
        elif reminder:
            text = reminder
        sys.stdout.write(json.dumps(_payload(text, result.mode if text else "reminder"), ensure_ascii=False))
    except (json.JSONDecodeError, UnicodeError, OSError, ValueError) as exc:
        _log(f"cf_user_prompt_hook error: {exc}")


if __name__ == "__main__":
    main()
