"""Acceptance evidence writer must update the Coverage status cell in place."""
from __future__ import annotations

from codeflow.acceptance.cf_acceptance_evidence import _status_line, line_status


def test_status_line_replaces_designed_in_place() -> None:
    line = (
        "| S-01 | design | unit | boundary | TASK-001 | designed | [\"pytest\"] | "
        "P1 | auto | none | tests/x.py | - | - | no |"
    )
    updated = _status_line(line, "S-01", "verified")
    assert updated.count("|") == line.count("|")
    assert "designed" not in updated
    assert line_status(updated, "S-01") == "verified"


def test_status_line_appends_only_when_no_status_cell() -> None:
    line = "| S-01 | design | unit | boundary | TASK-001 | | [\"pytest\"] |"
    updated = _status_line(line, "S-01", "verified")
    assert line_status(updated, "S-01") == "verified"
