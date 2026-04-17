#!/usr/bin/env python3
"""Tests for cf_stats.py — covers missing spec warnings and JSON output."""
import io
import json
import os
import sys
import tempfile
import unittest.mock as mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "core", "code-flow", "scripts"))

from cf_stats import main


def _write(path: str, content: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


def _run_stats(project_root: str, args: list[str]) -> str:
    with mock.patch("sys.argv", ["cf_stats.py", *args]), \
         mock.patch("sys.stdout", io.StringIO()) as out, \
         mock.patch("os.getcwd", return_value=project_root):
        main()
        return out.getvalue()


def test_json_reports_missing_specs_and_domain_warning() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        _write(
            os.path.join(tmpdir, ".code-flow", "config.yml"),
            """
version: 1
budget:
  total: 2500
  l0_max: 800
  l1_max: 1700
path_mapping:
  backend:
    patterns:
      - "**/*.py"
    specs:
      - path: "backend/_map.md"
      - path: "backend/code-quality-performance.md"
""".strip() + "\n",
        )

        output = _run_stats(tmpdir, [])
        data = json.loads(output)

        assert data["l1"] == {}
        assert len(data["missing_specs"]) == 2
        assert any(item["path"] == "backend/_map.md" for item in data["missing_specs"])
        assert any(item["path"] == "backend/code-quality-performance.md" for item in data["missing_specs"])
        assert any("配置的 spec 文件缺失: 2 个" in warning for warning in data["warnings"])
        assert any("以下域未加载到任何 L1 spec: backend" in warning for warning in data["warnings"])


def test_json_reports_partial_missing_without_domain_empty_warning() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        _write(
            os.path.join(tmpdir, ".code-flow", "config.yml"),
            """
version: 1
budget:
  total: 2500
  l0_max: 800
  l1_max: 1700
path_mapping:
  backend:
    patterns:
      - "**/*.py"
    specs:
      - path: "backend/_map.md"
      - path: "backend/code-quality-performance.md"
""".strip() + "\n",
        )
        _write(
            os.path.join(tmpdir, ".code-flow", "specs", "backend", "_map.md"),
            "# Backend Map\n",
        )

        output = _run_stats(tmpdir, [])
        data = json.loads(output)

        assert "backend" in data["l1"]
        assert len(data["missing_specs"]) == 1
        assert data["missing_specs"][0]["path"] == "backend/code-quality-performance.md"
        assert any("配置的 spec 文件缺失: 1 个" in warning for warning in data["warnings"])
        assert not any("以下域未加载到任何 L1 spec" in warning for warning in data["warnings"])


def test_json_prefers_discovered_spec_domains_over_stale_path_mapping() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        _write(
            os.path.join(tmpdir, ".code-flow", "config.yml"),
            """
version: 1
budget:
  total: 2500
  l0_max: 800
  l1_max: 1700
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
            os.path.join(tmpdir, ".code-flow", "specs", "cli", "_map.md"),
            "# CLI Map\n",
        )
        _write(
            os.path.join(tmpdir, ".code-flow", "specs", "scripts", "_map.md"),
            "# Scripts Map\n",
        )

        output = _run_stats(tmpdir, [])
        data = json.loads(output)

        assert "cli" in data["l1"]
        assert "scripts" in data["l1"]
        assert "frontend" not in data["l1"]
        assert "backend" not in data["l1"]
        assert data["missing_specs"] == []
        assert not any("frontend" in warning or "backend" in warning for warning in data["warnings"])


_COMPRESSIBLE_SPEC = (
    "## Rules   \n"
    "<!-- internal note: drop me -->\n"
    "- always validate  \n"
    "- always validate\n"
    "\n\n\n\n"
    "- handle errors\n"
)


def _setup_compressible_project(tmpdir: str) -> None:
    _write(
        os.path.join(tmpdir, ".code-flow", "config.yml"),
        """
version: 1
budget:
  total: 2500
  l0_max: 800
  l1_max: 1700
path_mapping:
  backend:
    patterns:
      - "**/*.py"
    specs:
      - path: "backend/_map.md"
      - path: "backend/rules.md"
""".strip() + "\n",
    )
    _write(
        os.path.join(tmpdir, ".code-flow", "specs", "backend", "_map.md"),
        "# Map\n",
    )
    _write(
        os.path.join(tmpdir, ".code-flow", "specs", "backend", "rules.md"),
        _COMPRESSIBLE_SPEC,
    )


def test_stats_includes_compression_summary() -> None:
    """JSON output must include compression_summary with raw/compressed/saved_pct."""
    with tempfile.TemporaryDirectory() as tmpdir:
        _setup_compressible_project(tmpdir)
        output = _run_stats(tmpdir, [])
        data = json.loads(output)

        assert "compression_summary" in data
        summary = data["compression_summary"]
        assert "total_raw" in summary
        assert "total_compressed" in summary
        assert "total_saved_pct" in summary
        # Compressible spec should yield nonzero savings
        assert summary["total_raw"] > summary["total_compressed"]
        assert summary["total_saved_pct"] > 0

        # Each item also carries raw/compressed token counts
        rules_item = next(
            item for item in data["l1"]["backend"] if item["path"] == "backend/rules.md"
        )
        assert "tokens_raw" in rules_item
        assert "tokens_compressed" in rules_item
        assert "saved_pct" in rules_item
        assert rules_item["tokens_raw"] >= rules_item["tokens_compressed"]


def test_stats_human_output_has_compression_line() -> None:
    """Human output must end with a COMPRESSION: raw → compressed (-pct%) line."""
    with tempfile.TemporaryDirectory() as tmpdir:
        _setup_compressible_project(tmpdir)
        output = _run_stats(tmpdir, ["--human"])
        assert "COMPRESSION:" in output
        # Per-spec line includes raw→compressed annotation
        assert "raw=" in output and "compressed=" in output
        assert "→" in output


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
