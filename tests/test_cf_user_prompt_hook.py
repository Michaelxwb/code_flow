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


def test_main_no_paths_fallback_injects_tier0():
    """Prompt without file refs → fallback loads all domains, injects Tier0 maps."""
    with tempfile.TemporaryDirectory() as tmpdir:
        _make_project(tmpdir)
        result = _run_main("what does the auth flow do?", tmpdir)
        assert "hookSpecificOutput" in result
        # Tier0 _map.md should be in the injected content
        ctx = result["hookSpecificOutput"]["additionalContext"]
        assert "_map.md" in ctx or "Map" in ctx


def test_main_already_injected_skips():
    """Second call in same session with same spec → no output (already injected)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        _make_project(tmpdir)
        pid = "88888"
        # First call
        result1 = _run_main("edit src/hook.py", tmpdir, pid=pid)
        assert "hookSpecificOutput" in result1
        # Second call in same session — state persists on disk
        result2 = _run_main("also update src/other.py", tmpdir, pid=pid)
        # specs already injected → no output
        assert result2 == {}


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
    """session_id should come from hook data, not PID."""
    with tempfile.TemporaryDirectory() as tmpdir:
        _make_project(tmpdir)
        custom_session = "custom-session-12345"
        result = _run_main("edit src/core/cf_core.py", tmpdir, pid="99999", session_id=custom_session)
        # If session_id is properly resolved, subsequent call with same session should not re-inject
        result2 = _run_main("edit src/other.py", tmpdir, pid="99999", session_id=custom_session)
        # Same session, specs already injected → no output
        assert result2 == {}


def test_main_fallback_writes_debug_log_with_loaded_count():
    """Prompt with no path / no tag hits → fallback debug line with loaded=N."""
    original = os.environ.get("CF_DEBUG")
    os.environ["CF_DEBUG"] = "1"
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            _make_project(tmpdir)
            # Prompt with no file ref and no Chinese/English tag aliases
            _run_main("hello there nothing matches anything at all", tmpdir)
            log_path = os.path.join(tmpdir, ".code-flow", ".debug.log")
            assert os.path.exists(log_path), "CF_DEBUG=1 must produce debug log"
            with open(log_path, "r", encoding="utf-8") as f:
                content = f.read()
            assert "fallback" in content
            assert "loaded=" in content
            assert "reason=no_tag_match" in content
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
