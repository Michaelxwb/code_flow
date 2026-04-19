#!/usr/bin/env python3
"""Tests for cf_inject_hook.py — covers stale path_mapping fallback behavior."""
import io
import json
import os
import sys
import tempfile
import unittest.mock as mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "core", "code-flow", "scripts"))

from cf_inject_hook import main


def _make_project_with_stale_mapping(tmpdir: str) -> str:
    cf_dir = os.path.join(tmpdir, ".code-flow")
    specs_dir = os.path.join(cf_dir, "specs", "cli")
    os.makedirs(specs_dir, exist_ok=True)

    with open(os.path.join(specs_dir, "_map.md"), "w", encoding="utf-8") as f:
        f.write("# CLI Map\n")
    with open(os.path.join(specs_dir, "code-standards.md"), "w", encoding="utf-8") as f:
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
    import yaml

    with open(os.path.join(cf_dir, "config.yml"), "w", encoding="utf-8") as f:
        yaml.dump(config, f)
    return tmpdir


def _run_main(file_path: str, project_root: str, pid: str = "77777") -> dict:
    stdin_data = json.dumps({
        "tool_name": "Edit",
        "tool_input": {"file_path": file_path},
    })
    with mock.patch("sys.stdin", io.StringIO(stdin_data)), \
         mock.patch("sys.stdout", io.StringIO()) as out, \
         mock.patch("os.getcwd", return_value=project_root), \
         mock.patch("os.getpid", return_value=int(pid)):
        main()
        output = out.getvalue()
    return json.loads(output) if output.strip() else {}


def test_main_stale_mapping_falls_back_to_discovered_domain_specs() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        _make_project_with_stale_mapping(tmpdir)
        result = _run_main("src/cli.js", tmpdir)
        assert "hookSpecificOutput" in result
        context = result["hookSpecificOutput"]["additionalContext"]
        assert "cli/_map.md" in context


def _make_project_with_unmatched_tier1(tmpdir: str) -> str:
    """A project where path_mapping matches but no spec tag intersects context_tags,
    so cf_inject_hook must take the `not has_tier1_match` fallback branch."""
    cf_dir = os.path.join(tmpdir, ".code-flow")
    specs_dir = os.path.join(cf_dir, "specs", "backend")
    os.makedirs(specs_dir, exist_ok=True)
    with open(os.path.join(specs_dir, "_map.md"), "w", encoding="utf-8") as f:
        f.write("# Map\n")
    with open(os.path.join(specs_dir, "rules-a.md"), "w", encoding="utf-8") as f:
        f.write("# Rules A\n")
    with open(os.path.join(specs_dir, "rules-b.md"), "w", encoding="utf-8") as f:
        f.write("# Rules B\n")

    config = {
        "version": 1,
        "budget": {"l1_max": 1700, "map_max": 400},
        "inject": {"auto": True, "code_extensions": [".py"]},
        "path_mapping": {
            "backend": {
                "patterns": ["**/*.py"],
                "specs": [
                    {"path": "backend/_map.md", "tags": ["*"], "tier": 0},
                    {"path": "backend/rules-a.md", "tags": ["very-specific-tag-not-in-any-path"], "tier": 1},
                    {"path": "backend/rules-b.md", "tags": ["another-unmatchable-tag"], "tier": 1},
                ],
            }
        },
    }
    import yaml
    with open(os.path.join(cf_dir, "config.yml"), "w", encoding="utf-8") as f:
        yaml.dump(config, f)
    return tmpdir


def test_inject_hook_unmatched_tier1_injects_only_tier0() -> None:
    """Strict match: Tier 1 tags miss → only Tier 0 (wildcard) gets injected.

    Bulk-load fallback was removed. A Tier 1 spec whose tags don't intersect
    context_tags must NOT be injected. Tier 0 uses '*' so navigation still
    reaches the model.
    """
    original = os.environ.get("CF_DEBUG")
    os.environ["CF_DEBUG"] = "1"
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            _make_project_with_unmatched_tier1(tmpdir)
            result = _run_main("src/whatever.py", tmpdir)
            assert "hookSpecificOutput" in result
            ctx = result["hookSpecificOutput"]["additionalContext"]
            assert "backend/_map.md" in ctx
            assert "backend/rules-a.md" not in ctx
            assert "backend/rules-b.md" not in ctx

            log_path = os.path.join(tmpdir, ".code-flow", ".debug.log")
            if os.path.exists(log_path):
                with open(log_path, "r", encoding="utf-8") as f:
                    content = f.read()
                assert "reason=no_tag_match" not in content
                assert "inject_hook fallback" not in content
    finally:
        if original is None:
            del os.environ["CF_DEBUG"]
        else:
            os.environ["CF_DEBUG"] = original


