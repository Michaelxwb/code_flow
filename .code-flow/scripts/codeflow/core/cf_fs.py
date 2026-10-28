#!/usr/bin/env python3
"""L0 filesystem primitives: text reads and atomic replacement writes."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Optional, Union

PathLike = Union[str, os.PathLike]


def read_text(path: PathLike) -> Optional[str]:
    """Read UTF-8 text; a missing file is None, other IO errors propagate."""
    try:
        return Path(path).read_text(encoding="utf-8")
    except FileNotFoundError:
        return None


def write_text(path: PathLike, text: str) -> None:
    """Write UTF-8 text in place (non-atomic convenience writer)."""
    Path(path).write_text(text, encoding="utf-8")


def atomic_write_text(path: PathLike, text: str) -> None:
    """Replace path with exact UTF-8 text via a temp file and os.replace.

    On any failure the target keeps its previous content and the temp file is
    removed before the original exception propagates. Disable native newline
    translation so transaction snapshots also round-trip unchanged on Windows.
    """
    target = Path(path)
    temporary = ""
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            newline="",
            dir=str(target.parent),
            prefix=f".{target.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary = handle.name
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    except Exception:
        if temporary:
            try:
                os.unlink(temporary)
            except OSError:
                pass  # best effort: the original failure is what callers need
        raise
