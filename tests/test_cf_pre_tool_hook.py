#!/usr/bin/env python3
"""Regression coverage for the PreToolUse edit hot path."""

from pathlib import Path
from types import SimpleNamespace
import sys

import pytest


SCRIPTS = Path(__file__).resolve().parents[1] / "src" / "core" / "code-flow" / "scripts"
sys.path.insert(0, str(SCRIPTS))

from codeflow.spec import cf_edit_service
from codeflow.spec import cf_spec_router
from codeflow.spec.cf_spec_router import RouteResult


def test_active_expansion_uses_frontmatter_candidates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    context = SimpleNamespace(bindings=(SimpleNamespace(spec_id="already-bound", path="app/rules.md"),))
    candidates = (
        SimpleNamespace(spec_id="already-bound", enforcement="required"),
        SimpleNamespace(spec_id="new-required", enforcement="required"),
        SimpleNamespace(spec_id="new-advisory", enforcement="advisory"),
    )
    captured: list[tuple[str, str, tuple[str, ...]]] = []

    def resolve_headers(root: str, stage: str, paths: tuple[str, ...], **kwargs: object) -> tuple[object, ...]:
        assert kwargs == {"matched_only": True, "excluded_paths": ("app/rules.md",)}
        captured.append((root, stage, paths))
        return candidates

    monkeypatch.setattr(cf_spec_router, "resolve_candidate_headers", resolve_headers)

    result = cf_spec_router._scope_expansion(str(tmp_path), context, ("src/app.py",))

    assert result == ("new-required",)
    assert captured == [(str(tmp_path), "code", ("src/app.py",))]


def test_scope_expansion_warns_without_blocking_required_edit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cf_edit_service, "load_config", lambda root: {})
    result = RouteResult("task", "bound rules", ("bound",), "hash", ("new-required",))
    monkeypatch.setattr(cf_edit_service, "route_prompt", lambda *args, **kwargs: result)

    text, specs, blocked = cf_edit_service._routing_result(str(tmp_path), "src/app.py", "native")

    assert "new-required" in text
    assert "refresh Context / Plan" in text
    assert "bound rules" in text
    assert specs == ("bound",)
    assert blocked is False
