#!/usr/bin/env python3
"""UserPromptSubmit hook for the Context-first three-branch router."""

import json
import os
import re
import sys

import cf_log
from cf_checks import detect_correction
from cf_core import _log, ensure_utf8_io, normalize_path, resolve_quality_loop, resolve_session_id, load_config
from cf_spec_router import RouterError, route_prompt


_PATH_RE = re.compile(r'[@`]?([a-zA-Z0-9_.][a-zA-Z0-9_./\\\-]*\.[a-zA-Z]{1,6})(?![a-zA-Z0-9_])')
_EXT_RE = re.compile(r'\.(py|js|ts|go|rs|java|rb|cs|cpp|c|h)$')


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
        paths = extract_paths_from_prompt(prompt)
        _record_correction(root, prompt, paths, sid)
        result = route_prompt(root, paths, sid)
        if not result.text:
            return
        cf_log.append_event(root, "inject", {"specs": list(result.specs), "mode": result.mode, "source": result.mode}, sid)
        sys.stdout.write(json.dumps(_payload(result.text, result.mode), ensure_ascii=False))
    except RouterError as exc:
        message = f"SPEC_WORKFLOW_BLOCKED [{exc.code}]: {exc}. Run cf-spec doctor before continuing."
        sys.stdout.write(json.dumps(_payload(message, "blocked"), ensure_ascii=False))
    except (json.JSONDecodeError, UnicodeError, OSError, ValueError) as exc:
        _log(f"cf_user_prompt_hook error: {exc}")


if __name__ == "__main__":
    main()
