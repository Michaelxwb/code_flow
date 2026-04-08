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
