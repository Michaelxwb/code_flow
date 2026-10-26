#!/usr/bin/env python3
"""UserPromptSubmit hook for the Context-first three-branch router."""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

from codeflow.core import cf_log
from codeflow.acceptance.cf_checks import detect_correction
from codeflow.core.cf_core import (
    ConfigError,
    ensure_utf8_io,
    load_config,
    normalize_path,
    resolve_quality_loop,
    resolve_session_id,
    timing_log,
)
from codeflow.core.cf_session_state import load_session_state, save_session_state
from codeflow.spec.cf_injection import injection_output, injection_text
from codeflow.spec.cf_spec_router import RouterError, RouteResult, route_prompt


_PATH_RE = re.compile(r'`([^`\n]+)`|@?((?:[a-zA-Z]:[\\/]|/)?[a-zA-Z0-9_.][a-zA-Z0-9_./\\\-]*\.[a-zA-Z]{1,8})(?![a-zA-Z0-9_])')
_EXT_RE = re.compile(r'\.(py|js|jsx|ts|tsx|vue|svelte|go|rs|java|rb|cs|cpp|c|h)$')
_URL_RE = re.compile(r'\b[a-zA-Z][a-zA-Z0-9+.-]*://[^\s`<>]+')
_HARNESS_RE = re.compile(
    r"<(?P<tag>task-notification|output-file)\b[^>]*>.*?</(?P=tag)>",
    re.IGNORECASE | re.DOTALL,
)

_COMPRESS_INTERVAL = 25
_REMINDER_TEXT = (
    "⚠ 本会话已处理较多轮次，上下文较长；批量任务建议在任务间压缩上下文，或拆到新会话继续。"
)


def extract_paths_from_prompt(prompt: str, root: str | None = None) -> list[str]:
    """Extract explicit file paths without semantic keyword inference.

    Paths outside the project are ignored: harness metadata (for example the
    `<output-file>` in a background-agent notification) and pasted logs often
    contain absolute paths that are not routable project files. Only in-project
    paths participate in spec routing.
    """
    paths = []
    seen = set()
    text = _HARNESS_RE.sub("", prompt)
    for match in _PATH_RE.finditer(_URL_RE.sub("", text)):
        candidate = normalize_path((match.group(1) or match.group(2)).lstrip('@'))
        if '/' not in candidate and not _EXT_RE.search(candidate):
            continue
        if root is not None:
            try:
                target = Path(candidate) if Path(candidate).is_absolute() else Path(root) / candidate
                candidate = target.resolve().relative_to(Path(root).resolve()).as_posix()
            except ValueError:
                continue
        if candidate not in seen and ('/' in candidate or _EXT_RE.search(candidate)):
            paths.append(candidate)
            seen.add(candidate)
    return paths


def _payload(text: str, mode: str) -> dict[str, object]:
    payload: dict[str, object] = {
        "hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": text}
    }
    if mode == "blocked":
        payload.update(decision="block", reason=text)
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
        next_at = int(state.get("next_remind_at", _COMPRESS_INTERVAL))
        reminder = ""
        if state["prompt_count"] >= next_at:
            reminder = _REMINDER_TEXT
            state["next_remind_at"] = next_at + _COMPRESS_INTERVAL
    except (ValueError, TypeError, KeyError):
        return ""
    save_session_state(root, state)
    return reminder


def build_prompt_context(prompt: str, sid: str, root: str) -> tuple[str, str]:
    try:
        return _build_prompt_context(prompt, sid, root)
    except (ConfigError, RouterError, OSError, UnicodeError, ValueError, TypeError) as exc:
        return f"SPEC_WORKFLOW_BLOCKED [{getattr(exc, 'code', 'invalid_prompt_context')}]: {exc}. Run cf-spec doctor before continuing.", "blocked"


def _build_prompt_context(prompt: str, sid: str, root: str) -> tuple[str, str]:
    if not prompt.strip():
        return "", ""
    config = load_config(root)
    active = (Path(root) / ".code-flow/.active-task.json").exists()
    paths = extract_paths_from_prompt(prompt, None if active else root)
    _record_correction(root, prompt, paths, sid)
    result = route_prompt(root, paths, sid)
    reminder = _session_reminder(root, sid) if config and resolve_quality_loop(config)["compress_reminder"] else ""
    text = injection_text(root, sid, result, prompt=True)
    if text and result.mode == "catalog":
        cf_log.append_event(root, "inject", {"specs": list(result.specs), "mode": result.mode, "source": result.mode}, sid)
    mode = result.mode if text else "reminder"
    return "\n\n".join(part.rstrip() for part in (text, reminder) if part), mode


def process_prompt(data: dict[str, object], root: str) -> None:
    try:
        prompt = data.get("prompt", "")
        if not isinstance(prompt, str) or not prompt.strip():
            return
        with injection_output():
            text, mode = build_prompt_context(prompt, resolve_session_id(data), root)
            if text:
                sys.stdout.write(json.dumps(_payload(text, mode), ensure_ascii=False))
                sys.stdout.flush()
    except (json.JSONDecodeError, UnicodeError, OSError, ValueError) as exc:
        cf_log.warn(f"cf_user_prompt_hook error: {exc}")


def main() -> None:
    try:
        ensure_utf8_io()
        if sys.stdin.isatty():
            cf_log.warn("cf_user_prompt_hook.py: missing stdin event")
            return
        raw = sys.stdin.read()
        if raw.strip():
            process_prompt(json.loads(raw), os.getcwd())
    except (json.JSONDecodeError, OSError, ValueError) as exc:
        cf_log.warn(f"cf_user_prompt_hook.py bad_stdin_json: {exc}")
