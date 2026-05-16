#!/usr/bin/env python3
"""Unified UserPromptSubmit Hook: inject matching specs into context.

This hook works for both Claude Code and Codex adapters. It extracts:
1. File paths from the prompt (for context_tags)
2. Keywords from the prompt (for prompt_tags via extract_prompt_tags)

Both tag sets are used to match specs for injection.

Input (stdin): {"prompt": "...", "session_id": "..."}
Output (stdout): {"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": "..."}}
or empty on no-op
"""
import json
import os
import re
import sys
from cf_core import (
    _log,
    assemble_context,
    build_effective_mapping,
    debug_log,
    ensure_utf8_io,
    extract_context_tags,
    extract_prompt_tags,
    fallback_domains_for_context,
    load_config,
    load_inject_state,
    match_domains,
    match_specs_by_tags,
    normalize_path,
    read_matched_specs,
    resolve_compress,
    resolve_session_id,
    save_inject_state,
    select_specs_tiered,
)

# Match bare paths, @-prefixed paths, and backtick-quoted paths.
# Right boundary uses an ASCII-only negative lookahead instead of \b. Python's
# \b is Unicode-aware on every platform, so "src/cli.js中" never terminated
# the match — common Chinese phrasing dropped real paths. The explicit ASCII
# class is locale- and OS-independent, so Windows/macOS/Linux behave the same.
# Character class includes `\` so Windows-style paths (`src\cli.js`) pasted
# from Explorer also match; `normalize_path()` downstream converts to `/`.
_PATH_RE = re.compile(r'[@`]?([a-zA-Z0-9_.][a-zA-Z0-9_./\\\-]*\.[a-zA-Z]{1,6})(?![a-zA-Z0-9_])')
_EXT_RE = re.compile(r'\.(py|js|ts|go|rs|java|rb|cs|cpp|c|h)$')