def _make_project_with_explicit_tag_hit(tmpdir: str) -> str:
    """A project where context_tags from path explicitly intersect a tier1 spec tag,
    so cf_inject_hook should NOT take the fallback branch."""
    cf_dir = os.path.join(tmpdir, ".code-flow")
    specs_dir = os.path.join(cf_dir, "specs", "backend")
    os.makedirs(specs_dir, exist_ok=True)
    with open(os.path.join(specs_dir, "_map.md"), "w", encoding="utf-8") as f:
        f.write("# Map\n")
    with open(os.path.join(specs_dir, "database.md"), "w", encoding="utf-8") as f:
        f.write("# DB\n")

    config = {
        "version": 1,
        "budget": {"l1_max": 1700, "map_max": 400},
        "inject": {"auto": True, "code_extensions": [".py"]},
        "path_mapping": {
            "backend": {
                "patterns": ["**/*.py"],
                "specs": [
                    {"path": "backend/_map.md", "tags": ["*"], "tier": 0},
                    # explicit non-wildcard tier-1 tag that "models/" semantic mapping hits
                    {"path": "backend/database.md", "tags": ["database", "model"], "tier": 1},
                ],
            }
        },
    }
    import yaml
    with open(os.path.join(cf_dir, "config.yml"), "w", encoding="utf-8") as f:
        yaml.dump(config, f)
    return tmpdir


def test_inject_hook_no_fallback_log_when_tag_matches() -> None:
    """Explicit tag match → no fallback log (strict-match regime never emits it)."""
    original = os.environ.get("CF_DEBUG")
    os.environ["CF_DEBUG"] = "1"
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            _make_project_with_explicit_tag_hit(tmpdir)
            # models/ → semantic tags include "database" + "model" → matches database.md tier1
            _run_main("models/user.py", tmpdir)
            log_path = os.path.join(tmpdir, ".code-flow", ".debug.log")
            if os.path.exists(log_path):
                with open(log_path, "r", encoding="utf-8") as f:
                    content = f.read()
                assert "reason=no_tag_match" not in content, (
                    f"tag-matched path must not trigger fallback log; got: {content}"
                )
    finally:
        if original is None:
            del os.environ["CF_DEBUG"]
        else:
            os.environ["CF_DEBUG"] = original


def _make_project_with_compressible_spec(tmpdir: str, compress: bool = True) -> str:
    """Project with a spec file full of redundancy: multi-blank-lines, HTML comments,
    trailing whitespace, duplicate bullets. Compression should demonstrably shrink it.
    """
    cf_dir = os.path.join(tmpdir, ".code-flow")
    specs_dir = os.path.join(cf_dir, "specs", "backend")
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
            "backend": {
                "patterns": ["**/*.py"],
                "specs": [
                    {"path": "backend/_map.md", "tags": ["*"], "tier": 0},
                    {"path": "backend/rules.md", "tags": ["*"], "tier": 1},
                ],
            }
        },
    }
    import yaml
    with open(os.path.join(cf_dir, "config.yml"), "w", encoding="utf-8") as f:
        yaml.dump(config, f)
    return tmpdir


def test_inject_applies_compression() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        _make_project_with_compressible_spec(tmpdir, compress=True)
        result = _run_main("src/whatever.py", tmpdir)
        ctx = result["hookSpecificOutput"]["additionalContext"]
        assert "\n\n\n" not in ctx
        assert "internal note" not in ctx
        # Duplicate bullet collapsed
        assert ctx.count("- always validate") == 1
        # Real content preserved
        assert "## Rules" in ctx
        assert "handle errors" in ctx


def test_inject_compress_disabled_via_config() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        _make_project_with_compressible_spec(tmpdir, compress=False)
        result = _run_main("src/whatever.py", tmpdir)
        ctx = result["hookSpecificOutput"]["additionalContext"]
        # Raw content should come through unaltered
        assert "\n\n\n" in ctx
        assert "internal note: drop me" in ctx
        assert ctx.count("- always validate") == 2


def test_inject_compress_falls_back_on_exception() -> None:
    """compress_content raising must not drop the spec: raw text still injected."""
    with tempfile.TemporaryDirectory() as tmpdir:
        _make_project_with_compressible_spec(tmpdir, compress=True)
        with mock.patch("cf_core.compress_content", side_effect=RuntimeError("boom")):
            result = _run_main("src/whatever.py", tmpdir)
        assert "hookSpecificOutput" in result
        ctx = result["hookSpecificOutput"]["additionalContext"]
        # Raw content survives the broken compressor — markers from the
        # redundant source should still be present.
        assert "internal note: drop me" in ctx
        assert ctx.count("- always validate") == 2


if __name__ == "__main__":
    import traceback

    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    passed = 0
    failed = 0
    for test in tests:
        try:
            test()
            passed += 1
            print(f"  PASS {test.__name__}")
        except Exception:
            failed += 1
            print(f"  FAIL {test.__name__}")
            traceback.print_exc()
    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
