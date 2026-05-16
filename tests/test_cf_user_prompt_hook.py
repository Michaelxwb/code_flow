#!/usr/bin/env python3
"""Tests for cf_user_prompt_hook.py — covers path extraction, prompt tag extraction, and main() hook."""
import io
import json
import os
import sys
import tempfile
import unittest.mock as mock
import yaml

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "core", "code-flow", "scripts"))
from cf_user_prompt_hook import extract_paths_from_prompt, main


# --- extract_paths_from_prompt ---
def test_extract_path_with_slash():
    paths = extract_paths_from_prompt("please edit src/components/Button.tsx")
    assert "src/components/Button.tsx" in paths


def test_extract_at_prefixed_path():
    paths = extract_paths_from_prompt("see @src/core/cf_core.py for reference")
    assert "src/core/cf_core.py" in paths


def test_extract_backtick_path():
    paths = extract_paths_from_prompt("look at `services/auth.py` and fix it")
    assert "services/auth.py" in paths


def test_extract_code_extension_no_slash():
    paths = extract_paths_from_prompt("update main.py to add error handling")
    assert "main.py" in paths


def test_extract_deduplicates():
    paths = extract_paths_from_prompt("edit src/app.py then check src/app.py again")
    assert paths.count("src/app.py") == 1


def test_extract_no_paths_returns_empty():
    paths = extract_paths_from_prompt("what does the auth system do?")
    assert paths == []


def test_extract_ignores_non_paths():
    paths = extract_paths_from_prompt("use version 1.0.2 and check the README")
    # "1.0.2" and "README" should not appear as file paths
    assert "1.0.2" not in paths
    assert "README" not in paths


def test_extract_multiple_paths():
    paths = extract_paths_from_prompt(
        "refactor src/cli.js and update tests/test_cf_core.py"
    )
    assert "src/cli.js" in paths
    assert "tests/test_cf_core.py" in paths


def test_extract_path_followed_by_chinese():
    # Python \b is Unicode-aware → "js中" was treated as a word-internal
    # boundary and the whole match was dropped. ASCII negative lookahead
    # restores correct termination.
    paths = extract_paths_from_prompt("看看 src/cli.js中的逻辑")
    assert paths == ["src/cli.js"]


def test_extract_paths_separated_by_chinese():
    paths = extract_paths_from_prompt("修改 src/a.py 和 src/b.py 都要测试")
    assert "src/a.py" in paths
    assert "src/b.py" in paths


def test_extract_path_chinese_glued_no_separator():
    paths = extract_paths_from_prompt("src/a.py和src/b.py都改")
    assert "src/a.py" in paths
    assert "src/b.py" in paths


def test_extract_path_with_extension_at_eol_chinese():
    paths = extract_paths_from_prompt("打开 cf_core.py")
    assert "cf_core.py" in paths


def test_extract_windows_backslash_path():
    """Windows users pasting Explorer paths get backslashes; the regex character
    class now matches `\\`, and normalize_path() downstream converts to `/` so
    downstream consumers (match_domains, extract_context_tags) stay forward-
    slash-only."""
    paths = extract_paths_from_prompt("edit src\\components\\Button.tsx")
    assert "src/components/Button.tsx" in paths


def test_extract_windows_backslash_path_with_at_prefix():
    paths = extract_paths_from_prompt("see @src\\core\\cf_core.py")
    assert "src/core/cf_core.py" in paths


def test_extract_mixed_separators_normalized():
    """Mixed `\\` and `/` in one path still extracts and normalizes."""
    paths = extract_paths_from_prompt("look at src\\foo/bar.py for the bug")
    assert "src/foo/bar.py" in paths


# --- main() integration ---
def _make_project(tmpdir: str, domains_with_specs: bool = True) -> str:
    """Set up a minimal .code-flow project in tmpdir."""
    cf_dir = os.path.join(tmpdir, ".code-flow")
    specs_dir = os.path.join(cf_dir, "specs", "scripts")
    os.makedirs(specs_dir, exist_ok=True)

    # Write a minimal spec file
    with open(os.path.join(specs_dir, "code-standards.md"), "w") as f:
        f.write("# Standards\nNo loose types.")
    with open(os.path.join(specs_dir, "_map.md"), "w") as f:
        f.write("# Map\nscripts domain.")

    # Add a performance spec for testing prompt_tags
    specs_perf_dir = os.path.join(cf_dir, "specs", "backend")
    os.makedirs(specs_perf_dir, exist_ok=True)
    with open(os.path.join(specs_perf_dir, "code-quality-performance.md"), "w") as f:
        f.write("# Performance\nOptimize for speed.")

    config = {
        "version": 1,
        "budget": {"l1_max": 1700, "map_max": 400},
        "inject": {"auto": True, "code_extensions": [".py", ".js"]},
        "path_mapping": {
            "scripts": {
                "patterns": ["**/*.py"],
                "specs": [
                    {"path": "scripts/_map.md", "tags": ["*"], "tier": 0},
                    {"path": "scripts/code-standards.md", "tags": ["core", "hook"], "tier": 1},
                ],
            },
            "backend": {
                "patterns": ["**/*.py"],
                "specs": [
                    {"path": "backend/_map.md", "tags": ["*"], "tier": 0},
                    {"path": "backend/code-quality-performance.md", "tags": ["performance"], "tier": 1},
                ],
            },
        },
    }

    with open(os.path.join(cf_dir, "config.yml"), "w") as f:
        yaml.dump(config, f)

    return tmpdir


