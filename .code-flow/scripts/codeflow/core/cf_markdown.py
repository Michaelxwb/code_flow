"""Shared Markdown primitives: frontmatter splitting and pipe-table headers.

Pure parsing only — no I/O, no schema knowledge. Feature modules keep their own
field aliases and value semantics.
"""

from __future__ import annotations

import re
from typing import Mapping, Optional, Sequence


_FRONTMATTER_RE = re.compile(r"\A---[ \t]*\n(.*?)\n---[ \t]*\n?", re.DOTALL)
_SEPARATOR_CELL_RE = re.compile(r"^:?-{2,}:?$")


def parse_frontmatter(text: str) -> tuple[Mapping[str, object], str]:
    """Split optional frontmatter into flat metadata + body.

    Parses only flat `key: value` string pairs — enough for `description:` —
    so the hook hot path never needs pyyaml for this. Content without
    frontmatter returns ({}, text) unchanged.
    """
    if not isinstance(text, str):
        return {}, text
    match = _FRONTMATTER_RE.match(text)
    if match is None:
        return {}, text
    meta: dict[str, object] = {}
    for line in match.group(1).splitlines():
        key, sep, value = line.partition(":")
        if not sep:
            continue
        key = key.strip()
        if key:
            meta[key] = value.strip().strip('"').strip("'")
    return meta, text[match.end():]


def frontmatter_block(text: str) -> Optional[str]:
    """Return the raw frontmatter text (no delimiters), or None when absent."""
    if not isinstance(text, str):
        return None
    match = _FRONTMATTER_RE.match(text)
    return match.group(1) if match else None


def table_cells(line: str) -> tuple[str, ...]:
    """Split one pipe-table line into trimmed cells; () for non-table lines."""
    stripped = line.strip()
    if not stripped.startswith("|"):
        return ()
    return tuple(cell.strip() for cell in stripped.strip("|").split("|"))


def is_separator_row(cells: Sequence[str]) -> bool:
    """True for the `|---|:--:|` alignment row."""
    return bool(cells) and all(_SEPARATOR_CELL_RE.match(cell.replace(" ", "")) for cell in cells)


def table_columns(lines: Sequence[str]) -> Mapping[str, int]:
    """Map header names to column offsets; {} when no header row exists."""
    for line in lines:
        cells = table_cells(line)
        if not cells or is_separator_row(cells):
            continue
        return {cell: index for index, cell in enumerate(cells)}
    return {}


def column_index(header: Sequence[str], *names: str) -> int:
    """Lowest header index containing any alias (case-insensitive), else -1."""
    for index, cell in enumerate(header):
        lowered = cell.lower()
        if any(name.lower() in lowered for name in names):
            return index
    return -1
