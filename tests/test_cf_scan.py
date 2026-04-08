#!/usr/bin/env python3
"""Tests for cf_scan.py — ensure scan follows on-disk specs, not stale path_mapping."""
import io
import json
import os
import sys
import tempfile
import unittest.mock as mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "core", "code-flow", "scripts"))

from cf_scan import main


def _write(path: str, content: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


def _run_scan(project_root: str, args: list[str]) -> str:
    with mock.patch("sys.argv", ["cf_scan.py", *args]), \
         mock.patch("sys.stdout", io.StringIO()) as out, \
         mock.patch("os.getcwd", return_value=project_root):
        main()
        return out.getvalue()


def test_scan_json_uses_discovered_specs_when_mapping_is_stale() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        _write(
            os.path.join(tmpdir, ".code-flow", "config.yml"),
            """
version: 1
budget:
  total: 2500
path_mapping:
  frontend:
    patterns:
      - "**/*.tsx"
    specs:
      - path: "frontend/_map.md"
  backend:
    patterns:
      - "**/*.py"
    specs:
      - path: "backend/_map.md"
""".strip() + "\n",
        )
        _write(
            os.path.join(tmpdir, "CLAUDE.md"),
            "# Local Agent Rules\n",
        )
        _write(
            os.path.join(tmpdir, ".code-flow", "specs", "cli", "_map.md"),
            "# CLI Map\n",
        )
        _write(
            os.path.join(tmpdir, ".code-flow", "specs", "scripts", "_map.md"),
            "# Scripts Map\n",
        )

        output = _run_scan(tmpdir, ["--json"])
        data = json.loads(output)
        paths = [item["path"] for item in data["files"]]

        assert "specs/cli/_map.md" in paths
        assert "specs/scripts/_map.md" in paths
        assert not any(path.startswith("specs/frontend/") for path in paths)
        assert not any(path.startswith("specs/backend/") for path in paths)


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
