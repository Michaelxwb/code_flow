#!/usr/bin/env python3
"""Retained cf_core primitives after the schema-1 router migration."""

import os
from pathlib import Path
import sys
import tempfile

import yaml

SCRIPTS = Path(__file__).resolve().parents[1] / "src/core/code-flow/scripts"
sys.path.insert(0, str(SCRIPTS))

from cf_core import (
    compress_content,
    debug_log,
    ensure_utf8_io,
    estimate_tokens,
    extract_context_tags,
    is_code_file,
    match_domains,
    normalize_spec_entry,
    resolve_session_id,
)


def test_context_tags_and_safe_deplural() -> None:
    tags = extract_context_tags("models/services/address.py")
    assert {"model", "database", "service", "address"} <= tags
    assert "addres" not in tags


def test_normalize_spec_entries() -> None:
    old = normalize_spec_entry("backend/database.md")
    new = normalize_spec_entry({"path": "backend/logging.md", "tags": ["log"], "tier": 1})
    assert old == {"path": "backend/database.md", "tags": ["*"], "tier": 1}
    assert new["tags"] == ["log"]


def test_code_file_and_domain_mapping() -> None:
    config = {"code_extensions": [".py"], "skip_extensions": [".md"], "skip_paths": ["docs/**"]}
    mapping = {"backend": {"patterns": ["**/*.py", "services/**"]}}
    assert is_code_file("services/app.py", config) is True
    assert is_code_file("docs/app.py", config) is False
    assert match_domains("services/app.py", mapping) == ["backend"]


def test_frontend_template_matches_service_and_composable_files() -> None:
    config_path = Path(__file__).resolve().parents[1] / "src/core/code-flow/config.yml"
    mapping = yaml.safe_load(config_path.read_text(encoding="utf-8"))["path_mapping"]
    assert "frontend" in match_domains("src/services/products.js", mapping)
    assert "frontend" in match_domains("src/composables/useProducts.js", mapping)


def test_estimate_tokens_uses_stable_formula() -> None:
    assert estimate_tokens("a" * 400) == 100


def test_resolve_session_id_prefers_payload_and_has_fallback() -> None:
    assert resolve_session_id({"session_id": "abc"}) == "abc"
    assert resolve_session_id({}) == str(os.getpid())


def test_debug_log_respects_environment() -> None:
    original = os.environ.get("CF_DEBUG")
    try:
        with tempfile.TemporaryDirectory() as root:
            os.environ.pop("CF_DEBUG", None)
            debug_log("hidden", root)
            assert not (Path(root) / ".code-flow/.debug.log").exists()
            os.environ["CF_DEBUG"] = "1"
            debug_log("visible", root)
            assert "visible" in (Path(root) / ".code-flow/.debug.log").read_text(encoding="utf-8")
    finally:
        if original is None:
            os.environ.pop("CF_DEBUG", None)
        else:
            os.environ["CF_DEBUG"] = original


def test_compress_content_is_lossless_for_structure_and_idempotent() -> None:
    text = "# H1   \n\n\n<!-- drop -->\n- item\n- item\n\n```python\n- item\n- item\n```\n"
    result = compress_content(text)
    assert "drop" not in result
    assert "\n\n\n" not in result
    assert result.count("- item") == 3
    assert compress_content(result) == result


class _Stream:
    def __init__(self, raises: bool = False) -> None:
        self.raises = raises
        self.calls = []

    def reconfigure(self, **kwargs: str) -> None:
        self.calls.append(kwargs)
        if self.raises:
            raise OSError("unsupported")


def test_ensure_utf8_io_reconfigures_and_tolerates_unsupported_stream() -> None:
    streams = (_Stream(), _Stream(), _Stream(True))
    saved = sys.stdin, sys.stdout, sys.stderr
    sys.stdin, sys.stdout, sys.stderr = streams
    try:
        ensure_utf8_io()
    finally:
        sys.stdin, sys.stdout, sys.stderr = saved
    assert all(stream.calls == [{"encoding": "utf-8"}] for stream in streams)


def test_resolve_enforcement_modes_and_defaults() -> None:
    from cf_core import resolve_enforcement

    assert resolve_enforcement({"spec_workflow": {"enforcement": "required"}}) == "required"
    assert resolve_enforcement({"spec_workflow": {"enforcement": "warn"}}) == "warn"
    assert resolve_enforcement({"spec_workflow": {"enforcement": "inject"}}) == "inject"
    assert resolve_enforcement({"spec_workflow": {"enforcement": "bogus"}}) == "required"
    assert resolve_enforcement({"spec_workflow": {}}) == "required"
    assert resolve_enforcement({}) == "required"
    assert resolve_enforcement(None) == "required"
