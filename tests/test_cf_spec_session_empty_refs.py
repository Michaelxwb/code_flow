#!/usr/bin/env python3
"""Test cf_spec_session handles empty Spec-Refs correctly."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / ".code-flow" / "scripts"))

from cf_spec_session import _refs


def test_empty_spec_refs_does_not_capture_next_line():
    """空 Spec-Refs 不得跨行吞掉下一字段（Acceptance-Refs 等）。"""
    section = """## TASK-001: Test Task
- **Spec-Refs**:
- **Acceptance-Refs**: S-01, S-02
- **Done-Evidence**: Unit tests pass
"""
    result = _refs(section)
    assert result == (), f"Expected empty tuple, got {result}"


def test_normal_spec_refs_parsed_correctly():
    """正常 Spec-Refs 仍能正确解析。"""
    section = """## TASK-001: Test Task
- **Spec-Refs**: cli#RULE-001, core#RULE-002
- **Acceptance-Refs**: S-01
"""
    result = _refs(section)
    assert result == ("cli#RULE-001", "core#RULE-002")


def test_spec_refs_with_trailing_spaces():
    """Spec-Refs 后有尾随空格/制表符。"""
    section = """## TASK-001: Test Task
- **Spec-Refs**:   \t
- **Acceptance-Refs**: S-01
"""
    result = _refs(section)
    assert result == (), f"Expected empty tuple, got {result}"


def test_spec_refs_single_item():
    """单个 Spec-Ref。"""
    section = """## TASK-001: Test Task
- **Spec-Refs**: cli#RULE-001
- **Acceptance-Refs**: S-01
"""
    result = _refs(section)
    assert result == ("cli#RULE-001",)


def test_spec_refs_with_spaces_around_commas():
    """Spec-Refs 逗号前后有空格。"""
    section = """## TASK-001: Test Task
- **Spec-Refs**: cli#RULE-001 , core#RULE-002 , scripts#RULE-003
- **Acceptance-Refs**: S-01
"""
    result = _refs(section)
    assert result == ("cli#RULE-001", "core#RULE-002", "scripts#RULE-003")
