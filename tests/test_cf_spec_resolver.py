#!/usr/bin/env python3
"""S-08/B-01 integration coverage for deterministic Spec resolution."""

from pathlib import Path
import sys

import pytest
import yaml


SCRIPTS = Path(__file__).resolve().parents[1] / "src" / "core" / "code-flow" / "scripts"
sys.path.insert(0, str(SCRIPTS))

from cf_spec_resolver import (
    SpecResolutionError,
    build_candidate_page,
    resolve_candidates,
    resolve_precedence,
)


def _spec(
    spec_id: str,
    rule_id: str,
    text: str,
    *,
    enforcement: str = "required",
    stages: tuple[str, ...] = ("design",),
) -> str:
    stage_text = ", ".join(stages)
    return f"""---
id: {spec_id}
description: rules for {spec_id}
stages: [{stage_text}]
enforcement: {enforcement}
verifiers:
  - rule: {rule_id}
    type: manual
    config:
      checklist: review {rule_id}
      owner: maintainers
---

# {spec_id}

## Rules
- [{rule_id}] {text}
"""


def _write_project(tmp_path: Path, specs: dict[str, str], mapping: dict[str, object]) -> Path:
    flow = tmp_path / ".code-flow"
    spec_root = flow / "specs"
    for relative, content in specs.items():
        path = spec_root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    flow.mkdir(exist_ok=True)
    (flow / "config.yml").write_text(
        yaml.safe_dump({"path_mapping": mapping}, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    return tmp_path


def test_s_08_precedence_and_same_level_required_conflict(tmp_path: Path) -> None:
    common = "RULE-shared-001"
    conflict = "RULE-shared-002"
    specs = {
        "global/base.md": _spec("global-base", common, "Use the global behavior.", enforcement="advisory"),
        "backend/path.md": _spec("backend-path", common, "Use the path behavior."),
        "_session/task.md": "# Generated task projection without Spec metadata\n",
        "backend/conflict-a.md": _spec("path-conflict-a", conflict, "Choose behavior A."),
        "backend/conflict-b.md": _spec("path-conflict-b", conflict, "Choose behavior B."),
        "backend/code-only.md": _spec(
            "backend-code-only", "RULE-shared-003", "Only during code.", stages=("code",)
        ),
    }
    mapping = {
        "global": {"patterns": [], "specs": [{"path": "global/base.md"}]},
        "backend": {
            "patterns": ["src/*.py"],
            "specs": [
                {"path": "backend/path.md"},
                {"path": "backend/conflict-a.md"},
                {"path": "backend/conflict-b.md"},
                {"path": "backend/code-only.md"},
            ],
        },
    }
    root = _write_project(tmp_path, specs, mapping)

    candidates = resolve_candidates(str(root), "design", ["src/app.py"])
    by_id = {candidate.spec_id: candidate for candidate in candidates}
    assert "backend-code-only" not in by_id
    assert by_id["global-base"].scope == "global"
    assert by_id["backend-path"].scope == "path"
    assert "task-session" not in by_id

    path_resolution = resolve_precedence((by_id["global-base"], by_id["backend-path"]))
    assert path_resolution.effective_rules[0].spec_id == "backend-path"
    assert path_resolution.effective_rules[0].overridden_spec_ids == ("global-base",)

    resolution = resolve_precedence(candidates)
    effective = {rule.ref: rule for rule in resolution.effective_rules}
    conflicts = {item.ref: item for item in resolution.conflicts}
    assert effective[common].spec_id == "backend-path"
    assert effective[common].overridden_spec_ids == ("global-base",)
    assert conflict not in effective
    assert conflicts[conflict].spec_ids == ("path-conflict-a", "path-conflict-b")
    assert conflicts[conflict].priority == 2


def test_b_01_machine_candidates_remain_complete_when_page_is_trimmed(tmp_path: Path) -> None:
    specs: dict[str, str] = {}
    entries: list[dict[str, str]] = []
    for index in range(500):
        relative = f"bulk/spec-{index:03d}.md"
        specs[relative] = _spec(
            f"bulk-spec-{index:03d}",
            f"RULE-bulk-{index + 1:03d}",
            f"Required behavior {index}.",
        )
        entries.append({"path": relative})
    root = _write_project(
        tmp_path,
        specs,
        {"bulk": {"patterns": ["bulk-src/*.py"], "specs": entries}},
    )

    first = resolve_candidates(str(root), "design", [])
    page = build_candidate_page(first, limit=25)
    second = resolve_candidates(str(root), "design", [])

    assert len(first) == 500
    assert page.total == 500
    assert len(page.items) == 25
    assert page.has_more is True
    assert len(first) == 500
    assert all(left.metadata is right.metadata for left, right in zip(first, second))
    assert sum(candidate.required_rule_count for candidate in first) == 500


def test_resolver_missing_config_is_explicit_error(tmp_path: Path) -> None:
    (tmp_path / ".code-flow" / "specs").mkdir(parents=True)

    with pytest.raises(SpecResolutionError) as caught:
        resolve_candidates(str(tmp_path), "design", [])

    assert caught.value.field == "config"
    assert "config.yml" in str(caught.value)
