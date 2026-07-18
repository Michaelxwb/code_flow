#!/usr/bin/env python3
"""E-01 integration coverage for schema-v1 Spec metadata parsing."""

from pathlib import Path
import sys
import textwrap

import pytest


SCRIPTS = Path(__file__).resolve().parents[1] / "src" / "core" / "code-flow" / "scripts"
sys.path.insert(0, str(SCRIPTS))

from cf_spec_metadata import SpecMetadataError, load_spec_metadata


VALID_SPEC = """\
---
id: scripts-code-standards
description: Python workflow rules
stages: [design, plan, code, review]
enforcement: required
owner: code-flow-maintainers
checks:
  - id: no-print-debug
    type: regex
    pattern: '^\\s*print\\('
    files: '*_hook.py'
    message: no print
verifiers:
  - rule: RULE-scripts-001
    type: regex
    config:
      check_id: no-print-debug
  - rule: RULE-scripts-002
    type: manual
    config:
      checklist: review exception handling
      owner: maintainers
---

# Python Standards

## Rules
- [RULE-scripts-001] Hook stdout must stay JSON.

## Patterns
- Use typed helper functions.

## Anti-Patterns
- Silent exception handling is forbidden.

## Examples
- A hook writes diagnostics to stderr.
"""


def _write_spec(tmp_path: Path, content: str = VALID_SPEC) -> Path:
    path = tmp_path / "scripts" / "code-standards.md"
    path.parent.mkdir(parents=True)
    path.write_text(textwrap.dedent(content), encoding="utf-8")
    return path


def test_e_01_valid_metadata_produces_stable_ids_and_hashes(tmp_path: Path) -> None:
    path = _write_spec(tmp_path)

    first = load_spec_metadata(str(path))
    second = load_spec_metadata(str(path))

    assert first == second
    assert first.id == "scripts-code-standards"
    assert first.stages == ("design", "plan", "code", "review")
    assert [rule.ref for rule in first.rules] == [
        "RULE-scripts-001",
        "PATTERN-scripts-001",
        "RULE-scripts-002",
        "EXAMPLE-scripts-001",
    ]
    assert [rule.enforcement for rule in first.rules] == [
        "required",
        "advisory",
        "required",
        "informational",
    ]
    assert all(len(value) == 64 for value in first.hashes.values())
    assert all(len(rule.text_sha256) == 64 for rule in first.rules)


def test_e_01_metadata_only_change_preserves_rule_hashes(tmp_path: Path) -> None:
    path = _write_spec(tmp_path)
    before = load_spec_metadata(str(path))
    path.write_text(VALID_SPEC.replace("code-flow-maintainers", "platform-team"), encoding="utf-8")

    after = load_spec_metadata(str(path))

    assert after.hashes.file_sha256 != before.hashes.file_sha256
    assert after.hashes.metadata_sha256 != before.hashes.metadata_sha256
    assert after.hashes.rules_sha256 == before.hashes.rules_sha256
    assert [rule.text_sha256 for rule in after.rules] == [
        rule.text_sha256 for rule in before.rules
    ]


def test_e_01_rule_change_updates_only_affected_rule_hash(tmp_path: Path) -> None:
    path = _write_spec(tmp_path)
    before = load_spec_metadata(str(path))
    changed = VALID_SPEC.replace("Hook stdout must stay JSON.", "Hook stdout must be one JSON object.")
    path.write_text(changed, encoding="utf-8")

    after = load_spec_metadata(str(path))

    assert after.hashes.rules_sha256 != before.hashes.rules_sha256
    assert after.rules[0].text_sha256 != before.rules[0].text_sha256
    assert [rule.text_sha256 for rule in after.rules[1:]] == [
        rule.text_sha256 for rule in before.rules[1:]
    ]


@pytest.mark.parametrize(
    ("old", "new", "field", "line"),
    [
        ("stages: [design, plan, code, review]", "stages: [design, deploy]", "stages", 4),
        ("enforcement: required", "enforcement: optional", "enforcement", 5),
        (
            "  - rule: RULE-scripts-001\n    type: regex",
            "  - rule: RULE-scripts-001\n    type: magic",
            "verifiers[0].type",
            15,
        ),
    ],
)
def test_e_01_invalid_schema_reports_path_field_and_line(
    tmp_path: Path, old: str, new: str, field: str, line: int
) -> None:
    path = _write_spec(tmp_path, VALID_SPEC.replace(old, new, 1))

    with pytest.raises(SpecMetadataError) as caught:
        load_spec_metadata(str(path))

    error = caught.value
    assert error.path == str(path)
    assert error.field == field
    assert error.line == line
    assert str(path) in str(error)
    assert field in str(error)


def test_e_01_required_rule_without_verifier_is_rejected(tmp_path: Path) -> None:
    verifier = """\
  - rule: RULE-scripts-002
    type: manual
    config:
      checklist: review exception handling
      owner: maintainers
"""
    path = _write_spec(tmp_path, VALID_SPEC.replace(verifier, ""))

    with pytest.raises(SpecMetadataError) as caught:
        load_spec_metadata(str(path))

    assert caught.value.field == "verifiers"
    assert "RULE-scripts-002" in str(caught.value)
    assert caught.value.line > 0


def test_e_01_broken_yaml_reports_frontmatter_location(tmp_path: Path) -> None:
    path = _write_spec(tmp_path, VALID_SPEC.replace("stages: [design, plan, code, review]", "stages: [design"))

    with pytest.raises(SpecMetadataError) as caught:
        load_spec_metadata(str(path))

    assert caught.value.field == "frontmatter"
    assert caught.value.line > 0
    assert "YAML" in str(caught.value)


def test_e_01_fenced_and_unrecognized_sections_do_not_create_rules(tmp_path: Path) -> None:
    extra = """

```markdown
- This fenced example is not a Rule.
```

## Notes
- This note is not an Example.
"""
    path = _write_spec(tmp_path, VALID_SPEC + extra)

    metadata = load_spec_metadata(str(path))

    assert len(metadata.rules) == 4


def test_e_01_invalid_explicit_rule_id_reports_body_line(tmp_path: Path) -> None:
    content = VALID_SPEC.replace("[RULE-scripts-001]", "[RULE-SCRIPTS-1]", 1)
    path = _write_spec(tmp_path, content)

    with pytest.raises(SpecMetadataError) as caught:
        load_spec_metadata(str(path))

    assert caught.value.field == "rules"
    assert caught.value.line > 20
    assert "RULE-<domain>-NNN" in str(caught.value)
