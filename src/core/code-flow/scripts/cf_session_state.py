#!/usr/bin/env python3
"""Shared per-session state for injection/reminder cadence.

Stores one JSON file per project root (`.code-flow/.session-state.json`),
keyed by session id. Both read and write are best-effort: a corrupt or
unwritable state degrades to no-op rather than breaking hook protocols.
"""

import json
import os
from pathlib import Path
from typing import Mapping


_STATE_PATH = ".code-flow/.session-state.json"


def load_session_state(root: str) -> dict:
    """Return the persisted state dict; {} on any failure (never raises)."""
    try:
        value = json.loads((Path(root) / _STATE_PATH).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeError):
        return {}
    return value if isinstance(value, dict) else {}


def save_session_state(root: str, state: Mapping) -> bool:
    """Atomically persist state; False on failure (never raises)."""
    path = Path(root) / _STATE_PATH
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
        temporary.write_text(json.dumps(dict(state), ensure_ascii=False), encoding="utf-8")
        os.replace(temporary, path)
        return True
    except (OSError, UnicodeError, TypeError):
        return False
