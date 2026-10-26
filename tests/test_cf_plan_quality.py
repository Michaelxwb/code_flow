"""Plan quality: checklist scenario IDs must match the TASK's Acceptance-Refs."""
from __future__ import annotations

import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "src/core/code-flow/scripts"
sys.path.insert(0, str(SCRIPTS))

from codeflow.acceptance.cf_plan_quality import _checklist_issues  # noqa: E402


def test_checklist_flags_scenario_missing_from_refs() -> None:
    text = (
        "## TASK-001: demo\n"
        "- **Acceptance-Refs**: S-01\n"
        "### Checklist\n"
        "- [ ] [S-01] ok\n"
        "- [ ] [E-01] wrong task\n"
        "### Acceptance Contract\n"
    )
    assert _checklist_issues(text) == [
        {"code": "checklist_scenario_not_in_refs", "task": "TASK-001", "scenario": "E-01"},
    ]


def test_checklist_clean_when_refs_and_checklist_match() -> None:
    text = (
        "## TASK-001: demo\n"
        "- **Acceptance-Refs**: S-01, E-01\n"
        "### Checklist\n"
        "- [ ] [S-01] ok\n"
        "- [ ] [E-01] ok\n"
        "### Acceptance Contract\n"
    )
    assert _checklist_issues(text) == []


def test_checklist_expands_scenario_ranges() -> None:
    text = (
        "## TASK-001: demo\n"
        "- **Acceptance-Refs**: S-01, S-02, S-03, S-04\n"
        "### Checklist\n"
        "- [x] [S-01~04][unit] range notation\n"
        "### Acceptance Contract\n"
    )
    assert _checklist_issues(text) == []


def test_checklist_flags_ref_missing_from_checklist() -> None:
    text = (
        "## TASK-001: demo\n"
        "- **Acceptance-Refs**: S-01, S-02\n"
        "### Checklist\n"
        "- [ ] [S-01] ok\n"
        "### Acceptance Contract\n"
    )
    assert _checklist_issues(text) == [
        {"code": "acceptance_ref_not_in_checklist", "task": "TASK-001", "scenario": "S-02"},
    ]


def test_checklist_ignores_fenced_example_headings() -> None:
    text = (
        "## TASK-001: demo\n"
        "- **Acceptance-Refs**: S-01\n"
        "### Description\n"
        "```markdown\n## TASK-007: example\n```\n"
        "### Checklist\n"
        "- [ ] [S-01] ok\n"
        "### Acceptance Contract\n"
    )
    assert _checklist_issues(text) == []