def _make_project_with_stale_mapping(tmpdir: str) -> str:
    """Set up a project where config path_mapping is stale but specs exist on disk."""
    cf_dir = os.path.join(tmpdir, ".code-flow")
    specs_dir = os.path.join(cf_dir, "specs", "cli")
    os.makedirs(specs_dir, exist_ok=True)

    with open(os.path.join(specs_dir, "_map.md"), "w") as f:
        f.write("# CLI Map\n")
    with open(os.path.join(specs_dir, "code-standards.md"), "w") as f:
        f.write("# CLI Standards\n")

    config = {
        "version": 1,
        "budget": {"l1_max": 1700, "map_max": 400},
        "inject": {"auto": True, "code_extensions": [".py", ".js"]},
        "path_mapping": {
            "backend": {
                "patterns": ["**/*.py"],
                "specs": [
                    {"path": "backend/_map.md", "tags": ["*"], "tier": 0},
                ],
            }
        },
    }

    with open(os.path.join(cf_dir, "config.yml"), "w") as f:
        yaml.dump(config, f)

    return tmpdir


def _run_main(prompt: str, project_root: str, pid: str = "99999", session_id: str = None) -> dict:
    """Run the main() function with given prompt and project root."""
    stdin_data = json.dumps({
        "prompt": prompt,
        "session_id": session_id or pid
    })
    with mock.patch("sys.stdin", io.StringIO(stdin_data)), \
        mock.patch("sys.stdout", io.StringIO()) as mock_out, \
        mock.patch("os.getcwd", return_value=project_root), \
        mock.patch("os.getpid", return_value=int(pid)):
        main()
    output = mock_out.getvalue()
    return json.loads(output) if output.strip() else {}


def test_main_injects_context_for_python_path():
    with tempfile.TemporaryDirectory() as tmpdir:
        _make_project(tmpdir)
        result = _run_main("edit src/core/cf_core.py", tmpdir)
        assert "hookSpecificOutput" in result
        assert "Active Specs" in result["hookSpecificOutput"]["additionalContext"]


def test_main_empty_prompt_no_output():
    with tempfile.TemporaryDirectory() as tmpdir:
        _make_project(tmpdir)
        result = _run_main("", tmpdir)
        assert result == {}


def test_main_no_paths_no_tags_injects_only_tier0():
    """No file refs, no tag hits → only Tier 0 (wildcard) maps reach the model.

    Tier 1 specs require an actual tag intersection — bulk-load fallback removed.
    Tier 0 _map.md has tags=["*"] so it still makes it through as navigation.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        _make_project(tmpdir)
        result = _run_main("what does the auth flow do?", tmpdir)
        assert "hookSpecificOutput" in result
        ctx = result["hookSpecificOutput"]["additionalContext"]
        assert "_map.md" in ctx
        assert "code-standards.md" not in ctx
        assert "code-quality-performance.md" not in ctx


def _set_dedup_window(tmpdir: str, window: int) -> None:
    """Patch inject.dedup_window in the project's config.yml."""
    config_path = os.path.join(tmpdir, ".code-flow", "config.yml")
    with open(config_path) as f:
        cfg = yaml.safe_load(f)
    cfg.setdefault("inject", {})["dedup_window"] = window
    with open(config_path, "w") as f:
        yaml.dump(cfg, f)


