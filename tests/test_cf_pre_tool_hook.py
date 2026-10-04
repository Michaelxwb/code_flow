#!/usr/bin/env python3
"""Regression coverage for the PreToolUse edit hot path."""

from pathlib import Path
from types import SimpleNamespace
import sys

import pytest


SCRIPTS = Path(__file__).resolve().parents[1] / "src" / "core" / "code-flow" / "scripts"
sys.path.insert(0, str(SCRIPTS))

import cf_edit_service


def test_active_expansion_uses_frontmatter_candidates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    marker = tmp_path / ".code-flow" / ".active-task.json"
    marker.parent.mkdir(parents=True)
    marker.write_text("{}", encoding="utf-8")
    active = SimpleNamespace(task_dir=".code-flow/tasks/demo")
    context = SimpleNamespace(bindings=(SimpleNamespace(spec_id="already-bound"),))
    candidates = (
        SimpleNamespace(spec_id="already-bound", enforcement="required"),
        SimpleNamespace(spec_id="new-required", enforcement="required"),
        SimpleNamespace(spec_id="new-advisory", enforcement="advisory"),
    )
    captured: list[tuple[str, str, tuple[str, ...]]] = []

    def resolve_headers(root: str, stage: str, paths: tuple[str, ...]) -> tuple[object, ...]:
        captured.append((root, stage, paths))
        return candidates

    monkeypatch.setattr(cf_edit_service, "load_active_task", lambda root: active)
    monkeypatch.setattr(cf_edit_service, "load_context", lambda path: context)
    monkeypatch.setattr(cf_edit_service, "resolve_candidate_headers", resolve_headers)

    result = cf_edit_service._active_expansion(str(tmp_path), "src/app.py")

    assert result == ("new-required",)
    assert captured == [(str(tmp_path), "code", ("src/app.py",))]


def test_scope_expansion_warns_without_blocking_required_edit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cf_edit_service, "load_config", lambda root: {})
    monkeypatch.setattr(cf_edit_service, "_active_expansion", lambda root, path: ("new-required",))
    monkeypatch.setattr(cf_edit_service, "route_prompt", lambda *args: SimpleNamespace())

    text, specs, blocked = cf_edit_service._routing_result(str(tmp_path), "src/app.py", "native")

    assert "new-required" in text
    assert "refresh Context / Plan" in text
    assert specs == ()
    assert blocked is False
