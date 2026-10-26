#!/usr/bin/env python3
"""Single source of truth for parsing TASK documents.

Pure module: standard library only, no cf_* imports. Headings are anchored at
column 0, fenced code blocks are inert, duplicate TASK IDs fail closed, and a
section without a Status line projects as `draft`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterator, Mapping

_HEADING_RE = re.compile(r"^## (TASK-\d+):[ \t]*(.*)$")
_FIELD_RE = re.compile(r"^- \*\*([^*]+)\*\*:[ \t]*(.*)$")
_FENCE_RE = re.compile(r"^ {0,3}(`{3,}|~{3,})")
_TASK_ID_RE = re.compile(r"TASK-\d+")
_DEPENDS_SPLIT_RE = re.compile(r"[,，\s]+")


class TaskDocumentError(ValueError):
    """Structured parse failure with a stable error code."""

    def __init__(self, code: str, message: str, details: tuple[str, ...] = ()) -> None:
        self.code = code
        self.details = details
        suffix = f": {'; '.join(details)}" if details else ""
        super().__init__(f"[{code}] {message}{suffix}")


@dataclass(frozen=True)
class TaskSection:
    id: str
    title: str
    status: str
    depends: tuple[str, ...]
    fields: Mapping[str, str]
    body: str


@dataclass(frozen=True)
class TaskDocument:
    tasks: tuple[TaskSection, ...]
    source: str = ""


def _unfenced_lines(text: str) -> Iterator[str]:
    fence = ""
    for line in text.splitlines():
        match = _FENCE_RE.match(line)
        if match is not None:
            marker = match.group(1)
            if not fence:
                fence = marker
            elif marker[0] == fence[0] and len(marker) >= len(fence) and line.strip() == marker:
                fence = ""
            continue
        if not fence:
            yield line


def _heading_spans(text: str) -> list[tuple[int, str, str]]:
    """Offsets/IDs/titles of real TASK headings, skipping fenced code blocks."""
    spans: list[tuple[int, str, str]] = []
    offset = 0
    fence = ""
    for line in text.splitlines(keepends=True):
        content = line.rstrip("\n")
        match = _FENCE_RE.match(content)
        if match is not None:
            marker = match.group(1)
            if not fence:
                fence = marker
            elif marker[0] == fence[0] and len(marker) >= len(fence) and content.strip() == marker:
                fence = ""
        elif not fence:
            heading = _HEADING_RE.match(content)
            if heading is not None:
                spans.append((offset, heading.group(1), heading.group(2).strip()))
        offset += len(line)
    return spans


def _fields(body: str) -> Mapping[str, str]:
    fields: dict[str, str] = {}
    for line in _unfenced_lines(body):
        match = _FIELD_RE.match(line.rstrip())
        if match is not None:
            fields.setdefault(match.group(1).strip(), match.group(2).strip())
    return fields


def _depends(fields: Mapping[str, str]) -> tuple[str, ...]:
    raw = fields.get("Depends", "")
    return tuple(
        part.strip() for part in _DEPENDS_SPLIT_RE.split(raw)
        if _TASK_ID_RE.fullmatch(part.strip())
    )


def _section(text: str, start: int, end: int, task_id: str, title: str) -> TaskSection:
    body = text[start:end]
    fields = _fields(body)
    return TaskSection(
        id=task_id,
        title=title,
        status=fields.get("Status") or "draft",
        depends=_depends(fields),
        fields=fields,
        body=body,
    )


def parse_task_document(text: str, *, source: str = "") -> TaskDocument:
    """Parse `## TASK-xxx` sections into the ordered TaskDocument contract."""
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    spans = _heading_spans(normalized)
    if not spans:
        raise TaskDocumentError("task_document_empty", "no TASK sections found", (source,) if source else ())
    tasks: list[TaskSection] = []
    seen: set[str] = set()
    for index, (start, task_id, title) in enumerate(spans):
        if task_id in seen:
            details = (task_id, source) if source else (task_id,)
            raise TaskDocumentError("duplicate_task_id", f"{task_id} appears more than once", details)
        seen.add(task_id)
        end = spans[index + 1][0] if index + 1 < len(spans) else len(normalized)
        tasks.append(_section(normalized, start, end, task_id, title))
    return TaskDocument(tuple(tasks), source)