def test_main_dedup_skips_same_spec_within_window():
    """Same session, dedup_window=5: spec injected in turn 1 is skipped in turn 2.

    Both prompts hit only the wildcard Tier 0 _map.md (no tag matches), so
    turn 2 produces a fully-deduped no-op.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        _make_project(tmpdir)
        _set_dedup_window(tmpdir, 5)
        sid = "sess-aaa"
        r1 = _run_main("edit src/hook.py", tmpdir, session_id=sid)
        assert "hookSpecificOutput" in r1
        r2 = _run_main("edit src/hook.py again", tmpdir, session_id=sid)
        # All matched specs already injected within window → no stdout emitted.
        assert r2 == {}


def test_main_dedup_reinjects_after_window_expires():
    """Same session, dedup_window=2: turn 1 injects, turns 2-3 skip, turn 4 re-injects."""
    with tempfile.TemporaryDirectory() as tmpdir:
        _make_project(tmpdir)
        _set_dedup_window(tmpdir, 2)
        sid = "sess-bbb"
        r1 = _run_main("edit src/hook.py", tmpdir, session_id=sid)
        assert "hookSpecificOutput" in r1
        r2 = _run_main("edit src/hook.py", tmpdir, session_id=sid)
        assert r2 == {}  # turn 2 within window
        r3 = _run_main("edit src/hook.py", tmpdir, session_id=sid)
        # turn 3: prompt_count - window_value = 3 - 1 = 2 >= dedup_window=2 → re-inject
        assert "hookSpecificOutput" in r3


def test_main_dedup_emits_only_new_specs():
    """Turn 1 matches A only; turn 2 matches A+B → turn 2 emits only B."""
    with tempfile.TemporaryDirectory() as tmpdir:
        _make_project(tmpdir)
        _set_dedup_window(tmpdir, 5)
        sid = "sess-ccc"
        # Turn 1: prompt has no perf keyword → only _map.md matches (wildcard).
        r1 = _run_main("edit src/hook.py", tmpdir, session_id=sid)
        assert "_map.md" in r1["hookSpecificOutput"]["additionalContext"]
        assert "code-quality-performance" not in r1["hookSpecificOutput"]["additionalContext"]
        # Turn 2: add "性能" → performance spec joins; _map.md was deduped.
        r2 = _run_main("edit src/hook.py 注意性能", tmpdir, session_id=sid)
        ctx2 = r2["hookSpecificOutput"]["additionalContext"]
        assert "code-quality-performance" in ctx2
        assert "_map.md" not in ctx2


def test_main_dedup_resets_on_new_session():
    """Different session_id → dedup state reset, spec re-injects on first turn."""
    with tempfile.TemporaryDirectory() as tmpdir:
        _make_project(tmpdir)
        _set_dedup_window(tmpdir, 5)
        r1 = _run_main("edit src/hook.py", tmpdir, session_id="sess-1")
        assert "hookSpecificOutput" in r1
        r2 = _run_main("edit src/hook.py", tmpdir, session_id="sess-2")
        assert "hookSpecificOutput" in r2
        assert "_map.md" in r2["hookSpecificOutput"]["additionalContext"]


def test_main_dedup_disabled_when_window_zero():
    """dedup_window=0 → every call re-injects (legacy behavior preserved)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        _make_project(tmpdir)
        _set_dedup_window(tmpdir, 0)
        sid = "sess-ddd"
        r1 = _run_main("edit src/hook.py", tmpdir, session_id=sid)
        assert "hookSpecificOutput" in r1
        r2 = _run_main("edit src/hook.py", tmpdir, session_id=sid)
        assert "hookSpecificOutput" in r2  # not deduped
        assert "_map.md" in r2["hookSpecificOutput"]["additionalContext"]


def test_main_inject_disabled_no_output():
    with tempfile.TemporaryDirectory() as tmpdir:
        _make_project(tmpdir)
        # Overwrite config with auto=false
        config_path = os.path.join(tmpdir, ".code-flow", "config.yml")
        with open(config_path) as f:
            cfg = yaml.safe_load(f)
        cfg["inject"]["auto"] = False
        with open(config_path, "w") as f:
            yaml.dump(cfg, f)

        result = _run_main("edit src/core/cf_core.py", tmpdir)
        assert result == {}


def test_main_stale_mapping_falls_back_to_discovered_domain_specs():
    with tempfile.TemporaryDirectory() as tmpdir:
        _make_project_with_stale_mapping(tmpdir)
        result = _run_main("edit src/cli.js to improve argument parsing", tmpdir)
        assert "hookSpecificOutput" in result
        ctx = result["hookSpecificOutput"]["additionalContext"]
        assert "cli/_map.md" in ctx


# --- NEW: prompt_tags tests (TASK-003) ---
def test_main_chinese_prompt_injects_performance_spec():
    """Chinese prompt "性能" should inject performance spec even without file paths."""
    with tempfile.TemporaryDirectory() as tmpdir:
        _make_project(tmpdir)
        # Chinese-only prompt, no file paths
        result = _run_main("写一个用户登录服务，注意性能和异常处理", tmpdir)
        assert "hookSpecificOutput" in result
        ctx = result["hookSpecificOutput"]["additionalContext"]
        # Should inject performance spec
        assert "code-quality-performance" in ctx


