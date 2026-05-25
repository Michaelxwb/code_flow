#!/usr/bin/env python3
"""Regression tests for Codex skill wording."""
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CODEX_SKILL_DIRS = [
    ROOT / "src" / "adapters" / "codex" / "skills",
    ROOT / ".agents" / "skills",
]
CLAUDE_TOOL_NAME_RE = re.compile(r"\b(Read|Write|Edit|Glob|Grep|Bash)\b")


def test_codex_skills_do_not_reference_claude_tool_names() -> None:
    offenders = []
    for skill_dir in CODEX_SKILL_DIRS:
        for path in sorted(skill_dir.glob("*/SKILL.md")):
            text = path.read_text(encoding="utf-8")
            for line_no, line in enumerate(text.splitlines(), start=1):
                if CLAUDE_TOOL_NAME_RE.search(line):
                    rel = path.relative_to(ROOT)
                    offenders.append(f"{rel}:{line_no}: {line}")

    assert offenders == []


def test_installed_codex_skills_match_adapter_templates() -> None:
    adapter_dir = ROOT / "src" / "adapters" / "codex" / "skills"
    installed_dir = ROOT / ".agents" / "skills"

    adapter_files = sorted(path.relative_to(adapter_dir) for path in adapter_dir.glob("*/SKILL.md"))
    installed_files = sorted(path.relative_to(installed_dir) for path in installed_dir.glob("*/SKILL.md"))
    assert installed_files == adapter_files

    for rel_path in adapter_files:
        adapter_text = (adapter_dir / rel_path).read_text(encoding="utf-8")
        installed_text = (installed_dir / rel_path).read_text(encoding="utf-8")
        assert installed_text == adapter_text, str(rel_path)