def extract_paths_from_prompt(prompt: str) -> list:
    """Extract candidate file paths referenced in prompt text."""
    paths = []
    seen = set()
    for m in _PATH_RE.finditer(prompt):
        candidate = normalize_path(m.group(1).lstrip('@`'))
        # Require at least one slash or a meaningful extension to reduce noise
        if candidate in seen:
            continue
        if '/' in candidate or _EXT_RE.search(candidate):
            paths.append(candidate)
            seen.add(candidate)
    return paths


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

        project_root = os.getcwd()
        
        # Resolve session_id consistently with PreToolUse hook
        sid = resolve_session_id(data)
        debug_log(
            f"user_prompt_hook start session={sid} "
            f"prompt_len={len(prompt)} prompt_head={prompt[:200]!r}",
            project_root,
        )

        config = load_config(project_root)
        if not config:
            debug_log(f"user_prompt_hook no_config session={sid}", project_root)
            return

        inject_config = config.get("inject") or {}
        if inject_config.get("auto") is False:
            return
        compress_enabled = resolve_compress(inject_config)

        mapping = config.get("path_mapping") or {}
        effective_mapping = build_effective_mapping(project_root, mapping)

        budget_cfg = config.get("budget") or {}
        l1_budget = 1700
        map_max = 400
        try:
            l1_budget = int(budget_cfg.get("l1_max", 1700))
        except (ValueError, TypeError):
            pass
        try:
            map_max = int(budget_cfg.get("map_max", 400))
        except (ValueError, TypeError):
            pass

        # Derive context_tags from file paths mentioned in the prompt
        candidate_paths = extract_paths_from_prompt(prompt)
        context_tags: set = set()
        matched_domains: set = set()
        for cp in candidate_paths:
            context_tags.update(extract_context_tags(cp))
            matched_domains.update(match_domains(cp, effective_mapping))

        # NEW: Extract prompt_tags from user prompt keywords
        prompt_tags = extract_prompt_tags(prompt)
        debug_log(f"user_prompt_hook paths={candidate_paths} context_tags={sorted(context_tags)} prompt_tags={sorted(prompt_tags)}", project_root)

        # Fallback: unresolved domains → prefer domain-name hint in tags, then all domains
        if not matched_domains:
            matched_domains = fallback_domains_for_context(effective_mapping, context_tags)
            debug_log(f"user_prompt_hook fallback_domains={sorted(matched_domains)}", project_root)

        # Strict tag-based matching per domain. No bulk-load fallback: when a
        # Tier 1 spec's tags don't intersect (context_tags ∪ prompt_tags), the
        # spec is NOT injected. Tier 0 (_map.md) uses "*" so navigation still
        # reaches the model. Re-inject every call (session dedup removed).
        all_matched = []
        for domain in matched_domains:
            domain_cfg = effective_mapping.get(domain) or {}
            specs_config = domain_cfg.get("specs") or []
            matched, _ = match_specs_by_tags(specs_config, context_tags, prompt_tags)
            if matched:
                specs = read_matched_specs(
                    project_root, domain, matched, compress=compress_enabled
                )
                all_matched.extend(specs)

        if not all_matched:
            debug_log(f"user_prompt_hook no_specs_matched session={sid}", project_root)
            return

        selected = select_specs_tiered(all_matched, l1_budget, map_max)
        if not selected:
            return

        # Load state with session isolation (deferred until after match success)
        state = load_inject_state(project_root)
        same_session = state.get("session_id") == sid
        if same_session:
            injected_specs = set(state.get("injected_specs") or [])
            prompt_window = dict(state.get("prompt_inject_window") or {})
            prompt_count = int(state.get("prompt_count") or 0) + 1
        else:
            injected_specs = set()
            prompt_window = {}
            prompt_count = 1

        # TTL-window dedup: skip specs re-injected within the last N prompts in
        # this session. dedup_window <= 0 disables dedup (every call re-injects).
        # The window bounds — not removes — re-injection, so an auto-compaction
        # that drops earlier context can still recover specs after N prompts.
        try:
            dedup_window = int(inject_config.get("dedup_window", 5))
        except (ValueError, TypeError):
            dedup_window = 5

        if dedup_window > 0:
            emitted = [
                s for s in selected
                if (s["path"] not in prompt_window)
                or (prompt_count - int(prompt_window[s["path"]]) >= dedup_window)
            ]
        else:
            emitted = list(selected)

        # Compare by path so this stays correct if `emitted` is ever rebuilt
        # from copies instead of filtered references to the same dicts.
        emitted_paths = {s["path"] for s in emitted}
        skipped = [s["path"] for s in selected if s["path"] not in emitted_paths]

        # Always persist prompt_count so the dedup window keeps advancing even
        # on fully-deduped turns. Preserve PreToolUse-owned fields verbatim.
        for s in emitted:
            prompt_window[s["path"]] = prompt_count
        save_inject_state(project_root, {
            "session_id": sid,
            "injected_specs": sorted(injected_specs | {s["path"] for s in emitted}),
            "last_file": state.get("last_file", "") if same_session else "",
            "prompt_count": prompt_count,
            "prompt_inject_window": prompt_window,
        })

        if not emitted:
            debug_log(
                f"user_prompt_hook dedup_all_skipped session={sid} "
                f"prompt_count={prompt_count} skipped={skipped}",
                project_root,
            )
            return

        debug_log(
            f"user_prompt_hook injected={[s['path'] for s in emitted]} "
            f"skipped={skipped} prompt_count={prompt_count} session={sid}",
            project_root,
        )

        payload = {
            "hookSpecificOutput": {
                "hookEventName": "UserPromptSubmit",
                "additionalContext": assemble_context(emitted, "## Active Specs (auto-injected)"),
            }
        }
        if os.environ.get("CF_DEBUG") == "1":
            payload["debug"] = {
                "candidate_paths": candidate_paths,
                "domains": sorted(matched_domains),
                "context_tags": sorted(context_tags),
                "prompt_tags": sorted(prompt_tags),
                "matched_specs": [s["path"] for s in emitted],
                "deduped_specs": skipped,
                "prompt_count": prompt_count,
                "dedup_window": dedup_window,
            }

        sys.stdout.write(json.dumps(payload, ensure_ascii=False))

    except Exception as exc:
        _log(f"cf_user_prompt_hook error: {exc}")
        return


if __name__ == "__main__":
    main()