def test_main_english_keyword_injects_matching_spec():
    """English keyword like 'performance' should inject matching spec."""
    with tempfile.TemporaryDirectory() as tmpdir:
        _make_project(tmpdir)
        result = _run_main("add retry and cache for better performance", tmpdir)
        assert "hookSpecificOutput" in result
        ctx = result["hookSpecificOutput"]["additionalContext"]
        assert "code-quality-performance" in ctx


def test_main_prompt_tags_debug_output():
    """When CF_DEBUG=1, debug info should include prompt_tags."""
    with tempfile.TemporaryDirectory() as tmpdir:
        _make_project(tmpdir)
        # Set CF_DEBUG env var
        with mock.patch.dict(os.environ, {"CF_DEBUG": "1"}):
            result = _run_main("写一个高性能的接口", tmpdir)
        assert "debug" in result
        # debug info should include prompt_tags
        assert "prompt_tags" in result["debug"]


def test_main_resolve_session_id_from_hook_data():
    """session_id should come from hook data, not PID.

    Verified by reading .inject-state after a run and asserting it persisted
    the hook-provided session_id rather than the PID.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        _make_project(tmpdir)
        custom_session = "custom-session-12345"
        _run_main("edit src/core/cf_core.py", tmpdir, pid="99999", session_id=custom_session)
        state_path = os.path.join(tmpdir, ".code-flow", ".inject-state")
        with open(state_path, "r", encoding="utf-8") as f:
            state = json.load(f)
        assert state["session_id"] == custom_session
        assert state["session_id"] != "99999"


def _make_project_with_compressible_spec(tmpdir: str, compress: bool = True) -> str:
    """Project where matched spec is full of redundancy for compression testing."""
    cf_dir = os.path.join(tmpdir, ".code-flow")
    specs_dir = os.path.join(cf_dir, "specs", "scripts")
    os.makedirs(specs_dir, exist_ok=True)
    with open(os.path.join(specs_dir, "_map.md"), "w", encoding="utf-8") as f:
        f.write("# Map  \n\n\n\nkeep me\n")
    with open(os.path.join(specs_dir, "rules.md"), "w", encoding="utf-8") as f:
        f.write(
            "## Rules   \n"
            "<!-- internal note: drop me -->\n"
            "- always validate  \n"
            "- always validate\n"
            "\n\n\n\n"
            "- handle errors\n"
        )
    config = {
        "version": 1,
        "budget": {"l1_max": 1700, "map_max": 400},
        "inject": {
            "auto": True,
            "compress": compress,
            "code_extensions": [".py"],
        },
        "path_mapping": {
            "scripts": {
                "patterns": ["**/*.py"],
                "specs": [
                    {"path": "scripts/_map.md", "tags": ["*"], "tier": 0},
                    {"path": "scripts/rules.md", "tags": ["*"], "tier": 1},
                ],
            }
        },
    }
    with open(os.path.join(cf_dir, "config.yml"), "w", encoding="utf-8") as f:
        yaml.dump(config, f)
    return tmpdir


def test_user_prompt_applies_compression():
    """Prompt referencing a .py file → matched spec should be compressed in context."""
    with tempfile.TemporaryDirectory() as tmpdir:
        _make_project_with_compressible_spec(tmpdir, compress=True)
        result = _run_main("edit src/whatever.py to fix a bug", tmpdir)
        assert "hookSpecificOutput" in result
        ctx = result["hookSpecificOutput"]["additionalContext"]
        # Compression markers: no triple-blank, HTML comment stripped, dedup
        assert "\n\n\n" not in ctx
        assert "internal note" not in ctx
        assert ctx.count("- always validate") == 1
        # Real content preserved
        assert "## Rules" in ctx
        assert "handle errors" in ctx


def test_main_no_tag_match_emits_no_fallback_log():
    """Strict match: no path / no tag hit → no fallback log line.

    The bulk-load fallback and its debug log entry were removed. This test
    guards the regression: we should NEVER emit reason=no_tag_match again.
    """
    original = os.environ.get("CF_DEBUG")
    os.environ["CF_DEBUG"] = "1"
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            _make_project(tmpdir)
            _run_main("hello there nothing matches anything at all", tmpdir)
            log_path = os.path.join(tmpdir, ".code-flow", ".debug.log")
            if os.path.exists(log_path):
                with open(log_path, "r", encoding="utf-8") as f:
                    content = f.read()
                assert "reason=no_tag_match" not in content
                assert "user_prompt_hook fallback domain=" not in content
    finally:
        if original is None:
            del os.environ["CF_DEBUG"]
        else:
            os.environ["CF_DEBUG"] = original


if __name__ == "__main__":
    import traceback
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    passed = 0
    failed = 0
    for test in tests:
        try:
            test()
            passed += 1
            print(f" PASS {test.__name__}")
        except Exception:
            failed += 1
            print(f" FAIL {test.__name__}")
            traceback.print_exc()
    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
